"""Bot UI 화면 — 트레이(BUI-01)·설정(BUI-03)·메인 창(BUI-02·04).

화면 없이 돈다 (`QT_QPA_PLATFORM=offscreen`). **보이는 글과 켜짐/꺼짐만** 본다 — 그림을 보는
시험이 아니다. Windows 실기에서 봐야 하는 것(트레이 아이콘 실제 동작, 자동 시작 등록)은
여기서 못 하므로 로드맵에 남겨 둔다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

# PySide6를 불러오기 **전에** 정해야 한다.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from conftest import FakeAutostart, FakeCredentials  # noqa: E402

from chaeksas.bot_ui.agent import Agent  # noqa: E402
from chaeksas.bot_ui.settings import Settings  # noqa: E402
from chaeksas.bot_ui.store import Store  # noqa: E402
from chaeksas.contracts.bot_ui import CurrentRun, JobDispatch  # noqa: E402

AT = "2026-10-03T09:00:00+09:00"


@pytest.fixture(scope="session")
def app() -> Any:
    from PySide6.QtWidgets import QApplication  # noqa: PLC0415

    existing = QApplication.instance()
    if existing is not None:
        return existing
    try:
        return QApplication([])
    except Exception as e:  # pragma: no cover - 환경 문제
        pytest.skip(f"Qt 플랫폼 플러그인을 띄울 수 없다: {e}")


@pytest.fixture(autouse=True)
def fake_autostart(monkeypatch: Any) -> FakeAutostart:
    """설정 창의 「저장」이 **진짜 작업 스케줄러를 부르지 않게.**

    부르면 그 PC에 자동 시작이 등록되고, 권한이 없는 PC에서는 경고 창이 응답을 기다리며 시험이 멈춘다
    (이슈 #3). 다른 동작을 보려는 시험은 다시 `monkeypatch.setattr`로 바꾼다.
    """
    from chaeksas.bot_ui import autostart as autostart_module  # noqa: PLC0415

    fake = FakeAutostart()
    monkeypatch.setattr(autostart_module, "autostart", lambda: fake)
    return fake


@pytest.fixture(autouse=True)
def _cleanup_qt(app: Any) -> Any:
    """시험이 만든 창·트레이를 **반드시 지운다.**

    남겨 두면 뒤에 도는 모듈이 앱 전체에 테마를 다시 입힐 때 그 좀비 위젯을 건드린다 —
    Windows CI에서 `apply_theme`이 access violation으로 터졌다.
    """
    from PySide6.QtWidgets import QSystemTrayIcon  # noqa: PLC0415

    yield
    for tray in app.findChildren(QSystemTrayIcon):
        tray.hide()
        tray.setParent(None)
        tray.deleteLater()
    for widget in app.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    app.processEvents()


@pytest.fixture
def agent(tmp_path: Path) -> Agent:
    return Agent(
        settings=Settings(name="재무팀 PC-03"),
        store=Store.load(tmp_path / "state.json"),
        credentials=FakeCredentials("chk_ctr_test"),
    )


def job(job_id: str = "job_1") -> JobDispatch:
    return JobDispatch(
        job_id=job_id, bpm_process_id="erp.order-entry", version="2.1.0", requested_by="홍길동", requested_at=AT
    )


# ─────────────────────────── BUI-01 트레이 ───────────────────────────


def test_tray_status_text_follows_the_screen_spec(agent: Agent) -> None:
    """BUI-01의 상태 글. 트레이 툴팁과 상태 줄이 같은 글을 쓴다."""
    agent.store.state.bot_ui_id = "bui_1"
    assert agent.tray_status() == "대기"

    agent.take_job(job())
    assert agent.tray_status() == "대기 · 대기 1건"

    agent.current_run = CurrentRun(
        run_id="run_1", bpm_process_id="erp.order-entry", version="2.1.0", state="running",
        started_at=AT, source="job",
    )
    assert agent.tray_status() == "실행 중 · 대기 1건"

    agent.current_run = agent.current_run.model_copy(update={"state": "waiting_approval"})
    assert agent.tray_status() == "결재 대기"
    agent.current_run = agent.current_run.model_copy(update={"state": "waiting_confirmation"})
    assert agent.tray_status() == "확인 대기"


def test_wire_status_uses_the_contract_words(agent: Agent) -> None:
    """트레이 글과 **하트비트의 `status`는 다르다** — 하나는 사람, 하나는 C4의 값이다."""
    from chaeksas.contracts.bot_ui import KNOWN_BOT_UI_STATUSES  # noqa: PLC0415

    agent.store.state.bot_ui_id = "bui_1"
    assert agent.wire_status() == "idle"
    agent.current_run = CurrentRun(
        run_id="run_1", bpm_process_id="a", version="1.0.0", state="waiting_approval", started_at=AT, source="job"
    )
    assert agent.wire_status() in KNOWN_BOT_UI_STATUSES


def test_tray_icon_has_a_status_dot(app: Any, agent: Agent) -> None:
    from chaeksas.bot_ui.tray import status_color, tray_icon  # noqa: PLC0415

    agent.store.state.bot_ui_id = "bui_1"
    icon = tray_icon(agent.tray_status())
    assert not icon.isNull()
    # 상태마다 점 색이 다르다 (색은 토큰에서 온다 — 값을 코드에 적지 않는다).
    assert status_color("연결 끊김") != status_color("대기")
    assert status_color("모르는 상태"), "모르는 글에도 색이 있다 (계약 원칙 10)"


def test_tray_menu_shows_the_information_rows(app: Any, agent: Agent) -> None:
    from chaeksas.bot_ui.tray import Tray  # noqa: PLC0415

    agent.store.state.bot_ui_id = "bui_1"
    agent.take_job(job())
    tray = Tray(agent, parent=app)
    texts = [action.text() for action in tray.contextMenu().actions()]

    assert any("재무팀 PC-03" in text for text in texts)
    assert "실행 중인 Bot 없음" in texts
    assert any("대기열 1건 — 다음: erp.order-entry" in text for text in texts)
    assert any("Worker: 꺼 둠" in text for text in texts)
    # 누를 수 있는 것은 이것뿐이다.
    assert {"창 열기", "설정...", "종료"} <= set(texts)
    assert tray.toolTip() == "Chaeksas Bot UI · 대기 · 대기 1건"


def test_the_tray_menu_is_rebuilt_on_refresh(app: Any, agent: Agent) -> None:
    """BUI-01 — 상태가 바뀔 때마다 다시 만든다."""
    from chaeksas.bot_ui.tray import Tray  # noqa: PLC0415

    agent.store.state.bot_ui_id = "bui_1"
    tray = Tray(agent, parent=app)
    assert not any("대기열" in a.text() for a in tray.contextMenu().actions())
    agent.take_job(job())
    tray.refresh()
    assert any("대기열 1건" in a.text() for a in tray.contextMenu().actions())


# ─────────────────────────── BUI-03 설정 ───────────────────────────


def test_settings_dialog_never_shows_the_key(app: Any, agent: Agent) -> None:
    """키는 **값이 보이지 않는다** — 저장되어 있다는 사실만 알려 준다."""
    from PySide6.QtWidgets import QLineEdit  # noqa: PLC0415

    from chaeksas.bot_ui.settings_dialog import KEY_SET_PLACEHOLDER, SettingsDialog  # noqa: PLC0415

    dialog = SettingsDialog(agent)
    assert dialog.api_key.text() == ""
    assert dialog.api_key.placeholderText() == KEY_SET_PLACEHOLDER
    assert dialog.api_key.echoMode() == QLineEdit.EchoMode.Password
    assert "chk_ctr_test" not in dialog.result_label.text()


def test_settings_dialog_saves_to_the_file_without_secrets(app: Any, agent: Agent, tmp_path: Path) -> None:
    from chaeksas.bot_ui.settings_dialog import SettingsDialog  # noqa: PLC0415

    dialog = SettingsDialog(agent)
    dialog.center_url.setText("http://center.example.com:8800")
    dialog.queue_max.setValue(5)
    dialog.api_key.setText("chk_ctr_newkey")

    dialog.save()

    assert agent.settings.center_url == "http://center.example.com:8800"
    assert agent.settings.queue_max == 5
    assert agent.credentials.center_api_key() == "chk_ctr_newkey"
    # 저장은 시험용 데이터 폴더로 간다 (conftest) — 개발 PC의 진짜 설정이 아니다.
    path = agent.settings.config_path
    assert path.parent == Path(os.environ["CHK_BOT_UI__DATA_DIR"])
    # **설정 파일에 키가 없다** (CLAUDE.md §5).
    assert "chk_ctr_newkey" not in path.read_text(encoding="utf-8")


def test_a_failed_autostart_is_not_saved_as_on(app: Any, agent: Agent, monkeypatch: Any) -> None:
    """권한이 없어 등록이 실패하면 경고하고, 칸·설정 파일을 **OS의 실제 상태**로 되돌린다 (BUI-03, 이슈 #3)."""
    from PySide6.QtWidgets import QMessageBox  # noqa: PLC0415

    from chaeksas.bot_ui import autostart as autostart_module  # noqa: PLC0415
    from chaeksas.bot_ui import settings_dialog  # noqa: PLC0415

    failing = FakeAutostart(fail="자동 시작을 등록하지 못했습니다: 오류: 액세스가 거부되었습니다.")
    monkeypatch.setattr(autostart_module, "autostart", lambda: failing)
    warnings: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, _title, text: warnings.append(text))

    dialog = settings_dialog.SettingsDialog(agent)
    dialog.autostart.setChecked(True)
    dialog.save()

    assert failing.calls == ["enable"]
    assert warnings == ["자동 시작을 등록하지 못했습니다: 오류: 액세스가 거부되었습니다."]
    assert dialog.autostart.isChecked() is False
    assert agent.settings.autostart is False
    assert Settings.load(agent.settings.config_path).autostart is False


def test_settings_dialog_reports_why_a_connection_failed(app: Any, tmp_path: Path) -> None:
    from chaeksas.bot_ui.settings_dialog import SettingsDialog  # noqa: PLC0415

    agent = Agent(
        settings=Settings(center_url="http://127.0.0.1:9"),  # 아무도 듣지 않는 포트
        store=Store.load(tmp_path / "state.json"),
        credentials=FakeCredentials("chk_ctr_test"),
    )
    dialog = SettingsDialog(agent)
    dialog.test_connection()
    assert "닿지 못함" in dialog.result_label.text()


def test_autostart_box_is_off_where_it_cannot_work(app: Any, agent: Agent, monkeypatch: Any) -> None:
    """U3 — 할 수 없는 OS면 끄고 이유를 보인다."""
    from chaeksas.bot_ui import autostart as autostart_module  # noqa: PLC0415
    from chaeksas.bot_ui.settings_dialog import SettingsDialog  # noqa: PLC0415

    monkeypatch.setattr(autostart_module, "autostart", lambda: autostart_module.NoAutostart())
    dialog = SettingsDialog(agent)
    assert not dialog.autostart.isEnabled()
    assert dialog.autostart.toolTip() == autostart_module.NoAutostart.reason


# ─────────────────────────── BUI-02·04 메인 창 ───────────────────────────


def test_main_window_shows_the_queue_without_values(app: Any, agent: Agent) -> None:
    """BUI-04 — 「입력 키」는 **이름만** 보인다 (U10)."""
    from chaeksas.bot_ui.main_window import MainWindow  # noqa: PLC0415

    agent.store.state.bot_ui_id = "bui_1"
    found = job()
    agent.take_job(found.model_copy(update={"inputs": {"금액": 999999, "거래처": "주식회사 가나"}}))

    window = MainWindow(agent)
    assert window.queue_table.rowCount() == 1
    def cell(column: int) -> str:
        item = window.queue_table.item(0, column)
        assert item is not None
        return item.text()

    row = [cell(c) for c in range(window.queue_table.columnCount())]
    assert row[1] == "erp.order-entry 2.1.0"
    assert row[2] == "Center 작업"
    assert row[5] == "거래처, 금액"
    assert "999999" not in " ".join(row)
    assert window.queue_title.text() == "대기 1/20"


def test_main_window_empty_queue_disables_cancel(app: Any, agent: Agent) -> None:
    from chaeksas.bot_ui.main_window import MainWindow  # noqa: PLC0415

    window = MainWindow(agent)
    assert window.running_label.text() == "실행 중인 Bot이 없습니다."
    assert not window.cancel_button.isEnabled()
    assert window.cancel_button.toolTip() == "기다리는 실행이 없습니다."


def test_main_window_status_bar_matches_the_spec(app: Any, agent: Agent) -> None:
    from chaeksas.bot_ui.main_window import MainWindow  # noqa: PLC0415

    agent.store.state.bot_ui_id = "bui_1"
    window = MainWindow(agent)
    assert window.statusBar().currentMessage() == f"대기 · Center {agent.settings.center_url}"


# ─────────────────────────── 종료 순서 (BUI-01 10번) ───────────────────────────


def test_shutdown_reports_center_jobs_as_rejected(app: Any, tmp_path: Path) -> None:
    """종료 순서: 새 요청 막기 → **대기열의 Center 작업을 「거절 — Bot UI 종료」로 보고** →
    실행기 취소 → Worker 종료 (C4 `bot_ui_shutdown`).
    """
    from PySide6.QtWidgets import QApplication  # noqa: PLC0415

    from chaeksas.bot_ui.app import BotUiApp  # noqa: PLC0415
    from chaeksas.core.processes import ChildProcess, Supervisor  # noqa: PLC0415

    agent = Agent(
        settings=Settings(center_url="http://127.0.0.1:9"),  # 보고는 닿지 못한다 — 디스크에 남아야 한다
        store=Store.load(tmp_path / "state.json"),
        credentials=FakeCredentials("chk_ctr_test"),
    )
    agent.store.state.bot_ui_id = "bui_1"
    agent.take_job(job("job_center"))
    agent.enqueue_manual("수동으로 넣은 것")

    worker = Supervisor(child=ChildProcess(args=[sys.executable, "-c", "import time; time.sleep(60)"]))
    worker.start()
    agent.supervisors["worker"] = worker

    existing = QApplication.instance()
    assert isinstance(existing, QApplication)
    found = BotUiApp(existing, agent)
    found.shutdown()

    # Center 작업은 거절로 보고되고 대기열에서 빠진다. 수동 항목은 그냥 사라진다.
    assert agent.store.state.seen_jobs["job_center"].reason == "bot_ui_shutdown"
    assert [item.job_id for item in agent.queue] == [None]
    # 닿지 못했으니 ack는 디스크에 남아 다음에 간다 (C4).
    assert [a.job_id for a in agent.store.state.pending_acks] == ["job_center"]
    # Worker는 꺼졌다 (ADR-0023 — 트리째).
    assert worker.state == "off" and not worker.child.alive
