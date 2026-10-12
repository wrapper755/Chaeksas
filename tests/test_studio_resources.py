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

from chaeksas.contracts.center_api import PackageInfo  # noqa: E402
from chaeksas.contracts.extension import ResourceView  # noqa: E402
from chaeksas.contracts.resources import (  # noqa: E402
    ContributedResource,
    ServiceAppResource,
    ToolpackResource,
)
from chaeksas.contracts.service_app import Operation as C11Operation  # noqa: E402
from chaeksas.core.extensions import Contribution  # noqa: E402
from chaeksas.studio import center_actions, resources, service_catalog, services  # noqa: E402
from chaeksas.studio.workspace import InstalledLib  # noqa: E402

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


def shared_lib(**over: Any) -> PackageInfo:
    """공유 BPM 프로세스 패키지 하나 (C5 `PackageInfo`). 「공유 BPM 프로세스」 뿌리가 읽는다."""
    base: dict[str, Any] = {
        "id": "shared.approval",
        "version": "1.1.0",
        "kind": "process_lib",
        "name": "공통 결재",
        "status": "approved",
        "content_hash": "sha256:" + "b" * 64,
        "uploaded_by": "설계자 PC",
        "uploaded_at": "2026-10-11T09:00:00+09:00",
        "manifest": {
            "schema": 1,
            "kind": "process_lib",
            "id": "shared.approval",
            "version": "1.1.0",
            "name": "공통 결재",
            "requires": {},
            "human": {},
            "provides": {
                "processes": [
                    {
                        "process_id": "Proc_approve",
                        "file": "process/approve.bpmn",
                        "name": "팀장 결재",
                        "reads": ["금액"],
                        "writes": ["승인"],
                    }
                ]
            },
            "built": {"by": "studio", "at": "2026-10-11T09:00:00+09:00", "core": "0.1.0",
                      "spec_version": 1},
            "content_hash": "sha256:" + "b" * 64,
        },
    }
    base.update(over)
    return PackageInfo.model_validate(base)


class FakeCenter(services.CenterReader):
    """Center를 읽는 척 — C7 세 갈래와 C5 패키지 표를 준다."""

    def __init__(
        self,
        *,
        pages: list[ContributedResource] | None = None,
        packs: list[ToolpackResource] | None = None,
        libs: list[PackageInfo] | None = None,
        unreachable: str | None = None,
    ) -> None:
        super().__init__(base_url="http://center.test", api_key="chk_studio_" + "a" * 40)
        self.pages = pages if pages is not None else [page()]
        self.packs = packs if packs is not None else [toolpack()]
        self.libs = libs if libs is not None else [shared_lib()]
        self.unreachable = unreachable
        #: 기여 뿌리가 물어본 자원 갈래들 (C7).
        self.asked: list[str] = []
        #: 패키지 표에 물어본 갈래들 (C5).
        self.asked_kinds: list[str] = []

    def contributed(self, resource_type: str) -> list[ContributedResource]:
        self.asked.append(resource_type)
        if self.unreachable:
            raise services.CenterUnreachable(self.unreachable)
        return [one for one in self.pages if one.resource_type == resource_type]

    def toolpacks(self) -> list[ToolpackResource]:
        if self.unreachable:
            raise services.CenterUnreachable(self.unreachable)
        return self.packs

    def packages(self, kind: str) -> list[PackageInfo]:
        self.asked_kinds.append(kind)
        if self.unreachable:
            raise services.CenterUnreachable(self.unreachable)
        return [one for one in self.libs if one.kind == kind]


def held(
    version: str = "1.1.0", processes: tuple[str, ...] = ("Proc_approve",)
) -> dict[str, InstalledLib]:
    """**열린 BPM 프로세스가 받아 둔 판** 하나 (`install.installed_of`가 주는 모양, ADR-0051).

    STU-03은 이것을 **받아서** 쓴다 — 여기서 디스크를 보지 않는다.
    """
    return {
        "shared.approval": InstalledLib(
            package_id="shared.approval",
            version=version,
            files=("shared.approval__approve.bpmn",),
            processes=processes,
        )
    }


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
    # 공유 뿌리는 **패키지 표**에 묻는다 (C5) — 리소스 목록이 아니다.
    assert reader.asked_kinds == [resources.KIND_LIB]


def test_contributed_roots_are_drawn_in_label_order() -> None:
    """확장이 실리는 순서에 흔들리지 않게 라벨 순이다."""
    tree = tree_with(
        views=[
            contributed(view(id="zz", label="하 보기", resource_type="z")),
            contributed(view(id="aa", label="가 보기", resource_type="a")),
        ]
    )
    assert [one.label for one in tree.roots[1:3]] == ["가 보기", "하 보기"]


