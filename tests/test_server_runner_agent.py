"""서버 실행기(`chaeksas.server_runner`)가 진짜 Center에 등록·하트비트한다 (C12, M7 조각 2).

**양쪽을 한 줄로 본다** — 실행기의 `agent.tick()`이 ASGI로 붙은 진짜 Center를 부른다. 그래서
C12가 「구현됨」으로 가는 조건(보내는 쪽과 받는 쪽이 다 있고 시험이 지킨다)을 이 파일이 센다.

**아직 Bot을 돌리지 않는다** (다음 조각) — 그러므로 여기서 보는 것은 「살아 있다고 말하고,
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
from chaeksas.server_runner import agent as agent_mod
from chaeksas.server_runner import main as main_mod
from chaeksas.server_runner.center_client import CenterClient, Unreachable, _problem
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
    """`machine_id`는 **Bot UI와 같은 함수**다 (`core.machine`) — 원값은 보내지 않는다."""
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
    """깔리지 않은 Bot의 작업은 **거절하고 그렇게 말한다** (C4) — 조용히 버리지 않는다.

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
    assert main_mod.main(["--once"]) == 2
    out = capsys.readouterr().out
    assert ENV_CENTER_API_KEY in out and "CON-11" in out


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


def test_service_key_env_name(monkeypatch: pytest.MonkeyPatch) -> None:
    from chaeksas.server_runner.credentials import service_key_env

    assert service_key_env("erp-key") == "CHK_SERVER_RUNNER__SVC__ERP_KEY"
    monkeypatch.setenv("CHK_SERVER_RUNNER__SVC__ERP_KEY", "secret")
    assert Credentials().service_app_key("erp-key") == "secret"


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
    """모델·읽기 폴더는 **설정이 정한다** — Bot UI는 BUI-03이 정하는 자리다 (ADR-0027·0032).

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


class _NoClient:
    """Center를 부르지 않는다 — 이 시험이 보는 것은 배선뿐이다."""


class _FakeBot:
    id = "fx.sample"
    version = "1.0.0"
    folder = Path(__file__).resolve().parent

    def processes(self) -> dict[str, Any]:
        return {}

    def decisions(self) -> dict[str, Any]:
        return {}
