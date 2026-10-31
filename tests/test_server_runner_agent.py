"""서버 실행기(`chaeksas.server_runner`)가 진짜 Center에 등록·하트비트한다 (C12, M7 조각 2).

**양쪽을 한 줄로 본다** — 실행기의 `agent.tick()`이 ASGI로 붙은 진짜 Center를 부른다. 그래서
C12가 「구현됨」으로 가는 조건(보내는 쪽과 받는 쪽이 다 있고 시험이 지킨다)을 이 파일이 센다.

**아직 BPM 프로세스를 돌리지 않는다** (다음 조각) — 그러므로 여기서 보는 것은 「살아 있다고 말하고,
자리를 정직하게 세고, 지시를 받아 두는가」다. 받고도 돌리지 않는 것을 **`started` ack로
거짓말하지 않는지**까지 본다.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi.testclient import TestClient

from chaeksas.center import create_app
from chaeksas.center.settings import Settings as CenterSettings
from chaeksas.center.storage import Store, now_iso
from chaeksas.contracts.manifest import Manifest
from chaeksas.contracts.resources import ServiceAppResource
from chaeksas.server_runner import agent as agent_mod
from chaeksas.server_runner import main as main_mod
from chaeksas.server_runner.center_client import (
    CenterClient,
    CenterProblem,
    Unreachable,
    _problem,
)
from chaeksas.server_runner.credentials import ENV_CENTER_API_KEY, Credentials
from chaeksas.server_runner.settings import Settings

ADMIN = {"Authorization": "Bearer t-admin"}
READ = {"Authorization": "Bearer t-read"}


@pytest.fixture
def store() -> Iterator[Store]:
    found = Store(Path(":memory:"))
    yield found
    found.close()


@pytest.fixture
def center(store: Store, tmp_path: Path) -> Iterator[TestClient]:
    settings = CenterSettings(
        admin_token="t-admin", read_token="t-read", package_dir=tmp_path / "pkg"
    )
    with TestClient(create_app(settings, store=store)) as found:
        yield found


@pytest.fixture
def key(center: TestClient) -> str:
    response = center.post(
        "/api/v1/center-keys", json={"name": "서버 1", "type": "server_runner"}, headers=ADMIN
    )
    assert response.status_code == 201, response.text
    return str(response.json()["key"])


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(center_url="http://center", name="서버 1", data_path=tmp_path / "runner")


def build(settings: Settings, key: str, center: TestClient) -> agent_mod.Agent:
    """진짜 Center에 ASGI로 붙은 실행기 하나 (소켓을 열지 않는다)."""
    settings.data_path.mkdir(parents=True, exist_ok=True)
    return agent_mod.build(settings, key, client=center)


# ─────────────────────────── 한 줄 (등록 → 하트비트) ───────────────────────────


def test_register_then_heartbeat(settings: Settings, key: str, center: TestClient) -> None:
    found = build(settings, key, center)
    assert not found.registered

    assert found.tick() is True  # 등록
    assert found.server_runner_id.startswith("srv_")
    assert found.next_in_s == 10, "주기는 C12의 10초다"

    assert found.tick() is True  # 하트비트
    listed = center.get("/api/v1/server-runners", headers=READ).json()
    assert len(listed) == 1
    assert listed[0]["server_runner_id"] == found.server_runner_id
    assert listed[0]["online"] is True and listed[0]["status"] == "running"
    assert listed[0]["name"] == "서버 1"


def test_it_reports_no_running_work(settings: Settings, key: str, center: TestClient) -> None:
    """**없는 것을 있는 척하지 않는다** — 돌리지 않으므로 `running`은 0이다 (M7 조각 2)."""
    found = build(settings, key, center)
    found.tick()
    found.tick()
    listed = center.get("/api/v1/server-runners", headers=READ).json()[0]
    assert listed["capacity"]["running"] == 0
    assert listed["running"] == [] and listed["waiting"] == []
    # 상한은 **실행기가 정한 값**이 그대로 올라간다 (C12 — 설정값이다).
    assert listed["capacity"]["max"] == settings.max_concurrency == 10


def test_the_machine_id_is_the_shared_rule(settings: Settings, key: str, center: TestClient) -> None:
    """`machine_id`는 **PC 실행기와 같은 함수**다 (`core.machine`) — 원값은 보내지 않는다."""
    from chaeksas.core import machine

    found = build(settings, key, center)
    assert found.machine_id() == machine.machine_id(settings.data_path)
    assert len(found.machine_id()) == 64
    found.tick()
    row = center.get("/api/v1/server-runners", headers=READ).json()[0]
    assert "machine_id" not in row, "목록에 기계 값을 싣지 않는다"


def test_max_concurrency_from_the_settings(key: str, center: TestClient, tmp_path: Path) -> None:
    found = build(
        Settings(center_url="http://center", max_concurrency=3, data_path=tmp_path / "r"),
        key,
        center,
    )
    found.tick()
    listed = center.get("/api/v1/server-runners", headers=READ).json()[0]
    assert listed["capacity"]["max"] == 3


# ─────────────────────────── 거부·끊김 (ADR-0007) ───────────────────────────


def test_a_wrong_key_type_blocks_and_stops_knocking(
    settings: Settings, center: TestClient
) -> None:
    """키 종류가 틀리면 **다시 걸어도 같다** — 막아 두고 두드리지 않는다 (C12 403)."""
    raw = center.post(
        "/api/v1/center-keys", json={"name": "PC 키", "type": "bot_ui"}, headers=ADMIN
    ).json()["key"]
    found = build(settings, raw, center)

    assert found.tick() is False
    assert found.blocked_by and "키 종류" in found.blocked_by
    assert found.tick() is False, "막힌 뒤에는 아무것도 하지 않는다"
    assert "막혔다" in found.status_line()


def test_a_bound_key_on_another_machine_blocks(
    settings: Settings, key: str, center: TestClient, tmp_path: Path
) -> None:
    """키 묶기가 어긋나면 운영자가 풀어야 한다 (C12 409 — 다시 걸어도 같다).

    **같은 키를 다른 기계에서** 쓴 경우다. 이 PC의 `machine_id`는 `/etc/machine-id`에서 와
    데이터 폴더를 바꿔도 같으므로, 둘째 실행기의 기계 값만 바꿔 끼운다.
    """
    build(settings, key, center).tick()
    other = build(Settings(center_url="http://center", data_path=tmp_path / "other"), key, center)
    other.machine_id = lambda: "b" * 64  # type: ignore[method-assign]

    assert other.tick() is False
    assert other.blocked_by and "묶" in other.blocked_by
    assert other.tick() is False, "막힌 뒤에는 두드리지 않는다"


def test_unreachable_center_does_not_block(settings: Settings, tmp_path: Path) -> None:
    """닿지 못한 것은 **사람이 고칠 문제가 아니다** — 막지 않고 계속 다시 건다 (ADR-0007)."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("꺼져 있다", request=request)

    settings.data_path.mkdir(parents=True, exist_ok=True)
    found = agent_mod.Agent(
        settings=settings,
        client=CenterClient(
            base_url="http://center",
            api_key="chk_ctr_" + "x" * 40,
            client=httpx.Client(transport=httpx.MockTransport(refuse)),
        ),
    )
    assert found.tick() is False
    assert found.blocked_by == "", "닿지 못한 것으로 막지 않는다"
    assert found.online is False
    assert "닿지 못한다" in found.status_line()