def test_the_shared_process_root_lists_center_libs_and_their_definitions() -> None:
    """뿌리는 **C5 패키지 표**에서 온다 (`?kind=process_lib`) — C7에 그 갈래가 없다.

    둘째 단계는 **매니페스트의 `provides.processes`**다 (C1) — Center가 짓는 값이 아니다.
    """
    found = root_of(tree_with(), resources.ROOT_SHARED)
    [one] = found.items
    assert (one.label, one.kind) == ("공통 결재", "1.1.0")
    assert one.note == "approved · 정의 1개"
    [definition] = one.children
    assert definition.label == "팀장 결재"
    assert definition.note == "받는 것: 금액 / 내놓는 것: 승인"


def test_an_installed_definition_becomes_a_call_activity() -> None:
    """설치된 판의 정의로 **Call Activity를 만든다**
    ([ADR-0051](../docs/decisions/0051-shared-process-conveniences.md)).

    만드는 것은 **`calledElement`뿐**이다 — `chk:call`의 입력·출력 짝은 내 변수 이름을 알아야
    하는 일이라 지어내지 않는다 (속성 패널에서 적는다).
    """
    found = root_of(tree_with(installed=held()), resources.ROOT_SHARED)
    [definition] = found.items[0].children
    assert definition.create == resources.Create(
        bpmn=resources.BPMN_CALL_ACTIVITY,
        name="팀장 결재",
        attrs={"calledElement": "Proc_approve"},
    )
    assert definition.create.chk == {}, "입력·출력 짝은 지어내지 않는다"
    assert definition.shared == resources.Shared(
        package_id="shared.approval", version="1.1.0", process_id="Proc_approve"
    )


def test_without_the_install_there_is_no_call_and_the_reason_sends_you_to_stu_11() -> None:
    """**설치되지 않은 것으로 만들어 주지 않는다** — B14가 막고 시험 실행이 부를 수 없다.

    그래도 줄은 그대로 있고(목록은 Center의 것이다) 셋은 끄고 **까닭을 적는다** (U3).
    """
    found = root_of(tree_with(), resources.ROOT_SHARED)
    [definition] = found.items[0].children
    assert definition.create is None
    assert definition.no_create == resources.NOT_INSTALLED
    assert definition.shared is not None
    assert definition.shared.off == resources.NOT_INSTALLED
    assert "STU-11" in definition.shared.off, "할 수 있는 자리를 가리킨다"
    assert [label for label, _ in found.blocked] == ["설치...", "제거..."]
    assert found.opens_center, "문맥 메뉴에서 STU-11로 갈 수 있어야 한다"


def test_another_held_version_says_which_one_is_held() -> None:
    """「갱신하세요」로는 **무엇을 쓰고 있는지** 모른다 — 받아 둔 판을 적는다."""
    found = root_of(tree_with(installed=held(version="1.0.0")), resources.ROOT_SHARED)
    [definition] = found.items[0].children
    assert definition.create is None
    assert definition.no_create == resources.OTHER_VERSION.format(version="1.0.0")
    assert found.items[0].note.endswith("· 다른 판 설치됨 (1.0.0)")


def test_a_held_version_that_does_not_bring_the_definition_says_so() -> None:
    """판은 맞는데 그 정의가 기록에 없다 — 설치할 때 **읽지 못한** 정의다 (F6이 까닭을 말한다)."""
    found = root_of(tree_with(installed=held(processes=())), resources.ROOT_SHARED)
    [definition] = found.items[0].children
    assert definition.create is None
    assert definition.no_create == resources.NOT_PROVIDED
    assert found.items[0].note.endswith("· 설치됨"), "판은 받아져 있다"


def test_the_package_row_tells_you_to_pick_a_definition() -> None:
    """첫 단계로는 **무엇을 부를지 모른다** — 조용히 끄지 않고 그 말을 한다."""
    found = root_of(tree_with(installed=held()), resources.ROOT_SHARED)
    assert found.items[0].create is None
    assert found.items[0].no_create == resources.PICK_DEFINITION
    assert found.items[0].shared is None, "패키지 줄로는 보기·복사를 하지 않는다"


