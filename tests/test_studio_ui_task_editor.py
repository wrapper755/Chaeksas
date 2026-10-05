"""STU-13 UI 태스크 편집기 (M4 조각 13).

화면 없이 돈다 (`QT_QPA_PLATFORM=offscreen`). 카탈로그는 가짜 HTTP다.

거듭 보는 것 다섯.

1. **셀렉터는 보이지 않는다** (ADR-0008) — 고를 것은 공개 카탈로그의 시맨틱 정보뿐이다.
2. **그 요소가 할 수 있는 동작만** 고른다.
3. **값·결과 변수가 빠지면 오류**이고 「적용」이 막힌다. 실행할 때 알면 늦다.
4. **등록되지 않은 요소·선행 입력 빠짐은 경고**다 — 막지 않는다 (아직 등록 전일 수 있다).
5. **서버에 닿지 못해도 고칠 수 있다** — 마지막 목록을 쓰고 「(오프라인)」이라고 말한다.
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from chaeksas.ext.ui_automation.client.catalog import Catalog, read_catalog  # noqa: E402
from chaeksas.ext.ui_automation.client.editor import UiTaskEditor  # noqa: E402

CATALOG: dict[str, Any] = {
    "schema": 1,
    "revision": 7,
    "items": [
        {
            "type": "ui_page",
            "id": "erp.order.form",
            "name": "주문 입력",
            "data": {
                "platform": "web",
                "revision": 4,
                "elements": [
                    {"semantic_key": "order.customer", "name": "거래처", "kind": "control",
                     "actions": ["fill"]},
                    {"semantic_key": "order.qty", "name": "수량", "kind": "control",
                     "actions": ["fill", "read_selection"], "depends_on": ["order.customer"]},
                    {"semantic_key": "order.total", "name": "합계", "kind": "text",
                     "actions": ["read"]},
                    {"semantic_key": "order.save", "name": "저장", "kind": "control",
                     "actions": ["click"], "navigates_to": "erp.order.list"},
                ],
            },
        },
        {"type": "bot", "id": "다른 종류", "data": {}},
    ],
}


class FakeHttp:
    """`GET /v1/catalog`를 흉내 낸다."""

    def __init__(self, *, body: Any = None, status: int = 200, fail: bool = False) -> None:
        self.body = CATALOG if body is None else body
        self.status = status
        self.fail = fail
        self.calls = 0

    def get(self, url: str) -> Any:
        import httpx  # noqa: PLC0415

        self.calls += 1
        if self.fail:
            raise httpx.ConnectError("닿지 못했다")
        return httpx.Response(self.status, json=self.body)


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


@pytest.fixture
def made(app: Any) -> Any:
    editor = UiTaskEditor()
    http = FakeHttp()
    editor.catalog = Catalog(base_url="http://app", client=http)
    editor.reload()
    yield editor, http
    editor.close()


# ─────────────────────────── 카탈로그 ───────────────────────────


def test_the_catalog_has_no_selectors() -> None:
    """**셀렉터는 여기 없다** (ADR-0008) — 설계할 때 물리 정보가 섞이면 안 된다."""
    raw = json.dumps(CATALOG, ensure_ascii=False)
    assert "css" not in raw and "#qty" not in raw
    pages = read_catalog(CATALOG)
    assert [one.page_id for one in pages] == ["erp.order.form"], "다른 종류는 지나간다"
    qty = pages[0].element("order.qty")
    assert qty is not None and qty.actions == ("fill", "read_selection")


def test_an_unreachable_server_keeps_the_last_list(app: Any) -> None:
    """**비행기에서도 태스크를 고칠 수 있어야 한다.**"""
    http = FakeHttp()
    catalog = Catalog(base_url="http://app", client=http)
    assert catalog.reload()
    http.fail = True
    assert not catalog.reload()
    assert catalog.offline and catalog.pages, "들고 있던 것은 버리지 않는다"
    assert "닿지 못했습니다" in catalog.last_error


def test_no_address_is_said_not_guessed(app: Any) -> None:
    catalog = Catalog(base_url=None)
    assert not catalog.reload()
    assert "주소를 모릅니다" in catalog.last_error


# ─────────────────────────── 고르기 ───────────────────────────


def test_the_screens_come_from_the_catalog(made: Any) -> None:
    editor, _ = made
    assert [editor.page_id.itemText(i) for i in range(editor.page_id.count())] == ["erp.order.form"]
    assert editor.source.text() == "", "온라인이면 아무 말도 안 한다"


def test_offline_is_said_on_the_screen(app: Any) -> None:
    editor = UiTaskEditor()
    editor.catalog = Catalog(base_url="http://app", client=FakeHttp(fail=True))
    editor.reload()
    assert "(오프라인)" in editor.source.text()
    editor.close()


def test_only_the_actions_that_element_can_do(made: Any) -> None:
    """**할 수 없는 동작을 고를 수 없다** — 카탈로그가 말해 준다."""
    editor, _ = made
    editor.page_id.setCurrentText("erp.order.form")
    editor._add_row("order.total", "read", "", "합계", False)  # noqa: SLF001
    actions = editor.steps.cellWidget(0, 2)
    assert [actions.itemText(i) for i in range(actions.count())] == ["read"]


def test_changing_the_screen_refills_the_choices(made: Any) -> None:
    editor, _ = made
    editor.page_id.setCurrentText("erp.order.form")
    editor._add_row("", "", "", "", False)  # noqa: SLF001
    element = editor.steps.cellWidget(0, 1)
    assert [element.itemText(i) for i in range(element.count())] == [
        "order.customer", "order.qty", "order.total", "order.save"
    ]


# ─────────────────────────── 읽고 쓰기 (C14) ───────────────────────────


def test_load_and_dump_round_trip(made: Any) -> None:
    editor, _ = made
    editor.load(
        {
            "page_id": "erp.order.form",
            "start_url": "https://erp.example/new",
            "steps": [
                {"key": "order.customer", "action": "fill", "value": "{거래처}"},
                {"key": "order.total", "action": "read", "result": "합계"},
                {"key": "order.save", "action": "click", "navigates": True},
            ],
            "heal": False,
            "close_browser": True,
            "key_ref": "uia-prod",
        }
    )
    found = editor.dump()
    assert found["page_id"] == "erp.order.form"
    assert found["start_url"] == "https://erp.example/new"
    assert found["key_ref"] == "uia-prod"
    assert found["heal"] is False and found["close_browser"] is True
    assert found["steps"] == [
        {"key": "order.customer", "action": "fill", "value": "{거래처}"},
        {"key": "order.total", "action": "read", "result": "합계"},
        {"key": "order.save", "action": "click", "navigates": True},
    ]


def test_empty_fields_are_not_written(made: Any) -> None:
    """**비어 있는 것은 적지 않는다** — 그림이 지저분해진다."""
    editor, _ = made
    editor.load({"page_id": "erp.order.form", "steps": [{"key": "order.save", "action": "click"}]})
    found = editor.dump()
    assert "start_url" not in found and "key_ref" not in found and "goal" not in found
    assert found["steps"] == [{"key": "order.save", "action": "click"}]


def test_moving_a_step_keeps_its_contents(made: Any) -> None:
    editor, _ = made
    editor.load(
        {
            "page_id": "erp.order.form",
            "steps": [
                {"key": "order.customer", "action": "fill", "value": "가"},
                {"key": "order.qty", "action": "fill", "value": "7"},
            ],
        }
    )
    editor.steps.selectRow(1)
    editor.move_step(-1)
    assert [one["key"] for one in editor.dump()["steps"]] == ["order.qty", "order.customer"]
    assert editor.dump()["steps"][0]["value"] == "7"


# ─────────────────────────── 검사 (STU-13 [W]) ───────────────────────────


def test_a_fill_without_a_value_is_an_error(made: Any) -> None:
    """**실행할 때 알면 늦다** — 「적용」을 막는다."""
    editor, _ = made
    editor.load({"page_id": "erp.order.form", "steps": [{"key": "order.qty", "action": "fill"}]})
    errors, _ = editor.problems()
    assert any("값이 필요합니다" in one for one in errors)
    assert not editor.valid()


def test_a_read_without_a_result_is_an_error(made: Any) -> None:
    editor, _ = made
    editor.load({"page_id": "erp.order.form", "steps": [{"key": "order.total", "action": "read"}]})
    errors, _ = editor.problems()
    assert any("결과 변수가 필요합니다" in one for one in errors)


def test_no_screen_or_no_steps_is_an_error(made: Any) -> None:
    editor, _ = made
    editor.load({})
    errors, _ = editor.problems()
    assert any("화면을 고르세요" in one for one in errors)
    assert any("스텝이 없습니다" in one for one in errors)


def test_an_unregistered_element_is_only_a_warning(made: Any) -> None:
    """**막지 않는다** — 아직 등록 전일 수 있다 (등록은 BUI-06에서 한다)."""
    editor, _ = made
    editor.load({"page_id": "erp.order.form", "steps": [{"key": "order.없는것", "action": "click"}]})
    errors, warnings = editor.problems()
    assert errors == []
    assert any("등록되지 않은 요소" in one for one in warnings)
    assert editor.valid()


def test_a_missing_prerequisite_is_a_warning(made: Any) -> None:
    """선행 입력이 앞 스텝에 없으면 비활성 칸을 누를 수 있다 — 경고한다."""
    editor, _ = made
    editor.load(
        {"page_id": "erp.order.form", "steps": [{"key": "order.qty", "action": "fill", "value": "7"}]}
    )
    _, warnings = editor.problems()
    assert any("선행 입력이 앞에 없습니다 — order.customer" in one for one in warnings)


def test_the_prerequisite_in_an_earlier_step_is_fine(made: Any) -> None:
    editor, _ = made
    editor.load(
        {
            "page_id": "erp.order.form",
            "steps": [
                {"key": "order.customer", "action": "fill", "value": "가"},
                {"key": "order.qty", "action": "fill", "value": "7"},
            ],
        }
    )
    _, warnings = editor.problems()
    assert not any("선행 입력" in one for one in warnings)


def test_an_impossible_action_is_a_warning(made: Any) -> None:
    editor, _ = made
    editor.load({"page_id": "erp.order.form", "steps": [{"key": "order.total", "action": "click"}]})
    _, warnings = editor.problems()
    assert any("할 수 없는 동작" in one for one in warnings)


def test_the_goal_is_off_and_says_why(made: Any) -> None:
    editor, _ = made
    assert not editor.use_goal.isEnabled()
    assert "자율 수행" in editor.goal.toolTip()


def test_an_impossible_action_is_kept_not_rewritten(made: Any) -> None:
    """**적어 둔 것을 조용히 바꾸지 않는다** — 고를 목록에서 빼면 값이 소리 없이 바뀐다."""
    editor, _ = made
    editor.load({"page_id": "erp.order.form", "steps": [{"key": "order.total", "action": "click"}]})
    assert editor.dump()["steps"][0]["action"] == "click"


# ─────────────────────────── 속성 패널에 붙기 (STU-04) ───────────────────────────


@pytest.fixture
def panel(app: Any) -> Any:
    from chaeksas.studio.extensions import Extensions
    from chaeksas.studio.properties import Properties

    extensions = Extensions.load()
    found = Properties(extensions=extensions)
    yield found, extensions
    found.close()


def ui_task(**data: Any) -> dict[str, Any]:
    """캔버스가 주는 모양 — `chk` 값은 **JSON 글**이다."""
    body = {"type": "ui_task", "extension": "ui-automation", "data": data}
    return {
        "id": "Task_Ui",
        "type": "ServiceTask",
        "name": "주문 입력",
        "chk": {"task": json.dumps(body, ensure_ascii=False)},
    }


def tab_titles(panel: Any) -> list[str]:
    return [panel.tabs.tabText(i) for i in range(panel.tabs.count())]


def test_the_editor_tab_appears_for_a_ui_task(panel: Any) -> None:
    """**Studio는 어느 확장인지 모른다** — `type`으로 찾아 붙인다 (ADR-0018)."""
    found, _ = panel
    found.show_element(ui_task(page_id="erp.order.form"))
    assert "UI 태스크" in tab_titles(found)


def test_no_editor_tab_for_other_elements(panel: Any) -> None:
    found, _ = panel
    found.show_element(ui_task(page_id="erp.order.form"))
    found.show_element(
        {"id": "Task_Ai", "type": "ServiceTask", "chk": {"aiTask": json.dumps({"goal": "…"})}}
    )
    assert "UI 태스크" not in tab_titles(found), "AI 태스크에는 붙지 않는다"
    found.show_nothing()
    assert "UI 태스크" not in tab_titles(found)


def test_editing_in_the_tab_becomes_a_patch(panel: Any) -> None:
    found, _ = panel
    found.show_element(ui_task(page_id="erp.order.form", steps=[{"key": "order.save", "action": "click"}]))
    editor = found._editor  # noqa: SLF001
    assert editor is not None
    changes, problem = found.patch()
    assert (changes, problem) == ({}, None), "붙인 직후에는 바뀐 것이 없다"

    editor.start_url.setText("https://erp.example/new")
    changes, problem = found.patch()
    assert problem is None
    sent = json.loads(changes["chk"]["task"])
    assert sent["data"]["start_url"] == "https://erp.example/new"
    assert sent["type"] == "ui_task" and sent["extension"] == "ui-automation", "종류는 그대로 간다"


def test_an_error_in_the_tab_blocks_apply(panel: Any) -> None:
    """**실행할 때 알면 늦다** — 값 없는 `fill`은 「적용」이 막는다."""
    found, _ = panel
    found.show_element(ui_task(page_id="erp.order.form"))
    editor = found._editor  # noqa: SLF001
    editor._add_row("order.qty", "fill", "", "", False)  # noqa: SLF001
    changes, problem = found.patch()
    assert changes == {} and problem is not None and "값이 필요합니다" in problem
    assert not found.apply_button.isEnabled()
