"""STU-14 서비스 앱 태스크 편집기 — 고를 거리와 편집기 (M5 조각 16).

거듭 보는 것 다섯.

1. **고를 거리는 Center에서 온다** — C11 서비스 앱(C7 리소스 등록)과 외부 확장 정의(C13 §4)가
   **같은 모양**으로 들어온다. 편집기는 어느 쪽인지 신경 쓰지 않는다.
2. **키 값은 없다** (ADR-0013) — 「API 키」는 **참조 이름**만 받고 기본은 「프로세스 설정을 따름」이다.
3. **적어 둔 것을 조용히 바꾸지 않는다** — 작업을 바꿔도 사람이 적은 값은 남고, 작업 정의에
   없는 칸은 **낡았다고 말한다**.
4. **필수 입력이 비면 「적용」을 막는다.** 실행할 때 알면 늦다.
5. **스키마는 선택 칸이다** — manifest가 입력·출력 칸을 알려 주지 않으면 사람이 적게 둔다
   (없는 칸을 지어내지 않는다).
"""

from __future__ import annotations

import os
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from chaeksas.contracts.extension import ExtensionManifest  # noqa: E402
from chaeksas.contracts.resources import ServiceAppResource  # noqa: E402
from chaeksas.studio.service_catalog import (  # noqa: E402
    KIND_C11,
    KIND_EXTERNAL,
    Catalog,
    Usage,
    build,
    missing_required,
    stale_fields,
)


@pytest.fixture(scope="module")
def app() -> Any:
    from PySide6.QtWidgets import QApplication

    try:
        return QApplication.instance() or QApplication([])
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"Qt를 띄울 수 없다: {type(e).__name__}: {e}")


# ─────────────────────────── 고를 거리 ───────────────────────────


def service_app(**over: Any) -> ServiceAppResource:
    base: dict[str, Any] = {
        "app_id": "hris",
        "name": "모의 인사 시스템",
        "status": "ok",
        "base_url": "http://127.0.0.1:8030",
        "operations": [
            {
                "name": "register_leave",
                "description": "휴가 등록",
                "modes": ["deterministic", "autonomous"],
                "timeout_s": 30,
                "input_schema": {
                    "type": "object",
                    "required": ["emp_id", "days"],
                    "properties": {
                        "emp_id": {"type": "string", "description": "사번"},
                        "start": {"type": "string"},
                        "days": {"type": "number"},
                    },
                },
                "output_schema": {"type": "object", "properties": {"result": {"type": "object"}}},
            },
            {"name": "get_leave_ledger", "description": "휴가 원장", "modes": ["autonomous"]},
        ],
    }
    base.update(over)
    return ServiceAppResource.model_validate(base)


def external() -> ExtensionManifest:
    return ExtensionManifest.model_validate({
        "schema": 2,
        "id": "ext-credit",
        "version": "1.0.0",
        "name": "외부 신용 조회",
        "publisher": "외부 업체",
        "tier": "external",
        "service": {
            "protocol": "http-adapter",
            "base_url": "https://credit.example.com",
            "adapter": {
                "allowed_hosts": ["credit.example.com"],
                "auth": {"type": "bearer"},
                "operations": [
                    {
                        "name": "lookup",
                        "description": "신용 조회",
                        "modes": ["deterministic", "autonomous"],
                        "retry_on": [429, 503],
                        "input_schema": {
                            "type": "object",
                            "required": ["biz_no"],
                            "properties": {"biz_no": {"type": "string"}},
                        },
                        "request": {"method": "POST", "path": "/v1/lookup"},
                        "response": {"output": {"result": "$.result"}},
                    }
                ],
            },
        },
    })


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    return build([service_app()], [external()])


def test_both_sources_come_in_the_same_shape(catalog: Catalog) -> None:
    """C11 앱과 외부 앱이 **한 목록**에 들어온다 — 구분만 다르다."""
    assert [one.app_id for one in catalog.apps] == ["ext-credit", "hris"]
    assert catalog.app("hris").kind == KIND_C11  # type: ignore[union-attr]
    assert catalog.app("ext-credit").kind == KIND_EXTERNAL  # type: ignore[union-attr]


