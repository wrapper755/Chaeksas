"""STU-04 BPM 프로세스 기본값 편집기 (`studio/defaults_editor.py`) — 화면 없이, 끝에 메인 창과 캔버스.

보는 것은 다섯이다: 그림에 적힌 것이 **다 보이는가**, 손대지 않으면 **C14 모델로 같은 뜻인가**(업무 예제
전부), 읽는 곳 없는 칸(`web`)을 **지우지 않고 말하는가**, 속성 패널이 **`chk:defaults`만** 보내는가
(`chk:process`는 다른 자리의 것이다), 빈 상태의 단추가 **열린 정의를 패널에** 보이는가.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from chaeksas.contracts.bpmn_ext import Defaults, read_process  # noqa: E402
from chaeksas.studio.defaults_editor import UNREAD_WEB, DefaultsEditor  # noqa: E402

EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples" / "bpmn"
DEFAULTS: dict[str, Any] = {
    "limits": {"timeout_s": 180, "max_steps": 10},
    "forbidden_actions": ["파일을 수정·삭제하지 않는다"],
    "confirm_triggers": ["로그인 화면"],
    "desktop": {"app": "ERP Client"},
}


@pytest.fixture(autouse=True)
def app() -> Any:
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


def loaded(body: dict[str, Any] | None) -> DefaultsEditor:
    made = DefaultsEditor()
    made.load(body)
    return made


def test_everything_in_the_defaults_is_shown() -> None:
    made = loaded(DEFAULTS)
    assert made.max_steps_box.value() == 10
    assert made.timeout_box.value() == 180
    assert made.forbidden_box.toPlainText() == "파일을 수정·삭제하지 않는다"
    assert made.confirm_box.toPlainText() == "로그인 화면"
    assert made.app_box.text() == "ERP Client"
    assert made.problems() == ([], [])


def test_an_untouched_dump_reads_back_the_same() -> None:
    assert loaded(DEFAULTS).dump() == DEFAULTS


def test_every_example_defaults_round_trips() -> None:
    """업무 예제의 `chk:defaults`가 **손대지 않으면 같은 뜻으로** 돌아온다."""
    seen = 0
    for path in sorted(EXAMPLES.glob("*.bpmn")):
        found = read_process(path.read_text(encoding="utf-8")).defaults
        if found is None:
            continue
        made = loaded(found.model_dump(exclude_unset=True))
        assert made.problems()[0] == [], path.name
        assert Defaults.model_validate(made.dump()) == found, path.name
        seen += 1
    assert seen >= 1, "예제가 기본값을 쓴다"


def test_unread_web_is_kept_and_said() -> None:
    """`web`은 계약에 있지만 읽는 곳이 없다 — 지우지 않고 경고로 말한다."""
    made = loaded({**DEFAULTS, "web": {"profile": "supplier-portal"}, "future": 1})
    assert made.problems() == ([], [UNREAD_WEB])
    out = made.dump()
    assert out is not None and out["web"] == {"profile": "supplier-portal"} and out["future"] == 1


def test_clearing_one_limit_keeps_the_other() -> None:
    made = loaded(DEFAULTS)
    made.max_steps_box.setValue(0)
    out = made.dump()
    assert out is not None and out["limits"] == {"timeout_s": 180}


def test_clearing_everything_drops_the_element() -> None:
    made = loaded(DEFAULTS)
    made.max_steps_box.setValue(0)
    made.timeout_box.setValue(0)
    made.forbidden_box.setPlainText("")
    made.confirm_box.setPlainText("  \n")
    made.app_box.setText("")
    assert made.dump() is None


def test_an_empty_definition_opens_empty() -> None:
    made = loaded(None)
    assert made.dump() is None and made.problems() == ([], [])
    made.forbidden_box.setPlainText("삭제하지 않는다\n\n저장하지 않는다")
    assert made.dump() == {"forbidden_actions": ["삭제하지 않는다", "저장하지 않는다"]}


# ── 속성 패널 ──


def process_panel(chk: dict[str, Any]) -> Any:
    from chaeksas.studio.properties import Properties  # noqa: PLC0415

    panel = Properties()
    panel.show_element({
        "id": "Proc_1", "type": "Process", "name": "청구서 점검",
        "chk": {name: json.dumps(body, ensure_ascii=False) for name, body in chk.items()},
    })
    return panel


def tab_texts(panel: Any) -> list[str]:
    return [panel.tabs.tabText(i) for i in range(panel.tabs.count())]


PROCESS = {"run_location": "pc", "inputs": [{"name": "금액", "type": "number", "required": True}]}


def test_the_definition_gets_a_defaults_tab() -> None:
    panel = process_panel({"process": PROCESS, "defaults": DEFAULTS})
    assert tab_texts(panel) == ["폼", "기본값", "JSON"]
    assert panel.tabs.currentIndex() == 1
    assert panel.patch() == ({}, None), "손대지 않으면 보내지 않는다"


def test_only_chk_defaults_is_sent() -> None:
    """`chk:process`는 「변수」 탭·STU-06·STU-15의 것이다 — 이 탭은 그것을 보내지 않는다."""
    panel = process_panel({"process": PROCESS, "defaults": DEFAULTS})
    panel._editor.app_box.setText("Calculator")  # noqa: SLF001
    changes, problem = panel.patch()
    assert problem is None
    assert changes == {"chk": {"defaults": json.dumps({**DEFAULTS, "desktop": {"app": "Calculator"}},
                                                      ensure_ascii=False, indent=2)}}


def test_new_defaults_are_added_and_emptied_ones_removed() -> None:
    panel = process_panel({"process": PROCESS})
    panel._editor.max_steps_box.setValue(12)  # noqa: SLF001
    changes, _ = panel.patch()
    assert json.loads(changes["chk"]["defaults"]) == {"limits": {"max_steps": 12}}

    panel = process_panel({"defaults": {"limits": {"max_steps": 12}}})
    panel._editor.max_steps_box.setValue(0)  # noqa: SLF001
    assert panel.patch() == ({"chk": {"defaults": None}}, None)


def test_an_untouched_definition_without_defaults_sends_nothing() -> None:
    panel = process_panel({"process": PROCESS})
    panel.name_box.setText("다른 이름")
    assert panel.patch() == ({"name": "다른 이름"}, None)


def test_the_empty_state_has_the_button_and_hides_it_for_an_element() -> None:
    from chaeksas.studio.properties import Properties  # noqa: PLC0415

    panel = Properties()
    asked: list[bool] = []
    panel.process_wanted.connect(lambda: asked.append(True))
    assert not panel.process_button.isHidden()
    assert not panel.process_button.isEnabled(), "열린 정의가 없으면 끈다"
    panel.set_definition_open(True)
    panel.process_button.click()
    assert asked == [True]
    panel.show_element({"id": "Task_1", "type": "ScriptTask", "chk": {}})
    assert panel.process_button.isHidden()
    panel.show_nothing()
    assert not panel.process_button.isHidden()


# ── 메인 창과 캔버스 ──

_PROBE: list[Any] = []


def wait_for(condition: Callable[[], bool], ms: int = 30_000) -> bool:
    from PySide6.QtCore import QEventLoop, QTimer  # noqa: PLC0415

    loop = QEventLoop()
    poll = QTimer()
    poll.timeout.connect(lambda: loop.quit() if condition() else None)
    poll.start(50)
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
    poll.stop()
    return condition()


@pytest.fixture
def window(app: Any, tmp_path: Path) -> Any:
    """뜬 캔버스를 쥔 메인 창 — WebEngine이 못 뜨면 건너뛴다 (`test_studio_canvas`와 같은 태도)."""
    try:
        from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: PLC0415

        if not _PROBE:
            _PROBE.append(QWebEngineView())
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"QtWebEngine을 띄울 수 없다: {type(e).__name__}: {e}")
    from chaeksas.studio.main_window import MainWindow  # noqa: PLC0415
    from chaeksas.studio.settings import Settings  # noqa: PLC0415

    found = MainWindow(Settings(data_dir=tmp_path))
    if not wait_for(lambda: found.canvas.live):
        pytest.skip("캔버스가 30초 안에 뜨지 않았다 (WebEngine이 이 환경에서 막혀 있다)")
    return found


def test_the_button_shows_the_definition_and_applying_keeps_chk_process(window: Any) -> None:
    """빈 상태의 단추 → 열린 정의가 패널에 → 「적용」은 `chk:defaults`만 바꾸고 `chk:process`는 그대로다."""
    from chaeksas.studio import file_actions  # noqa: PLC0415

    made = window.workspace.import_example(EXAMPLES, "bx01_invoice_reconciliation")
    file_actions.open_definition(window, made.entry_definition.path.as_posix())
    panel = window.properties
    assert wait_for(lambda: panel.process_button.isEnabled())
    before = read_process(window.canvas.save_xml())

    panel.process_button.click()
    assert wait_for(lambda: panel.node_id == before.id)
    assert "기본값" in tab_texts(panel)
    panel._editor.max_steps_box.setValue(20)  # noqa: SLF001
    assert panel.apply() is True

    def steps() -> int | None:
        drawn = read_process(window.canvas.save_xml()).defaults
        return drawn.limits.max_steps if drawn is not None and drawn.limits is not None else None

    assert wait_for(lambda: steps() == 20)
    after = read_process(window.canvas.save_xml())
    assert after.info == before.info, "chk:process는 그대로다"
    assert after.defaults is not None and before.defaults is not None
    assert after.defaults.forbidden_actions == before.defaults.forbidden_actions
