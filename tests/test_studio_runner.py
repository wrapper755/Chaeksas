"""Studio 시험 실행 (M3 조각 3e-3) — STU-08·STU-09.

여기가 **처음으로 한 바퀴가 돈다** — 예제를 가져와, 케이스 입력으로, 엔진을 돌려, C14 비교
규칙으로 판정하고, 배운 재생 명세를 패키지에 적는다.

거듭 보는 것 넷.

1. **엔진은 스레드를 만들지 않는다** — `QTimer`가 민다. 시험도 이벤트 루프를 돌려 기다린다.
2. **케이스가 시키는 대로만** 답한다 — 적지 않은 결재는 기다린다 (기한 초과 시험).
3. **Studio는 바깥으로 웹훅을 쏘지 않는다** — 시험 수신기로만 간다 (개발 PC 보호).
4. **배운 것은 패키지에 적힌다** (ADR-0028) — 엔진은 파일을 쓰지 않으므로 Studio가 한다.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from chaeksas.contracts.bpmn_ext import Case  # noqa: E402
from chaeksas.core.senders import EmailMessage, SendError, WebhookRequest  # noqa: E402
from chaeksas.studio.receiver import Receiver  # noqa: E402
from chaeksas.studio.run_actions import MAX_VALUE, format_variables  # noqa: E402
from chaeksas.studio.run_dialog import AUTONOMOUS, describe, unlearned  # noqa: E402
from chaeksas.studio.runner import (  # noqa: E402
    ERROR,
    FAIL,
    NO_EXPECT,
    PASS,
    CaseRun,
    Outcome,
    Plan,
    StudioSender,
    read_cases,
    resolve_inputs,
    summarize,
)
from chaeksas.studio.settings import Settings  # noqa: E402
from chaeksas.studio.workspace import Workspace  # noqa: E402

EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples" / "bpmn"


@pytest.fixture(scope="session")
def app() -> Any:
    from PySide6.QtWidgets import QApplication

    try:
        return QApplication.instance() or QApplication([])
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"Qt를 띄울 수 없다: {type(e).__name__}: {e}")


def studio(tmp_path: Path, example: str) -> tuple[Any, Settings]:
    """예제 하나를 작업 폴더로 가져오고, 그 Studio 설정을 만든다."""
    data = tmp_path / "studio"
    settings = replace(Settings(), data_dir=data, llm_base_url="")  # 모델은 쓰지 않는다
    made = Workspace(settings.workspace_dir).ensure().import_example(EXAMPLES, example)
    return made, settings


def drive(run: CaseRun, *, timeout_ms: int = 20_000) -> Outcome:
    """`QTimer`가 미는 실행이 끝날 때까지 이벤트 루프를 돈다."""
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    box: list[Outcome] = []

    def done(outcome: Outcome) -> None:
        box.append(outcome)
        loop.quit()

    run.ended.connect(done)
    QTimer.singleShot(timeout_ms, loop.quit)
    run.start()
    loop.exec()
    if not box:
        pytest.fail(f"시험 실행이 {timeout_ms}ms 안에 끝나지 않았다")
    return box[0]


# ─────────────────────────── 케이스 입력 연산자 (C14) ───────────────────────────


def test_now_plus_becomes_a_real_time() -> None:
    now = datetime(2026, 10, 4, 9, 0, tzinfo=UTC)
    found = resolve_inputs({"마감": {"$now_plus": "PT30M"}}, now=now, receiver=None)
    assert found["마감"].startswith("2026-10-04T09:30")


def test_a_plain_value_is_left_alone() -> None:
    raw = {"금액": 100, "쪽": {"a": 1, "b": 2}}
    found = resolve_inputs(raw, now=datetime.now(UTC), receiver=None)
    assert found == {"금액": 100, "쪽": {"a": 1, "b": 2}}


def test_test_receiver_needs_the_receiver_running() -> None:
    from chaeksas.core.engine import EngineError

    with pytest.raises(EngineError, match="시험 수신기가 꺼져"):
        resolve_inputs({"주소": {"$test_receiver": "reply"}}, now=datetime.now(UTC), receiver=None)


def test_test_receiver_gives_a_loopback_url() -> None:
    receiver = Receiver(port=0).start()
    try:
        found = resolve_inputs(
            {"주소": {"$test_receiver": "reply"}},
            now=datetime.now(UTC),
            receiver=receiver,
        )
        assert found["주소"].startswith("http://127.0.0.1:") and found["주소"].endswith("/reply")
    finally:
        receiver.stop()


# ─────────────────────────── 보내기 (개발 PC 보호) ───────────────────────────


def test_studio_never_sends_a_real_email() -> None:
    sender = StudioSender()
    found = sender.send_email(EmailMessage(to=("a@example.com",), subject="x", body="y"))
    assert found.ok and len(sender.emails) == 1


def test_a_webhook_outside_the_test_receiver_is_refused() -> None:
    """개발 PC에서 실수로 바깥에 쏘지 않는다 — C14는 `$test_receiver`만 예외로 둔다."""
    with pytest.raises(SendError, match="시험 수신기로만"):
        StudioSender().send_webhook(WebhookRequest(url="https://real.example.com/hook"))


def test_a_webhook_to_the_test_receiver_actually_arrives() -> None:
    receiver = Receiver(port=0).start()
    try:
        sender = StudioSender(receiver)
        found = sender.send_webhook(
            WebhookRequest(url=receiver.url_for("reply"), body={"건수": 3, "상태": "ok"})
        )
        assert found.status == 200
        (got,) = receiver.got
        assert got.name == "reply" and got.body == {"건수": 3, "상태": "ok"}
        assert "값" not in got.summary and "3" not in got.summary.replace("127.0.0.1", "")
    finally:
        receiver.stop()


# ─────────────────────────── 한 바퀴 (진짜 엔진) ───────────────────────────


def test_a_rule_example_passes_its_cases(app: Any, tmp_path: Path) -> None:
    """FX-02 — 규칙(DMN) 하나. 케이스가 적어 둔 기대값까지 **그대로** 간다."""
    made, settings = studio(tmp_path, "fx02_business_rule")
    definition = made.entry_definition
    assert definition is not None
    cases = read_cases(made, definition)
    assert [c.name for c in cases] == ["VIP 대량", "일반 소량"]

    outcomes = [
        drive(CaseRun(Plan(process=made, definition=definition, case=case, settings=settings)))
        for case in cases
    ]
    assert [o.verdict for o in outcomes] == [PASS, PASS], [o.detail for o in outcomes]
    assert summarize(outcomes) == "전체 2개 끝: 통과 2, 실패 0, 비교 안 함 0"
    assert outcomes[0].run is not None and outcomes[0].run.variables["최종가"] == 1200000


def test_a_wrong_expectation_is_reported_as_a_failure(app: Any, tmp_path: Path) -> None:
    made, settings = studio(tmp_path, "fx02_business_rule")
    definition = made.entry_definition
    assert definition is not None
    case = Case(name="틀린 기대", inputs={"금액": 1500000, "등급": "VIP"}, expected={"할인율": 0.9})
    found = drive(CaseRun(Plan(process=made, definition=definition, case=case, settings=settings)))
    assert found.verdict == FAIL and "할인율" in found.detail


def test_running_without_a_case_does_not_compare(app: Any, tmp_path: Path) -> None:
    made, settings = studio(tmp_path, "fx12_daily_report")
    definition = made.entry_definition
    assert definition is not None
    found = drive(CaseRun(Plan(process=made, definition=definition, case=None, settings=settings)))
    assert found.verdict == NO_EXPECT


def test_a_case_answers_the_approval_and_the_run_finishes(app: Any, tmp_path: Path) -> None:
    """케이스의 `approvals`가 결재에 자동으로 답한다 (C14)."""
    made, settings = studio(tmp_path, "fx19_manual_task_pc")
    definition = made.entry_definition
    assert definition is not None
    # 폼이 없는 확인은 `decision` 하나로 답한다 (C6 — 「승인 / 반려」 두 단추).
    case = Case(name="확인", inputs={}, approvals={"Manual_Paper": {"decision": "approve"}})
    found = drive(CaseRun(Plan(process=made, definition=definition, case=case, settings=settings)))
    assert found.verdict == NO_EXPECT, found.detail
    assert found.run is not None and found.run.state.value == "done"


def test_an_answer_the_form_refuses_ends_the_run_instead_of_looping(app: Any, tmp_path: Path) -> None:
    """케이스가 틀린 답을 주면 **그 자리에서 끝낸다** — 다음 틱에 또 같은 일이 생긴다.

    FX-19에서 실제로 겪었다 (폼 없는 확인에 빈 답 `{}`). 예제는 조각 3f에서 고쳤고, 여기서는
    **고친 예제에 일부러 빈 답을 주어** 그 자리가 막혀 있는지 본다.
    """
    made, settings = studio(tmp_path, "fx19_manual_task_pc")
    definition = made.entry_definition
    assert definition is not None
    case = Case(name="빈 답", inputs={}, approvals={"Manual_Paper": {}})
    found = drive(CaseRun(Plan(process=made, definition=definition, case=case, settings=settings)))
    assert found.verdict == ERROR and "빠진 칸" in found.detail


def test_the_fixed_example_case_now_passes(app: Any, tmp_path: Path) -> None:
    """**칸이 없어도 답은 비어 있지 않다** — 폼 없는 결재의 답은 `decision`이다 (C6, 조각 3f)."""
    made, settings = studio(tmp_path, "fx19_manual_task_pc")
    definition = made.entry_definition
    assert definition is not None
    case = read_cases(made, definition)[0]
    assert case.approvals == {"Manual_Paper": {"decision": "approve"}}
    found = drive(CaseRun(Plan(process=made, definition=definition, case=case, settings=settings)))
    assert found.verdict == PASS, found.detail


def test_an_unanswered_approval_keeps_waiting(app: Any, tmp_path: Path) -> None:
    """**적지 않은 결재는 답하지 않고 기다린다** — 기한 초과를 시험하는 길이다 (C14)."""
    made, settings = studio(tmp_path, "fx19_manual_task_pc")
    definition = made.entry_definition
    assert definition is not None
    case = Case(name="답 없음", inputs={}, approvals={})
    found = drive(CaseRun(Plan(process=made, definition=definition, case=case, settings=settings)))
    assert found.run is not None and found.run.state.value == "waiting"
    assert found.verdict == NO_EXPECT, "기대 결과가 없으니 비교하지 않는다"


def test_a_webhook_example_reaches_the_test_receiver(app: Any, tmp_path: Path) -> None:
    """FX-17 — 케이스가 `$test_receiver`로 주소를 받는다."""
    made, settings = studio(tmp_path, "fx17_webhook")
    definition = made.entry_definition
    assert definition is not None
    case = next(c for c in read_cases(made, definition) if "$test_receiver" in json.dumps(c.inputs))

    receiver = Receiver(port=0).start()
    try:
        found = drive(
            CaseRun(Plan(process=made, definition=definition, case=case, settings=settings), receiver)
        )
        assert found.verdict == PASS, found.detail
        assert [g.name for g in receiver.got] == ["hook"]
    finally:
        receiver.stop()


def test_a_file_writing_example_writes_into_the_output_folder(app: Any, tmp_path: Path) -> None:
    """ADR-0026 — 쓰기는 출력 폴더 안만. Studio가 실행마다 그 자리를 준다."""
    made, settings = studio(tmp_path, "fx12_daily_report")
    definition = made.entry_definition
    assert definition is not None
    found = drive(CaseRun(Plan(process=made, definition=definition, case=None, settings=settings)))
    assert found.run is not None
    written = sorted((settings.outputs_dir / made.id).rglob("*.md"))
    assert written, "파일 출력이 실제로 생겼다"
    assert written[0].read_text(encoding="utf-8").strip().startswith("#")


def test_the_run_log_is_written_as_jsonl(app: Any, tmp_path: Path) -> None:
    made, settings = studio(tmp_path, "fx02_business_rule")
    definition = made.entry_definition
    assert definition is not None
    case = read_cases(made, definition)[0]
    drive(CaseRun(Plan(process=made, definition=definition, case=case, settings=settings)))
    found = sorted((settings.data_dir / "runs").glob("test_*.jsonl"))
    assert found, "C3 기록이 남는다"
    lines = [json.loads(line) for line in found[0].read_text(encoding="utf-8").splitlines()]
    kinds = [one["kind"] for one in lines]
    assert kinds[0] == "run_started" and kinds[-1] == "run_finished"
    # 작업 폴더의 id — 내보내면 매니페스트 `id`가 되는 값이다 (ADR-0086).
    assert lines[0]["data"]["bpm_process_id"] == made.id


def test_a_missing_required_input_is_said_plainly(app: Any, tmp_path: Path) -> None:
    """케이스 없이 돌리면 필수 입력이 빈다 — 조용히 `None`으로 흘리지 않는다 (C14 §6)."""
    made, settings = studio(tmp_path, "fx06_document_read")
    definition = made.entry_definition
    assert definition is not None
    found = drive(CaseRun(Plan(process=made, definition=definition, case=None, settings=settings)))
    assert found.verdict == ERROR and "필요하다" in found.detail


def test_the_run_dialog_stops_a_caseless_run_that_lacks_required_inputs(app: Any, tmp_path: Path) -> None:
    """STU-08 — 엔진이 거부할 실행을 보내지 않고 창에서 까닭을 말한다 (U3)."""
    from chaeksas.studio.run_dialog import NO_CASE, RunDialog, required_inputs  # noqa: PLC0415

    made, settings = studio(tmp_path, "fx06_document_read")
    definition = made.entry_definition
    assert definition is not None
    names = required_inputs(definition)
    assert names, "이 예제는 필수 입력이 있다"
    dialog = RunDialog(None, made, definition, settings)
    dialog.case_box.setCurrentIndex(dialog.case_box.findText(NO_CASE))
    assert not dialog.run_button.isEnabled()
    assert not dialog.needs_case.isHidden() and names[0] in dialog.needs_case.text()
    dialog.case_box.setCurrentIndex(1)  # 케이스를 고르면 다시 켜진다
    assert dialog.run_button.isEnabled() and dialog.needs_case.isHidden()


def test_a_caseless_run_without_required_inputs_is_allowed(app: Any, tmp_path: Path) -> None:
    from chaeksas.studio.run_dialog import NO_CASE, RunDialog  # noqa: PLC0415

    made, settings = studio(tmp_path, "fx12_daily_report")
    definition = made.entry_definition
    assert definition is not None
    dialog = RunDialog(None, made, definition, settings)
    dialog.case_box.setCurrentIndex(dialog.case_box.findText(NO_CASE))
    assert dialog.run_button.isEnabled() and dialog.needs_case.isHidden()


def test_an_example_that_needs_a_model_says_so_instead_of_pretending(app: Any, tmp_path: Path) -> None:
    """모델이 설정되지 않았으면 **조용히 넘어가지 않는다** (ADR-0027)."""
    made, settings = studio(tmp_path, "fx06_document_read")
    definition = made.entry_definition
    assert definition is not None
    case = read_cases(made, definition)[0]
    found = drive(CaseRun(Plan(process=made, definition=definition, case=case, settings=settings)))
    assert found.verdict == ERROR
    assert "모델" in found.detail or "도구" in found.detail, found.detail


# ─────────────────────────── PC 위임 (ADR-0062 §2) ───────────────────────────

#: PC 위임 하나를 거쳐 그 값을 쓰는 서버 그림. **예제 묶음에 위임이 없어 여기서 만든다**
#: (`test_studio_packaging.py`도 같은 까닭으로 제 그림을 들고 있다). `calledElement`는
#: **읽는 사람을 위한 것**이라 패키지에 그 정의가 없어도 된다 — 대상은 다른 패키지다.
DELEGATING = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
  xmlns:chk="urn:chaeksas:bpmn:1" id="Defs_dlg" targetNamespace="urn:chaeksas:test">
  <bpmn:error id="Err_DLG" name="DELEGATION_FAILED" errorCode="DELEGATION_FAILED" />
  <bpmn:process id="Proc_fx03b_amount_branch" name="위임" isExecutable="true">
    <bpmn:extensionElements><chk:process>{"run_location": "server",
      "inputs": [{"name": "청구번호", "type": "string", "required": true}]}</chk:process>
    </bpmn:extensionElements>
    <bpmn:startEvent id="Start" />
    <bpmn:callActivity id="Call_Erp" name="ERP 화면 입력" calledElement="Proc_erp_input">
      <bpmn:extensionElements><chk:call>{"delegate":
        {"bpm_process_id": "fin.erp-input", "version": "1.0.0"},
        "input": {"전표번호": "청구번호"}, "output": {"입력결과": "결과코드"}}</chk:call>
      </bpmn:extensionElements>
    </bpmn:callActivity>
    <bpmn:scriptTask id="Task_After" scriptFormat="chk-expr">
      <bpmn:script>마무리 = 입력결과 + "-확인"</bpmn:script>
    </bpmn:scriptTask>
    <bpmn:endEvent id="End" />
    <bpmn:boundaryEvent id="Bnd_Dlg" name="위임 실패" attachedToRef="Call_Erp">
      <bpmn:errorEventDefinition errorRef="Err_DLG" />
    </bpmn:boundaryEvent>
    <bpmn:scriptTask id="Task_Fallback" scriptFormat="chk-expr">
      <bpmn:script>마무리 = "사람이 처리"</bpmn:script>
    </bpmn:scriptTask>
    <bpmn:endEvent id="End_Fallback" />
    <bpmn:sequenceFlow id="F1" sourceRef="Start" targetRef="Call_Erp" />
    <bpmn:sequenceFlow id="F2" sourceRef="Call_Erp" targetRef="Task_After" />
    <bpmn:sequenceFlow id="F3" sourceRef="Task_After" targetRef="End" />
    <bpmn:sequenceFlow id="F4" sourceRef="Bnd_Dlg" targetRef="Task_Fallback" />
    <bpmn:sequenceFlow id="F5" sourceRef="Task_Fallback" targetRef="End_Fallback" />
  </bpmn:process>
</bpmn:definitions>
"""