def test_a_center_that_forgot_us_makes_us_register_again(
    settings: Settings, key: str, center: TestClient, store: Store
) -> None:
    """Center의 DB가 새로 서면 `not_registered`다 — **다시 등록하면 이어진다** (멱등)."""
    found = build(settings, key, center)
    found.tick()
    first = found.server_runner_id
    with store.tx() as cur:  # Center가 우리를 잊었다
        cur.execute("DELETE FROM server_runners")

    assert found.tick() is False  # 하트비트가 409를 받고 신원을 버린다
    assert found.server_runner_id == ""
    assert found.blocked_by == "", "Center가 잊은 것은 사람이 고칠 문제가 아니다"

    assert found.tick() is True  # 다시 등록
    assert found.server_runner_id.startswith("srv_")
    assert found.tick() is True, "그다음 하트비트가 다시 돈다"
    assert first != "" and found.server_runner_id != first, "새 행이라 새 id다"


# ─────────────────────────── 일시 중지·지시 (CON-12) ───────────────────────────


def test_pause_is_heard_and_reported_back(
    settings: Settings, key: str, center: TestClient
) -> None:
    found = build(settings, key, center)
    found.tick()
    found.tick()
    assert found.paused is False

    center.post(f"/api/v1/server-runners/{found.server_runner_id}/pause", headers=ADMIN)
    found.tick()
    assert found.paused is True
    # 다음 하트비트의 `status`가 그렇게 올라간다 (C12 — 열린 문자열의 아는 값).
    found.tick()
    listed = center.get("/api/v1/server-runners", headers=READ).json()[0]
    assert listed["status"] == agent_mod.STATUS_PAUSED

    center.post(f"/api/v1/server-runners/{found.server_runner_id}/resume", headers=ADMIN)
    found.tick()
    assert found.paused is False