def test_the_install_mark_only_shows_up_when_something_is_held() -> None:
    """받아 둔 것이 없으면 **아무 말도 붙지 않는다** (없음이 그 뜻이다)."""
    assert root_of(tree_with(), resources.ROOT_SHARED).items[0].note == "approved · 정의 1개"
    marked = root_of(tree_with(installed=held()), resources.ROOT_SHARED)
    assert marked.items[0].note == "approved · 정의 1개 · 설치됨"


def test_the_root_lists_exactly_what_center_has() -> None:
    """**멤버십은 Center 목록 그대로다** (ADR-0051) — 설치는 줄을 늘리거나 줄이지 않는다.

    Center에 없는데 설치된 것(「로컬만」)은 **STU-11의 일이다** — 둘째 단계와 「받는 것·
    내놓는 것」은 매니페스트의 `provides`가 주는 것이라 지어낼 수 없다.
    """
    gone = {
        "shared.gone": InstalledLib(package_id="shared.gone", version="3.0.0"),
        **held(),
    }
    found = root_of(tree_with(installed=gone), resources.ROOT_SHARED)
    assert [one.id for one in found.items] == ["shared.approval@1.1.0"]


def test_a_lib_without_provides_says_so_instead_of_zero() -> None:
    """**없는 것과 비어 있는 것은 다르다** — 0으로 적으면 「정의가 없다」로 읽힌다 (CON-06과 같다)."""
    bare = shared_lib(manifest=None)
    found = root_of(tree_with(reader=FakeCenter(libs=[bare])), resources.ROOT_SHARED)
    [one] = found.items
    assert one.children == ()
    assert "`provides`가 없습니다" in one.note


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
    """지금 꺼지는 뿌리는 없다 — 그려 보고 **`off`를 적은 뿌리만** 꺼지는지 본다 (U3)."""
    window = explorer()
    model = window.view.model()
    first = model.index(0, 0)
    assert model.data(first) == "공유 BPM 프로세스"
    assert model.flags(first) & Qt.ItemFlag.ItemIsEnabled

    off = resources.Tree(roots=(resources.Root(id="x", label="실험", off="까닭 한 줄"),))
    window.show_tree(off)
    row = model.index(0, 0)
    assert not model.flags(row) & Qt.ItemFlag.ItemIsEnabled
    assert "까닭 한 줄" == str(model.data(row, Qt.ItemDataRole.ToolTipRole))


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


#  ─────────────────────── 끌어다 놓기 (ADR-0044) ───────────────────────


def test_the_payload_survives_a_round_trip() -> None:
    """실은 것과 푼 것이 같다 — 끌 때와 놓을 때가 **같은 `Create`**여야 한다."""
    create = root_of(tree_with(), "forms").items[0].create
    assert create is not None
    again = resources.from_payload(resources.as_payload(create))
    assert again == create


def test_rubbish_dropped_on_the_canvas_is_not_a_create() -> None:
    """남이 끌어 온 것일 수 있다 — **모양이 아니면 `None`**이고 터지지 않는다."""
    for bad in ("", "{", "[]", '"글"', "null", "{}", '{"name": "이름만"}', '{"bpmn": ""}'):
        assert resources.from_payload(bad) is None, bad

    # `chk`가 우리 모양이 아니면 **버리고 나머지로 만든다** (JSON 글의 사전이어야 한다).
    found = resources.from_payload('{"bpmn": "bpmn:ServiceTask", "chk": {"task": 7}}')
    assert found is not None and found.chk == {}
    assert resources.from_payload('{"bpmn": "bpmn:Task"}') == resources.Create(
        bpmn="bpmn:Task", name="", chk={}, attrs={}
    )
    # `attrs`도 **글만** 받는다 (수를 넣으면 bpmn-js가 속성에 수를 쓴다).
    found = resources.from_payload('{"bpmn": "bpmn:CallActivity", "attrs": {"calledElement": 7}}')
    assert found is not None and found.attrs == {}


def test_only_a_row_that_makes_something_can_be_dragged() -> None:
    """끌고 가서 놓았는데 아무 일도 없는 것보다 **아예 끌리지 않는** 쪽이 낫다."""
    window = explorer()
    model = window.view.model()
    assert model.mimeTypes() == [resources.MIME_TYPE]

    # 만들 수 있는 줄 — 「서식」 → 「주문 등록」.
    form = model.index(0, 0, model.index(1, 0))
    data = model.mimeData([form])
    assert data is not None and data.hasFormat(resources.MIME_TYPE)
    carried = resources.from_payload(bytes(data.data(resources.MIME_TYPE).data()).decode("utf-8"))
    assert carried is not None
    assert body_of(carried, "task")["data"] == {"form_id": "erp.order.form"}

    # 만들 것이 없는 줄들 — 끌리지 않는다 (STU-03 표의 「—」와 §4-5의 꺼진 줄들).
    nothing = {
        "뿌리": model.index(1, 0),
        "앱 (자식이 있다)": model.index(0, 0, model.index(2, 0)),
        "툴팩": model.index(0, 0, model.index(3, 0)),
        "도구 (허용 목록에서 고른다)": model.index(0, 0, model.index(0, 0, model.index(3, 0))),
        "공유 BPM 프로세스 (설치가 없다)": model.index(0, 0, model.index(0, 0)),
    }
    for what, index in nothing.items():
        assert model.data(index), f"{what} 줄을 찾지 못했다"
        assert model.mimeData([index]) is None, f"{what}이 끌렸다"