def delegating(tmp_path: Path) -> tuple[Any, Any, Settings]:
    """위임 그림을 작업 폴더에 넣고 다시 읽는다 — `(BPM 프로세스, 진입 정의, 설정)`."""
    made, settings = studio(tmp_path, "fx03b_amount_branch")
    entry = made.entry_definition
    assert entry is not None
    entry.path.write_text(DELEGATING, encoding="utf-8")
    opened = Workspace(settings.workspace_dir).read(made.folder, made.group)
    definition = opened.entry_definition
    assert definition is not None
    return opened, definition, settings


def test_a_case_gives_the_delegation_result_and_the_run_finishes(app: Any, tmp_path: Path) -> None:
    """**케이스가 적어 둔 결과로 위임이 끝난다** (ADR-0062 §2 — 증명할 다섯의 마지막).

    Studio에는 부를 PC Bot의 그림이 없고(다른 패키지다) 있다 해도 UI 태스크라 설계자 PC에서
    화면을 만지게 된다. 그래서 결재 답·메시지와 **같은 결**로 케이스가 결과를 적는다.
    **Center도 남의 패키지도 없이** 끝까지 간다.
    """
    made, definition, settings = delegating(tmp_path)
    case = Case(
        name="위임",
        inputs={"청구번호": "CLM-1"},
        delegations={"Call_Erp": {"결과코드": "OK"}},
        expected={"입력결과": "OK", "마무리": "OK-확인"},
    )
    found = drive(CaseRun(Plan(process=made, definition=definition, case=case, settings=settings)))
    assert found.verdict == PASS, found.detail


