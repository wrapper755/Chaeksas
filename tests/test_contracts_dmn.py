"""C14 §규칙 태스크와 DMN — 결정표를 읽고 판정한다 (`chaeksas.contracts.dmn`).

예제의 `.dmn` 7개가 **그대로 읽히고 판정되는지**가 가장 중요한 시험이다. 규칙 태스크의
`input`·`output`이 결정표와 맞는지도 B14로 함께 본다 (같은 이름을 두 곳에 적으니까).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chaeksas.contracts.bpmn_ext import read_process
from chaeksas.contracts.bpmn_ext import validate as validate_bpmn
from chaeksas.contracts.dmn import (
    Decision,
    DmnError,
    DmnReadError,
    decision_io,
    parse_cell,
    read_decisions,
)

EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples" / "bpmn"


def table(*, hit: str = "FIRST", inputs: str = "", outputs: str = "", rules: str = "") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<dmn:definitions xmlns:dmn="https://www.omg.org/spec/DMN/20191111/MODEL/" id="Defs_d" name="시험">
  <dmn:decision id="d" name="시험 결정">
    <dmn:decisionTable id="DT_d" hitPolicy="{hit}">
      {inputs}{outputs}{rules}
    </dmn:decisionTable>
  </dmn:decision>
</dmn:definitions>
"""


def column(index: int, name: str, type_ref: str = "string", label: str | None = None) -> str:
    return (
        f'<dmn:input id="In_{index}" label="{label or name}">'
        f'<dmn:inputExpression id="InE_{index}" typeRef="{type_ref}">'
        f"<dmn:text>{name}</dmn:text></dmn:inputExpression></dmn:input>"
    )


def result(index: int, name: str, type_ref: str = "string") -> str:
    return f'<dmn:output id="Out_{index}" name="{name}" typeRef="{type_ref}" />'


def row(index: int, cells: list[str], values: list[str]) -> str:
    body = "".join(f'<dmn:inputEntry id="R{index}I{i}"><dmn:text>{c}</dmn:text></dmn:inputEntry>'
                   for i, c in enumerate(cells))
    body += "".join(f'<dmn:outputEntry id="R{index}O{i}"><dmn:text>{v}</dmn:text></dmn:outputEntry>'
                    for i, v in enumerate(values))
    return f'<dmn:rule id="Rule_{index}">{body}</dmn:rule>'


def one(xml: str) -> Decision:
    decisions = read_decisions(xml)
    return next(iter(decisions.values()))


# ─────────────────────────── 입력 칸 (unary test) ───────────────────────────


@pytest.mark.parametrize(
    ("cell", "type_ref", "value", "expected"),
    [
        ("-", "string", "무엇이든", True),
        ("", "string", None, True),
        ('"write"', "string", "write", True),
        ('"write"', "string", "read", False),
        ('"ERP","HRIS"', "string", "HRIS", True),  # 쉼표는 「또는」
        ('"ERP","HRIS"', "string", "CRM", False),
        ("&gt;= 750", "number", 750, True),
        ("&gt;= 750", "number", 749, False),
        ("&lt; 600", "number", 599, True),
        ("[0..7]", "number", 7, True),  # 대괄호는 포함
        ("[1..30)", "number", 30, False),  # 소괄호는 제외
        ("[1..30)", "number", 1, True),
        ("true", "boolean", True, True),
        ("true", "boolean", False, False),
        ("&gt; 20", "number", None, False),  # 견줄 수 없으면 맞지 않은 것으로 본다
        ("&gt; 20", "number", "스물다섯", False),
        ("&gt; 20", "string", 25, False),  # 타입이 string이면 숫자 비교가 아니다
    ],
)
def test_input_cells_follow_the_contract_table(
    cell: str, type_ref: str, value: object, expected: bool
) -> None:
    """C14 §규칙 태스크와 DMN의 「입력 칸 문법」 표 그대로."""
    xml = table(inputs=column(0, "값", type_ref), outputs=result(0, "답"), rules=row(0, [cell], ['"맞음"']))
    assert (one(xml).decide({"값": value})["답"] == "맞음") is expected