def test_the_label_says_the_name_the_kind_and_the_status(catalog: Catalog) -> None:
    """STU-14 콤보 — 「<앱 이름> (<구분>) — 정상 / 응답 없음」."""
    assert catalog.app("hris").label == "모의 인사 시스템 (서비스 앱) — 정상"  # type: ignore[union-attr]
    # 외부 앱은 `/healthz`가 없어 Center가 상태를 모른다 (C7).
    assert "알 수 없음" in catalog.app("ext-credit").label  # type: ignore[union-attr]


def test_input_fields_come_from_the_schema(catalog: Catalog) -> None:
    found = catalog.app("hris").operation("register_leave")  # type: ignore[union-attr]
    assert found is not None
    assert [one.name for one in found.inputs] == ["emp_id", "start", "days"]
    assert [one.required for one in found.inputs] == [True, False, True]
    assert [one.type for one in found.inputs] == ["string", "string", "number"]
    assert [one.name for one in found.outputs] == ["result"]


def test_an_operation_without_a_schema_has_no_fields(catalog: Catalog) -> None:
    """스키마는 **선택 칸**이다 — 없으면 칸을 지어내지 않는다."""
    found = catalog.app("hris").operation("get_leave_ledger")  # type: ignore[union-attr]
    assert found is not None
    assert not found.has_schema
    assert found.inputs == () and found.outputs == ()


def test_a_mode_that_is_not_deterministic_is_flagged(catalog: Catalog) -> None:
    """Bot에서 돌지 않는 작업 — STU-14가 경고한다."""
    app = catalog.app("hris")
    assert app is not None
    assert app.operation("register_leave").deterministic_ok is True  # type: ignore[union-attr]
    assert app.operation("get_leave_ledger").deterministic_ok is False  # type: ignore[union-attr]


def test_an_empty_catalog_is_falsy() -> None:
    """**고를 것이 없으면 그렇게 말한다** — 편집기가 빈 콤보를 두지 않는다."""
    assert not build()
    assert not Catalog()


def test_unreachable_center_keeps_the_problems() -> None:
    from chaeksas.studio.service_catalog import from_center  # noqa: PLC0415

    found = from_center(None)
    assert not found
    assert found.problems and "STU-10" in found.problems[0]


# ─────────────────────────── 그림에 적힌 것 ───────────────────────────


CALL = {
    "app_id": "hris",
    "operation": "register_leave",
    "input": {"emp_id": "사번", "days": "일수"},
    "output": {"등록": "result"},
    "retry": {"max": 2, "on": [503]},
}


def test_usage_reads_and_writes_the_contract_shape() -> None:
    """`chk:serviceCall` → 화면 → 다시 `chk:serviceCall`에서 **잃는 것이 없다**."""
    assert Usage.of(CALL).to_call() == CALL


def test_empty_boxes_are_not_written() -> None:
    """빈 것은 그림에 넣지 않는다 — 쓸모없는 칸을 남기지 않는다."""
    made = Usage(app_id="hris", operation="register_leave").to_call()
    assert made == {"app_id": "hris", "operation": "register_leave"}


def test_stale_fields_are_named(catalog: Catalog) -> None:
    """manifest가 바뀌어 없는 필드가 남으면 **그것을 말한다** (STU-14 검증)."""
    operation = catalog.app("hris").operation("register_leave")  # type: ignore[union-attr]
    usage = Usage.of({**CALL, "input": {"emp_id": "사번", "없는칸": "값"}, "output": {"x": "없는출력"}})
    assert stale_fields(operation, usage) == (["없는칸"], ["없는출력"])


def test_nothing_is_stale_when_the_manifest_said_nothing(catalog: Catalog) -> None:
    operation = catalog.app("hris").operation("get_leave_ledger")  # type: ignore[union-attr]
    usage = Usage.of({"app_id": "hris", "operation": "get_leave_ledger", "input": {"무엇": "값"}})
    assert stale_fields(operation, usage) == ([], [])