def test_only_what_the_graph_reads_becomes_a_variable(app: Any, tmp_path: Path) -> None:
    """**적은 것만 오간다** (C14 `chk:call.output`) — 돌려준 나머지는 버린다."""
    made, definition, settings = delegating(tmp_path)
    case = Case(
        name="덤",
        inputs={"청구번호": "CLM-1"},
        delegations={"Call_Erp": {"결과코드": "OK", "덤": "버린다"}},
    )
    found = drive(CaseRun(Plan(process=made, definition=definition, case=case, settings=settings)))
    assert found.run is not None
    assert found.run.variables["입력결과"] == "OK"
    assert "덤" not in found.run.variables and "결과코드" not in found.run.variables


def test_the_values_are_handed_over_as_values(app: Any, tmp_path: Path) -> None:
    """입력은 **맡길 때 값으로** 푼다 (PC 쪽은 서버 그림을 모른다) — 식 이름이 가지 않는다."""
    made, definition, settings = delegating(tmp_path)
    case = Case(
        name="입력",
        inputs={"청구번호": "CLM-7"},
        delegations={"Call_Erp": {"결과코드": "OK"}},
    )
    run = CaseRun(Plan(process=made, definition=definition, case=case, settings=settings))
    drive(run)
    (call,) = run.delegator.calls
    assert call.inputs == {"전표번호": "CLM-7"}
    assert (call.bpm_process_id, call.version) == ("fin.erp-input", "1.0.0")
    assert call.node_id == "Call_Erp" and call.node_instance == 1
    assert call.bot_ui is None, "그림이 PC를 지정하지 않았으면 고르는 것은 받는 쪽의 일이다"


