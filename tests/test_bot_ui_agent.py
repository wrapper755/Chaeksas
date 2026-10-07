"""Bot UI ↔ Center 한 바퀴 (C4) — **실제 Center를 붙여** 돈다.

`TestClient`(httpx 클라이언트다)를 `CenterClient`에 그대로 끼워 Center 앱을 물린다. 그래서
「Bot UI가 등록하고 하트비트를 보내면 Center 콘솔(CON-03)에 보인다」는 M2 기준을 Windows 실기
없이도 여기서 지킨다 — 남은 것은 트레이·자동 시작 같은 OS 동작뿐이다.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from conftest import FakeCredentials
from fastapi.testclient import TestClient

from chaeksas.bot_ui.agent import (
    TRAY_DISABLED,
    TRAY_DISCONNECTED,
    TRAY_KEY_REVOKED,
    TRAY_UNREGISTERED,
    Agent,
)
from chaeksas.bot_ui.center_client import CenterClient, KeyRejected, MachineMismatch, Unreachable
from chaeksas.bot_ui.settings import Settings
from chaeksas.bot_ui.store import Store
from chaeksas.center.app import create_app
from chaeksas.center.settings import Settings as CenterSettings
from chaeksas.contracts.bot_ui import JobDispatch

ADMIN = "t-center-admin"


#: `TestClient`의 기본 주소. `CenterClient`가 이 주소로 부른다.
BASE_URL = "http://testserver"


@pytest.fixture
def center(tmp_path: Path) -> Iterator[TestClient]:
    """진짜 Center 앱. 토큰·DB는 시험 폴더 안에만 있다."""
    settings = CenterSettings(
        db_path=tmp_path / "center.sqlite3",
        package_dir=tmp_path / "packages",
        admin_token=ADMIN,
    )
    with TestClient(create_app(settings)) as client:
        yield client


def issue_key(center: TestClient, *, key_type: str = "bot_ui", name: str = "시험 PC") -> str:
    """콘솔이 하는 일 (CON-11) — 관리자 토큰으로 키를 발급한다."""
    response = center.post(
        "/api/v1/center-keys",
        json={"name": name, "type": key_type},
        headers={"Authorization": f"Bearer {ADMIN}"},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["key"])


def make_agent(center: TestClient, tmp_path: Path, *, key: str | None, name: str = "재무팀 PC-03") -> Agent:
    def factory(base_url: str, api_key: str) -> CenterClient:
        # 같은 전송을 쓰되, 키는 Agent가 비밀 저장소에서 꺼낸 것을 그대로 받는다.
        return CenterClient(base_url=BASE_URL, api_key=api_key, client=center)

    return Agent(
        settings=Settings(name=name, center_url=BASE_URL),
        # `load`로 만든다 — 다시 켠 Bot UI와 같은 길이다 (상태 파일을 읽는다).
        store=Store.load(tmp_path / "state.json"),
        credentials=FakeCredentials(key),
        client_factory=factory,
    )


# ─────────────────────────── 등록 → 하트비트 ───────────────────────────


def test_register_then_heartbeat_shows_up_in_the_console_listing(center: TestClient, tmp_path: Path) -> None:
    """M2 기준 그 자체: 키를 넣으면 등록되고, 하트비트가 콘솔 목록(CON-03)에 보인다."""
    agent = make_agent(center, tmp_path, key=issue_key(center))

    found = agent.register()
    assert found.bot_ui_id.startswith("bui_")
    assert agent.registered

    response = agent.beat()
    assert response is not None
    assert response.next_heartbeat_s == 30

    listing = center.get("/api/v1/bot-uis", headers={"Authorization": f"Bearer {ADMIN}"}).json()
    assert [(row["name"], row["online"], row["status"]) for row in listing] == [("재무팀 PC-03", True, "idle")]
    # **원값이 아니라 해시**를 보냈다 (C4).
    assert len(listing[0]["machine_id"]) == 64
    assert listing[0]["versions"]["bot_ui"]


def test_registering_twice_keeps_the_same_bot_ui_id(center: TestClient, tmp_path: Path) -> None:
    """등록은 멱등이다 (C4) — 켤 때마다 불러도 Bot UI가 늘어나지 않는다."""
    agent = make_agent(center, tmp_path, key=issue_key(center))
    first = agent.register()
    second = agent.register()
    assert first.bot_ui_id == second.bot_ui_id

    listing = center.get("/api/v1/bot-uis", headers={"Authorization": f"Bearer {ADMIN}"}).json()
    assert len(listing) == 1


def test_the_bot_ui_id_survives_a_restart(center: TestClient, tmp_path: Path) -> None:
    """상태 파일에 남으므로 다시 켜도 등록 상태다."""
    key = issue_key(center)
    first = make_agent(center, tmp_path, key=key)
    found = first.register()

    again = make_agent(center, tmp_path, key=key)
    assert again.store.state.bot_ui_id == str(found.bot_ui_id)
    assert again.registered


def test_beat_registers_first_if_needed(center: TestClient, tmp_path: Path) -> None:
    agent = make_agent(center, tmp_path, key=issue_key(center))
    assert agent.beat() is not None
    assert agent.registered


# ─────────────────────────── 키가 문제일 때 ───────────────────────────


def test_a_key_bound_to_another_pc_is_refused(center: TestClient, tmp_path: Path) -> None:
    """키는 처음 등록한 PC에 묶인다 (C4) — 새어도 다른 Bot UI를 사칭할 수 없다."""
    key = issue_key(center)
    make_agent(center, tmp_path, key=key).register()

    other = make_agent(center, tmp_path / "other", key=key, name="다른 PC")
    # 다른 PC인 척하려면 machine_id가 달라야 한다.
    other.machine_id = lambda: "f" * 64  # type: ignore[method-assign]
    with pytest.raises(MachineMismatch) as problem:
        other.register()
    assert "다른 PC에 묶여" in str(problem.value)
    assert other.tray_status() == TRAY_UNREGISTERED


def test_a_second_key_on_the_same_pc_is_refused(center: TestClient, tmp_path: Path) -> None:
    """이 PC가 이미 다른 키로 등록돼 있으면 거부다 (C4 「키 묶기」 — PC → 키 방향).

    운영자가 같은 PC에 키를 한 번 더 발급해 넣은 경우다. 지나가면 CON-03에 같은 PC가 두 줄로
    보인다. 트레이는 「등록 전」이고 BUI-03이 Center가 준 말을 그대로 보인다.
    """
    make_agent(center, tmp_path, key=issue_key(center)).register()

    second = make_agent(center, tmp_path / "second", key=issue_key(center, name="두 번째 키"))
    with pytest.raises(MachineMismatch) as problem:
        second.register()
    assert "이미 다른 키로 등록" in str(problem.value)
    assert second.tray_status() == TRAY_UNREGISTERED

    listing = center.get("/api/v1/bot-uis", headers={"Authorization": f"Bearer {ADMIN}"}).json()
    assert len(listing) == 1


def test_studio_key_cannot_register_as_a_bot_ui(center: TestClient, tmp_path: Path) -> None:
    agent = make_agent(center, tmp_path, key=issue_key(center, key_type="studio"))
    with pytest.raises(KeyRejected) as problem:
        agent.register()
    assert problem.value.code == "wrong_key_type"


def test_a_revoked_key_shows_up_in_the_tray(center: TestClient, tmp_path: Path) -> None:
    key = issue_key(center)
    agent = make_agent(center, tmp_path, key=key)
    agent.register()

    listing = center.get("/api/v1/center-keys", headers={"Authorization": f"Bearer {ADMIN}"}).json()
    center.delete(f"/api/v1/center-keys/{listing[0]['key_id']}", headers={"Authorization": f"Bearer {ADMIN}"})

    with pytest.raises(KeyRejected):
        agent.beat()
    assert agent.tray_status() == TRAY_KEY_REVOKED


def test_no_key_at_all_is_unregistered(tmp_path: Path) -> None:
    agent = Agent(
        settings=Settings(), store=Store(path=tmp_path / "state.json"), credentials=FakeCredentials(None)
    )
    assert agent.tray_status() == TRAY_UNREGISTERED
    with pytest.raises(KeyRejected):
        agent.register()


def test_unreachable_center_keeps_running(tmp_path: Path) -> None:
    """닿지 못한 것은 오류가 아니다 (ADR-0007) — 「연결 끊김」이고 실행은 계속한다."""
    agent = Agent(
        settings=Settings(center_url="http://127.0.0.1:9"),  # 아무도 듣지 않는 포트
        store=Store(path=tmp_path / "state.json"),
        credentials=FakeCredentials("chk_ctr_x"),
    )
    agent.store.state.bot_ui_id = "bui_12345678"
    assert agent.beat() is None
    assert isinstance(agent.last_problem, Unreachable)
    assert agent.tray_status() == TRAY_DISCONNECTED


def test_disabled_bot_ui_is_shown_and_refuses_new_jobs(center: TestClient, tmp_path: Path) -> None:
    """C4 `disabled` — 하트비트는 계속 받지만 새 작업을 받지 않는다."""
    agent = make_agent(center, tmp_path, key=issue_key(center))
    agent.register()
    agent.beat()

    listing = center.get("/api/v1/bot-uis", headers={"Authorization": f"Bearer {ADMIN}"}).json()
    center.post(
        f"/api/v1/bot-uis/{listing[0]['bot_ui_id']}/disable", headers={"Authorization": f"Bearer {ADMIN}"}
    )

    response = agent.beat()
    assert response is not None and response.disabled is True
    assert agent.tray_status() == TRAY_DISABLED

    job = JobDispatch(
        job_id="job_1",
        bpm_process_id="erp.order",
        requested_by="홍길동",
        requested_at="2026-10-03T00:00:00+00:00",
    )
    ack = agent.take_job(job)
    assert (ack.result, ack.reason) == ("rejected", "bot_ui_shutdown")
    assert agent.queue == []


def test_an_unreachable_center_before_the_first_register_is_quiet(tmp_path: Path) -> None:
    """등록도 못 한 채 Center가 꺼져 있으면 **조용히 기다린다** — 30초마다 알림을 띄우지 않는다."""
    agent = Agent(
        settings=Settings(center_url="http://127.0.0.1:9"),
        store=Store.load(tmp_path / "state.json"),
        credentials=FakeCredentials("chk_ctr_x"),
    )
    assert agent.beat() is None  # 예외를 올리지 않는다 (사람이 고칠 것이 없다)
    assert isinstance(agent.last_problem, Unreachable)
    assert agent.tray_status() == TRAY_DISCONNECTED


# ─────────────────────────── 실행 기록 보내기 (C3, 조각 3g) ───────────────────────────


def test_the_heartbeat_ships_the_run_log_and_counts_what_is_left(
    center: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """쌓인 기록이 하트비트 뒤에 Center로 간다 (C3 §전송) — 콘솔 CON-01이 그것을 그린다.

    **실행 중에 보내지 않는다** — 느린 Center가 업무를 붙잡으면 안 된다. 하트비트가 끝난 뒤
    큐를 비우고, 남은 줄 수는 `unsent_events`로 알린다 (C4).
    """
    from chaeksas.core.run_log import RunLog, log_path
    from chaeksas.core.run_shipping import HttpUploader

    data_dir = tmp_path / "botui"
    monkeypatch.setattr("chaeksas.bot_ui.settings.data_dir", lambda: data_dir)

    run_id = "run_20261005_120000_abcdef"
    log = RunLog(run_id=run_id, path=log_path(data_dir, run_id))
    log.emit("run_started", bpm_process_id="fin.invoice", version="1.0.0", run_location="pc",
             executor="bot_ui", mode="deterministic", source="job")
    log.emit("run_finished", status="success", duration_s=3.0, ai_tasks=0, replayed_tasks=0,
             ui_tasks=0, service_calls=0, human_requests=0)

    key = issue_key(center)
    agent = make_agent(center, tmp_path, key=key)
    # 보내기도 같은 시험 전송을 쓴다 (바깥으로 나가지 않는다).
    monkeypatch.setattr(
        agent, "ship_runs",
        lambda: agent.runs().ship(HttpUploader(base_url=BASE_URL, api_key=key, client=center)),
    )

    assert agent.heartbeat_request().unsent_events == 2, "보내기 전에는 두 줄이 밀려 있다"
    agent.beat()

    found = center.get(f"/api/v1/runs/{run_id}", headers={"Authorization": f"Bearer {ADMIN}"})
    assert found.status_code == 200
    assert found.json()["status"] == "success"
    assert agent.heartbeat_request().unsent_events == 0


def test_without_a_key_nothing_is_shipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """키가 없으면 보내지 않는다 — 기록은 쌓아 두고 화면이 키 문제를 말한다 (C3 §오류)."""
    from chaeksas.core.run_log import RunLog, log_path

    data_dir = tmp_path / "botui"
    monkeypatch.setattr("chaeksas.bot_ui.settings.data_dir", lambda: data_dir)
    RunLog(run_id="run_20261005_120000_abcdef", path=log_path(data_dir, "run_20261005_120000_abcdef")).emit(
        "log", level="info", message="한 줄"
    )

    agent = Agent(
        settings=Settings(name="키 없음", center_url=BASE_URL),
        store=Store.load(tmp_path / "state.json"),
        credentials=FakeCredentials(None),
    )
    assert agent.ship_runs().sent == 0
    assert agent.runs().unsent_count() == 1
