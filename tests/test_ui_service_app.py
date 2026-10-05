"""UI 자동화 앱 — 레지스트리의 서버 부분 (C9·C11, M4 조각 8).

**진짜 앱을 띄우고 진짜 클라이언트로 부른다** (in-process). 그래야 계약 봉투·권한·저장이
한 줄로 맞물리는지 보인다.

거듭 보는 것 다섯.

1. **셀렉터가 나가는 작업은 `registry_write` 키만** 부를 수 있다 (C9). 없으면 403.
2. **공개 카탈로그에는 셀렉터가 없다** — 인증 없이 열리는 자리다.
3. **등록은 더하기다** — 기존 로케이터를 지우지 않고, 바뀐 것이 없으면 `revision`도 안 오른다.
4. **다시 띄워도 남는다** (SQLite) — 레지스트리가 메모리에만 있으면 되는 척이다.
5. **4xx는 다시 보내지 않는다** — 클라이언트가 그렇게 판단할 수 있어야 한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from chaeksas.contracts.service_app import ServiceAppKey
from chaeksas.ext.ui_automation.client.registry_client import RegistryClient, RegistryProblem
from chaeksas.ext.ui_automation.contracts.plan import LocatorSpec, SessionReport
from chaeksas.ext.ui_automation.contracts.registry import CatalogEntry, ElementHint, PageRegistration
from chaeksas.ext.ui_automation.service.app import REGISTRY_WRITE, create
from chaeksas.ext.ui_automation.service.store import Database, SqliteKeyStore
from chaeksas.service_kit import hash_key

WRITE_KEY = "chk_svc_" + "w" * 40
READ_KEY = "chk_svc_" + "r" * 40


def key(raw: str, *, name: str, scopes: list[str]) -> ServiceAppKey:
    return ServiceAppKey(
        name=name,
        hash=hash_key(raw),
        prefix=raw[:16],
        allowed_operations=["*"],
        allowed_modes=["deterministic", "autonomous"],
        extra_scopes=scopes,
        created_at="2026-10-05T09:00:00+09:00",
    )


@pytest.fixture
def served(tmp_path: Path) -> Any:
    path = tmp_path / "uia.sqlite3"
    app = create(db_path=path, admin_token="t-admin")
    store = SqliteKeyStore(db=Database(path=path))
    store.add(key(WRITE_KEY, name="등록 담당자", scopes=[REGISTRY_WRITE]))
    store.add(key(READ_KEY, name="운영 Bot", scopes=[]))
    return app, path


@pytest.fixture
def writer(served: Any) -> RegistryClient:
    app, _ = served
    return RegistryClient(base_url="http://app", api_key=WRITE_KEY, client=TestClient(app))


@pytest.fixture
def reader(served: Any) -> RegistryClient:
    app, _ = served
    return RegistryClient(base_url="http://app", api_key=READ_KEY, client=TestClient(app))


def page(page_id: str = "erp.order.form", **extra: Any) -> PageRegistration:
    body: dict[str, Any] = {
        "schema": 1,
        "page_id": page_id,
        "platform": "web",
        "name": "주문 입력",
        "locators": {
            "order.qty": [LocatorSpec(type="css", value="#qty")],
            "order.save": [LocatorSpec(type="role", value="button", name="저장", exact=True)],
        },
        "elements": {
            "order.qty": ElementHint(name="수량", kind="control"),
            "order.save": ElementHint(name="저장", kind="control"),
        },
    }
    body.update(extra)
    return PageRegistration.model_validate(body)


# ─────────────────────────── 권한 (C9) ───────────────────────────


def test_a_key_without_registry_write_cannot_register(reader: RegistryClient) -> None:
    """**운영 Bot 키로는 등록하지 못한다** — 셀렉터가 나가는 자리다 (C9)."""
    with pytest.raises(RegistryProblem) as caught:
        reader.register(page())
    assert caught.value.status == 403
    assert caught.value.code == "scope_missing"
    assert caught.value.permanent, "4xx는 다시 보내지 않는다"


def test_a_key_without_registry_write_cannot_read_selectors(
    writer: RegistryClient, reader: RegistryClient
) -> None:
    writer.register(page())
    with pytest.raises(RegistryProblem) as caught:
        reader.get_page("erp.order.form")
    assert caught.value.code == "scope_missing"


def test_listing_pages_needs_no_extra_scope(writer: RegistryClient, reader: RegistryClient) -> None:
    """목록에는 셀렉터가 없다 — 아무 키나 본다 (BUI-06 「화면 ID」 콤보)."""
    writer.register(page())
    found = reader.list_pages()
    assert [one.page_id for one in found] == ["erp.order.form"]
    assert found[0].element_count == 2


# ─────────────────────────── 등록 (C9) ───────────────────────────


def test_registering_a_new_page(writer: RegistryClient) -> None:
    found = writer.register(page())
    assert found.created_page
    assert len(found.created) == 2
    assert not found.unchanged


def test_registering_the_same_thing_changes_nothing(writer: RegistryClient) -> None:
    """같은 것을 다시 올려도 **Worker 계획 캐시가 버려지지 않는다** (C9)."""
    first = writer.register(page())
    again = writer.register(page())
    assert again.unchanged and again.created == []
    assert again.revision == first.revision, "바뀐 것이 없으면 revision도 그대로다"


def test_registering_adds_without_deleting(writer: RegistryClient) -> None:
    """**기존 것을 지우지 않는다** — 새 로케이터를 더한다 (C9)."""
    writer.register(page())
    writer.register(
        page(
            locators={"order.qty": [LocatorSpec(type="test_id", value="qty-input")]},
            elements={"order.qty": ElementHint(name="수량", kind="control")},
        )
    )
    found, _ = writer.get_page("erp.order.form")
    assert [one.type for one in found.locators["order.qty"]] == ["css", "test_id"]
    assert "order.save" in found.locators, "다른 요소는 그대로다"


def test_a_new_locator_is_unverified(writer: RegistryClient) -> None:
    """**사람이 검증해도 `unverified`**다 — `active`는 실행 통계로만 (C9·C8)."""
    writer.register(page())
    found, _ = writer.get_page("erp.order.form")
    assert {one.status for ladder in found.locators.values() for one in ladder} == {"unverified"}


def test_a_page_without_a_ladder_is_refused(writer: RegistryClient) -> None:
    """**사다리 없는 정보는 받지 않는다** (C9) — 보낸 쪽을 고쳐야 한다."""
    with pytest.raises(RegistryProblem) as caught:
        writer.register(page(locators={}, elements={"order.qty": ElementHint(name="수량"),
                                                    "order.save": ElementHint(name="저장")}))
    assert caught.value.status == 422
    assert caught.value.permanent


# ─────────────────────────── 삭제 (C9) ───────────────────────────


def test_deleting_an_element_says_what_went(writer: RegistryClient) -> None:
    writer.register(page())
    found = writer.delete("erp.order.form", "order.qty")
    assert (found.elements, found.locators) == (1, 1)
    left, _ = writer.get_page("erp.order.form")
    assert list(left.locators) == ["order.save"]


def test_deleting_something_pointed_at_needs_a_second_look(writer: RegistryClient) -> None:
    """끊길 경로가 있으면 `force` 없이는 막는다 (U9)."""
    writer.register(page())
    writer.register(
        page(
            "erp.order.list",
            locators={"list.new": [LocatorSpec(type="css", value="#new")]},
            elements={"list.new": ElementHint(name="새로", kind="control")},
            catalog={"list.new": CatalogEntry(actions=["click"], navigates_to="erp.order.form")},
        )
    )
    with pytest.raises(RegistryProblem) as caught:
        writer.delete("erp.order.form")
    assert caught.value.status == 409
    assert caught.value.code == "has_links"
    assert caught.value.detail["links"][0]["page_id"] == "erp.order.list"

    forced = writer.delete("erp.order.form", force=True)
    assert forced.broken_links and forced.elements == 2


def test_deleting_what_is_not_there(writer: RegistryClient) -> None:
    with pytest.raises(RegistryProblem) as caught:
        writer.delete("없는.화면")
    assert caught.value.status == 404


# ─────────────────────────── 보고·승격 (C8) ───────────────────────────


def report(status: str = "succeeded", *, origin: str = "run") -> SessionReport:
    return SessionReport.model_validate(
        {
            "schema": 1,
            "business_key": "run_1:Task:1:1",
            "page_id": "erp.order.form",
            "origin": origin,
            "status": status,
            "attempts": [
                {
                    "semantic_key": "order.qty",
                    "locator_key": LocatorSpec(type="css", value="#qty").key,
                    "succeeded": True,
                }
            ],
        }
    )


def test_three_runs_promote_a_locator(writer: RegistryClient) -> None:
    """`active`는 **실행에서 세 번 연속 성공**해야 준다 (C9)."""
    writer.register(page())
    for _ in range(2):
        assert writer.call("report", report().to_json_dict())["promoted"] == []
    promoted = writer.call("report", report().to_json_dict())["promoted"]
    assert promoted, "세 번째에 올라간다"
    found, _ = writer.get_page("erp.order.form")
    assert found.locators["order.qty"][0].status == "active"


def test_a_test_report_does_not_count(writer: RegistryClient) -> None:
    """**`test` 보고는 통계에 넣지 않는다** — 셀렉터 시험은 승격 근거가 아니다 (BUI-08)."""
    writer.register(page())
    for _ in range(5):
        writer.call("report", report(origin="test").to_json_dict())
    found, _ = writer.get_page("erp.order.form")
    assert found.locators["order.qty"][0].status == "unverified"


def test_a_report_needs_no_extra_scope(writer: RegistryClient, reader: RegistryClient) -> None:
    """보고는 **실행 중 Bot의 키**로 온다 — 등록 권한을 요구하면 안 된다 (C8)."""
    writer.register(page())
    assert reader.call("report", report().to_json_dict())["accepted"]


# ─────────────────────────── 카탈로그·저장 ───────────────────────────


def test_the_public_catalog_has_no_selectors(served: Any, writer: RegistryClient) -> None:
    """공개 카탈로그는 **인증 없이** 열린다 — 셀렉터가 새면 안 된다 (C9·C13 §5)."""
    app, _ = served
    writer.register(page())
    answer = TestClient(app).get("/v1/catalog")
    assert answer.status_code == 200
    body = answer.text
    assert "erp.order.form" in body
    assert "#qty" not in body and "css" not in body


def test_the_registry_survives_a_restart(served: Any, writer: RegistryClient) -> None:
    """**메모리에만 있으면 되는 척이다** — 다시 띄워도 남아야 한다."""
    _, path = served
    writer.register(page())
    again = RegistryClient(
        base_url="http://app", api_key=WRITE_KEY, client=TestClient(create(db_path=path))
    )
    found, _ = again.get_page("erp.order.form")
    assert list(found.locators) == ["order.qty", "order.save"]


def test_the_manifest_is_open(served: Any) -> None:
    """C7이 읽는 자리라 인증이 없다 — **비밀이 들어가지 않는다**."""
    app, _ = served
    body = TestClient(app).get("/manifest").json()
    assert body["app_id"] == "ui-automation"
    names = {one["name"] for one in body["operations"]}
    assert names == {
        "registry_list_pages", "registry_get_page", "registry_register", "registry_delete",
        "plan", "report",
    }
    assert "heal" not in names, "치유(C8)는 모델이 하는 일이라 아직 없다 — 되는 척하지 않는다"
    plan = next(one for one in body["operations"] if one["name"] == "plan")
    assert plan["modes"] == ["deterministic"], "자연어 목표(자율)는 아직 없다"


# ─────────────────────────── 멱등 (C11) ───────────────────────────


def test_the_same_call_twice_is_done_once(served: Any, writer: RegistryClient) -> None:
    """C11 멱등 — 같은 `(run_id, node_id, node_instance, attempt, call_seq)`는 **한 번만** 한다.

    서버 실행기가 부르고 죽었다 되살아나 같은 것을 다시 보내는 경우다 (원칙 9).
    """
    app, _ = served
    writer.register(page())
    body = writer.request("registry_delete", {"page_id": "erp.order.form"}, run_id="reg_abcd1234")
    client = TestClient(app)
    head = {"Authorization": f"Bearer {WRITE_KEY}"}

    first = client.post("/v1/ops/registry_delete", json=body.to_json_dict(), headers=head).json()
    assert first["output"]["elements"] == 2 and not first["replayed"]

    writer.register(page())  # 다시 만들어 둔다 — 멱등이 아니면 또 지울 것이다
    again = client.post("/v1/ops/registry_delete", json=body.to_json_dict(), headers=head).json()
    assert again["replayed"], "저장된 답을 돌려준다"
    assert [one.page_id for one in writer.list_pages()] == ["erp.order.form"], (
        "두 번째 삭제가 실제로 일어나지 않았다"
    )


def test_a_resend_counts_as_a_new_attempt(writer: RegistryClient) -> None:
    """C9 — 다시 보낼 때는 **`attempt`를 올린다**. 같은 등록이 두 번 들어가도 더하기라 안전하다."""
    first = writer.request("registry_register", {"page": {}}, run_id="reg_abcd1234")
    again = writer.request("registry_register", {"page": {}}, run_id="reg_abcd1234")
    assert (first.attempt, again.attempt) == (1, 2)
    assert first.run_id == again.run_id and first.node_id == "registry"
    assert first.mode == "deterministic", "등록은 LLM을 쓰지 않는다"
