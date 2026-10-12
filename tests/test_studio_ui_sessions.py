"""STU-09 아래 탭 「UI 태스크」 — 그 시험 실행의 UI 세션 한 줄씩 (C3 `ui_session`).

이 탭은 「화면」이라는 이름으로 「실행 중 스크린샷」을 보이기로 적혀 있었고, **그것을 걷은 것이
이 조각이다** (화면 문서 STU-09 「「UI 태스크」 탭」). 그래서 여기서 지키는 것이 둘이다.

1. **재료가 C3 `ui_session`이고 열이 CON-01과 같다** — 플랫폼 계약이라 Studio가 그려도 UI
   자동화를 알게 되지 않는다 (BUI-09는 재료가 C10이라 확장이 그린다, ADR-0042).
2. **그림이 들어올 길이 없다** — C10에 이미지 칸이 없고 C3는 `data`에 스크린샷을 금한다.
   누가 그 길을 다시 열면 이 시험이 먼저 말한다.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

#: 업무 예제 — 시험 실행 하나를 짜려면 작업 폴더에 정의가 있어야 한다.
EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples" / "bpmn"

from chaeksas.contracts.events import REQUIRED_DATA_KEYS, RunEvent  # noqa: E402
from chaeksas.qt.theme import tokens  # noqa: E402
from chaeksas.studio.ui_sessions import (  # noqa: E402
    CASE,
    COLUMNS,
    EMPTY,
    NONE,
    RESULT,
    RESULT_LABEL,
    STATUS_GROUP,
    Row,
    UiSessions,
    row_of,
)


@pytest.fixture(scope="session")
def app() -> Any:
    from PySide6.QtWidgets import QApplication

    try:
        return QApplication.instance() or QApplication([])
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"Qt를 띄울 수 없다: {type(e).__name__}: {e}")


RUN = "test_20261012_010203_abc123"


def session(**extra: Any) -> RunEvent:
    """C3 `ui_session` 줄 하나 — 필수 키 여섯이 다 있다 (C3)."""
    data: dict[str, Any] = {
        "business_key": f"{RUN}:T1:1:1",
        "page_id": "order-form",
        "result": "success",
        "steps": 4,
        "fallback_depth_max": 0,
        "healed": False,
    }
    data.update(extra)
    return RunEvent(schema=1, run_id=RUN, seq=7, ts="2026-10-12T01:02:03Z", kind="ui_session",
                    node_id="T1", data=data)


# ─────────────────────── 줄 짓기 (Qt 없이 시험한다) ───────────────────────


def test_a_session_line_becomes_a_row() -> None:
    found = row_of(session(), case="정상 주문")
    assert found == Row(
        case="정상 주문",
        node_id="T1",
        page_id="order-form",
        result="성공",
        steps="4",
        fallback_depth_max="0",
        healed="아니오",
    )


def test_escalated_is_its_own_word_not_a_failure() -> None:
    """전환은 실패가 아니다 (C10) — 표기도 다르다."""
    assert row_of(session(result="escalated")).result == "전환"
    assert row_of(session(result="failed")).result == "실패"


def test_an_unknown_result_shows_as_it_came() -> None:
    """상태는 **열린 문자열**이다 (계약 원칙 10) — 모르는 값 하나로 표가 깨지지 않는다."""
    assert row_of(session(result="rescheduled")).result == "rescheduled"


def test_every_result_word_is_in_the_status_map() -> None:
    """표기는 `status_map`에 있는 것만 쓴다 (스타일 가이드 §2-2)."""
    known = tokens.STATUS_MAP[STATUS_GROUP]
    assert set(RESULT_LABEL.values()) <= set(known)


def test_running_is_not_one_of_the_words_we_write() -> None:
    """줄은 세션이 **끝날 때** 생긴다 — 「진행 중」은 BUI-09가 아는 것이다 (UIA-03도 같다)."""
    assert "진행 중" not in RESULT_LABEL.values()


def test_a_missing_count_is_a_dash_not_zero() -> None:
    """0으로 보이면 「없었다」로 읽힌다 (CON-01의 셈 열과 같은 결)."""
    found = row_of(session(steps=None, fallback_depth_max=None))
    assert (found.steps, found.fallback_depth_max) == (NONE, NONE)


def test_the_case_name_comes_from_the_caller() -> None:
    """케이스는 C3 `ui_session`에 없다 — 돌리는 쪽이 준다. 없으면 「—」."""
    assert "case_id" not in REQUIRED_DATA_KEYS["ui_session"]
    assert row_of(session()).case == NONE


def test_a_row_has_exactly_one_cell_per_column() -> None:
    assert len(row_of(session()).cells) == len(COLUMNS)


# ─────────────────────── 그림은 들어올 길이 없다 ───────────────────────


def test_the_run_event_contract_has_no_screenshot() -> None:
    """C3가 `data`에 스크린샷을 금한다 — 실행 기록으로 올 길이 없다 (화면 문서 STU-09)."""
    keys = REQUIRED_DATA_KEYS["ui_session"]
    assert not {key for key in keys if "shot" in key or "image" in key or "snapshot" in key}


def test_the_worker_step_result_has_no_image() -> None:
    """C10도 그림을 주지 않는다 — 치유에 가는 것은 **가린 글**이다 (C8 `aria_snapshot`)."""
    from chaeksas.ext.ui_automation.contracts.worker_local import SessionSummary, StepResult

    for model in (StepResult, SessionSummary):
        fields = set(model.model_fields)
        assert not {name for name in fields if "shot" in name or "image" in name}


def test_the_tab_shows_the_page_as_text_only() -> None:
    """「화면」은 글자 하나(`page_id`)다 — 그림이 아니고, 링크도 아니다 (창은 Center를 안 부른다)."""
    assert row_of(session()).page_id == "order-form"


# ─────────────────────── 표 (Qt) ───────────────────────


def test_the_table_starts_with_the_empty_state(app: Any) -> None:
    """빈 상태는 **다음에 할 일**이 아니라 「없다」를 말한다 — 실행이 돌아야 생기는 표다 (U12)."""
    table = UiSessions()
    item = table.item(0, CASE)
    assert item is not None and item.text() == EMPTY


def test_adding_a_row_replaces_the_empty_state(app: Any) -> None:
    table = UiSessions()
    table.add(row_of(session(), case="정상 주문"))
    assert table.rowCount() == 1
    first = table.item(0, CASE)
    assert first is not None and first.text() == "정상 주문"


def test_rows_pile_up_across_cases(app: Any) -> None:
    """「모든 케이스 차례로」 — 케이스마다 비우지 않는다 (마지막 케이스가 앞의 전환을 덮지 않게)."""
    table = UiSessions()
    table.add(row_of(session(), case="첫째"))
    table.add(row_of(session(result="escalated"), case="둘째"))
    assert table.rowCount() == 2
    cells = [table.item(row, CASE) for row in range(2)]
    assert [one.text() for one in cells if one is not None] == ["첫째", "둘째"]
    second = table.item(1, RESULT)
    assert second is not None and second.text() == "전환"


def test_resetting_brings_the_empty_state_back(app: Any) -> None:
    """「실행」 한 번에 한 번 비운다 (`run_actions.run_test`)."""
    table = UiSessions()
    table.add(row_of(session()))
    table.reset_rows()
    assert table.rowCount() == 1
    item = table.item(0, CASE)
    assert item is not None and item.text() == EMPTY


def test_an_unknown_result_has_no_colour(app: Any) -> None:
    """색은 그 표기의 것만 — 모르는 상태는 글자만 보인다 (U7: 색만으로 말하지 않는다)."""
    table = UiSessions()
    table.add(row_of(session(result="rescheduled")))
    item = table.item(0, RESULT)
    assert item is not None and item.text() == "rescheduled"


# ─────────────────────── 시험 실행이 그 줄을 올린다 ───────────────────────


def test_the_runner_hands_the_session_line_up(app: Any, tmp_path: Path) -> None:
    """「로그」·「변수」 탭과 **같은 길**이다 — 시험 실행이 받는 C3 이벤트에서 온다.

    줄을 짓는 것은 탭이므로 실행은 **이벤트를 그대로** 올린다 (ADR-0041 — 뜻은 C3가 정한다).
    """
    from dataclasses import replace

    from chaeksas.studio.runner import CaseRun, Plan
    from chaeksas.studio.settings import Settings
    from chaeksas.studio.workspace import Workspace

    settings = replace(Settings(), data_dir=tmp_path / "studio", llm_base_url="")
    made = Workspace(settings.workspace_dir).ensure().import_example(EXAMPLES, "fx02_business_rule")
    definition = made.entry_definition
    assert definition is not None

    run = CaseRun(Plan(process=made, definition=definition, case=None, settings=settings))
    seen: list[Any] = []
    run.ui_session.connect(seen.append)
    event = session()
    run._on_event(event)
    assert seen == [event]
    assert row_of(seen[0]).page_id == "order-form"
