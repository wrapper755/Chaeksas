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
    read_vars,
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


def data_output(props: str) -> str:
    return ('<bpmn:dataObjectReference id="D"><bpmn:extensionElements>'
            f"<chk:dataOutput>{props}</chk:dataOutput>"
            "</bpmn:extensionElements></bpmn:dataObjectReference>")


def test_b5_file_output_format_rules() -> None:
    """C14 §파일 출력 — xlsx에 template, csv에 이름 둘, 이어 쓸 수 없는 형식 (ADR-0026)."""
    body = line('<bpmn:scriptTask id="T"><bpmn:script>a = 1</bpmn:script></bpmn:scriptTask>')
    xlsx = '{"path": "a.xlsx", "format": "xlsx", "template": "{a}", "store_as": "경로"}'
    assert "B5" in codes(wrap(body + data_output(xlsx)))
    csv = '{"path": "a.csv", "format": "csv", "variables": ["가", "나"], "store_as": "경로"}'
    assert "B5" in codes(wrap(body + data_output(csv)))
    appended = '{"path": "a.json", "format": "json", "variables": ["가"], "append": true, "store_as": "경로"}'
    assert "B5" in codes(wrap(body + data_output(appended)))
    fine = '{"path": "a.md", "format": "md", "template": "{a}", "append": true, "store_as": "경로"}'
    assert "B5" not in codes(wrap(body + data_output(fine)))


def file_list(props: str) -> str:
    return (f'<bpmn:serviceTask id="T"><bpmn:extensionElements><chk:fileList>{props}</chk:fileList>'
            "</bpmn:extensionElements></bpmn:serviceTask>")


def test_b5_and_b12_check_the_file_list_task() -> None:
    """C14 §파일 목록 — `store_as`가 필수, `pattern`에 경로 구분자 금지 (ADR-0026)."""
    assert "B5" in codes(wrap(line(file_list('{"folder": "/share"}'))))
    bad_pattern = '{"folder": "/share", "pattern": "하위/*.pdf", "store_as": "파일"}'
    assert "B5" in codes(wrap(line(file_list(bad_pattern))))
    bad_sort = '{"folder": "/share", "sort": "크기", "store_as": "파일"}'
    assert "B12" in codes(wrap(line(file_list(bad_sort))))
    fine = '{"folder": "/share", "pattern": "*.pdf", "store_as": "파일", "count_as": "건수"}'
    found = codes(wrap(line(file_list(fine))))
    assert "B5" not in found and "B12" not in found


def test_b11_sees_what_the_file_list_makes_and_reads() -> None:
    """`store_as`·`count_as`는 그 뒤에서 쓸 수 있고, `folder`의 `{변수}`는 읽는 것이다."""
    spec = '{"folder": "{감시폴더}", "store_as": "파일", "count_as": "건수"}'
    body = line(file_list(spec), '<bpmn:scriptTask id="T2"><bpmn:script>수 = 건수</bpmn:script></bpmn:scriptTask>')
    declared = '{"run_location": "pc", "inputs": [{"name": "감시폴더", "type": "string"}]}'
    assert "B11" not in codes(wrap(body, process_json=declared))
    assert "B11" in codes(wrap(body)), "선언하지 않은 `감시폴더`를 읽으면 경고한다"


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


# ─────────────────── B11을 흘려보내지 않는다 (ADR-0039) ───────────────────

#: 업무 예제 50개에 **지금 떠 있는** B11 경고. `(예제, 노드, 변수들)`.
#:
#: **비어 가는 것이 좋다.** 한때 열둘이었고 열하나가 거짓 양성이었다 (ADR-0039) — 하위 프로세스,
#: 경계 이벤트, 포함 합류, 조건식의 지연 평가, 결재의 `show`를 분석이 못 보던 것이 원인이었다.
#: 지금 남은 것은 **일부러 남긴 하나**뿐이다.
#:
#: **목록에 없는 경고가 생기면 이 시험이 깨진다.** BX-33이 그렇게 새어 나갔다 — 생성기의
#: 좁은 검사(템플릿 `{변수}`만 본다)를 지나 M5 인수 시험에서야 드러났다 (ADR-0039).
KNOWN_B11: dict[tuple[str, str], tuple[str, ...]] = {
    # **하나뿐이고, 일부러 남긴 것이다** — BX-33의 「배운 것」이 해법까지 적고 있다.
    # 검사가 도는 것을 보여 주는 예제이므로 고치지 않는다 (ADR-0039).
    ("bx33_access_request", "Task_Schedule"): ("기간",),
}


def _b11_in_examples() -> dict[tuple[str, str], tuple[str, ...]]:
    from pathlib import Path  # noqa: PLC0415

    folder = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples" / "bpmn"
    found: dict[tuple[str, str], tuple[str, ...]] = {}
    for path in sorted(folder.glob("*.bpmn")):
        for one in validate(read_process(path.read_text(encoding="utf-8"))):
            if one.rule != "B11":
                continue
            node = one.message.split(":", 1)[0].strip()
            found[(path.stem, node)] = tuple(sorted(one.items))
    return found