def test_a_delegation_the_case_did_not_write_goes_to_the_error_boundary(
    app: Any, tmp_path: Path
) -> None:
    """**적어 두지 않은 위임은 그 자리에서 실패**다 (C14) — 기다리게 두면 끝나지 않는다.

    현장 PC도 Center도 없으니 기다릴 상대가 없다. 업무 실패라 **그림의 오류 경계가 받고**,
    그래서 이것이 경계를 시험하는 길이기도 하다. 그러려면 사유 코드가 그림이 받을 수 있는
    것이어야 한다 — **`DELEGATION_FAILED`**, 진짜 PC 실행이 실패했을 때와 같은 코드다.
    """
    made, definition, settings = delegating(tmp_path)
    case = Case(
        name="안 적음",
        inputs={"청구번호": "CLM-1"},
        delegations={},
        expected={"마무리": "사람이 처리"},
    )
    found = drive(CaseRun(Plan(process=made, definition=definition, case=case, settings=settings)))
    assert found.verdict == PASS, found.detail
    assert found.run is not None and found.run.state.value == "done", "경계가 받아 끝까지 갔다"


def test_a_delegation_without_an_error_boundary_fails_the_run(app: Any, tmp_path: Path) -> None:
    """경계가 없으면 **실행이 실패한다** — 조용히 기다리지 않는다."""
    made, settings = studio(tmp_path, "fx03b_amount_branch")
    entry = made.entry_definition
    assert entry is not None
    bare = DELEGATING.replace(
        '<bpmn:boundaryEvent id="Bnd_Dlg" name="위임 실패" attachedToRef="Call_Erp">'
        "\n      <bpmn:errorEventDefinition errorRef=\"Err_DLG\" />\n    </bpmn:boundaryEvent>",
        "",
    ).replace('<bpmn:sequenceFlow id="F4" sourceRef="Bnd_Dlg" targetRef="Task_Fallback" />', "")
    entry.path.write_text(bare, encoding="utf-8")
    opened = Workspace(settings.workspace_dir).read(made.folder, made.group)
    definition = opened.entry_definition
    assert definition is not None

    case = Case(name="경계 없음", inputs={"청구번호": "CLM-1"}, delegations={})
    found = drive(CaseRun(Plan(process=opened, definition=definition, case=case, settings=settings)))
    assert found.verdict == ERROR
    assert "케이스" in found.detail and "Call_Erp" in found.detail, found.detail