def test_a_job_for_an_uninstalled_bot_is_refused_not_dropped(
    settings: Settings, key: str, center: TestClient, store: Store
) -> None:
    """깔리지 않은 BPM 프로세스의 작업은 **거절하고 그렇게 말한다** (C4) — 조용히 버리지 않는다.

    버리면 Center가 「넘겼는데 소식이 없다」로 두 주기 뒤 `runner_lost`를 적는다. 거짓
    `started`를 보내는 것은 더 나쁘다 — Center가 도는 줄 알고 기다린다.
    """
    found = build(settings, key, center)
    found.tick()
    with store.tx() as cur:
        cur.execute(
            "INSERT INTO jobs (job_id, bpm_process_id, version, target_type, target_id,"
            " inputs_json, requested_by, requested_at, state, owner, body_hash)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("job_a", "finance.invoice-issue", "1.0.0", "server_runner", "", "{}", "운영자",
             now_iso(), "pending", "admin", "h"),
        )
    found.tick()  # 작업을 받아 보고 거절한다
    assert [(a.job_id, a.result, a.reason) for a in found.pending_acks] == [
        ("job_a", "rejected", "no_deployment")
    ]
    assert found.workers == {}, "띄우지 않았다"

    found.tick()  # ack를 올린다
    row = store.row("SELECT state, state_reason, run_id FROM jobs WHERE job_id = ?", ("job_a",))
    assert row is not None
    assert row["state"] == "rejected" and row["state_reason"] == "no_deployment"
    assert row["run_id"] is None, "돌지 않았으므로 실행도 없다"


def test_an_unknown_cancel_is_answered(settings: Settings, key: str, center: TestClient) -> None:
    """받은 적 없는 작업의 취소에도 **답한다** — 답이 없으면 Center가 매번 다시 싣는다."""
    found = build(settings, key, center)
    found.tick()
    found.cancel_job("job_ghost")
    assert [(a.job_id, a.result) for a in found.pending_acks] == [("job_ghost", "cancelled")]


def test_restored_is_sent_once(settings: Settings, key: str, center: TestClient) -> None:
    """`restored[]`는 **첫 하트비트에만** 올린다 (C12) — 올린 뒤에는 비운다."""
    found = build(settings, key, center)
    found.tick()
    found.restored = ["run_20261013_090000_aa11bb"]
    found.tick()
    assert found.restored == []