def test_a_comma_inside_a_string_is_not_a_separator() -> None:
    assert parse_cell('"가, 나"', where="t") == parse_cell('"가, 나"', where="t")
    xml = table(inputs=column(0, "값"), outputs=result(0, "답"), rules=row(0, ['"가, 나"'], ['"맞음"']))
    assert one(xml).decide({"값": "가, 나"})["답"] == "맞음"


def test_unknown_cell_grammar_is_refused_when_reading() -> None:
    """FEEL 전체를 들이지 않는다 — Studio 검사가 미리 잡게 **읽기 단계에서** 거부한다."""
    xml = table(inputs=column(0, "값"), outputs=result(0, "답"), rules=row(0, ["not(3)"], ['"맞음"']))
    with pytest.raises(DmnReadError, match="값으로 읽을 수 없다"):
        read_decisions(xml)


def test_an_unknown_hit_policy_is_refused() -> None:
    xml = table(hit="PRIORITY", inputs=column(0, "값"), outputs=result(0, "답"), rules=row(0, ["-"], ['"ㅇ"']))
    with pytest.raises(DmnReadError, match="적중 정책"):
        read_decisions(xml)


# ─────────────────────────── 적중 정책 ───────────────────────────


def grades() -> str:
    return table(
        inputs=column(0, "점수", "number"),
        outputs=result(0, "등급"),
        rules=row(0, ["&gt;= 90"], ['"A"']) + row(1, ["&gt;= 80"], ['"B"']),
    )


def test_first_takes_the_first_matching_row() -> None:
    decision = one(grades())
    assert decision.decide({"점수": 95})["등급"] == "A"
    assert decision.decide({"점수": 85})["등급"] == "B"


def test_no_matching_row_gives_none_not_a_failure() -> None:
    """C14 — 해당 없음은 실패가 아니다. 게이트웨이로 가른다."""
    assert one(grades()).decide({"점수": 10}) == {"등급": None}


def test_collect_gathers_every_matching_row() -> None:
    xml = table(
        hit="COLLECT",
        inputs=column(0, "점수", "number"),
        outputs=result(0, "표시"),
        rules=row(0, ["&gt;= 90"], ['"높음"']) + row(1, ["&gt;= 80"], ['"보통 이상"']),
    )
    decision = one(xml)
    assert decision.decide({"점수": 95}) == {"표시": ["높음", "보통 이상"]}
    assert decision.decide({"점수": 10}) == {"표시": []}, "맞는 줄이 없으면 빈 목록이다"


def test_unique_refuses_two_matching_rows() -> None:
    xml = table(
        hit="UNIQUE",
        inputs=column(0, "점수", "number"),
        outputs=result(0, "등급"),
        rules=row(0, ["&gt;= 90"], ['"A"']) + row(1, ["&gt;= 80"], ['"B"']),
    )
    with pytest.raises(DmnError, match="UNIQUE"):
        one(xml).decide({"점수": 95})


def test_any_allows_two_rows_only_when_they_agree() -> None:
    def built(second: str) -> Decision:
        return one(
            table(
                hit="ANY",
                inputs=column(0, "점수", "number"),
                outputs=result(0, "등급"),
                rules=row(0, ["&gt;= 90"], ['"A"']) + row(1, ["&gt;= 80"], [second]),
            )
        )

    assert built('"A"').decide({"점수": 95})["등급"] == "A"
    with pytest.raises(DmnError, match="ANY"):
        built('"B"').decide({"점수": 95})


# ─────────────────────────── 이름·타입 ───────────────────────────


def test_the_input_name_is_the_expression_not_the_label() -> None:
    """`label`은 사람이 읽는 이름이다 (예제의 「시각」/`시`). `chk:rule.input`은 식 쪽을 쓴다."""
    xml = table(
        inputs=column(0, "시", "number", label="시각"),
        outputs=result(0, "답"),
        rules=row(0, ["&gt;= 23"], ['"심야"']),
    )
    decision = one(xml)
    assert [i.name for i in decision.inputs] == ["시"]
    assert [i.label for i in decision.inputs] == ["시각"]
    assert decision.decide({"시": 23})["답"] == "심야"


