"""STU-04a 결정표 읽고 쓰기 (`studio/dmn_table.py`, ADR-0109) — 화면 없이.

보는 것은 넷이다: 업무 예제의 결정표를 **손대지 않고 열어 저장하면 판정이 같은가**(글자가 아니라 판정 결과로),
고친 것이 **판정에 그대로 나타나는가**, 고치는 결정표 **하나만** 바뀌고 모르는 것은 남는가, 칸 검사가
`contracts.dmn`과 **같은 판단**인가.
"""

from __future__ import annotations

import itertools
from pathlib import Path
from typing import Any

import pytest

from chaeksas.contracts.dmn import (
    Compare,
    Decision,
    DmnError,
    DmnReadError,
    Equals,
    Range,
    parse_cell,
    read_decisions,
)
from chaeksas.studio.dmn_table import (
    DmnTableError,
    Table,
    blank,
    catalog,
    cell_problem,
    decisions_of,
    problems,
    read_tables,
    summary,
    write_table,
)

EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples" / "bpmn"
DMN_FILES = sorted(EXAMPLES.glob("*.dmn"))


def test_there_are_example_decision_tables() -> None:
    assert len(DMN_FILES) >= 9


# ── 뜻이 같은가 — 판정으로 ──


def _samples(decision: Decision) -> list[dict[str, Any]]:
    """입력마다 **칸에 적힌 경계값과 그 둘레**를 모아 조합한다 — 줄마다 맞고 안 맞는 자리를 지난다."""
    per_input: list[list[Any]] = []
    for index, column in enumerate(decision.inputs):
        values: list[Any] = [None]
        for rule in decision.rules:
            cell = rule.cells[index]
            for term in cell or ():
                if isinstance(term, Equals):
                    values.append(term.value)
                elif isinstance(term, Compare):
                    values.append(term.bound)
                elif isinstance(term, Range):
                    values.extend((term.low, term.high))
        around: list[Any] = []
        for value in values:
            around.append(value)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                around.extend((value - 1, value + 1, value - 0.5, value + 0.5))
        if column.type and column.type.lower() in ("string", "text"):
            around.append("다른 값")
        unique: list[Any] = []
        for value in around:
            if not any(value is u or (type(value) is type(u) and value == u) for u in unique):
                unique.append(value)
        per_input.append(unique[:12])
    combos = list(itertools.product(*per_input))
    step = max(1, len(combos) // 3000)  # 너무 많으면 고르게 덜어 낸다
    return [{c.name: v for c, v in zip(decision.inputs, combo, strict=True)} for combo in combos[::step]]


def _judge(decision: Decision, values: dict[str, Any]) -> Any:
    try:
        return ("ok", decision.decide(values))
    except DmnError as e:
        return ("error", str(e))


@pytest.mark.parametrize("path", DMN_FILES, ids=lambda p: p.stem)
def test_opening_and_saving_untouched_keeps_every_judgment(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    before = read_decisions(source)
    written = source
    for table in read_tables(source).values():
        assert problems(table) == ([], []) or not problems(table)[0], "예제 결정표는 막히지 않는다"
        written = write_table(written, table)
    after = read_decisions(written)
    assert after == before, "읽은 모델이 같다"
    for decision_id, decision in before.items():
        samples = _samples(decision)
        assert samples
        for values in samples:
            assert _judge(after[decision_id], values) == _judge(decision, values), values


@pytest.mark.parametrize("path", DMN_FILES, ids=lambda p: p.stem)
def test_saving_twice_is_stable(path: Path) -> None:
    once = path.read_text(encoding="utf-8")
    for table in read_tables(once).values():
        once = write_table(once, table)
    twice = once
    for table in read_tables(twice).values():
        twice = write_table(twice, table)
    assert twice == once


def test_an_edited_cell_changes_the_judgment() -> None:
    source = (EXAMPLES / "card_policy.dmn").read_text(encoding="utf-8")
    table = read_tables(source)["card_policy"]
    hour = [c.expression for c in table.inputs].index("시")
    night = next(r for r in table.rules if r.cells[hour] == ">= 23")
    night.cells[hour] = ">= 22"
    written = write_table(source, table)
    decision = read_decisions(written)["card_policy"]
    values = {"요일": "월", "시": 22, "업종": "식당", "금액": 1000}
    assert decision.decide(values) == {"violation": ["심야 사용"]}
    assert read_decisions(source)["card_policy"].decide(values) == {"violation": []}


def test_a_new_column_and_rule_are_judged() -> None:
    source = (EXAMPLES / "card_policy.dmn").read_text(encoding="utf-8")
    table = read_tables(source)["card_policy"]
    column = table.add_input()
    column.expression = "부서"
    column.label = "부서"
    rule = table.add_rule()
    rule.cells[-1] = '"영업"'
    rule.values[0] = '"영업 확인"'
    decision = read_decisions(write_table(source, table))["card_policy"]
    assert decision.decide({"요일": "월", "시": 10, "업종": "식당", "금액": 1, "부서": "영업"}) == {
        "violation": ["영업 확인"]
    }


def test_removing_a_column_drops_its_cells() -> None:
    source = (EXAMPLES / "card_policy.dmn").read_text(encoding="utf-8")
    table = read_tables(source)["card_policy"]
    table.remove_input(0)
    decision = read_decisions(write_table(source, table))["card_policy"]
    assert [i.name for i in decision.inputs] == ["시", "업종", "금액"]
    assert all(len(rule.cells) == 3 for rule in decision.rules)


# ── 하나만 바꾸고 나머지는 남긴다 ──

TWO = """<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="https://www.omg.org/spec/DMN/20191111/MODEL/"
  xmlns:dmndi="https://www.omg.org/spec/DMN/20191111/DMNDI/" xmlns:x="urn:x" id="Defs" name="둘" namespace="urn:t">
  <!-- 사람이 남긴 주석 -->
  <decision id="a" name="가">
    <decisionTable id="DT_a" hitPolicy="FIRST" x:keep="1">
      <input id="In_a" label="점수">
        <inputExpression id="InE_a" typeRef="number"><text>점수</text></inputExpression>
        <inputValues id="IV_a"><text>[0..100]</text></inputValues>
      </input>
      <output id="Out_a" name="등급" typeRef="string" />
      <annotation name="메모" />
      <rule id="R1">
        <description>높음</description>
        <inputEntry id="R1_I"><text>&gt;= 90</text></inputEntry>
        <outputEntry id="R1_O"><text>"A"</text></outputEntry>
        <annotationEntry><text>메모 하나</text></annotationEntry>
      </rule>
    </decisionTable>
  </decision>
  <decision id="b" name="나">
    <decisionTable id="DT_b">
      <input id="In_b"><inputExpression id="InE_b"><text>x</text></inputExpression></input>
      <output id="Out_b" name="y" />
      <rule id="Rb"><inputEntry id="Rb_I"><text>-</text></inputEntry>
        <outputEntry id="Rb_O"><text>1</text></outputEntry></rule>
    </decisionTable>
  </decision>
  <decision id="c" name="결정표가 아니다"><literalExpression><text>1</text></literalExpression></decision>
  <dmndi:DMNDI><dmndi:DMNDiagram id="D1" /></dmndi:DMNDI>
</definitions>
"""


def test_only_the_edited_table_changes() -> None:
    tables = read_tables(TWO)
    assert set(tables) == {"a", "b"}, "결정표가 아닌 결정은 건너뛴다"
    table = tables["a"]
    table.name = "등급표"
    table.rules[0].values[0] = '"S"'
    written = write_table(TWO, table)
    decisions = read_decisions(written)
    assert decisions["a"].name == "등급표"
    assert decisions["a"].decide({"점수": 95}) == {"등급": "S"}
    assert decisions["b"] == read_decisions(TWO)["b"], "다른 결정은 그대로"
    for kept in (
        "사람이 남긴 주석",
        "<literalExpression>",
        "dmndi:DMNDiagram",
        'x:keep="1"',
        'id="IV_a"',
        "<annotation",
        "메모 하나",
        'id="R1_I"',
        'id="R1_O"',
        'id="InE_a"',
    ):
        assert kept in written, kept
    assert written.count("<definitions") == 1, "기본 네임스페이스 그대로 (접두사를 짓지 않는다)"


def test_prefix_stays_as_written() -> None:
    source = (EXAMPLES / "card_policy.dmn").read_text(encoding="utf-8")
    written = write_table(source, read_tables(source)["card_policy"])
    assert written.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<dmn:definitions')
    assert "ns0:" not in written


def test_a_new_table_makes_a_file_the_reader_accepts() -> None:
    table = blank("new_decision", "새 결정")
    table.inputs[0].expression = "금액"
    table.outputs[0].name = "결과"
    table.rules[0].values[0] = '"좋다"'
    assert problems(table)[0] == []
    written = write_table(None, table)
    decision = read_decisions(written)["new_decision"]
    assert decision.name == "새 결정"
    assert decision.hit == "UNIQUE"
    assert decision.decide({"금액": 1}) == {"결과": "좋다"}


def test_a_broken_cell_still_opens_in_the_grid() -> None:
    broken = TWO.replace("&gt;= 90", "높음")
    with pytest.raises(DmnReadError):
        read_decisions(broken)
    table = read_tables(broken)["a"]
    assert table.rules[0].cells == ["높음"]
    errors, _ = problems(table)
    assert any("규칙 1 · 입력 점수" in e and "큰따옴표" in e for e in errors)


def test_xml_that_does_not_parse_is_said() -> None:
    with pytest.raises(DmnTableError):
        read_tables("<definitions")


# ── 검사 ──


@pytest.mark.parametrize(
    "text",
    ["-", "", '"높음"', "3", "true", '"ERP","HRIS"', ">= 20", "< 0.5", "[1..30)", "(0..7]"]
    + ["높음", "a+b", ">= x", "[1..]"],
)
def test_cell_check_is_the_readers_judgment(text: str) -> None:
    try:
        parse_cell(text, where="칸")
        accepted = True
    except DmnReadError:
        accepted = False
    assert (cell_problem(text, output=False) is None) == accepted


@pytest.mark.parametrize(
    ("text", "ok"),
    [('"높음"', True), ("0.05", True), ("", True), ("null", True), ("높음", False), ("a + 1", False)],
)
def test_output_cells_are_one_value(text: str, ok: bool) -> None:
    assert (cell_problem(text, output=True) is None) == ok


def _table(**changes: Any) -> Table:
    table = blank("t", "표")
    table.inputs[0].expression = "x"
    table.outputs[0].name = "y"
    for key, value in changes.items():
        setattr(table, key, value)
    return table


def test_what_blocks_saving() -> None:
    assert problems(_table())[0] == []
    assert any("ID가 비었" in e for e in problems(_table(id=""))[0])
    assert any("ID는" in e for e in problems(_table(id="1번"))[0])
    assert any("이미 있는" in e for e in problems(_table(), taken={"t"})[0])
    assert any("적중 정책" in e for e in problems(_table(hit="RULE ORDER"))[0])
    no_name = _table()
    no_name.inputs[0].expression = ""
    assert any("식 이름이 비었" in e for e in problems(no_name)[0])
    twin = _table()
    twin.add_output().name = "y"
    assert any("출력 이름이 겹칩니다" in e for e in problems(twin)[0])
    no_out = _table()
    no_out.remove_output(0)
    assert any("출력 열이 없습니다" in e for e in problems(no_out)[0])


def test_what_is_only_warned() -> None:
    empty = _table()
    empty.rules.clear()
    assert problems(empty)[0] == []
    assert any("규칙 줄이 없습니다" in w for w in problems(empty)[1])
    odd = _table()
    odd.inputs[0].type = "date"
    assert any("typeRef date" in w for w in problems(odd)[1])
    mismatch = _table()
    mismatch.inputs[0].type = "number"
    mismatch.rules[0].cells[0] = '"25"'
    errors, warnings = problems(mismatch)
    assert errors == []
    assert any("number 열인데" in w for w in warnings)
    twin = _table()
    twin.add_input().expression = "x"
    assert any("입력 식 이름이 겹칩니다" in w for w in problems(twin)[1])


def test_summary_line() -> None:
    table = read_tables((EXAMPLES / "card_policy.dmn").read_text(encoding="utf-8"))["card_policy"]
    assert summary(table) == "COLLECT · 입력 4 · 출력 1 · 규칙 4"


# ── 작업 폴더의 결정표들 ──


def test_my_table_wins_over_a_received_one(tmp_path: Path) -> None:
    (tmp_path / "process").mkdir()
    (tmp_path / "libs").mkdir()
    source = (EXAMPLES / "card_policy.dmn").read_text(encoding="utf-8")
    (tmp_path / "libs" / "card_policy.dmn").write_text(source, encoding="utf-8")
    (tmp_path / "libs" / "broken.dmn").write_text("<x", encoding="utf-8")
    found, broken = catalog([(tmp_path / "libs" / "card_policy.dmn", True), (tmp_path / "libs" / "broken.dmn", True)])
    assert found["card_policy"].received
    assert list(broken) == [tmp_path / "libs" / "broken.dmn"]
    (tmp_path / "process" / "card_policy.dmn").write_text(source, encoding="utf-8")

    class Owner:
        folder = tmp_path

        def decision_files(self) -> list[tuple[Path, bool]]:
            from chaeksas.studio.workspace import BpmProcess  # noqa: PLC0415

            return BpmProcess.decision_files(self)  # type: ignore[arg-type]

    made = decisions_of(Owner())
    assert made is not None
    assert not made.found["card_policy"].received, "내 process/가 이긴다"
    assert made.process_dir == tmp_path / "process"
    assert decisions_of(None) is None
