"""STU-03 리소스 탐색기 — BPM 프로세스 밖에서 가져다 쓰는 것 (M6 조각 19).

보는 것:

1. **뿌리는 선언에서 온다** — 고정 셋(공유 BPM 프로세스·서비스 앱·툴팩)과 확장이 선언한 것
   (`studio.resource_views`). 이 파일에 쓴 라벨은 **시험이 지은 확장의 것**이고 코드에는 없다.
2. **쓸 수 없는 뿌리도 사라지지 않는다** — 줄을 끄고 까닭을 적는다 (U3).
3. **들고 있지 않는다** — Center에 닿지 못하면 그 자리에서 말하고, 다음 번에도 낡은 목록을
   보이지 않는다 (ADR-0007은 현장 쪽 규칙이다 — Studio는 개발 도구다).
4. **`data`를 해석하지 않는다** (C13 §5) — 기여 뿌리는 **한 단계**다. 「서비스 앱 → 작업」·
   「툴팩 → 도구」는 플랫폼이 아는 것이라 둘째 단계를 그린다.
5. **「캔버스에 추가」는 선언대로만 만든다** — 자원 id는 `creates_task_field`가 가리키는 칸에만
   들어가고, 선언이 없으면 `data`를 비운 채 만든다.
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402

from chaeksas.contracts.extension import ResourceView  # noqa: E402
from chaeksas.contracts.resources import (  # noqa: E402
    ContributedResource,
    ServiceAppResource,
    ToolpackResource,
)
from chaeksas.contracts.service_app import Operation as C11Operation  # noqa: E402
from chaeksas.core.extensions import Contribution  # noqa: E402
from chaeksas.studio import resources, service_catalog, services  # noqa: E402

NOW = "2026-10-10T09:00:00+09:00"


# ─────────────────────────── 재료 ───────────────────────────


def view(**over: Any) -> ResourceView:
    """어느 확장이 선언했다고 치는 뿌리 하나 — **글이 모두 여기서 온다**."""
    base: dict[str, Any] = {
        "id": "forms",
        "label": "서식",
        "resource_type": "ocr_form",
        "creates_task_type": "ocr_task",
        "creates_task_field": "form_id",
    }
    base.update(over)
    return ResourceView.model_validate(base)


def contributed(view_: ResourceView, extension_id: str = "doc-ocr") -> Contribution[ResourceView]:
    return Contribution(extension_id=extension_id, extension_version="1.0.0", value=view_)


def page(resource_id: str = "erp.order.form", **over: Any) -> ContributedResource:
    base: dict[str, Any] = {
        "resource_type": "ocr_form",
        "id": resource_id,
        "name": "주문 등록",
        "summary": "요소 7개 · 사용 중 5 · 검증 전 2",
        "updated_at": NOW,
        "extension_id": "doc-ocr",
        "revision": 3,
        # 확장의 것 — 플랫폼이 읽어서는 안 되는 자리다 (C13 §5).
        "data": {"elements": [{"semantic_key": "order_no"}, {"semantic_key": "submit"}]},
    }
    base.update(over)
    return ContributedResource.model_validate(base)


def service_app(**over: Any) -> ServiceAppResource:
    base: dict[str, Any] = {
        "app_id": "svc-invoice",
        "name": "세금계산서",
        "status": "ok",
        "extension_id": "invoice-ext",
        "console_url": "http://console.test/svc-invoice",
        "operations": [
            C11Operation(
                name="issue",
                description="세금계산서를 발행한다",
                modes=["autonomous", "deterministic"],
                input_schema={
                    "type": "object",
                    "properties": {"biz_no": {"type": "string", "description": "사업자번호"}},
                    "required": ["biz_no"],
                },
                output_schema={"type": "object", "properties": {"invoice_no": {"type": "string"}}},
            )
        ],
    }
    base.update(over)
    return ServiceAppResource.model_validate(base)


def toolpack(**over: Any) -> ToolpackResource:
    base: dict[str, Any] = {
        "id": "finance-tools",
        "version": "1.2.0",
        "status": "approved",
        "content_hash": "sha256:" + "a" * 64,
        "tools": [{"name": "vat_lookup", "domain": "api", "description": "부가세율"}],
    }
    base.update(over)
    return ToolpackResource.model_validate(base)


class FakeCenter(services.CenterReader):
    """Center를 읽는 척 — C7 세 갈래만 준다 (`contributed`·`toolpack`·`service_app`)."""

    def __init__(
        self,
        *,
        pages: list[ContributedResource] | None = None,
        packs: list[ToolpackResource] | None = None,
        unreachable: str | None = None,
    ) -> None:
        super().__init__(base_url="http://center.test", api_key="chk_studio_" + "a" * 40)
        self.pages = pages if pages is not None else [page()]
        self.packs = packs if packs is not None else [toolpack()]
        self.unreachable = unreachable
        self.asked: list[str] = []

    def contributed(self, resource_type: str) -> list[ContributedResource]:
        self.asked.append(resource_type)
        if self.unreachable:
            raise services.CenterUnreachable(self.unreachable)
        return [one for one in self.pages if one.resource_type == resource_type]

    def toolpacks(self) -> list[ToolpackResource]:
        if self.unreachable:
            raise services.CenterUnreachable(self.unreachable)
        return self.packs


def catalog_with(*apps: ServiceAppResource, problems: tuple[str, ...] = ()) -> service_catalog.Catalog:
    return service_catalog.build(apps, problems=problems)


def tree_with(**over: Any) -> resources.Tree:
    settings: dict[str, Any] = {
        "views": [contributed(view())],
        "catalog": catalog_with(service_app()),
        "reader": FakeCenter(),
    }
    settings.update(over)
    return resources.collect(settings.pop("views"), **settings)


def root_of(tree: resources.Tree, root_id: str) -> resources.Root:
    found = next(one for one in tree.roots if one.id == root_id)
    return found


@pytest.fixture(autouse=True)
def _app() -> Any:
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


# ─────────────────────────── 뿌리 ───────────────────────────


def test_the_roots_are_the_four_the_screen_doc_lists() -> None:
    """고정 셋 + 확장이 선언한 것. 순서는 STU-03 표 그대로다."""
    tree = tree_with()
    assert [one.id for one in tree.roots] == [
        resources.ROOT_SHARED,
        "forms",
        resources.ROOT_SERVICE,
        resources.ROOT_TOOLPACK,
    ]
    assert [one.label for one in tree.roots] == [
        "공유 BPM 프로세스",
        "서식",  # **선언에서 온 말이다** — 코드에 없다
        "서비스 앱",
        "툴팩",
    ]


def test_a_contributed_root_asks_center_for_its_own_resource_type() -> None:
    """선언한 `resource_type`으로만 묻는다 (C7) — 플랫폼이 갈래 이름을 적어 두지 않는다."""
    reader = FakeCenter()
    tree_with(reader=reader)
    assert reader.asked == ["ocr_form"]


def test_contributed_roots_are_drawn_in_label_order() -> None:
    """확장이 실리는 순서에 흔들리지 않게 라벨 순이다."""
    tree = tree_with(
        views=[
            contributed(view(id="zz", label="하 보기", resource_type="z")),
            contributed(view(id="aa", label="가 보기", resource_type="a")),
        ]
    )
    assert [one.label for one in tree.roots[1:3]] == ["가 보기", "하 보기"]


def test_the_shared_process_root_stays_but_says_why_it_is_off() -> None:
    """올리는 길이 없어 늘 비어 있다 — **뿌리를 지우지 않고** 까닭을 적는다 (U3)."""
    found = root_of(tree_with(), resources.ROOT_SHARED)
    assert found.items == ()
    assert "§4-5" in found.off


def test_no_center_means_no_knocking_and_a_reason() -> None:
    """주소·키가 없으면 **두드리지 않는다** — 뿌리는 그리고 까닭 한 줄을 남긴다."""
    tree = resources.collect([contributed(view())], catalog=None, reader=None)
    assert len(tree.roots) == 4
    assert resources.NO_CENTER in tree.problems
    assert root_of(tree, "forms").empty == resources.NO_CENTER
    assert root_of(tree, resources.ROOT_TOOLPACK).empty == resources.NO_CENTER


def test_unreachable_center_says_so_and_holds_nothing() -> None:
    """닿지 못하면 **그 자리에서** 말한다 (Studio는 현장이 아니다) — 낡은 목록이 남지 않는다."""
    reader = FakeCenter()
    assert root_of(tree_with(reader=reader), "forms").items  # 한 번은 받았다

    broken = FakeCenter(unreachable="Center에 닿지 못했습니다 (ConnectError)")
    tree = tree_with(reader=broken)
    assert root_of(tree, "forms").items == ()
    assert root_of(tree, resources.ROOT_TOOLPACK).items == ()
    assert any("서식을 받지 못했습니다" in one for one in tree.problems)
    assert any("툴팩 목록을 받지 못했습니다" in one for one in tree.problems)


def test_one_root_failing_does_not_take_the_others() -> None:
    """서비스 앱은 이미 받아 둔 것이라 기여 뿌리가 깨져도 그대로 그린다."""
    tree = tree_with(reader=FakeCenter(unreachable="끊겼다"))
    assert [one.label for one in root_of(tree, resources.ROOT_SERVICE).items] == ["세금계산서"]


def test_catalog_problems_come_along() -> None:
    """STU-14가 못 받은 사유도 같은 안내 줄에 모인다 (출처가 하나다)."""
    tree = tree_with(catalog=catalog_with(problems=("서비스 앱 목록을 받지 못했습니다 — 끊겼다",)))
    assert any("서비스 앱 목록" in one for one in tree.problems)


# ─────────────────────────── 기여 뿌리는 한 단계다 ───────────────────────────


def test_a_contributed_item_shows_only_name_and_summary() -> None:
    """**`data`를 해석하지 않는다** (C13 §5) — 요소는 자식으로 그리지 않는다."""
    item = root_of(tree_with(), "forms").items[0]
    assert item.label == "주문 등록"
    assert item.note == "요소 7개 · 사용 중 5 · 검증 전 2"  # 요소 수는 `summary`가 말해 준다
    assert item.children == (), "둘째 단계를 그리려면 `data`의 모양을 알아야 한다"
    assert "erp.order.form" in item.tip


def test_an_item_without_a_name_falls_back_to_its_id() -> None:
    tree = tree_with(reader=FakeCenter(pages=[page(name=None)]))
    assert root_of(tree, "forms").items[0].label == "erp.order.form"


def test_the_console_link_comes_from_the_extensions_service_app() -> None:
    """「관리 콘솔에서 보기」 주소는 C7의 `console_url`이다 — 플랫폼이 짓지 않는다."""
    tree = tree_with(catalog=catalog_with(service_app(extension_id="doc-ocr")))
    assert root_of(tree, "forms").items[0].console_url == "http://console.test/svc-invoice"


def test_without_a_registered_app_there_is_no_console_link() -> None:
    assert root_of(tree_with(), "forms").items[0].console_url == ""


# ─────────────────────────── 「캔버스에 추가」 ───────────────────────────


def body_of(create: resources.Create, element: str) -> dict[str, Any]:
    found: dict[str, Any] = json.loads(create.chk[element])
    return found


def test_the_resource_id_goes_only_where_the_declaration_says() -> None:
    """`creates_task_field` 선언대로 한 칸에만 넣는다 (C13) — 아무 칸에나 넣지 않는다."""
    create = root_of(tree_with(), "forms").items[0].create
    assert create is not None
    assert create.bpmn == resources.BPMN_SERVICE_TASK
    assert body_of(create, "task") == {
        "type": "ocr_task",
        "extension": "doc-ocr",
        "data": {"form_id": "erp.order.form"},
    }


def test_without_the_field_declaration_the_data_stays_empty() -> None:
    """플랫폼은 그 확장의 `data` 모양을 모른다 — 비운 채 만들고 사람이 편집기에서 고른다."""
    create = resources.view_create(view(creates_task_field=None), "doc-ocr", "p1", "화면")
    assert create is not None
    assert body_of(create, "task")["data"] == {}


def test_a_root_that_creates_nothing_offers_no_node() -> None:
    """`creates_task_type`이 없으면 그 뿌리에서 태스크를 만들 수 없다."""
    tree = tree_with(views=[contributed(view(creates_task_type=None))])
    assert root_of(tree, "forms").items[0].create is None


def test_a_service_operation_becomes_a_service_call_without_a_key_ref() -> None:
    """`chk:serviceCall`은 `{app_id, operation}`뿐 — **키 참조는 BPM 프로세스에서 상속한다**."""
    app = root_of(tree_with(), resources.ROOT_SERVICE).items[0]
    operation = app.children[0]
    assert operation.create is not None
    assert body_of(operation.create, "serviceCall") == {"app_id": "svc-invoice", "operation": "issue"}
    assert "key_ref" not in operation.create.chk["serviceCall"]


def test_a_toolpack_tool_is_not_dragged_onto_the_canvas() -> None:
    """툴팩의 도구는 AI 태스크의 **허용 도구**에서 고르는 것이다 (STU-03 표 — 「—」)."""
    pack = root_of(tree_with(), resources.ROOT_TOOLPACK).items[0]
    assert pack.create is None
    assert pack.children[0].create is None


# ─────────────────────────── 둘째 단계 (플랫폼이 아는 것) ───────────────────────────


def test_the_service_app_root_draws_apps_and_their_operations() -> None:
    app = root_of(tree_with(), resources.ROOT_SERVICE).items[0]
    assert (app.label, app.note) == ("세금계산서", "정상")
    assert [one.label for one in app.children] == ["issue"]
    assert app.children[0].kind == resources.OPERATION_KIND


def test_an_operation_that_bots_cannot_run_says_so_on_its_row() -> None:
    """결정 수행을 지원하지 않는 작업은 그 줄이 말한다 (STU-14도 경고하는 것)."""
    only_auto = service_app(
        operations=[C11Operation(name="guess", modes=["autonomous"], description="")]
    )
    app = root_of(tree_with(catalog=catalog_with(only_auto)), resources.ROOT_SERVICE).items[0]
    assert app.children[0].note == "결정 수행 불가"


def test_an_operation_tooltip_lists_its_input_and_output_fields() -> None:
    """STU-03 「툴팁」 — 서비스 앱 작업은 입력·출력 칸이다."""
    operation = root_of(tree_with(), resources.ROOT_SERVICE).items[0].children[0]
    assert operation.tip == "입력: biz_no / 출력: invoice_no"


def test_the_operation_detail_shows_what_the_manifest_said() -> None:
    """「작업 설명 보기」 — 설명·수행 모드·입력·출력. 지어내지 않는다."""
    operation = root_of(tree_with(), resources.ROOT_SERVICE).items[0].children[0]
    assert "세금계산서를 발행한다" in operation.detail
    assert "autonomous, deterministic" in operation.detail
    assert "biz_no (string) *필수 — 사업자번호" in operation.detail


def test_without_a_schema_the_detail_says_the_person_must_write_it() -> None:
    """`input_schema`·`output_schema`는 선택 칸이다 (C11) — 없는 칸을 지어내지 않는다."""
    bare = service_app(operations=[C11Operation(name="run", modes=["deterministic"])])
    operation = root_of(tree_with(catalog=catalog_with(bare)), resources.ROOT_SERVICE).items[0].children[0]
    assert "정의가 알려 주지 않았습니다" in operation.detail
    assert "정의가 알려 주지 않았습니다" in operation.tip
    assert "입력:" not in operation.tip, "없는 칸을 「(없음)」으로도 말하지 않는다"


def test_the_toolpack_root_draws_packs_and_their_tools() -> None:
    pack = root_of(tree_with(), resources.ROOT_TOOLPACK).items[0]
    assert (pack.label, pack.kind) == ("finance-tools", "1.2.0")
    assert "도구 1개" in pack.note
    assert [one.label for one in pack.children] == ["vat_lookup"]


def test_toolpack_install_is_blocked_with_a_reason() -> None:
    """설치·제거는 STU-11의 일이다 — 메뉴에 두고 끄고 이유를 붙인다 (U3)."""
    found = root_of(tree_with(), resources.ROOT_TOOLPACK)
    assert [label for label, _ in found.blocked] == ["설치...", "제거..."]
    assert all("§4-5" in why for _, why in found.blocked)


def test_empty_roots_say_so_instead_of_staying_blank() -> None:
    tree = tree_with(catalog=catalog_with(), reader=FakeCenter(pages=[], packs=[]))
    assert root_of(tree, resources.ROOT_SERVICE).empty == resources.EMPTY_SERVICE
    assert root_of(tree, resources.ROOT_TOOLPACK).empty == resources.EMPTY_TOOLPACK
    assert root_of(tree, "forms").empty == resources.EMPTY_VIEW


# ─────────────────────────── 창 ───────────────────────────


def explorer(tree: resources.Tree | None = None) -> resources.ResourceExplorer:
    made = resources.ResourceExplorer()
    made.show_tree(tree if tree is not None else tree_with())
    return made


def pick(window: resources.ResourceExplorer, *path: int) -> None:
    """나무에서 줄 하나를 고른다 — `path`는 위에서부터의 자리다."""
    index = window.view.model().index(path[0], 0)
    for step in path[1:]:
        index = window.view.model().index(step, 0, index)
    window.view.setCurrentIndex(index)


def test_the_window_draws_the_roots_and_their_children() -> None:
    window = explorer()
    model = window.view.model()
    assert model.rowCount() == 4
    service = model.index(2, 0)
    assert model.data(service) == "서비스 앱"
    assert model.rowCount(service) == 1
    assert model.rowCount(model.index(0, 0, service)) == 1, "앱 아래에 작업 한 줄"


def test_a_root_that_is_off_is_drawn_disabled_with_its_reason() -> None:
    window = explorer()
    model = window.view.model()
    first = model.index(0, 0)
    assert model.data(first) == "공유 BPM 프로세스"
    assert not model.flags(first) & Qt.ItemFlag.ItemIsEnabled
    assert "§4-5" in str(model.data(first, Qt.ItemDataRole.ToolTipRole))


def test_the_note_line_carries_the_problems() -> None:
    window = explorer(resources.collect([], catalog=None, reader=None))
    assert resources.NO_CENTER in window.note.text()
    window.show_tree(tree_with())
    assert window.note.text() == resources.EMPTY_TREE


def test_adding_a_resource_sends_the_create_up() -> None:
    """창은 캔버스를 모른다 — `adding`으로 올리고 메인 창이 캔버스를 부른다."""
    window = explorer()
    got: list[Any] = []
    window.adding.connect(got.append)
    pick(window, 1, 0)  # 「서식」 → 「주문 등록」
    window.add_selected()
    assert len(got) == 1
    assert body_of(got[0], "task")["data"] == {"form_id": "erp.order.form"}


def test_adding_something_that_makes_nothing_says_why() -> None:
    """조용히 아무 일도 없는 것보다 한 줄 말하는 쪽이 낫다."""
    window = explorer(tree_with(views=[contributed(view(creates_task_type=None))]))
    said: list[str] = []
    window.said.connect(said.append)
    pick(window, 1, 0)
    window.add_selected()
    assert said and "만들 수 없습니다" in said[0]


def test_double_clicking_a_row_with_children_only_expands_it() -> None:
    """앱 줄을 두 번 누르면 펼치는 것이 뜻이다 — 「만들 수 없습니다」라고 하지 않는다."""
    window = explorer()
    said: list[str] = []
    window.said.connect(said.append)
    got: list[Any] = []
    window.adding.connect(got.append)
    pick(window, 2, 0)  # 서비스 앱 → 세금계산서 (작업이 자식으로 있다)
    window._double_clicked()  # noqa: SLF001 — 더블클릭이 무엇을 하나를 본다
    assert (said, got) == ([], [])


def test_refresh_asks_the_main_window_to_read_center_again() -> None:
    """「새로 고침」은 창이 직접 Center를 부르지 않는다 (받는 쪽은 하나다)."""
    window = explorer()
    rung: list[int] = []
    window.reloading.connect(lambda: rung.append(1))
    window.reload_button.click()
    assert rung == [1]


def test_the_selected_row_is_found_by_root_and_item() -> None:
    """같은 id가 다른 뿌리에 있어도 섞이지 않는다 (뿌리 id를 함께 담는다)."""
    window = explorer()
    pick(window, 2, 0, 0)  # 서비스 앱 → 세금계산서 → issue
    found = window.selected_item()
    assert found is not None and found.label == "issue"
    assert window.selected_root() is not None
    assert window.selected_root().id == resources.ROOT_SERVICE  # type: ignore[union-attr]


def test_the_detail_window_only_reads() -> None:
    window = explorer()
    pick(window, 2, 0, 0)
    item = window.selected_item()
    assert item is not None
    dialog = resources.DetailDialog(item.label, item.detail)
    assert dialog.body.isReadOnly()
    assert "세금계산서를 발행한다" in dialog.body.toPlainText()


# ─────────────────────────── 메인 창에 붙은 자리 ───────────────────────────


#: 띄워 본 WebEngine 화면 하나 — **살려 둔다**. 지우면 Qt가 종료 때 프로필을 두고 투덜댄다.
_PROBE: list[Any] = []


@pytest.fixture
def webengine(_app: Any) -> Any:
    """캔버스(QtWebEngine)가 뜨는 환경인가 — 못 뜨면 건너뛴다 (`test_studio_canvas`와 같은 태도)."""
    if _PROBE:
        return True
    try:
        from PySide6.QtWebEngineWidgets import QWebEngineView

        _PROBE.append(QWebEngineView())
    except Exception as e:  # noqa: BLE001 — 환경 문제면 건너뛴다
        pytest.skip(f"QtWebEngine을 띄울 수 없다: {type(e).__name__}: {e}")
    return True


@pytest.fixture
def window(tmp_path: Any, webengine: Any) -> Any:
    """STU-01 메인 창 하나. 캔버스가 뜨기를 **기다리지 않는다** — 여기서 보는 것은 붙은 자리다."""
    from chaeksas.studio.main_window import MainWindow
    from chaeksas.studio.settings import Settings

    return MainWindow(Settings(data_dir=tmp_path))


def test_the_resource_tab_holds_the_explorer_not_a_label(window: Any) -> None:
    """STU-01 [E] — 탭 둘이고 「리소스」가 탐색기다 (「아직 없습니다」 라벨이 아니다)."""
    tabs = window.explorer_tabs
    assert [tabs.tabText(i) for i in range(tabs.count())] == ["BPM 프로세스", "리소스"]
    assert tabs.widget(1) is window.resource_tree
    assert isinstance(window.resource_tree, resources.ResourceExplorer)


def test_the_view_menu_has_the_resource_shortcut(window: Any) -> None:
    """STU-01 메뉴 표 — 「보기 → 리소스」는 Ctrl+Shift+E다."""
    view_menu = next(one for one in window.menuBar().actions() if one.text() == "보기")
    found = {one.text(): one.shortcut().toString() for one in view_menu.menu().actions()}
    assert found["BPM 프로세스 탐색기"] == "Ctrl+E"
    assert found["리소스"] == "Ctrl+Shift+E"


def test_showing_the_resources_brings_the_tab_forward(window: Any) -> None:
    window.show_resources()
    assert window.explorer_tabs.currentWidget() is window.resource_tree
    window.show_explorer()
    assert window.explorer_tabs.currentWidget() is window.explorer


def test_the_roots_are_drawn_without_knocking_on_center(window: Any) -> None:
    """뜨면서 Center를 두드리지 않는다 — 뿌리는 선언에서 오므로 바로 보인다."""
    assert [one.id for one in window.resource_tree.tree.roots] == [
        resources.ROOT_SHARED,
        "ui-pages",  # 설치된 UI 자동화 확장이 **선언한** 뿌리다
        resources.ROOT_SERVICE,
        resources.ROOT_TOOLPACK,
    ]
    assert resources.NO_CENTER in window.resource_tree.note.text()


def test_adding_without_an_open_definition_says_so(window: Any) -> None:
    """열린 정의가 없으면 캔버스를 부르지 않고 말한다 (조용히 아무 일도 없지 않다)."""
    window.add_to_canvas(resources.Create(bpmn=resources.BPMN_SERVICE_TASK, name="X", chk={}))
    assert "열린 정의가 없습니다" in window.log_view.toPlainText()