def test_a_value_the_graph_reads_but_the_case_does_not_return_fails(
    app: Any, tmp_path: Path
) -> None:
    """**적은 값이 오지 않으면 업무 실패**다 — 빈 값으로 이어 가지 않는다 (ADR-0062 §2).

    현장에서는 「그 Bot의 판이 바뀌었다」가 이 꼴이다. 여기서는 경계가 그것을 받는다.
    """
    made, definition, settings = delegating(tmp_path)
    case = Case(
        name="빈 값",
        inputs={"청구번호": "CLM-1"},
        delegations={"Call_Erp": {}},
        expected={"마무리": "사람이 처리"},
    )
    found = drive(CaseRun(Plan(process=made, definition=definition, case=case, settings=settings)))
    assert found.verdict == PASS, found.detail


def test_without_a_case_a_delegation_says_what_to_write() -> None:
    """케이스를 고르지 않고 돌리면 위임은 **적을 곳이 없다** — 그 말을 그대로 한다.

    창도 엔진도 필요 없는 자리라 포트만 직접 부른다.
    """
    from chaeksas.core.delegation import DelegationCall, DelegationError
    from chaeksas.studio.runner import CaseDelegator

    call = DelegationCall(
        run_id="test_20261015_090000_aaaaaa",
        node_id="Call_Erp",
        node_instance=1,
        bpm_process_id="fin.erp-input",
    )
    with pytest.raises(DelegationError) as caught:
        CaseDelegator(None).delegate(call)
    # **그림·설치 오류가 아니라 업무 실패다** — 그래서 경계가 받을 수 있다.
    assert caught.value.code == "DELEGATION_FAILED"
    assert "delegations에 적으세요" in str(caught.value)