def test_an_installed_shared_definition_drags_its_called_element() -> None:
    """설치하면 그 줄도 끌린다 (ADR-0051) — **끌어다 놓기와 메뉴가 같은 `Create`**다.

    `calledElement`는 `chk:*`가 아니라 그냥 BPMN 속성이라 **실린 글에 `attrs`로** 간다.
    """
    window = explorer(tree_with(installed=held()))
    model = window.view.model()
    definition = model.index(0, 0, model.index(0, 0, model.index(0, 0)))
    assert model.data(definition) == "팀장 결재"

    data = model.mimeData([definition])
    assert data is not None and data.hasFormat(resources.MIME_TYPE)
    carried = resources.from_payload(bytes(data.data(resources.MIME_TYPE).data()).decode("utf-8"))
    assert carried is not None
    assert carried.bpmn == resources.BPMN_CALL_ACTIVITY
    assert carried.attrs == {"calledElement": "Proc_approve"}
    assert carried.chk == {}


def test_viewing_and_copying_send_the_ref_up_not_the_file() -> None:
    """창은 디스크를 모른다 (ADR-0051) — 가리키는 것만 올리고 읽고 쓰는 일은 메인 창이 한다."""
    window = explorer(tree_with(installed=held()))
    seen: list[Any] = []
    copied: list[Any] = []
    window.viewing.connect(seen.append)
    window.copying.connect(copied.append)

    pick(window, 0, 0, 0)  # 공유 BPM 프로세스 → 공통 결재 → 팀장 결재
    window.view_selected()
    window.copy_selected()
    assert seen == copied
    assert seen[0] == resources.Shared(
        package_id="shared.approval", version="1.1.0", process_id="Proc_approve"
    )


def test_viewing_something_that_is_not_installed_says_why() -> None:
    """꺼진 줄을 눌러도 **조용히 아무 일도 없지 않다** — 까닭 한 줄이다 (U3)."""
    window = explorer()
    said: list[str] = []
    seen: list[Any] = []
    window.said.connect(said.append)
    window.viewing.connect(seen.append)

    pick(window, 0, 0, 0)
    window.view_selected()
    assert seen == [], "할 수 없는 일을 올려 보내지 않는다"
    assert said and resources.NOT_INSTALLED in said[0]


def test_a_row_that_is_not_a_shared_definition_has_nothing_to_view() -> None:
    """서비스 앱 작업 줄에는 보기·복사가 **메뉴에 없다** (`shared`가 `None`이다)."""
    window = explorer(tree_with(installed=held()))
    said: list[str] = []
    seen: list[Any] = []
    window.said.connect(said.append)
    window.viewing.connect(seen.append)

    pick(window, 2, 0, 0)  # 서비스 앱 → 세금계산서 → issue
    assert window.selected_item() is not None
    assert window.selected_item().shared is None  # type: ignore[union-attr]
    window.view_selected()
    assert (said, seen) == ([], [])


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
    center_actions.add_to_canvas(
        window, resources.Create(bpmn=resources.BPMN_SERVICE_TASK, name="X", chk={})
    )
    assert "열린 정의가 없습니다" in window.log_view.toPlainText()


def test_dropping_without_an_open_definition_says_the_same_thing(window: Any) -> None:
    """끌어다 놓기도 **같은 관문**이다 (ADR-0044) — 한쪽만 통과하면 사람이 혼란스럽다."""
    create = resources.Create(bpmn=resources.BPMN_SERVICE_TASK, name="X", chk={})
    center_actions.drop_on_canvas(window, resources.as_payload(create), 10, 20)
    assert "열린 정의가 없습니다" in window.log_view.toPlainText()


