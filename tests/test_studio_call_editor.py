"""STU-04 호출 편집기 (`studio/call_editor.py`) — 화면 없이.

보는 것은 넷이다: 업무 예제의 호출이 **손대지 않으면 같은 본문으로** 돌아오는가, 엔진·검사·Center가
거부할 것을 **「적용」 전에 막는가**(대상을 모르면 건너뛰는가), 「채우기」가 **빈 자리만** 더하는가,
속성 패널이 `calledElement`와 `bpm:call`을 **통째로** 넘기는가.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from chaeksas.contracts.bpmn_ext import BpmnProcess, Call, read_process  # noqa: E402
from chaeksas.contracts.center_api import PackageInfo  # noqa: E402
from chaeksas.studio.call_editor import (  # noqa: E402
    BOUNDARY_NOTE,
    MODE_DELEGATE,
    MODE_LOCAL,
    PC_NO_DELEGATE,
    SERVER_BOT_NO_PC,
    CallEditor,
    local_targets,
)
from chaeksas.studio.service_catalog import (  # noqa: E402
    CallInput,
    CallTarget,
    delegation_targets,
    target_of,
)

EXAMPLES = Path("docs/08-business-examples/bpmn")

SHIPPING = CallTarget(
    id="Proc_ship",
    name="배송비",
    where="이 패키지",
    inputs=(CallInput("지역", required=True), CallInput("무게"), CallInput("담당", from_center=True)),
    outputs=("배송비", "구간"),
)
PC_BOT = CallTarget(
    id="erp-entry",
    name="ERP 입력",
    where="PC",
    run_location="pc",
    process_id="Proc_erp_entry",
    inputs=(CallInput("전표번호", required=True),),
    outputs=("결과코드",),
)
SERVER_BOT = CallTarget(id="batch-item", run_location="server", process_id="Proc_batch_item", outputs=("결과",))
BOTS = {one.id: one for one in (PC_BOT, SERVER_BOT)}
LOCAL_CALL: dict[str, Any] = {"input": {"지역": "고객.지역"}, "output": {"비용": "배송비"}}


@pytest.fixture(autouse=True)
def _app() -> Any:
    from PySide6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


def loaded(
    body: dict[str, Any],
    *,
    run_location: str | None = "server",
    targets: dict[str, CallTarget] | None = None,
    bots: dict[str, CallTarget] | None = None,
) -> CallEditor:
    made = CallEditor(
        run_location=run_location,
        targets={SHIPPING.id: SHIPPING} if targets is None else targets,
        bots=BOTS if bots is None else bots,
    )
    made.load(body)
    return made


def rows(table: Any) -> list[tuple[str, str]]:
    return [(table.item(r, 0).text(), table.item(r, 1).text()) for r in range(table.rowCount())]


# ── 보이기·되돌려 주기 ──


def test_a_local_call_is_shown() -> None:
    made = loaded({"calledElement": "Proc_ship", "call": LOCAL_CALL})
    assert made.mode() == MODE_LOCAL
    assert made.target_box.currentData() == "Proc_ship"
    assert rows(made.inputs) == [("지역", "고객.지역")]
    assert rows(made.outputs) == [("비용", "배송비")]
    assert not made.delegate_box.isVisibleTo(made)
    assert made.boundary_note.text() == BOUNDARY_NOTE
    assert "받는 것: 지역, 무게" in made.target_note.text(), "Center가 넣는 입력은 받는 것이 아니다"


def test_a_delegation_is_shown() -> None:
    body = {
        "calledElement": "Proc_erp_entry",
        "call": {"delegate": {"bpm_process_id": "erp-entry", "version": "1.2.0", "bot_ui": "담당자PC"}},
    }
    made = loaded(body)
    assert made.mode() == MODE_DELEGATE
    assert made.bot_id() == "erp-entry"
    assert made.version_box.text() == "1.2.0"
    assert made.bot_ui_box.text() == "담당자PC"
    assert made.delegate_box.isVisibleTo(made)
    assert made.dump() == body


def test_unknown_keys_survive() -> None:
    body = {"calledElement": "Proc_ship", "call": {"future": 1, "input": {"지역": "x"}}}
    made = loaded(body)
    assert made.dump() == body


def test_absent_maps_are_not_added() -> None:
    """읽은 그림에 `input`·`output`이 없으면 빈 사전을 더하지 않는다 (조용히 바꾸지 않는다)."""
    made = loaded({"calledElement": "Proc_ship", "call": {}})
    assert made.dump() == {"calledElement": "Proc_ship", "call": {}}


def _example_targets() -> dict[str, BpmnProcess]:
    return {
        found.id: found
        for found in (read_process(p.read_text(encoding="utf-8")) for p in sorted(EXAMPLES.glob("*.bpmn")))
    }


def test_every_example_call_round_trips_and_is_not_blocked() -> None:
    """업무 예제의 호출이 **손대지 않으면 같은 본문으로** 돌아오고, 고칠 것 없이 막히지 않는다.

    대상은 예제 폴더의 정의들이다. 위임 대상은 생성기의 이름 규칙(`Proc_<id>`)으로 그 정의를 찾아
    BPM 프로세스로 세운다 — 그래야 출력·입력 대조까지 진짜 예제로 밟는다.
    """
    processes = _example_targets()
    targets = {pid: target_of(found, "이 패키지") for pid, found in processes.items()}
    seen = delegated = 0
    for path in sorted(EXAMPLES.glob("*.bpmn")):
        drawn = read_process(path.read_text(encoding="utf-8"))
        for node in drawn.all_nodes():
            if node.kind != "callActivity":
                continue
            seen += 1
            spec: Call | None = node.prop("call")
            call = spec.model_dump(exclude_unset=True) if spec is not None else {}
            bots: dict[str, CallTarget] = {}
            if spec is not None and spec.delegate is not None:
                delegated += 1
                bot = spec.delegate.bpm_process_id
                found = processes["Proc_" + bot.replace("-", "_")]
                bots[bot] = CallTarget(**{**target_of(found, "").__dict__, "id": bot})
            body = {"calledElement": node.called_element or "", "call": call}
            made = loaded(body, run_location=drawn.info.run_location, targets=targets, bots=bots)
            assert made.dump() == body, f"{path.name}:{node.id}"
            errors, _ = made.problems()
            assert errors == [], f"{path.name}:{node.id}: {errors}"
    assert seen >= 9 and delegated >= 2, "예제의 호출·위임을 찾았다"


# ── 막는 것 ──


def test_nothing_picked_is_blocked() -> None:
    made = loaded({"calledElement": "", "call": {}})
    assert made.problems()[0] == ["부를 정의를 고르세요."]


def test_a_target_outside_the_package_is_shown_and_blocked() -> None:
    made = loaded({"calledElement": "Proc_gone", "call": {}})
    assert "(패키지에 없음)" in made.target_box.currentText()
    assert "B14" in made.problems()[0][0]
    assert made.dump()["calledElement"] == "Proc_gone", "지우지 않는다"


def test_unknown_targets_skip_the_check() -> None:
    """열린 BPM 프로세스가 없으면(`None`) 모른다 — 모르는 것으로 막지 않는다."""
    made = CallEditor(run_location="server", targets=None)
    made.load({"calledElement": "Proc_x", "call": {"output": {"a": "b"}}})
    assert made.problems()[0] == []


def test_delegation_is_off_for_pc_processes_and_blocked_if_present() -> None:
    made = loaded({"calledElement": "Proc_ship", "call": {}}, run_location="pc")
    assert not made.mode_picks[MODE_DELEGATE].isEnabled()
    assert made.mode_note.text() == PC_NO_DELEGATE
    written = loaded({"call": {"delegate": {"bpm_process_id": "erp-entry"}}}, run_location="pc")
    assert written.mode_picks[MODE_DELEGATE].isEnabled(), "적힌 위임은 끄지 않는다"
    assert PC_NO_DELEGATE in written.problems()[0]


def test_a_drawing_without_run_location_cannot_delegate() -> None:
    """B14와 같은 판정이다 — 적지 않은 것은 `server`가 아니다."""
    made = loaded({"call": {"delegate": {"bpm_process_id": "erp-entry"}}}, run_location=None)
    assert PC_NO_DELEGATE in made.problems()[0]


def test_an_empty_bot_is_blocked() -> None:
    made = loaded({"calledElement": "Proc_ship", "call": {}})
    made.mode_picks[MODE_DELEGATE].setChecked(True)
    made.bot_box.setEditText("")
    assert "맡길 BPM 프로세스를 고르세요 (bpm_process_id)." in made.problems()[0]


def test_a_pc_expression_for_a_server_bot_is_blocked() -> None:
    made = loaded({"call": {"delegate": {"bpm_process_id": "batch-item", "bot_ui": "'pc-1'"}}})
    assert SERVER_BOT_NO_PC in made.problems()[0]
    made.bot_ui_box.setText("")
    assert made.problems()[0] == []
    assert not made.bot_ui_box.isEnabled(), "비우면 꺼진다"


@pytest.mark.parametrize(
    ("call", "expected"),
    [
        ({"input": {"": "x"}}, "「호출 대상 변수」이 빈 줄"),
        ({"input": {"지역": ""}}, "「식」을 적으세요"),
        ({"output": {"1잘못": "배송비"}}, "내 변수 이름으로 쓸 수 없습니다"),
        ({"output": {"비용": "없는출력"}}, "내놓지 않는 출력"),
        ({"input": {"없는입력": "1"}}, "input_unknown"),
        ({"input": {"담당": "'나'"}}, "input_not_from_caller"),
    ],
)
def test_what_the_engine_or_b14_refuses_is_blocked(call: dict[str, Any], expected: str) -> None:
    made = loaded({"calledElement": "Proc_ship", "call": call})
    errors, _ = made.problems()
    assert any(expected in one for one in errors), errors


def test_duplicate_keys_are_blocked() -> None:
    made = loaded({"calledElement": "Proc_ship", "call": {"input": {"지역": "a"}}})
    made.add_input.click()
    table: Any = made.inputs
    table.item(1, 0).setText("지역")
    table.item(1, 1).setText("b")
    assert any("겹칩니다" in one for one in made.problems()[0])


def test_unknown_bot_skips_the_comparisons() -> None:
    made = loaded({"call": {"delegate": {"bpm_process_id": "not-listed"}, "output": {"a": "b"}, "input": {"x": "1"}}})
    assert made.problems()[0] == []
    assert not made.fill_inputs.isEnabled()


def test_a_missing_required_input_is_a_warning() -> None:
    made = loaded({"calledElement": "Proc_ship", "call": {}})
    errors, warnings = made.problems()
    assert errors == [] and warnings == ["넘기지 않은 필수 입력: 지역"]


# ── 갈래 바꾸기·채우기 ──


def test_switching_to_local_drops_the_delegation() -> None:
    made = loaded({"calledElement": "Proc_erp_entry", "call": {"delegate": {"bpm_process_id": "erp-entry"}}})
    made.mode_picks[MODE_LOCAL].setChecked(True)
    made.target_box.setCurrentIndex(made.target_box.findData("Proc_ship"))
    assert made.dump() == {"calledElement": "Proc_ship", "call": {}}


def test_picking_a_bot_writes_its_process_id() -> None:
    made = loaded({"calledElement": "Proc_ship", "call": {}})
    made.mode_picks[MODE_DELEGATE].setChecked(True)
    made.bot_box.setCurrentIndex(made.bot_box.findData("erp-entry"))
    assert made.dump() == {"calledElement": "Proc_erp_entry", "call": {"delegate": {"bpm_process_id": "erp-entry"}}}
    made.bot_box.setEditText("typed-bot")
    assert made.dump()["calledElement"] == "", "모르는 BPM 프로세스이면 남의 이름을 남기지 않는다"


def test_fill_adds_only_missing_rows() -> None:
    made = loaded({"calledElement": "Proc_ship", "call": LOCAL_CALL})
    made.fill_inputs.click()
    made.fill_outputs.click()
    assert rows(made.inputs) == [("지역", "고객.지역"), ("무게", "무게")], "있는 줄을 덮지 않고, Center 입력은 뺀다"
    assert rows(made.outputs) == [("비용", "배송비"), ("구간", "구간")]
    made.fill_outputs.click()
    assert len(rows(made.outputs)) == 2, "두 번 눌러도 같다"


def test_fill_from_a_bot_manifest() -> None:
    made = loaded({"call": {"delegate": {"bpm_process_id": "erp-entry"}}})
    made.fill_inputs.click()
    made.fill_outputs.click()
    assert made.dump()["call"]["input"] == {"전표번호": "전표번호"}
    assert made.dump()["call"]["output"] == {"결과코드": "결과코드"}


# ── 고를 거리 짓기 ──


def _package(version: str, **manifest: Any) -> PackageInfo:
    raw = {
        "schema": 1,
        "kind": "bpm_process",
        "id": "erp-entry",
        "version": version,
        "name": "ERP 입력",
        "entry": "main.bpmn",
        "process_id": "Proc_erp_entry",
        "requires": {},
        "human": {},
        "built": {"by": "studio", "at": "2026-10-01T00:00:00Z", "core": "0.1.0", "spec_version": 1},
        "content_hash": "sha256:" + "0" * 64,
        **manifest,
    }
    return PackageInfo.model_validate({
        "id": "erp-entry", "version": version, "kind": "bpm_process", "status": "approved",
        "content_hash": "sha256:" + "0" * 64, "uploaded_by": "s", "uploaded_at": "2026-10-01T00:00:00Z",
        "manifest": raw,
    })


def test_delegation_targets_merge_versions() -> None:
    found = delegation_targets([
        _package("1.0.0", run_location="pc", outputs=["a"], inputs=[
            {"name": "x", "type": "str", "required": True},
            {"name": "who", "type": "str", "source": "staff.id"},
        ]),
        _package("1.1.0", run_location="pc", outputs=["b"], inputs=[
            {"name": "who", "type": "str", "source": "staff.id"},
        ]),
    ])["erp-entry"]
    assert found.outputs == ("a", "b")
    assert found.run_location == "pc" and found.where == "PC" and found.process_id == "Proc_erp_entry"
    by_name = {one.name: one for one in found.inputs}
    assert by_name["x"].required and not by_name["x"].from_center
    assert by_name["who"].from_center, "모든 판이 Center 출처로 선언했다"


def test_delegation_targets_forget_a_run_location_that_differs() -> None:
    found = delegation_targets([_package("1.0.0", run_location="pc"), _package("2.0.0", run_location="server")])
    assert found["erp-entry"].run_location is None


def test_local_targets_include_installed_libs(tmp_path: Path) -> None:
    """**엔진·B14가 찾는 `processes()`**와 같은 것을 고른다 — 설치한 공유 정의에는 판이 붙는다."""
    from chaeksas.studio.workspace import Workspace  # noqa: PLC0415

    space = Workspace(tmp_path).ensure()
    made = space.create("caller", name="부르는 쪽")
    lib_xml = (EXAMPLES / "bx12_shipping_fee.bpmn").read_text(encoding="utf-8")
    space.install_lib(made, package_id="ship-lib", version="1.0.0", definitions={"shipping.bpmn": lib_xml})
    made = space.read(made.folder, made.group)
    found = local_targets(made)
    assert found is not None
    shared = found[read_process(lib_xml).id]
    assert shared.where == "공유 (ship-lib@1.0.0)"
    assert local_targets(None) is None


# ── 속성 패널 ──


def panel_with(body: dict[str, Any], *, chk: dict[str, Any] | None = None) -> Any:
    from chaeksas.studio.properties import Properties  # noqa: PLC0415
    from chaeksas.studio.service_catalog import Catalog  # noqa: PLC0415

    panel = Properties()
    panel.run_location = "server"
    panel.call_targets = lambda: {SHIPPING.id: SHIPPING}
    panel.catalog = Catalog(bots=BOTS)
    panel.show_element({
        "id": "Call_1", "type": "CallActivity", "name": "호출", **body,
        "chk": {name: json.dumps(value, ensure_ascii=False) for name, value in (chk or {}).items()},
    })
    return panel


def test_the_panel_attaches_it_and_sends_both_parts() -> None:
    panel = panel_with({"calledElement": "Proc_ship"}, chk={"call": {"input": {"지역": "a"}}})
    assert panel.tabs.tabText(1) == "호출"
    editor: Any = panel._editor  # noqa: SLF001
    editor.mode_picks[MODE_DELEGATE].setChecked(True)
    editor.bot_box.setCurrentIndex(editor.bot_box.findData("erp-entry"))
    editor.inputs.item(0, 0).setText("전표번호")
    changes, problem = panel.patch()
    assert problem is None
    assert changes["calledElement"] == "Proc_erp_entry"
    assert json.loads(changes["chk"]["call"]) == {
        "input": {"전표번호": "a"},
        "delegate": {"bpm_process_id": "erp-entry"},
    }


def test_an_untouched_call_sends_nothing() -> None:
    panel = panel_with({"calledElement": "Proc_ship"})
    assert panel.tabs.tabText(1) == "호출"
    assert panel.patch() == ({}, None)


def test_changing_only_the_target_does_not_add_a_chk_call() -> None:
    panel = panel_with({"calledElement": ""})
    editor: Any = panel._editor  # noqa: SLF001
    editor.target_box.setCurrentIndex(editor.target_box.findData("Proc_ship"))
    assert panel.patch() == ({"calledElement": "Proc_ship"}, None)


def test_a_blocking_problem_blocks_the_panel() -> None:
    panel = panel_with({"calledElement": "Proc_ship"})
    editor: Any = panel._editor  # noqa: SLF001
    editor.target_box.setCurrentIndex(0)
    assert panel.patch() == ({}, "부를 정의를 고르세요.")