def test_a_number_typeref_makes_a_string_compare_as_a_number() -> None:
    """`typeRef`가 없으면 `"25" > 20`이 문자열 비교가 된다 (BX-12의 교훈)."""
    xml = table(
        inputs=column(0, "무게", "number"),
        outputs=result(0, "구간"),
        rules=row(0, ["&gt; 20"], ['"초과"']),
    )
    assert one(xml).decide({"무게": "25"})["구간"] == "초과"


def test_a_boolean_typeref_reads_the_string_true() -> None:
    xml = table(
        inputs=column(0, "연체", "boolean"),
        outputs=result(0, "답"),
        rules=row(0, ["true"], ['"있음"']),
    )
    assert one(xml).decide({"연체": "true"})["답"] == "있음"


def test_a_missing_input_is_an_error_not_a_silent_none() -> None:
    """빠진 입력을 `None`으로 흘리면 엉뚱한 줄이 맞는다. B14가 미리 잡는 자리이기도 하다."""
    with pytest.raises(DmnError, match="입력이 빠졌다"):
        one(grades()).decide({})


# ─────────────────────────── 업무 예제 ───────────────────────────


def test_every_example_dmn_reads() -> None:
    found = {}
    for path in sorted(EXAMPLES.glob("*.dmn")):
        found.update(read_decisions(path.read_text(encoding="utf-8")))
    assert len(found) == 7, sorted(found)
    assert all(decision.rules for decision in found.values())
    assert {d.hit for d in found.values()} == {"FIRST", "COLLECT"}


def test_the_example_decisions_answer_the_way_the_cases_expect() -> None:
    """케이스가 적어 둔 값 몇 개를 그대로 판정해 본다 (FX-02·BX-07·BX-33)."""
    decisions = {}
    for path in sorted(EXAMPLES.glob("*.dmn")):
        decisions.update(read_decisions(path.read_text(encoding="utf-8")))

    discount = decisions["discount_policy"]
    assert discount.decide({"amount": 1500000, "grade": "VIP"}) == {
        "discount": 0.2,
        "discount_reason": "VIP 대량 주문",
    }
    assert discount.decide({"amount": 50000, "grade": "일반"})["discount"] == 0

    # COLLECT — 어긴 것을 모두 모은다.
    card = decisions["card_policy"]
    assert card.decide({"요일": "토", "시": 23, "업종": "유흥", "금액": 600000})["violation"] == [
        "주말 사용", "심야 사용", "제한 업종", "1회 한도 초과",
    ]
    assert card.decide({"요일": "월", "시": 10, "업종": "식당", "금액": 10000})["violation"] == []

    risk = decisions["access_risk"]
    assert risk.decide({"시스템": "ERP", "권한": "write"})["risk"] == "높음"
    assert risk.decide({"시스템": "WIKI", "권한": "read"})["risk"] == "낮음"


def test_b14_sees_the_example_rule_tasks_match_their_dmn() -> None:
    """같은 이름을 BPMN과 DMN 두 곳에 적는다 — B14가 그 둘을 대조한다."""
    decisions = {}
    for path in sorted(EXAMPLES.glob("*.dmn")):
        decisions.update(read_decisions(path.read_text(encoding="utf-8")))
    table_io = decision_io(decisions.values())

    checked = 0
    for path in sorted(EXAMPLES.glob("*.bpmn")):
        process = read_process(path.read_text(encoding="utf-8"))
        if not any(n.prop("rule") for n in process.all_nodes()):
            continue
        checked += 1
        b14 = [v for v in validate_bpmn(process, dmn_decisions=table_io) if v.rule == "B14"]
        assert not b14, f"{path.name}: {[v.message for v in b14]}"
    assert checked == 7, "규칙 태스크를 쓰는 예제 수가 바뀌었다"