def test_a_broken_payload_is_dropped_quietly(window: Any) -> None:
    """사람에게 할 말이 없다 — 우리 형식만 받으므로 여기 오면 우리 쪽 흠이다 (로그만)."""
    center_actions.drop_on_canvas(window, "{망가진", 10, 20)
    assert window.log_view.toPlainText() == ""


def test_the_canvas_is_told_which_format_to_accept(window: Any) -> None:
    """**캔버스는 무엇이 떨어졌는지 모른다** (ADR-0044) — 형식은 창이 알려 준다."""
    assert window.canvas.acceptDrops()
    assert window.canvas._drop_format == resources.MIME_TYPE  # noqa: SLF001 — 알려 준 것을 본다

    from pathlib import Path  # noqa: PLC0415

    window.definition = Path("열린.bpmn")  # 관문을 지난다 (위 시험이 그 관문을 본다)
    got: list[Any] = []
    window.canvas.create_task = lambda *a, **kw: got.append((a, kw))
    create = resources.Create(bpmn=resources.BPMN_SERVICE_TASK, name="끌어 온 것", chk={})
    window.canvas.dropped.emit(resources.as_payload(create), 321, 234)
    assert len(got) == 1, "드롭이 「캔버스에 추가」로 이어지지 않았다"
    assert got[0][0][:2] == (create.bpmn, create.name)
    assert got[0][1]["at"] == (321, 234), "놓은 자리가 캔버스로 가지 않았다"


def test_viewing_or_copying_without_an_open_process_says_so(window: Any) -> None:
    """받아 둔 공유 BPM 프로세스는 **BPM 프로세스마다**다 (ADR-0048) — 열린 것이 없으면 말한다."""
    shared = resources.Shared(
        package_id="shared.approval", version="1.1.0", process_id="Proc_approve"
    )
    center_actions.view_shared(window, shared)
    center_actions.copy_shared(window, shared)
    assert window.log_view.toPlainText().count(center_actions.NO_PROCESS) == 2


def test_something_that_is_not_a_shared_ref_is_ignored(window: Any) -> None:
    """신호는 자료형을 모른다 — 우리 것이 아니면 **조용히** 아무 일도 하지 않는다."""
    center_actions.view_shared(window, "쓰레기")
    center_actions.copy_shared(window, {"package_id": "x"})
    assert window.log_view.toPlainText() == ""


def test_the_read_only_window_draws_the_diagram_and_says_it_cannot_be_edited(
    webengine: Any,
) -> None:
    """STU-03 「열기 (읽기 전용)」의 창 (ADR-0051) — **정말 못 고치는 페이지**를 띄운다.

    머리 한 줄이 **어디서 온 것인지와 못 고친다는 것**을 함께 말하고, 그림이 들어가면 경고
    줄은 비어 있다 (`chk:*`를 뷰어도 moddle 설명으로 읽는다).
    """
    from pathlib import Path as _Path

    from PySide6.QtCore import QEventLoop, QTimer

    from chaeksas.studio.canvas import VIEW_PAGE
    from chaeksas.studio.viewer import DiagramViewer

    examples = _Path(__file__).resolve().parent.parent / "docs" / "08-business-examples" / "bpmn"
    xml = (examples / "fx02_business_rule.bpmn").read_text(encoding="utf-8")

    dialog = DiagramViewer("shared.approval@1.1.0 / Proc_approve", xml)
    assert "읽기 전용입니다" in dialog.header.text()
    assert "shared.approval@1.1.0 / Proc_approve" in dialog.header.text()

    loop = QEventLoop()
    dialog.canvas.opened.connect(loop.quit)
    QTimer.singleShot(30_000, loop.quit)
    loop.exec()
    if not dialog.canvas.live:
        dialog.close()
        _PROBE.append(dialog)
        pytest.skip("뷰어가 30초 안에 뜨지 않았다 (WebEngine이 이 환경에서 막혀 있다)")

    assert dialog.canvas.url().fileName() == VIEW_PAGE, "모델러 페이지가 아니다"
    # 그림을 넣는 것은 비동기다 — `stats`를 묻는 동안 안쪽 루프가 그것을 끝낸다.
    assert dialog.canvas.call_sync("stats")["elements"] > 4
    assert dialog.note.text() == "", "우리 예제는 경고 없이 들어간다"
    dialog.close()
    # **치우지 않고 들고 있는다** — `_PROBE`와 같은 까닭이다 (끝날 때 Qt가 프로필을 두고
    # 투덜대고, 뒤 시험이 도는 중에 Qt 객체가 죽으면 더 나쁜 꼴로 터진다, 04-setup §7).
    _PROBE.append(dialog)