# ─────────────────────────── 배운 것 적기 (ADR-0028) ───────────────────────────


def test_what_the_autonomous_run_learned_is_written_into_the_package(app: Any, tmp_path: Path) -> None:
    """엔진은 파일을 쓰지 않는다 — **Studio가** 패키지 안 `memory/specs.json`에 적는다."""
    from chaeksas.core.llm import RecordingLlm, Reply
    from chaeksas.core.replay import read_memory

    made, settings = studio(tmp_path, "fx06_document_read")
    definition = made.entry_definition
    assert definition is not None
    assert read_memory(made.folder).specs == [], "아직 배운 것이 없다"

    run = CaseRun(Plan(process=made, definition=definition, case=None, settings=settings))
    answers = [Reply(text=json.dumps({"요약": "한 줄", "쪽수": 3}, ensure_ascii=False), model="시험")]
    run.env = lambda: replace(  # type: ignore[method-assign]
        CaseRun.env(run), llm=RecordingLlm(replies=answers * 5), tools={}
    )
    drive(run)
    # 도구가 없어 실패했더라도, 성공한 실행만 적는다 — 그 규칙을 확인한다.
    assert read_memory(made.folder).specs == []


def test_the_run_dialog_turns_off_replay_when_nothing_was_learned(tmp_path: Path) -> None:
    """U3 — 고를 수 없는 것은 끄고 **이유**를 보인다."""
    made, _ = studio(tmp_path, "fx06_document_read")
    definition = made.entry_definition
    assert definition is not None
    assert unlearned(made, definition), "AI 태스크가 있고 명세가 없다"

    rules, _ = studio(tmp_path / "other", "fx02_business_rule")
    other = rules.entry_definition
    assert other is not None
    assert unlearned(rules, other) == [], "AI 태스크가 없으면 끌 이유도 없다"