def test_no_new_b11_warning_slips_into_the_examples() -> None:
    """**적어 둔 것과 똑같아야 한다** (ADR-0039) — 새 경고도, 사라진 경고도 알려 준다.

    사라졌으면 좋은 일이다 — `KNOWN_B11`에서 지운다. 생긴 것은 보고 갈래를 정한다.
    """
    found = _b11_in_examples()
    new = {k: v for k, v in found.items() if k not in KNOWN_B11}
    gone = {k: v for k, v in KNOWN_B11.items() if k not in found}
    changed = {k: (KNOWN_B11[k], v) for k, v in found.items() if k in KNOWN_B11 and v != KNOWN_B11[k]}
    assert not new, f"새 B11 경고다 — 보고 ADR-0039의 갈래를 정한 뒤 KNOWN_B11에 적는다: {new}"
    assert not gone, f"사라진 B11 경고다 — KNOWN_B11에서 지운다: {gone}"
    assert not changed, f"변수 목록이 달라졌다: {changed}"


def test_b11_sees_through_a_subprocess() -> None:
    """**하위 프로세스가 안에서 만든 변수는 바깥에도 있다** (ADR-0039).

    엔진의 변수 공간은 하나다 (`Run.variables`). 분석이 범위에서 끊기면 하위 프로세스 뒤를
    모두 「출처 없음」이라고 한다 — BX-22의 거짓 경고 셋이 그 때문이었다.
    """
    from pathlib import Path  # noqa: PLC0415

    folder = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples" / "bpmn"
    found = read_process((folder / "bx22_offboarding_access.bpmn").read_text(encoding="utf-8"))
    available = available_vars(found)
    # `Rv_Init`이 하위 프로세스 안에서 두는 값들을 바깥의 `Task_Count`가 읽는다.
    assert {"메일실패", "VPN실패", "ERP실패"} <= available["Task_Count"]
    assert not [one for one in validate(found) if one.rule == "B11"]


# ─────────────── B11의 정확도 (ADR-0039 — 거짓 양성 열하나를 없앤 자리) ───────────────


def _process(stem: str) -> Any:
    from pathlib import Path  # noqa: PLC0415

    folder = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples" / "bpmn"
    return read_process((folder / f"{stem}.bpmn").read_text(encoding="utf-8"))


def test_a_boundary_event_carries_the_variables_of_the_node_it_is_on() -> None:
    """경계 이벤트는 붙은 노드 자리에서 떠난다 — **고정점 안에서** 그래야 한다.

    뒤로 미루면 경계 뒤의 노드가 **낡은 값**으로 계산되어, 선행 노드에 값이 있는데도 경고가
    떴다 (BX-32·BX-34·BX-36이 그랬다).
    """
    found = _process("bx32_customer_inquiry")
    available = available_vars(found)
    assert "최종답변" in available["Approve_Check"]
    assert not [one for one in validate(found) if one.rule == "B11"]


def test_an_inclusive_join_counts_the_branches_that_always_run() -> None:
    """포함 합류 — **조건 없는(또는 `true`인) 가지는 늘 지나간다** (BX-10의 서류 확인).

    조건이 붙은 가지는 세지 않는다 (`신용`·`제재`는 그래서 보장되지 않는다).
    """
    found = _process("bx10_vendor_onboarding_review")
    available = available_vars(found)
    assert "서류결과" in available["Task_Summary"], "늘 지나가는 가지가 만든 값이다"
    assert not [one for one in validate(found) if one.rule == "B11"]


def test_a_default_flow_is_not_always_taken() -> None:
    """기본 흐름은 **다른 조건이 하나도 맞지 않을 때만** 지나간다 — 보장이 아니다."""
    from chaeksas.contracts.bpmn_ext import ALWAYS_TRUE, _always_taken  # noqa: PLC0415

    assert "true" in ALWAYS_TRUE
    found = _process("bx10_vendor_onboarding_review")
    by_target = {f.target: f for f in found.outgoing("Gw_Checks", found.flows)}
    # `true`는 조건 없음과 같다. 조건이 붙은 가지는 아니다.
    assert _always_taken(found, by_target["Task_Docs"], found.flows)
    assert not _always_taken(found, by_target["Task_Credit"], found.flows)


def test_a_name_only_inside_a_conditional_branch_is_not_definitely_read() -> None:
    """`a if c else b`는 **고른 가지만** 평가한다 — 예제가 일부러 쓰는 꼴이다 (BX-10·BX-02).

    조건 자리의 이름은 늘 읽는다. 중첩이면 안쪽 조건도 바깥 가지에 들어 있어 함께 지연된다.
    """
    assert expression_vars("신용 if 예상거래액 >= 50000000 else None") == {"예상거래액"}
    assert expression_vars("('필요' if 조치필요 else '불필요') if 경고수 > 0 else '없음'") == {"경고수"}
    # 가지 **밖에서도** 읽히면 늘 읽는 것이다 (`가`). 가지에만 있으면 아니다 (`다`).
    assert expression_vars("가 + (가 if 나 else 다)") == {"가", "나"}
    assert expression_vars("가 if 나 else 다") == {"나"}


def test_what_an_approval_shows_is_not_a_read() -> None:
    """`show`는 읽기가 아니다 — 엔진이 `.get()`으로 가져가 없으면 `None`이다 (FX-08).

    B11은 「읽으면 실행 오류」를 잡는 검사다. 멈추지 않는 것을 넣으면 범주가 어긋난다.
    """
    found = _process("fx08_error_boundary")
    node = found.node("Approve_Check")
    assert node is not None
    approval = node.prop("approval")
    assert approval is not None and "대체" in approval.show
    assert "대체" not in read_vars(node, found.flows)
    assert not [one for one in validate(found) if one.rule == "B11"]
