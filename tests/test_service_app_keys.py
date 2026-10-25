"""서비스 앱 키와 사전 점검 — 키가 없으면 막고, 있으면 돈다 (로드맵 M5, ADR-0013·0094).

키는 이제 **Center가 배포와 함께 내려 준다** (ADR-0094 — `test_service_keys.py`가 그 길을 본다).
여기서는 「이 PC에 값이 있나」를 보는 사전 점검이 그대로인지 본다 — 값을 넣는 길은 시험이 비밀
저장소에 바로 넣는다(관리 API 발급은 자동화·시험용으로 남았다).

보는 것은 **네 조각이 한 줄로 맞물리는가**다.

1. 앱의 관리 API가 키를 발급한다 (`service_kit`, C11 — 자동화·시험용) — 원문은 한 번만 온다.
2. 시험이 그 값을 참조 이름으로 이 PC의 비밀 저장소에 넣는다 (Center가 내려 줄 때와 같은 자리를 본다).
3. **사전 점검**이 빠진 키를 잡고(`core.preflight`), 넣으면 「준비됨」이 된다.
4. **C4 `readiness`**가 그것을 Center로 올리고, 준비되지 않은 Bot은 **시작되지 않는다**
   (작업 ack `rejected`·`not_ready`).

앱은 **진짜 소켓**에 뜬 모의 앱이다 (`samples/mock_apps` — TestClient가 아니다). 그래야 「확인」이
부르는 `GET /v1/keys/self`(Studio 「연결 테스트」가 쓴다)가 실제로 왕복한다. 바깥에 나가지 않는다 — 127.0.0.1이다.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from conftest import FakeCredentials

from chaeksas.bot_ui.agent import Agent
from chaeksas.bot_ui.main_window import NO_KEYS, READY, readiness_label
from chaeksas.bot_ui.settings import Settings, data_dir
from chaeksas.bot_ui.store import Store
from chaeksas.core.extensions import load_host
from chaeksas.core.key_check import key_status
from chaeksas.core.packages import InstalledBot, install
from chaeksas.mock_apps import catalog
from chaeksas.mock_apps.c11 import build as build_mock

#: BX-36이 부르는 앱과 그 키 참조 — 예제가 정한 것이다 (눈으로 고른 이름이 아니다).
APP_ID = "crm"
KEY_REF = "it-crm"
#: 같은 예제의 UI 태스크가 부르는 UI 자동화 앱 키 — 키를 받는 확장의 줄도 매니페스트에 든다 (ADR-0094).
UI_REF = "it-legacy-ui"
EXAMPLE = "bx36_legacy_migration"
EXAMPLES = Path("docs/08-business-examples/bpmn")

#: 모의 앱의 관리자 토큰 (C11 — 없으면 관리 API가 503으로 닫혀 있다).
ADMIN_TOKEN = "t-mock-crm-admin"
ADMIN = {"Authorization": f"Bearer {ADMIN_TOKEN}"}


@pytest.fixture(scope="session")
def qt_app() -> Any:
    from PySide6.QtWidgets import QApplication  # noqa: PLC0415

    existing = QApplication.instance()
    if existing is not None:
        return existing
    try:
        return QApplication([])
    except Exception as e:  # pragma: no cover - 환경 문제
        pytest.skip(f"Qt 플랫폼 플러그인을 띄울 수 없다: {e}")


@pytest.fixture(scope="module")
def crm_app() -> Iterator[str]:
    """모의 `crm` 앱을 127.0.0.1의 빈 포트에 띄운다 — 관리 API를 열어 둔다 (SVC-02)."""
    os.environ.setdefault("CHK_MOCK_APPS__DEV_KEY", "chk_svc_mock_dev_key_0001")
    mock = next(one for one in catalog.C11_APPS if one.app_id == APP_ID)
    built = build_mock(mock, admin_token=ADMIN_TOKEN)
    server = uvicorn.Server(uvicorn.Config(built.app, host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started, "모의 앱이 뜨지 않았다"
    yield f"http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}"
    server.should_exit = True
    thread.join(timeout=10)


def issue(base_url: str, name: str) -> str:
    """관리 API 발급 (C11 — 자동화·시험용, SVC-02 화면에는 없다). **원문은 이 응답에만 있다**.

    앱은 모듈 수명이라 **시험마다 다른 이름**을 쓴다 — 같은 이름을 두 번 발급하면 C11이 409로
    거절한다 (그래야 어느 키인지 알 수 있다, C11 §키 이름).
    """
    import httpx  # noqa: PLC0415

    answer = httpx.post(f"{base_url}/admin/v1/keys", json={"name": name}, headers=ADMIN, timeout=10)
    assert answer.status_code == 201, answer.text
    raw = answer.json()["key"]
    assert raw, "발급 응답에 원문이 없다"
    # 목록에는 원문이 없어야 한다 (C11 — 앞자리만).
    listed = httpx.get(f"{base_url}/admin/v1/keys", headers=ADMIN, timeout=10).json()
    assert raw not in str(listed)
    return str(raw)


def install_example(tmp_path: Path) -> InstalledBot:
    """Studio처럼 내보내고 Bot UI에 설치한다 (배포 길은 `test_m5_pc_rerun.py`가 본다)."""
    from chaeksas.studio.packaging import export  # noqa: PLC0415
    from chaeksas.studio.workspace import Workspace  # noqa: PLC0415

    made = Workspace(tmp_path / "studio").ensure().import_example(EXAMPLES, EXAMPLE)
    return install(data_dir(), export(made, tmp_path / "bot.zip"))


def make_agent(tmp_path: Path, **extra: Any) -> Agent:
    return Agent(
        settings=Settings(center_url="http://127.0.0.1:1", **extra),
        store=Store.load(tmp_path / "state.json"),
        credentials=FakeCredentials(),
        host=load_host(),
    )


# ─────────────────────────── 한 바퀴 ───────────────────────────


def test_issue_in_the_console_register_in_bot_ui_and_the_check_goes_green(
    crm_app: str, tmp_path: Path
) -> None:
    """로드맵 M5의 그 줄 — **발급 → 등록 → 사전 점검이 빠진 키를 잡음**."""
    bot = install_example(tmp_path)
    agent = make_agent(tmp_path)

    # ① 아직 키가 없다 — 사전 점검이 그 참조를 집어서 말한다.
    before = agent.preflight(bot)
    assert before.blocks and before.missing_key_refs == (KEY_REF, UI_REF)
    token, shown, tip = readiness_label(before)
    assert token == NO_KEYS and shown == f"{NO_KEYS}: {KEY_REF}, {UI_REF}"
    assert KEY_REF in tip, "무엇이 빠졌는지 툴팁에 있어야 고칠 수 있다"

    # ② 발급받아 참조 이름으로 넣는다 (현장에서는 Center가 배포와 함께 내려 준다).
    raw = issue(crm_app, KEY_REF)
    agent.credentials.set_service_app_key(KEY_REF, raw)
    agent.credentials.set_service_app_key(UI_REF, "chk_svc_ui000000000000")
    agent.invalidate_preflight()

    # ③ 이제 막지 않는다.
    after = agent.preflight(bot)
    assert not after.blocks and after.blocked == ()
    assert readiness_label(after)[0] == READY

    # ④ 「확인」이 앱에 물으면 그 키가 살아 있다고 답한다 (C11 `/v1/keys/self`).
    assert key_status(crm_app, raw).startswith("정상")


def test_the_heartbeat_reports_the_readiness_so_con_03_can_show_it(crm_app: str, tmp_path: Path) -> None:
    """C4 `readiness` — 올리지 않으면 「왜 설치가 안 됐나」가 CON-03에 영영 안 남는다."""
    bot = install_example(tmp_path)
    agent = make_agent(tmp_path)

    missing = agent.heartbeat_request().readiness
    assert [(one.bpm_process_id, one.ready, one.missing_key_refs) for one in missing] == [
        (bot.id, False, [KEY_REF, UI_REF])
    ]
    assert missing[0].blocked == ["missing_service_app_keys"], "막힘 코드는 C4의 열린 문자열이다"

    agent.credentials.set_service_app_key(KEY_REF, issue(crm_app, "하트비트-시험"))
    agent.credentials.set_service_app_key(UI_REF, "chk_svc_ui000000000000")
    agent.invalidate_preflight()
    ready = agent.heartbeat_request().readiness
    assert (ready[0].ready, ready[0].missing_key_refs, ready[0].blocked) == (True, [], [])


def test_a_bot_with_no_key_is_refused_instead_of_started(tmp_path: Path) -> None:
    """ADR-0013 §사전 점검 — 띄우면 그 태스크에서 죽는다. **띄우기 전에** 거절한다."""
    bot = install_example(tmp_path)
    agent = make_agent(tmp_path)
    item = agent.enqueue_manual(bot.id, version=bot.version)
    agent.store.state.inputs[item.queue_id] = {}

    agent._start_next()

    assert agent.current_run is None, "실행 자리를 쥐지 않았다"
    assert agent.queue == [], "대기열에 남겨 두면 영원히 막힌다"


def test_a_center_job_is_acked_as_not_ready(tmp_path: Path) -> None:
    """C4 — 사람이 Center에서 「왜 안 돌았나」를 알아야 한다 (`rejected`·`not_ready`)."""
    bot = install_example(tmp_path)
    agent = make_agent(tmp_path)
    item = agent.enqueue_manual(bot.id, version=bot.version)
    agent.store.state.queue = [item.model_copy(update={"source": "job", "job_id": "job_1"})]

    agent._start_next()

    acks = [(one.job_id, one.result, one.reason) for one in agent.store.state.pending_acks]
    assert acks == [("job_1", "rejected", "not_ready")]


def test_registering_the_key_lets_the_same_bot_start(tmp_path: Path) -> None:
    """빠진 키를 넣으면 **다음 주기에** 돌아야 한다 — 캐시가 그것을 막으면 안 된다.

    사전 점검은 「값이 있나」까지만 본다 (서버를 부르지 않는다) — 그래서 여기 값은 아무것이나 된다.
    「맞는 키인가」는 앱이 부를 때 답한다.
    """
    bot = install_example(tmp_path)
    agent = make_agent(tmp_path)
    agent.runner().make_child = _FakeChild
    agent.credentials.set_service_app_key(KEY_REF, "chk_svc_x000000000000")
    agent.credentials.set_service_app_key(UI_REF, "chk_svc_ui000000000000")
    agent.invalidate_preflight()

    item = agent.enqueue_manual(bot.id, version=bot.version)
    agent.store.state.inputs[item.queue_id] = {}
    agent._start_next()

    assert agent.current_run is not None, "준비됐으면 시작한다"


class _FakeChild:
    """실행기 자식 대신 — **띄웠나**까지만 본다 (실제 실행은 M4·M5 인수 시험이 본다)."""

    def __init__(self, **_: Any) -> None:
        self.started = 0

    def start(self) -> None:
        self.started += 1

    @property
    def alive(self) -> bool:
        return True

    def poll(self) -> int | None:
        return None

    def stop(self, **_: Any) -> None:
        return None


# ─────────────────────────── BUI-04 「준비」 ───────────────────────────


def test_the_readiness_label_only_uses_words_from_the_status_map() -> None:
    """CLAUDE.md §5 — 상태 표기는 `status_map`에 있는 것만 쓴다 (색이 붙지 않는다)."""
    from chaeksas.core.preflight import (  # noqa: PLC0415
        EXTENSIONS_UNUSABLE,
        MISSING_ENVIRONMENT,
        MISSING_KEYS,
        TASK_TYPES_UNSUPPORTED,
        Preflight,
    )
    from chaeksas.extension_api import SEVERITY_BLOCK, Finding  # noqa: PLC0415
    from chaeksas.qt import theme  # noqa: PLC0415

    cases = [
        Preflight(),
        Preflight((Finding(id=MISSING_KEYS, severity=SEVERITY_BLOCK, message="", items=("a",)),)),
        Preflight((Finding(id=TASK_TYPES_UNSUPPORTED, severity=SEVERITY_BLOCK, message=""),)),
        Preflight((Finding(id=EXTENSIONS_UNUSABLE, severity=SEVERITY_BLOCK, message=""),)),
        Preflight((Finding(id=MISSING_ENVIRONMENT, severity=SEVERITY_BLOCK, message=""),)),
        Preflight((Finding(id="pages", severity=SEVERITY_BLOCK, message=""),)),
    ]
    for one in cases:
        token, _shown, _tip = readiness_label(one)
        assert theme.status_color("Bot 준비", token) is not None, f"표에 없는 표기: {token}"


def test_the_bots_table_says_the_key_has_not_arrived_and_offers_no_button(qt_app: Any, tmp_path: Path) -> None:
    """BUI-04 — 키는 Center가 내려 주므로 「키 등록...」 단추가 없다 (BUI-10은 없다, ADR-0094)."""
    from chaeksas.bot_ui.main_window import READY_COLUMN, MainWindow  # noqa: PLC0415

    install_example(tmp_path)
    window = MainWindow(make_agent(tmp_path))

    assert window.bots_table.cellWidget(0, READY_COLUMN) is None
    item = window.bots_table.item(0, READY_COLUMN)
    assert item is not None and item.text() == f"{NO_KEYS}: {KEY_REF}, {UI_REF}"
    assert "Center가 배포와 함께" in item.toolTip()
    window.close()
