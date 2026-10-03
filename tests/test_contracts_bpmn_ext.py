"""C14 BPMN 확장 속성 — 모델·읽기·검사 B1~B14.

가장 센 시험은 맨 아래 **업무 예제 50개**다 (`docs/08-business-examples/bpmn/`). 그 묶음이 이
형식으로 쓰였으니, 모델이 틀리면 거기서 바로 드러난다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from chaeksas.contracts.bpmn_ext import (
    BUILTIN_VARS,
    BpmnReadError,
    CaseFile,
    DecisionIo,
    available_vars,
    blocking,
    duration_hours,
    expression_vars,
    is_var_name,
    matches,
    read_process,
    script_vars,
    validate,
)

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "docs" / "08-business-examples"


def wrap(body: str, *, process_json: str = '{"run_location": "pc"}') -> str:
    """최소 BPMN 한 벌. 본문만 바꿔 가며 규칙을 시험한다."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
  xmlns:chk="urn:chaeksas:bpmn:1" id="Defs_t" targetNamespace="urn:chaeksas:test">
  <bpmn:process id="Proc_t" name="시험" isExecutable="true">
    <bpmn:extensionElements><chk:process>{process_json}</chk:process></bpmn:extensionElements>
    {body}
  </bpmn:process>
</bpmn:definitions>"""


def line(*nodes: str) -> str:
    """시작 → 노드들 → 끝으로 잇는다 (B9에 걸리지 않게)."""
    ids = ["Start", *[n.split('id="')[1].split('"')[0] for n in nodes], "End"]
    flows = "".join(
        f'<bpmn:sequenceFlow id="F{i}" sourceRef="{a}" targetRef="{b}" />'
        for i, (a, b) in enumerate(zip(ids, ids[1:], strict=False))
    )
    incoming = "".join(
        f"<!-- {a}→{b} -->" for a, b in zip(ids, ids[1:], strict=False)
    )
    return f'<bpmn:startEvent id="Start" />{"".join(nodes)}<bpmn:endEvent id="End" />{flows}{incoming}'


def codes(xml: str, **kw: Any) -> list[str]:
    return [v.rule for v in validate(read_process(xml), **kw)]


# ─────────────────────────── 기본 규칙 ───────────────────────────


def test_variable_names_allow_hangul_but_not_spaces() -> None:
    for good in ("대상월", "지급합계", "amount", "_tmp", "값2"):
        assert is_var_name(good), good
    for bad in ("대상 월", "지급-합계", "2월", "", "$x"):
        assert not is_var_name(bad), bad


def test_expression_vars_skips_strings_functions_and_kwargs() -> None:
    """식에서 변수만 뽑는다. 하나라도 새면 B11 경고가 쏟아진다 (실제로 그랬다)."""
    assert expression_vars("지급진행 == '지급 대상대로 진행'") == {"지급진행"}
    assert expression_vars("대상월 or 지난달()") == {"대상월"}
    # 키워드 이름(품목·수량)은 변수가 아니고, 값으로 쓰인 `x`·`q`는 변수다.
    assert expression_vars("dict(품목=x.code, 수량=q)") == {"x", "q"}
    assert expression_vars("[x for x in 청구목록 if x.금액 > 0]") == {"청구목록"}
    assert expression_vars("[dict(건, 사유=s) for 건, s in zip(내역, 사유목록)]") == {"내역", "사유목록"}
    assert expression_vars("f'{오늘} 요약'") == set()


def test_script_vars_follow_line_order() -> None:
    """앞줄에서 만든 변수는 뒷줄에서 읽어도 된다."""
    reads, made = script_vars("보류 = [x for x in 목록 if x.보류]\n보류건수 = len(보류)")
    assert reads == {"목록"}
    assert made == {"보류", "보류건수"}


def test_duration_hours() -> None:
    assert duration_hours("PT30M") == 0.5
    assert duration_hours("P3D") == 72
    assert duration_hours("P1DT2H") == 26
    assert duration_hours("마감시각") is None  # 변수 이름


# ─────────────────────────── 읽기 ───────────────────────────


def test_read_process_reads_chk_elements() -> None:
    xml = wrap(
        line(
            '<bpmn:serviceTask id="Task_Ai"><bpmn:extensionElements>'
            '<chk:aiTask>{"goal": "## 할 일", "domain": "llm", "results": {"요약": "string"}}</chk:aiTask>'
            "</bpmn:extensionElements></bpmn:serviceTask>"
        )
    )
    process = read_process(xml)
    assert process.id == "Proc_t"
    assert process.info.run_location == "pc"
    task = process.node("Task_Ai")
    assert task is not None
    assert task.prop("aiTask").domain == "llm"
    assert task.prop("aiTask").results == {"요약": "string"}


def test_extension_task_keeps_its_body_opaque() -> None:
    """확장 태스크의 속은 플랫폼이 해석하지 않는다 (ADR-0018)."""
    xml = wrap(
        line(
            '<bpmn:serviceTask id="Task_Ui"><bpmn:extensionElements>'
            '<chk:task type="ui_task" extension="ui-automation">{"page_id": "erp.order", "steps": []}</chk:task>'
            "</bpmn:extensionElements></bpmn:serviceTask>"
        )
    )
    task = read_process(xml).node("Task_Ui")
    assert task is not None
    found = task.prop("task")
    assert (found.type, found.extension) == ("ui_task", "ui-automation")
    assert found.data["page_id"] == "erp.order"  # 그대로 담아 둔다


def test_broken_xml_and_missing_process_raise() -> None:
    with pytest.raises(BpmnReadError):
        read_process("<not xml")
    with pytest.raises(BpmnReadError, match="bpmn:process"):
        read_process(
            '<?xml version="1.0"?><bpmn:definitions '
            'xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" />'
        )


def test_unknown_chk_element_is_ignored() -> None:
    """모르는 `chk:*`는 거부하지 않는다 (호환 규칙)."""
    xml = wrap(line('<bpmn:serviceTask id="T"><bpmn:extensionElements><chk:future>{}</chk:future>'
                    "</bpmn:extensionElements></bpmn:serviceTask>"))
    task = read_process(xml).node("T")
    assert task is not None and task.props == {} and task.bad_props == {}


# ─────────────────────────── 검사 규칙 ───────────────────────────


def test_b1_reports_chk_json_that_does_not_fit() -> None:
    xml = wrap(line('<bpmn:serviceTask id="T"><bpmn:extensionElements>'
                    '<chk:aiTask>{"domain": "llm"}</chk:aiTask>'  # goal이 없다
                    "</bpmn:extensionElements></bpmn:serviceTask>"))
    assert "B1" in codes(xml)


def test_b2_show_must_be_variable_names() -> None:
    xml = wrap(line('<bpmn:userTask id="Ap"><bpmn:extensionElements>'
                    '<chk:approval>{"title": "확인", "show": ["대상 월"]}</chk:approval>'
                    "</bpmn:extensionElements></bpmn:userTask>"))
    assert "B2" in codes(xml)


def test_b3_unconditional_branch_must_be_default() -> None:
    body = (
        '<bpmn:startEvent id="Start" /><bpmn:exclusiveGateway id="Gw" /><bpmn:endEvent id="E1" />'
        '<bpmn:endEvent id="E2" />'
        '<bpmn:sequenceFlow id="F0" sourceRef="Start" targetRef="Gw" />'
        '<bpmn:sequenceFlow id="F1" sourceRef="Gw" targetRef="E1">'
        "<bpmn:conditionExpression>값 &gt; 0</bpmn:conditionExpression></bpmn:sequenceFlow>"
        '<bpmn:sequenceFlow id="F2" sourceRef="Gw" targetRef="E2" />'
    )
    assert "B3" in codes(wrap(body))
    # default로 지정하면 통과한다.
    assert "B3" not in codes(wrap(body.replace('<bpmn:exclusiveGateway id="Gw" />',
                                               '<bpmn:exclusiveGateway id="Gw" default="F2" />')))


def test_b4_loop_needs_collect_into() -> None:
    xml = wrap(line('<bpmn:serviceTask id="T"><bpmn:extensionElements>'
                    '<chk:aiTask>{"goal": "x", "domain": "llm"}</chk:aiTask>'
                    '<chk:loop>{"collection": "목록", "item": "건"}</chk:loop>'
                    "</bpmn:extensionElements>"
                    '<bpmn:multiInstanceLoopCharacteristics isSequential="true" /></bpmn:serviceTask>'))
    assert "B4" in codes(xml)


def test_b5_file_output_needs_store_as_and_content() -> None:
    xml = wrap(line('<bpmn:scriptTask id="T"><bpmn:script>a = 1</bpmn:script></bpmn:scriptTask>')
               + '<bpmn:dataObjectReference id="D" dataObjectRef="DO"><bpmn:extensionElements>'
                 '<chk:dataOutput>{"path": "보고.md", "format": "md"}</chk:dataOutput>'
                 "</bpmn:extensionElements></bpmn:dataObjectReference>")
    found = codes(xml)
    assert found.count("B5") == 2  # store_as 없음 + template·variables 모두 없음


def test_b6_server_cannot_run_pc_only_things() -> None:
    xml = wrap(
        line('<bpmn:serviceTask id="T"><bpmn:extensionElements>'
             '<chk:aiTask>{"goal": "x", "domain": "web"}</chk:aiTask>'
             "</bpmn:extensionElements></bpmn:serviceTask>"),
        process_json='{"run_location": "server"}',
    )
    assert "B6" in codes(xml)
    # PC면 괜찮다.
    assert "B6" not in codes(wrap(
        line('<bpmn:serviceTask id="T"><bpmn:extensionElements>'
             '<chk:aiTask>{"goal": "x", "domain": "web"}</chk:aiTask>'
             "</bpmn:extensionElements></bpmn:serviceTask>")))


def test_b6_asks_the_host_about_extension_task_locations() -> None:
    """어느 태스크 종류가 PC 전용인지 플랫폼은 스스로 모른다 (ADR-0018)."""
    xml = wrap(
        line('<bpmn:serviceTask id="T"><bpmn:extensionElements>'
             '<chk:task type="ui_task" extension="ui-automation">{}</chk:task>'
             "</bpmn:extensionElements></bpmn:serviceTask>"),
        process_json='{"run_location": "server"}',
    )
    assert "B6" not in codes(xml)  # 알려 주지 않으면 건너뛴다
    assert "B6" in codes(xml, task_type_locations={"ui_task": ["pc"]})


def test_b7_service_call_needs_a_key_ref() -> None:
    task = ('<bpmn:serviceTask id="T"><bpmn:extensionElements>'
            '<chk:serviceCall>{"app_id": "erp", "operation": "read"}</chk:serviceCall>'
            "</bpmn:extensionElements></bpmn:serviceTask>")
    assert "B7" in codes(wrap(line(task)))
    ok = wrap(line(task), process_json='{"run_location": "pc", "service_keys": {"erp": "erp-reader"}}')
    assert "B7" not in codes(ok)


def test_b8_result_types_and_code_like_names() -> None:
    bad_type = wrap(line('<bpmn:serviceTask id="T"><bpmn:extensionElements>'
                         '<chk:aiTask>{"goal": "x", "domain": "llm", "results": {"합계": "integer"}}</chk:aiTask>'
                         "</bpmn:extensionElements></bpmn:serviceTask>"))
    assert "B8" in codes(bad_type)
    warn = wrap(line('<bpmn:serviceTask id="T"><bpmn:extensionElements>'
                     '<chk:aiTask>{"goal": "x", "domain": "llm", "results": {"발주번호": "int"}}</chk:aiTask>'
                     "</bpmn:extensionElements></bpmn:serviceTask>"))
    found = validate(read_process(warn))
    assert [v.severity for v in found if v.rule == "B8"] == ["warning"]
    assert blocking(found) == []


def test_b9_unconnected_nodes() -> None:
    xml = wrap('<bpmn:startEvent id="Start" /><bpmn:serviceTask id="Lonely" /><bpmn:endEvent id="End" />'
               '<bpmn:sequenceFlow id="F0" sourceRef="Start" targetRef="End" />')
    assert codes(xml).count("B9") == 2  # 들어오는 흐름·나가는 흐름 둘 다 없다


def test_b10_generated_ids_warn() -> None:
    xml = wrap(line('<bpmn:scriptTask id="Activity_0ngrasb"><bpmn:script>a = 1</bpmn:script></bpmn:scriptTask>'))
    found = [v for v in validate(read_process(xml)) if v.rule == "B10"]
    assert len(found) == 1 and found[0].severity == "warning"


def test_b11_warns_about_a_variable_made_on_only_one_path() -> None:
    """C14가 들고 있는 예 — 한 가지에서만 생기는 값을 합류 뒤에 읽는다."""
    body = (
        '<bpmn:startEvent id="Start" /><bpmn:exclusiveGateway id="Gw" default="F2" />'
        '<bpmn:serviceTask id="Task_A"><bpmn:extensionElements>'
        '<chk:aiTask>{"goal": "x", "domain": "llm", "results": {"대체": "string"}}</chk:aiTask>'
        "</bpmn:extensionElements></bpmn:serviceTask>"
        '<bpmn:scriptTask id="Task_B"><bpmn:script>통과 = True</bpmn:script></bpmn:scriptTask>'
        '<bpmn:exclusiveGateway id="Merge" />'
        '<bpmn:scriptTask id="Task_Use"><bpmn:script>결과 = 대체</bpmn:script></bpmn:scriptTask>'
        '<bpmn:endEvent id="End" />'
        '<bpmn:sequenceFlow id="F0" sourceRef="Start" targetRef="Gw" />'
        '<bpmn:sequenceFlow id="F1" sourceRef="Gw" targetRef="Task_A">'
        "<bpmn:conditionExpression>참</bpmn:conditionExpression></bpmn:sequenceFlow>"
        '<bpmn:sequenceFlow id="F2" sourceRef="Gw" targetRef="Task_B" />'
        '<bpmn:sequenceFlow id="F3" sourceRef="Task_A" targetRef="Merge" />'
        '<bpmn:sequenceFlow id="F4" sourceRef="Task_B" targetRef="Merge" />'
        '<bpmn:sequenceFlow id="F5" sourceRef="Merge" targetRef="Task_Use" />'
        '<bpmn:sequenceFlow id="F6" sourceRef="Task_Use" targetRef="End" />'
    )
    found = [v for v in validate(read_process(wrap(body))) if v.rule == "B11"]
    assert len(found) == 1
    assert found[0].items == ["대체"] and found[0].severity == "warning"


def test_b11_is_quiet_after_a_parallel_join() -> None:
    """병렬 합류는 **모든** 가지를 기다린다 — 가지가 만든 값이 모두 있다."""
    body = (
        '<bpmn:startEvent id="Start" /><bpmn:parallelGateway id="Split" />'
        '<bpmn:scriptTask id="T_A"><bpmn:script>a = 1</bpmn:script></bpmn:scriptTask>'
        '<bpmn:scriptTask id="T_B"><bpmn:script>b = 2</bpmn:script></bpmn:scriptTask>'
        '<bpmn:parallelGateway id="Join" />'
        '<bpmn:scriptTask id="T_Sum"><bpmn:script>합 = a + b</bpmn:script></bpmn:scriptTask>'
        '<bpmn:endEvent id="End" />'
        '<bpmn:sequenceFlow id="F0" sourceRef="Start" targetRef="Split" />'
        '<bpmn:sequenceFlow id="F1" sourceRef="Split" targetRef="T_A" />'
        '<bpmn:sequenceFlow id="F2" sourceRef="Split" targetRef="T_B" />'
        '<bpmn:sequenceFlow id="F3" sourceRef="T_A" targetRef="Join" />'
        '<bpmn:sequenceFlow id="F4" sourceRef="T_B" targetRef="Join" />'
        '<bpmn:sequenceFlow id="F5" sourceRef="Join" targetRef="T_Sum" />'
        '<bpmn:sequenceFlow id="F6" sourceRef="T_Sum" targetRef="End" />'
    )
    assert [v for v in validate(read_process(wrap(body))) if v.rule == "B11"] == []


def test_b11_says_nothing_after_an_extension_task() -> None:
    """확장 태스크가 무엇을 만드는지 모르면 「없다」고 말하지 않는다 (ADR-0018)."""
    xml = wrap(
        line('<bpmn:serviceTask id="T_Ui"><bpmn:extensionElements>'
             '<chk:task type="ui_task" extension="ui-automation">{}</chk:task>'
             "</bpmn:extensionElements></bpmn:serviceTask>",
             '<bpmn:scriptTask id="T_Use"><bpmn:script>합 = 거래내역</bpmn:script></bpmn:scriptTask>')
    )
    assert [v for v in validate(read_process(xml)) if v.rule == "B11"] == []
    # 확장이 알려 주면 그때는 말한다.
    found = validate(read_process(xml), extension_task_vars=lambda _task: ["다른것"])
    assert [v.items for v in found if v.rule == "B11"] == [["거래내역"]]


def test_b11_allows_builtin_variables() -> None:
    xml = wrap(line('<bpmn:scriptTask id="T"><bpmn:script>이름 = 오늘</bpmn:script></bpmn:scriptTask>'))
    assert [v for v in validate(read_process(xml)) if v.rule == "B11"] == []
    assert "오늘" in BUILTIN_VARS


def test_b12_approval_fields_and_boundary_hosts() -> None:
    bad_choice = wrap(line('<bpmn:userTask id="Ap"><bpmn:extensionElements>'
                           '<chk:approval>{"title": "t", "fields": [{"key": "k", "label": "l", "type": "choice"}]}'
                           "</chk:approval></bpmn:extensionElements></bpmn:userTask>"))
    assert "B12" in codes(bad_choice)
    bad_host = wrap(
        '<bpmn:startEvent id="Start" /><bpmn:exclusiveGateway id="Gw" />'
        '<bpmn:boundaryEvent id="Bnd" attachedToRef="Gw"><bpmn:outgoing>F2</bpmn:outgoing>'
        "<bpmn:errorEventDefinition /></bpmn:boundaryEvent>"
        '<bpmn:endEvent id="End" /><bpmn:endEvent id="End2" />'
        '<bpmn:sequenceFlow id="F0" sourceRef="Start" targetRef="Gw" />'
        '<bpmn:sequenceFlow id="F1" sourceRef="Gw" targetRef="End" />'
        '<bpmn:sequenceFlow id="F2" sourceRef="Bnd" targetRef="End2" />'
    )
    assert "B12" in codes(bad_host)


def test_b13_warns_about_webhook_sending_everything() -> None:
    xml = wrap(line('<bpmn:sendTask id="T"><bpmn:extensionElements>'
                    '<chk:webhook>{"url": "https://x.example.com/h", "body": "all"}</chk:webhook>'
                    "</bpmn:extensionElements></bpmn:sendTask>"))
    found = [v for v in validate(read_process(xml)) if v.rule == "B13"]
    assert len(found) == 1 and found[0].severity == "warning"


def test_b13_warns_about_long_field_approvals() -> None:
    xml = wrap(line('<bpmn:userTask id="Ap"><bpmn:extensionElements>'
                    '<chk:approval>{"title": "t", "location": "field", "expires": "P3D"}</chk:approval>'
                    "</bpmn:extensionElements></bpmn:userTask>"))
    assert "B13" in [v.rule for v in validate(read_process(xml))]


def test_b14_parallel_branches_must_match() -> None:
    body = (
        '<bpmn:startEvent id="Start" /><bpmn:parallelGateway id="Split" />'
        '<bpmn:scriptTask id="T_A"><bpmn:script>a = 1</bpmn:script></bpmn:scriptTask>'
        '<bpmn:scriptTask id="T_B"><bpmn:script>b = 2</bpmn:script></bpmn:scriptTask>'
        '<bpmn:scriptTask id="T_C"><bpmn:script>c = 3</bpmn:script></bpmn:scriptTask>'
        '<bpmn:parallelGateway id="Join" /><bpmn:endEvent id="End" />'
        '<bpmn:sequenceFlow id="F0" sourceRef="Start" targetRef="Split" />'
        '<bpmn:sequenceFlow id="F1" sourceRef="Split" targetRef="T_A" />'
        '<bpmn:sequenceFlow id="F2" sourceRef="Split" targetRef="T_B" />'
        '<bpmn:sequenceFlow id="F3" sourceRef="Split" targetRef="T_C" />'
        '<bpmn:sequenceFlow id="F4" sourceRef="T_A" targetRef="Join" />'
        '<bpmn:sequenceFlow id="F5" sourceRef="T_B" targetRef="Join" />'
        '<bpmn:sequenceFlow id="F6" sourceRef="T_C" targetRef="End" />'
        '<bpmn:sequenceFlow id="F7" sourceRef="Join" targetRef="End" />'
    )
    assert "B14" in codes(wrap(body))


def test_b14_timer_start_cannot_need_inputs() -> None:
    xml = wrap(
        line('<bpmn:scriptTask id="T"><bpmn:script>a = 1</bpmn:script></bpmn:scriptTask>').replace(
            '<bpmn:startEvent id="Start" />',
            '<bpmn:startEvent id="Start"><bpmn:timerEventDefinition>'
            "<bpmn:timeCycle>0 9 * * 1-5</bpmn:timeCycle></bpmn:timerEventDefinition></bpmn:startEvent>",
        ),
        process_json=(
            '{"run_location": "server", '
            '"inputs": [{"name": "대상월", "type": "string", "required": true}]}'
        ),
    )
    assert "B14" in codes(xml)


def test_b14_matches_rule_against_dmn_and_call_against_target() -> None:
    xml = wrap(line('<bpmn:businessRuleTask id="R"><bpmn:extensionElements>'
                    '<chk:rule>{"decision": "등급판정", "input": {"연체일": "일"}, '
                    '"output": {"등급": "grade"}}</chk:rule>'
                    "</bpmn:extensionElements></bpmn:businessRuleTask>"))
    ok = DecisionIo(inputs=("연체일",), outputs=("grade",))
    assert "B14" not in codes(xml, dmn_decisions={"등급판정": ok})
    wrong = DecisionIo(inputs=("연체일", "금액"), outputs=("rating",))
    assert codes(xml, dmn_decisions={"등급판정": wrong}).count("B14") == 2
    assert "B14" in codes(xml, dmn_decisions={})  # 결정이 패키지에 없다


# ─────────────────────────── 시험 케이스 형식 ───────────────────────────


@pytest.mark.parametrize(
    ("expected", "actual", "ok"),
    [
        (5, 5, True),
        (5, 6, False),
        ("*", "값", True),
        ("*", "", False),
        ("*", None, False),
        ({"$gt": 10}, 11, True),
        ({"$gt": 10}, 10, False),
        ({"$gte": 10}, 10, True),
        ({"$lt": 10}, 9, True),
        ({"$lte": 10}, 11, False),
        ({"$contains": "확인"}, "공급사에 확인 요청", True),
        ({"$contains": "확인"}, ["확인", "요청"], True),
        ({"$contains": "없음"}, "공급사 요청", False),
        ({"보류": 5}, {"보류": 5, "지급": 2}, True),  # 부분 일치
        ({"보류": 5}, {"지급": 2}, False),
        ([1, {"$gt": 1}], [1, 2], True),
        ([1, 2], [1, 2, 3], False),
        (True, 1, False),  # 참거짓은 숫자와 같지 않다
        ({"$gt": 1}, True, False),
    ],
)
def test_expected_comparison_rules(expected: Any, actual: Any, ok: bool) -> None:
    assert matches(expected, actual) is ok


def test_case_file_reads_messages_and_approvals() -> None:
    raw = {
        "schema": 1,
        "cases": [
            {
                "name": "8월 정상",
                "inputs": {"대상월": "2026-08"},
                "expected": {"지급합계": 6358000},
                "approvals": {"Approve_Hold": {"지급진행": "진행"}},
                "messages": [{"after_s": 5, "name": "return_arrived", "correlation": "RT-01",
                              "payload": {"검수통과": True}}],
            }
        ],
    }
    found = CaseFile.model_validate(raw)
    case = found.cases[0]
    assert case.messages[0].name == "return_arrived"
    assert case.approvals["Approve_Hold"]["지급진행"] == "진행"
    assert case.manual is False


# ─────────────────────────── 업무 예제 50개 (가장 센 시험) ───────────────────────────


def example_processes() -> list[Path]:
    return sorted((EXAMPLES / "bpmn").glob("*.bpmn"))


def test_the_examples_are_there() -> None:
    assert len(example_processes()) >= 40, "예제 묶음이 줄었다 — 이 시험의 값이 사라진다"


@pytest.mark.parametrize("path", example_processes(), ids=lambda p: p.stem)
def test_every_example_reads_and_passes(path: Path) -> None:
    """예제 묶음이 C14 형식으로 쓰였다. 읽히지 않거나 **오류**가 나오면 모델이 틀린 것이다.

    경고(B10·B11·B13)는 막지 않는다 — 예제에 대한 판단은 예제 쪽에서 한다.
    """
    process = read_process(path.read_bytes())
    unreadable = {n.id: n.bad_props for n in process.all_nodes() if n.bad_props}
    assert not process.bad_props and not unreadable, unreadable
    found = blocking(validate(process))
    assert found == [], [str(v) for v in found]


@pytest.mark.parametrize("path", sorted((EXAMPLES / "cases").glob("*.json")), ids=lambda p: p.stem)
def test_every_case_file_reads(path: Path) -> None:
    found = CaseFile.model_validate(json.loads(path.read_text(encoding="utf-8")))
    assert found.cases, "케이스가 없다"


def test_available_vars_covers_every_example_without_crashing() -> None:
    """변수 흐름 분석이 50개 모두에서 끝나는가 (반복·합류에서 멈추지 않는가)."""
    for path in example_processes():
        process = read_process(path.read_bytes())
        found = available_vars(process)
        assert set(found) == {n.id for n in process.all_nodes()}