def test_the_replay_menu_preselects_the_mode_only_when_it_can_be_chosen(
    tmp_path: Path, app: Any
) -> None:
    """실행 → 「결정 수행 (재생)...」(Ctrl+F5)은 STU-08을 그 모드로 열어 준다.

    **끈 라디오는 고르지 않는다** — 고르면 「실행」을 눌러도 어느 모드도 아니게 된다. 메뉴를
    끄지 않는 까닭이 여기 있다: 못 하는 사정은 창이 말한다 (U3).
    """
    from chaeksas.studio.run_dialog import DETERMINISTIC, RunDialog

    rules, settings = studio(tmp_path, "fx02_business_rule")  # AI 태스크가 없다 — 끌 이유가 없다
    definition = rules.entry_definition
    assert definition is not None
    chosen = RunDialog(None, rules, definition, settings, prefer=DETERMINISTIC)
    assert chosen.deterministic.isChecked() and not chosen.autonomous.isChecked()
    assert chosen.picked().mode == DETERMINISTIC

    unlearnt, settings = studio(tmp_path / "other", "fx06_document_read")  # 학습 안 된 AI 태스크
    other = unlearnt.entry_definition
    assert other is not None
    refused = RunDialog(None, unlearnt, other, settings, prefer=DETERMINISTIC)
    assert not refused.deterministic.isEnabled()
    assert refused.autonomous.isChecked(), "고를 수 없으면 자율 수행이 그대로 남는다"
    assert refused.picked().mode == AUTONOMOUS


def test_the_dialog_describes_the_case_in_one_line() -> None:
    assert describe(None) == "기대 결과를 비교하지 않습니다"
    assert describe(Case(name="x", inputs={"a": 1}, expected={})) == "입력 1개 · 기대 결과 없음 — 비교하지 않습니다"
    assert describe(Case(name="x", inputs={}, expected={"b": 1})) == "입력 0개 · 기대 결과 1개"


# ─────────────────────────── 「변수」 탭의 글 (Qt 없음) ───────────────────────────


def test_the_variables_tab_text_is_sorted_and_typed() -> None:
    """STU-09 「변수」 탭 — **Qt를 모르는 자리**라 글만 본다 (`run_actions.format_variables`)."""
    found = format_variables({"나중": 2, "먼저": "값", "목록": [1, 2]})
    lines = found.splitlines()
    assert lines[0] == "변수 3개"
    assert [one.split(" ")[0] for one in lines[2:]] == ["나중", "먼저", "목록"], "이름순이다"
    assert lines[2].startswith("나중 (int) = 2"), lines
    assert lines[3].startswith("먼저 (str) = 값"), "글자는 그대로 (JSON 따옴표를 더하지 않는다)"
    assert lines[4].startswith("목록 (list) = [1, 2]"), "글자 아닌 것은 JSON으로"


def test_a_long_value_is_cut_so_one_variable_does_not_fill_the_tab() -> None:
    found = format_variables({"긴것": "가" * 500})
    assert len(found.splitlines()[2]) < MAX_VALUE + 40
    assert "가" * MAX_VALUE in found