def test_a_missing_required_input_is_named(catalog: Catalog) -> None:
    operation = catalog.app("hris").operation("register_leave")  # type: ignore[union-attr]
    usage = Usage.of({**CALL, "input": {"emp_id": "사번", "days": "  "}})
    assert missing_required(operation, usage) == ["days"]


# ─────────────────────────── 편집기 (Qt) ───────────────────────────


def editor(app: Any, catalog: Catalog, call: dict[str, Any] | None = None) -> Any:
    from chaeksas.studio.service_editor import ServiceTaskEditor  # noqa: PLC0415

    made = ServiceTaskEditor(catalog)
    made.load(dict(call) if call is not None else {})
    return made


def test_the_editor_draws_what_the_drawing_says(app: Any, catalog: Catalog) -> None:
    made = editor(app, catalog, CALL)
    assert made.app_box.currentData() == "hris"
    assert made.operation_box.currentData() == "register_leave"
    assert made.dump() == CALL
    # 작업 설명과 지원 모드가 보인다 (STU-14).
    assert made.operation_note.text() == "휴가 등록"
    assert "deterministic" in made.modes_note.text()


def test_the_editor_shows_every_schema_field_even_if_unused(app: Any, catalog: Catalog) -> None:
    """입력 칸은 **manifest에서** 만든다 — 아직 값이 없는 칸도 보인다."""
    made = editor(app, catalog, CALL)
    names = [made.inputs.item(row, 0).text() for row in range(made.inputs.rowCount())]
    assert names == ["emp_id", "start", "days"]
    values = [made.inputs.item(row, 3).text() for row in range(made.inputs.rowCount())]
    assert values == ["사번", "", "일수"]


def test_the_editor_keeps_what_a_person_wrote_outside_the_schema(app: Any, catalog: Catalog) -> None:
    """**적어 둔 것을 조용히 지우지 않는다** — 스키마에 없는 칸도 줄로 남는다."""
    made = editor(app, catalog, {**CALL, "input": {"emp_id": "사번", "옛칸": "값"}})
    names = [made.inputs.item(row, 0).text() for row in range(made.inputs.rowCount())]
    assert "옛칸" in names
    assert made.dump()["input"]["옛칸"] == "값"
    _, warnings = made.problems()
    assert any("작업 정의가 바뀌었습니다" in one for one in warnings)


def test_the_key_box_is_off_until_you_ask_for_an_exception(app: Any, catalog: Catalog) -> None:
    """기본은 「BPM 프로세스 설정을 따름」이다 — 참조를 적는 것은 예외일 때만 (STU-14)."""
    made = editor(app, catalog, CALL)
    assert made.follow_key.isChecked()
    assert not made.key_box.isEnabled()
    assert "key_ref" not in made.dump()

    made.follow_key.setChecked(False)
    made.key_box.setText("hr-hris-write")
    assert made.key_box.isEnabled()
    assert made.dump()["key_ref"] == "hr-hris-write"


def test_the_editor_never_holds_a_key_value(app: Any, catalog: Catalog) -> None:
    """**키 값은 Studio의 비밀 창고에 있다** (ADR-0013) — 편집기는 이름만 안다."""
    made = editor(app, catalog, {**CALL, "key_ref": "hr-hris"})
    body = made.dump()
    assert body["key_ref"] == "hr-hris"
    assert not any("chk_svc" in str(one) for one in body.values())


def test_a_missing_required_input_blocks_apply(app: Any, catalog: Catalog) -> None:
    made = editor(app, catalog, {**CALL, "input": {"emp_id": "사번"}})
    blocking, _ = made.problems()
    assert any("days" in one for one in blocking)


def test_an_empty_output_row_blocks_apply(app: Any, catalog: Catalog) -> None:
    from PySide6.QtWidgets import QTableWidgetItem  # noqa: PLC0415

    made = editor(app, catalog, CALL)
    made.outputs.setRowCount(made.outputs.rowCount() + 1)
    made.outputs.setItem(made.outputs.rowCount() - 1, 0, QTableWidgetItem("result"))
    made.outputs.setItem(made.outputs.rowCount() - 1, 1, QTableWidgetItem(""))
    blocking, _ = made.problems()
    assert any("빈 칸" in one for one in blocking)