def test_restored_is_kept_when_center_is_down(settings: Settings, tmp_path: Path) -> None:
    """올리지 못했으면 **들고 있는다** (ADR-0007) — 버리면 Center가 영영 모른다."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("꺼져 있다", request=request)

    settings.data_path.mkdir(parents=True, exist_ok=True)
    found = agent_mod.Agent(
        settings=settings,
        client=CenterClient(
            base_url="http://center",
            api_key="k",
            client=httpx.Client(transport=httpx.MockTransport(refuse)),
        ),
        server_runner_id="srv_12345678",
        restored=["run_20261013_090000_aa11bb"],
    )
    assert found.tick() is False
    assert found.restored == ["run_20261013_090000_aa11bb"]


# ─────────────────────────── CLI (`chk-server-runner`) ───────────────────────────


def test_without_a_key_it_says_where_to_put_one(
    monkeypatch: pytest.MonkeyPatch, capsys: Any, tmp_path: Path
) -> None:
    monkeypatch.delenv(ENV_CENTER_API_KEY, raising=False)
    monkeypatch.setenv("CHK_SERVER_RUNNER__DATA_DIR", str(tmp_path))
    monkeypatch.setattr(Credentials, "center_api_key", lambda self: None)
    # 비밀 저장소도 없다 — 받은 키를 둘 곳이 없으니 등록 요청을 보내지 않는다 (C12).
    monkeypatch.setattr(Credentials, "available", property(lambda self: False))
    assert main_mod.main(["--once"]) == 2
    out = capsys.readouterr().out
    assert ENV_CENTER_API_KEY in out and "비밀 저장소" in out


class MemoryCredentials(Credentials):
    """OS 비밀 저장소 대신 메모리 (시험이 개발 PC의 키링을 건드리지 않게)."""

    def __init__(self) -> None:
        super().__init__()
        self.values: dict[str, str] = {}

    @property
    def available(self) -> bool:
        return True

    def get(self, name: str, *, env: str | None = None) -> str | None:
        return self.values.get(name)

    def set(self, name: str, value: str) -> None:
        self.values[name] = value


def test_without_a_key_it_asks_center_and_is_let_in_by_approval(
    settings: Settings, center: TestClient, caplog: Any
) -> None:
    """C12 §등록 요청과 승인 — 요청 코드는 로그 한 줄, 승인은 CON-12. 사람은 키를 보지 않는다."""
    from chaeksas.server_runner import enroll  # noqa: PLC0415

    found = build(settings, "", center)
    found.credentials = MemoryCredentials()
    caplog.set_level("INFO")
    assert enroll.step(found) is None
    pending = center.get("/api/v1/enrollments?type=server_runner", headers=READ).json()
    assert len(pending) == 1
    assert pending[0]["code"] in caplog.text, "요청 코드는 로그에 찍힌다 — 관리자가 그것과 맞춰 본다"

    approved = center.post(f"/api/v1/enrollments/{pending[0]['enrollment_id']}/approve", json={}, headers=ADMIN)
    assert approved.status_code == 200, approved.text
    key = enroll.step(found)
    assert key is not None and key.startswith("chk_ctr_")
    assert found.credentials.center_api_key() == key
    assert key not in caplog.text, "키는 로그에 남지 않는다"
    assert not (settings.data_path / enroll.STATE_FILE).exists()

    found.client.api_key = key
    assert found.tick() is True  # 평소처럼 등록한다
    assert found.registered


def test_a_bundled_runner_is_let_in_by_the_join_token(
    settings: Settings, store: Store, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: Any
) -> None:
    """같이 배포된 실행기 (ADR-0117) — 들이기 비밀이 맞으면 **첫 걸음에** 키를 받는다."""
    from chaeksas.server_runner import enroll  # noqa: PLC0415

    center_settings = CenterSettings(
        admin_token="t-admin", package_dir=tmp_path / "pkg", server_runner_join_token="j" * 43
    )
    with TestClient(create_app(center_settings, store=store)) as joined:
        found = build(settings, "", joined)
        found.credentials = MemoryCredentials()
        caplog.set_level("INFO")
        monkeypatch.setenv("CHK_SERVER_RUNNER__JOIN_TOKEN", "j" * 43)
        key = enroll.step(found)
        assert key is not None and key.startswith("chk_ctr_")
        assert "j" * 43 not in caplog.text
        found.client.api_key = key
        assert found.tick() is True and found.registered

        # 틀린 비밀은 사람에게 무엇을 맞출지 말한다.
        other = build(settings, "", joined)
        other.credentials = MemoryCredentials()
        monkeypatch.setenv("CHK_SERVER_RUNNER__JOIN_TOKEN", "x" * 43)
        (settings.data_path / enroll.STATE_FILE).unlink(missing_ok=True)
        with pytest.raises(CenterProblem, match="CHK_CENTER__SERVER_RUNNER_JOIN_TOKEN"):
            enroll.step(other)


def test_restart_drains_then_says_ready(settings: Settings, key: str, center: TestClient) -> None:
    """「재시작」 (ADR-0117) — 들으면 `draining`이고, 도는 실행·올릴 ack가 없으면 끝내도 된다."""
    found = build(settings, key, center)
    found.tick()
    found.tick()
    assert found.restart_ready() is False

    center.post(f"/api/v1/server-runners/{found.server_runner_id}/restart", headers=ADMIN)
    found.tick()
    assert found.restarting is True
    found.tick()
    listed = center.get("/api/v1/server-runners", headers=READ).json()[0]
    assert listed["status"] == agent_mod.STATUS_DRAINING
    assert found.restart_ready() is True


def test_once_prints_a_line_without_the_key(
    monkeypatch: pytest.MonkeyPatch, capsys: Any, tmp_path: Path, key: str, center: TestClient
) -> None:
    monkeypatch.setenv("CHK_SERVER_RUNNER__DATA_DIR", str(tmp_path))
    monkeypatch.setenv(ENV_CENTER_API_KEY, key)
    # ASGI로 붙인다 — `--once`가 진짜로 Center를 한 번 두드린다.
    monkeypatch.setattr(
        agent_mod,
        "build",
        lambda settings, api_key, client=None: agent_mod.Agent(
            settings=settings,
            client=CenterClient(base_url="http://center", api_key=api_key, client=center),
        ),
    )
    assert main_mod.main(["--once"]) == 0
    out = capsys.readouterr().out
    assert "srv_" in out and "동작" in out
    assert key not in out, "키 값을 찍지 않는다"

    # **등록만 하고 끝나지 않는다** — 하트비트까지 해야 콘솔이 「온라인」으로 본다.
    # 진짜 소켓으로 돌려 보고 발견한 자리다: `--once`가 성공했는데 CON-12는 오프라인이었다.
    listed = center.get("/api/v1/server-runners", headers=READ).json()[0]
    assert listed["online"] is True and listed["status"] == "running"


def test_runs_dir_is_made(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, key: str, center: TestClient) -> None:
    """실행 기록 폴더가 없으면 나중에 실행기가 뜨지 못한다 (M4에서 실제로 그랬다)."""
    monkeypatch.setenv("CHK_SERVER_RUNNER__DATA_DIR", str(tmp_path / "fresh"))
    monkeypatch.setenv(ENV_CENTER_API_KEY, key)
    monkeypatch.setattr(
        agent_mod,
        "build",
        lambda settings, api_key, client=None: agent_mod.Agent(
            settings=settings,
            client=CenterClient(base_url="http://center", api_key=api_key, client=center),
        ),
    )
    main_mod.main(["--once"])
    assert (tmp_path / "fresh" / "runs").is_dir()


# ─────────────────────────── 설정 ───────────────────────────


def test_settings_come_from_the_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CHK_SERVER_RUNNER__CENTER_URL", "http://center:8800")
    monkeypatch.setenv("CHK_SERVER_RUNNER__MAX_CONCURRENCY", "4")
    monkeypatch.setenv("CHK_SERVER_RUNNER__DATA_DIR", str(tmp_path))
    found = Settings.from_env()
    assert found.center_url == "http://center:8800"
    assert found.max_concurrency == 4
    assert found.state_db == tmp_path / "state.sqlite3"
    assert found.runs_dir == tmp_path / "runs"


def test_a_zero_limit_is_lifted_to_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """상한 0이면 영원히 빈자리가 없다 — 계약이 거부하기 전에 여기서 올린다."""
    monkeypatch.setenv("CHK_SERVER_RUNNER__MAX_CONCURRENCY", "0")
    assert Settings.from_env().max_concurrency == 1


def test_the_key_is_read_from_the_environment_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """서버에서는 환경변수가 주 경로다 (컨테이너·systemd가 그렇게 준다)."""
    monkeypatch.setenv(ENV_CENTER_API_KEY, "chk_ctr_fromenv")
    assert Credentials().center_api_key() == "chk_ctr_fromenv"


@pytest.mark.parametrize(
    ("status", "code", "expected"),
    [
        (403, "wrong_key_type", "KeyRejected"),
        (403, "key_revoked", "KeyRejected"),
        (401, "key_invalid", "KeyRejected"),
        (409, "machine_mismatch", "MachineMismatch"),
        (409, "machine_already_registered", "MachineMismatch"),
        (409, "not_registered", "NotRegistered"),
        (422, "input_invalid", "CenterProblem"),
        (500, None, "CenterProblem"),
    ],
)
def test_center_errors_are_split_by_what_to_do(status: int, code: str | None, expected: str) -> None:
    """오류를 **갈라서** 올린다 — 무엇을 할지가 다르다 (막는다 / 다시 등록 / 다시 건다).

    뭉개면 거부된 키를 주기마다 두드리거나, 거꾸로 잠깐 끊긴 것을 사람 손으로 넘긴다.
    """
    body = {"code": code, "message": "x"} if code else {}
    problem = _problem(httpx.Response(status, json=body, request=httpx.Request("POST", "http://x")))
    assert type(problem).__name__ == expected
    # 닿지 못한 것만이 `Unreachable`이다 — 상태 코드가 있는 답은 모두 닿은 것이다.
    assert not isinstance(problem, Unreachable)


# ─────────────────────── 바깥 세계 배선 (M7 조각 8) ───────────────────────


def test_the_outside_world_comes_from_the_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """모델·읽기 폴더는 **설정이 정한다** — PC 실행기는 BUI-03이 정하는 자리다 (ADR-0027·0032).

    **주지 않으면 기본값이 남아 부르지 않고 실패한다**(조용히 넘어가지 않는다)는 것이 요점이라,
    여기서는 「준 것이 정말 `RunEnv`에 닿았는가」를 본다.
    """
    monkeypatch.setenv("CHK_SERVER_RUNNER__LLM__API_KEY", "k-model")
    settings = Settings(
        data_path=tmp_path / "runner",
        llm_base_url="http://127.0.0.1:1/v1",
        llm_model="stub",
        readable_dirs=(tmp_path / "in",),
        writable_dirs=(tmp_path / "out",),
    )
    made = agent_mod.Agent(settings=settings, client=cast(Any, _NoClient()))
    env = made.run_env(_FakeBot())

    assert type(env.llm).__name__ != "NoLlm", "모델이 꽂히지 않았다"
    space = env.workspace
    assert (tmp_path / "in") in space.readable
    assert (tmp_path / "out") in space.writable


def test_no_model_address_means_no_model(tmp_path: Path) -> None:
    """주소가 비면 **`NoLlm`이다** — 「없는데 된 척」하지 않는다 (ADR-0027)."""
    made = agent_mod.Agent(
        settings=Settings(data_path=tmp_path / "runner"), client=cast(Any, _NoClient())
    )
    assert type(made.run_env(_FakeBot()).llm).__name__ == "NoLlm"


def test_folder_lists_split_on_the_os_separator(monkeypatch: pytest.MonkeyPatch) -> None:
    """여러 폴더는 `os.pathsep`으로 가른다 (Linux `:`, Windows `;`).

    **빈 조각은 버린다** — 끝에 구분자가 하나 붙었다고 현재 폴더가 열리면 안 된다.
    """
    import os

    monkeypatch.setenv("CHK_SERVER_RUNNER__READABLE_DIRS", os.pathsep.join(["/a", "", "/b"]))
    monkeypatch.setenv("CHK_SERVER_RUNNER__WRITABLE_DIRS", "")
    found = Settings.from_env()
    assert [one.as_posix() for one in found.readable_dirs] == ["/a", "/b"]
    assert found.writable_dirs == ()


def test_the_model_key_is_not_in_the_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """키는 **설정에 없다** (CLAUDE.md §5) — 환경변수나 OS 비밀 저장소에서 읽는다."""
    monkeypatch.setenv("CHK_SERVER_RUNNER__LLM__API_KEY", "k-model")
    assert "k-model" not in repr(Settings.from_env())
    assert Credentials().llm_api_key() == "k-model"


# ─────────────────────── 바깥 앱 명부 (M7 조각 9) ───────────────────────


#: `erp` 하나를 부르는 BPM 프로세스 (C1 `requires.service_apps` — 키는 **참조 이름**이다).
_CALLS_ERP = {"service_apps": [{"app_id": "erp", "operations": ["get"], "key_ref": "fin-erp"}]}


class _Resources:
    """C7 리소스 목록만 주는 Center — **실행기가 제 손으로 읽는다**는 것을 본다.

    `extension()`은 404다 (외부 확장이 없는 BPM 프로세스) — 404는 **들고 있던 것을 버리는** 쪽이고
    여기서는 버릴 것이 없다.
    """

    def __init__(self, base_url: str = "http://127.0.0.1:9/erp") -> None:
        self.base_url = base_url
        self.asked = 0

    def service_apps(self) -> list[ServiceAppResource]:
        self.asked += 1
        return [
            ServiceAppResource(
                app_id="erp", name="모의 ERP", base_url=self.base_url, status="ok"
            )
        ]

    def extension(self, extension_id: str) -> Any:
        raise CenterProblem("없다", code="not_found", status=404)


class _DeadCenter:
    """닿지 못하는 Center — **들고 있던 것을 쓴다** (ADR-0007)."""

    def service_apps(self) -> list[ServiceAppResource]:
        raise Unreachable("꺼져 있다")

    def extension(self, extension_id: str) -> Any:
        raise Unreachable("꺼져 있다")


def test_service_calls_go_to_center_as_external_tasks(tmp_path: Path) -> None:
    """서비스 태스크는 **Center에 외부 작업으로** 올린다 (C15, ADR-0102) — 주소·키를 묻지 않는다.

    토큰은 이 실행기의 Center API 키이고 **부를 때마다 읽는다**(회전으로 바뀐다). **누가 부르는가**가
    PC와 다르다 (C11 `caller.type`) — 앱의 기록에 그대로 남는다.
    """
    from chaeksas.core.services import CenterServiceCaller  # noqa: PLC0415

    found = _Resources()
    client = cast(Any, found)
    client.api_key = "chk_ctr_first"
    made = agent_mod.Agent(settings=Settings(data_path=tmp_path / "runner", center_url="http://c:8800"), client=client)
    env = made.run_env(_FakeBot(requires=_CALLS_ERP))

    services = env.services
    assert isinstance(services, CenterServiceCaller)
    assert services.base_url == "http://c:8800" and services.caller_type == "server_runner"
    client.api_key = "chk_ctr_rotated"
    assert services.token() == "chk_ctr_rotated", "회전한 키를 그 자리에서 쓴다"
    assert found.asked == 0, "서비스 앱 주소를 묻지 않는다"


def test_the_register_answer_already_carries_the_admin_keys(
    settings: Settings,
    key: str,
    center: TestClient,
    store: Store,
) -> None:
    """공개키는 **등록 응답에도** 온다 (C12) — 되살리기가 첫 하트비트 **전에** 일어난다.

    되살린 실행도 바깥 앱 명부를 짓고, 봉투는 공개키로만 검증된다 (C13 E6). 등록에서 받지
    않으면 되살린 실행은 외부 앱을 **한 번도** 부를 수 없다.
    """
    from chaeksas.center import signer  # noqa: PLC0415

    found = build(settings, key, center)
    assert found.tick() is True  # 등록만 했다
    assert found.last_response is None, "아직 하트비트를 보내지 않았다"
    # Center가 처음 뜰 때 만든 서명 키다 (ADR-0090) — 승인·배포 봉투는 이 키가 서명한다.
    assert signer.current_key_id(store) in [one.key_id for one in found.admin_keys], (
        "등록 응답의 공개키를 들고 있어야 한다"
    )


class _NoClient:
    """Center를 부르지 않는다 — 이 시험이 보는 것은 배선뿐이다."""


class _FakeBot:
    id = "fx.sample"
    version = "1.0.0"
    folder = Path(__file__).resolve().parent

    def __init__(self, *, requires: dict[str, Any] | None = None) -> None:
        #: 기본은 **바깥 앱을 부르지 않는** BPM 프로세스이다 (C1 `requires`).
        self.manifest = Manifest.model_validate(
            {
                "schema": 1,
                "id": "fx.sample",
                "version": "1.0.0",
                "name": "시험 BPM 프로세스",
                "kind": "bpm_process",
                "run_location": "server",
                "entry": "main.bpmn",
                "content_hash": "sha256:" + "0" * 64,
                "requires": requires or {},
                "human": {"approval_center": False, "approval_field": False, "confirmation": False},
                "built": {
                    "by": "studio",
                    "at": "2026-10-14T09:00:00+09:00",
                    "core": "0.1.0",
                    "spec_version": 1,
                },
            }
        )

    def processes(self) -> dict[str, Any]:
        return {}

    def decisions(self) -> dict[str, Any]:
        return {}


# ─────────────────── 보내기 (M7 조각 10, ADR-0059) ───────────────────


def test_the_sender_comes_from_the_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """메일·웹훅 설정은 **환경변수가 정한다** (서버에는 BUI-03에 해당하는 화면이 없다).

    비밀번호는 **설정에 없다** — `credentials.smtp_password()`가 환경변수·비밀 저장소에서 읽는다.
    """
    monkeypatch.setenv("CHK_SERVER_RUNNER__SMTP__HOST", "smtp.example.com")
    monkeypatch.setenv("CHK_SERVER_RUNNER__SMTP__FROM", "bot@example.com")
    monkeypatch.setenv("CHK_SERVER_RUNNER__SMTP__PASSWORD", "비밀")
    monkeypatch.setenv("CHK_SERVER_RUNNER__WEBHOOK__ALLOWED_HOSTS", "hooks.example.com, a.example.com")
    found = Settings.from_env()

    assert found.smtp().host == "smtp.example.com"
    assert found.smtp().security == "starttls", "기본은 느슨한 쪽이 아니다"
    assert found.webhook().allowed_hosts == ("hooks.example.com", "a.example.com")
    assert found.webhook().allow_private_network is False, "사설망 스위치는 설정에 없다"
    assert "비밀" not in repr(found), "비밀번호는 설정에 들어가지 않는다"
    assert Credentials().smtp_password() == "비밀"


def test_the_runner_plugs_the_sender_in(tmp_path: Path) -> None:
    """실행기가 그 설정으로 어댑터를 짓는다 — **PC 실행기와 같은 함수**다 (`make_sender`)."""
    settings = Settings(
        data_path=tmp_path / "runner",
        smtp_host="smtp.example.com",
        smtp_sender="bot@example.com",
        webhook_allowed_hosts=("hooks.example.com",),
    )
    made = agent_mod.Agent(settings=settings, client=cast(Any, _NoClient()))
    sender = made.run_env(_FakeBot()).sender

    assert type(sender).__name__ == "PlatformSender", "보내기가 꽂히지 않았다"
    assert sender.mail.config.host == "smtp.example.com"  # type: ignore[attr-defined]
    assert sender.webhook.config.allowed_hosts == ("hooks.example.com",)  # type: ignore[attr-defined]


def test_without_smtp_the_mail_task_fails_clearly(tmp_path: Path) -> None:
    """**주지 않으면 보내지 않고 실패한다** — 조용히 넘어가지 않는다 (C14 §보내기)."""
    from chaeksas.core.senders import EmailMessage, SendError

    made = agent_mod.Agent(
        settings=Settings(data_path=tmp_path / "runner"), client=cast(Any, _NoClient())
    )
    with pytest.raises(SendError, match="SMTP 주소가 비어"):
        made.run_env(_FakeBot()).sender.send_email(EmailMessage(to=("a@example.com",)))


def test_a_mail_bot_without_smtp_is_not_ready(tmp_path: Path) -> None:
    """메일을 보내는 BPM 프로세스는 SMTP가 없으면 **사전 점검이 막는다** (C1 `requires.settings`)."""
    settings = Settings(data_path=tmp_path / "runner")
    assert settings.ready_settings() == ()
    assert Settings(
        data_path=tmp_path / "r2", smtp_host="smtp.example.com", smtp_sender="bot@example.com"
    ).ready_settings() == ("smtp",)