def test_an_operation_that_cannot_run_deterministically_warns(app: Any, catalog: Catalog) -> None:
    made = editor(app, catalog, {"app_id": "hris", "operation": "get_leave_ledger"})
    _, warnings = made.problems()
    assert any("Bot(결정 수행)에서 실행할 수 없습니다" in one for one in warnings)


def test_filling_expected_inputs_does_not_overwrite_what_is_there(app: Any, catalog: Catalog) -> None:
    """「기대 입력 채우기」는 **빈 값만** 채운다 (STU-14)."""
    made = editor(app, catalog, {**CALL, "input": {"emp_id": "다른변수"}})
    made._fill_expected()
    found = made.dump()["input"]
    assert found["emp_id"] == "다른변수"  # 적어 둔 것은 그대로
    assert found["start"] == "start" and found["days"] == "days"


def test_same_names_fills_only_empty_variables(app: Any, catalog: Catalog) -> None:
    made = editor(app, catalog, {"app_id": "hris", "operation": "register_leave"})
    made._same_names()
    assert made.dump()["output"] == {"result": "result"}


def test_an_external_operation_is_editable_the_same_way(app: Any, catalog: Catalog) -> None:
    """외부 앱도 **같은 편집기**다 — 어댑터 작업인지 신경 쓰지 않는다 (C13 §4)."""
    made = editor(app, catalog, {"app_id": "ext-credit", "operation": "lookup", "input": {"biz_no": "사업자번호"}})
    assert made.operation_box.currentData() == "lookup"
    # 다시 부를 상태 코드는 **정의가 알려 준 것**이다.
    assert "429" in made.retry_note.text()
    blocking, _ = made.problems()
    assert not blocking


def test_an_empty_catalog_says_so_instead_of_an_empty_combo(app: Any) -> None:
    made = editor(app, Catalog(), {})
    assert not made.app_box.isEnabled()
    assert "없습니다" in made.app_box.currentText()
    blocking, _ = made.problems()
    assert any("서비스 앱을 고르세요" in one for one in blocking)


# ─────────────────────────── 속성 패널에 붙는다 ───────────────────────────


def test_the_properties_panel_attaches_the_editor_for_a_service_call(app: Any, catalog: Catalog) -> None:
    """STU-04가 `chk:serviceCall`을 만나면 STU-14 편집기를 탭으로 끼운다."""
    import json  # noqa: PLC0415

    from chaeksas.studio.properties import Properties  # noqa: PLC0415
    from chaeksas.studio.service_editor import TAB_LABEL  # noqa: PLC0415

    panel = Properties()
    panel.catalog = catalog
    panel.show_element({
        "id": "Task_Leave",
        "type": "bpmn:ServiceTask",
        "name": "휴가 등록",
        "chk": {"serviceCall": json.dumps(CALL, ensure_ascii=False)},
    })
    assert panel.tabs.tabText(1) == TAB_LABEL
    assert panel._editor_key == "serviceCall"

    # 고친 것은 `chk.serviceCall` **통째로** 간다 (`data` 포장이 없다).
    panel._editor.retry_box.setValue(3)
    changes, problem = panel.patch()
    assert problem is None, problem
    assert json.loads(changes["chk"]["serviceCall"])["retry"]["max"] == 3


def test_the_panel_blocks_apply_when_the_editor_blocks(app: Any, catalog: Catalog) -> None:
    import json  # noqa: PLC0415

    from chaeksas.studio.properties import Properties  # noqa: PLC0415

    panel = Properties()
    panel.catalog = catalog
    panel.show_element({
        "id": "Task_Leave",
        "type": "bpmn:ServiceTask",
        "chk": {"serviceCall": json.dumps(CALL, ensure_ascii=False)},
    })
    panel._editor.inputs.item(2, 3).setText("")  # 필수 `days`를 비운다
    changes, problem = panel.patch()
    assert changes == {}
    assert problem is not None and "days" in problem
