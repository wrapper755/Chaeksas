"""식 `chk-expr`·스크립트·템플릿 (ADR-0025, C14 §식).

마지막 묶음이 중요하다 — **업무 예제 50개가 실제로 쓰는 식 자리 전부**를 파싱한다. 식 언어를
좁히거나 넓힐 때 예제가 먼저 깨지는 자리다.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from chaeksas.contracts.bpmn_ext import read_process
from chaeksas.core.expr import (
    ExprError,
    Scope,
    evaluate,
    fill,
    parse,
    parse_script,
    run_script,
    template_names,
    truthy,
)
from chaeksas.core.helpers import HELPER_NAMES, bind

NOW = datetime(2026, 10, 4, 9, 30)
BPMN_DIR = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples" / "bpmn"


def scope(where: str | None = "Task_X", **variables: Any) -> Scope:
    return Scope(variables=dict(variables), helpers=bind(now=NOW), where=where)


def ev(source: str, **variables: Any) -> Any:
    return evaluate(source, scope(**variables))


# ─────────────────────────── 값 내기 ───────────────────────────


def test_comparisons_and_logic() -> None:
    assert ev("보류건수 > 0", 보류건수=2) is True
    assert ev("경로 == '결재'", 경로="결재") is True
    assert ev("not 발행대상", 발행대상=False) is True
    assert ev("1 <= 값 <= 10", 값=5) is True, "이어 쓴 비교"


def test_or_falls_back_to_a_helper() -> None:
    """C14 §6 — 선언했지만 값이 없으면 `None`이라 `대상월 or 지난달()`이 된다."""
    assert ev("대상월 or 지난달()", 대상월=None) == "2026-09"
    assert ev("대상월 or 지난달()", 대상월="2026-05") == "2026-05"


def test_a_dot_reads_a_dictionary_key() -> None:
    """ADR-0025 §3 — 예제가 `결과.지급`처럼 쓴다 (파이썬 의미로는 오류다)."""
    assert ev("결과.지급", 결과={"지급": [1, 2]}) == [1, 2]
    assert ev("결과.지급[0]", 결과={"지급": [7]}) == 7


def test_a_dot_on_a_non_dictionary_says_so() -> None:
    with pytest.raises(ExprError, match="점으로 읽을 수 없는"):
        ev("이름.length", 이름="가나")
    with pytest.raises(ExprError, match="「없는열」가 없다"):
        ev("결과.없는열", 결과={"지급": []})


def test_comprehensions() -> None:
    assert ev("[r['합계'] for r in 목록 if r['합계'] > 1]", 목록=[{"합계": 1}, {"합계": 5}]) == [5]
    assert ev("{r['id']: r for r in 목록}", 목록=[{"id": "a"}]) == {"a": {"id": "a"}}
    assert ev("[a + b for a, b in zip(목록1, 목록2)]", 목록1=[1, 2], 목록2=[10, 20]) == [11, 22]
    # 내포의 변수는 **그 안에서만** 산다 (바깥을 더럽히지 않는다).
    found = scope(목록=[1, 2])
    evaluate("[x for x in 목록]", found)
    assert "x" not in found.variables


def test_conditional_expression_and_fstring() -> None:
    assert ev("[] if 진행 == '보류' else 지급대상", 진행="보류", 지급대상=[1]) == []
    assert ev("f'{대상월} 마감'", 대상월="2026-09") == "2026-09 마감"


def test_missing_variable_is_an_error_with_the_place() -> None:
    """C14 §6 — 선언하지 않은 이름을 읽으면 실행 오류다. 어디서 틀렸는지 말한다."""
    with pytest.raises(ExprError) as problem:
        ev("없는변수 + 1")
    assert problem.value.where == "Task_X"
    assert "모르는 변수다: 없는변수" in str(problem.value)
    assert "식: 없는변수 + 1" in str(problem.value)


def test_comparing_none_says_which_types() -> None:
    """값이 없는 변수를 견주는 것은 흔한 실수다 — 무엇과 무엇인지 알려 준다."""
    with pytest.raises(ExprError, match="견줄 수 없는 값이다"):
        ev("금액 > 0", 금액=None)


def test_dividing_by_zero_points_at_the_helper() -> None:
    with pytest.raises(ExprError, match="나누기"):
        ev("1 / 0")


def test_truthy_takes_a_bare_variable() -> None:
    """예제의 조건식 36곳 중 여러 곳이 `발행대상`처럼 변수 하나다."""
    assert truthy("발행대상", scope(발행대상=["a"])) is True
    assert truthy("발행대상", scope(발행대상=[])) is False


# ─────────────────────────── 막아야 할 것 ───────────────────────────


@pytest.mark.parametrize(
    "source",
    [
        "__import__('os').listdir('.')",
        "open('/etc/passwd').read()",
        "().__class__.__bases__[0].__subclasses__()",
        "오늘.__class__",
        "[x for x in '12' if x.__class__]",
        "eval('1')",
        "exec('x=1')",
        "globals()",
        "lambda: 1",
        "1 if (x := 2) else 0",
        "오늘['__class__']",
    ],
)
def test_dangerous_things_are_refused(source: str) -> None:
    """`eval`을 쓰지 않으므로 허용 목록 밖은 **실행되지 않는다** (ADR-0025)."""
    with pytest.raises(ExprError):
        ev(source, 오늘="2026-10-04")


def test_an_empty_expression_is_refused() -> None:
    with pytest.raises(ExprError, match="비어 있다"):
        ev("   ")


def test_bad_syntax_says_it_is_syntax() -> None:
    with pytest.raises(ExprError, match="식 문법이 틀렸다"):
        ev("보류건수 >")


# ─────────────────────────── 스크립트 ───────────────────────────


def test_a_script_assigns_in_order() -> None:
    """뒤 줄이 앞 줄의 결과를 쓴다 (예제가 그렇게 쓴다)."""
    found = scope(청구서폴더="/share", 대상월=None, where="Task_Collect")
    changed = run_script(
        "대상월 = 대상월 or 지난달()\n대장파일 = 청구서폴더 + '/' + 대상월 + '/ledger.xlsx'",
        found,
    )
    assert changed == {"대상월": "2026-09", "대장파일": "/share/2026-09/ledger.xlsx"}
    # 스코프에도 남는다 — 다음 노드가 쓴다.
    assert found.variables["대장파일"] == "/share/2026-09/ledger.xlsx"


def test_a_script_takes_only_assignments() -> None:
    """반복문·조건문은 BPMN으로 그린다 (ADR-0025 §1)."""
    for source in ("for x in 목록:\n    y = x", "if 참:\n    y = 1", "합계(목록, '값')", "del 목록"):
        with pytest.raises(ExprError):
            run_script(source, scope(목록=[1], 참=True))


def test_a_script_cannot_assign_to_a_strange_name() -> None:
    with pytest.raises(ExprError, match="대입 대상은 변수 이름"):
        run_script("목록[0] = 1", scope(목록=[1]))
    with pytest.raises(ExprError, match="대입 대상은 변수 이름"):
        run_script("결과.지급 = 1", scope(결과={"지급": 1}))


def test_parse_script_does_not_run_it() -> None:
    """Studio·검사가 **값 없이** 문법만 본다."""
    assert len(parse_script("가 = 1\n나 = 가 + 1")) == 2
    assert parse("보류건수 > 0") is not None


# ─────────────────────────── 템플릿 ───────────────────────────


def test_a_template_fills_names() -> None:
    found = scope(대상월="2026-09", 보고서본문="본문", 지급합계=1000)
    assert fill("대사표/대사표_{대상월}.md", found) == "대사표/대사표_2026-09.md"
    assert fill("[{대상월}] 지급 {지급합계}원", found) == "[2026-09] 지급 1000원"
    assert fill("표 없음", found) == "표 없음"


def test_a_template_escapes_double_braces() -> None:
    assert fill("{{그대로}} {대상월}", scope(대상월="2026-09")) == "{그대로} 2026-09"


def test_a_template_refuses_an_expression() -> None:
    """ADR-0025 §1 — 중괄호 안은 이름 하나만. 예제 86곳이 모두 그렇다."""
    with pytest.raises(ExprError, match="변수 이름만"):
        fill("{합계(목록, '값')}", scope(목록=[]))
    with pytest.raises(ExprError, match="비어 있다"):
        fill("{}", scope())


def test_a_template_with_an_unknown_name_is_an_error() -> None:
    with pytest.raises(ExprError, match="모르는 변수다: 없는것"):
        fill("{없는것}", scope())


def test_a_template_leaves_a_missing_value_empty() -> None:
    """선언했지만 값이 없으면(`None`) 빈 칸이다 — 파일 이름이 `None`이 되면 안 된다."""
    assert fill("일일/{메모}.md", scope(메모=None)) == "일일/.md"


def test_template_names_lists_what_it_needs() -> None:
    assert template_names("{가}/{나}_{가}.md") == ["가", "나"]
    assert template_names("{{아님}}") == []


# ─────────────────────────── 도우미 ───────────────────────────


def test_table_helpers() -> None:
    rows = [{"키": "a", "값": 3}, {"키": "b", "값": 4}]
    assert ev("합계(목록, '값')", 목록=rows) == 7
    assert ev("평균(목록, '값')", 목록=rows) == 3.5
    assert ev("세기(목록)", 목록=rows) == 2
    assert ev("열뽑기(목록, '키')", 목록=rows) == ["a", "b"]
    assert ev("골라내기(목록, '키', 'a')", 목록=rows) == [rows[0]]
    assert ev("표를사전(목록, '키')", 목록=rows) == {"a": rows[0], "b": rows[1]}
    assert ev("묶기(목록, '키')", 목록=rows) == {"a": [rows[0]], "b": [rows[1]]}
    assert ev("펼치기(목록)", 목록=[[1, 2], [3]]) == [1, 2, 3]
    assert ev("합계(목록, '값')", 목록=[]) == 0, "빈 목록은 0"


def test_a_table_helper_says_which_column_is_missing() -> None:
    with pytest.raises(ExprError, match="「없는열」 열이 없다"):
        ev("합계(목록, '없는열')", 목록=[{"값": 1}])


def test_number_helpers_never_blow_up_on_zero() -> None:
    assert ev("나누기(1, 0)") == 0
    assert ev("round(비율(3, 4) * 100, 1)") == 75.0


def test_check_helpers() -> None:
    assert ev("빈칸없음(줄, ['가', '나'])", 줄={"가": 1, "나": 2}) is True
    assert ev("빈칸없음(줄, ['가', '나'])", 줄={"가": 1, "나": ""}) is False
    assert ev("범위벗어남(값, 1, 10)", 값=11) is True
    assert ev("범위벗어남(값, 1, 10)", 값=None) is True, "값이 없으면 벗어난 것으로 본다"


def test_date_helpers_are_bound_to_the_run_start() -> None:
    """같은 실행에서 자정을 넘겨도 `오늘()`이 흔들리지 않는다."""
    assert ev("오늘()") == "2026-10-04"
    assert ev("어제()") == "2026-10-03"
    assert ev("이번달()") == "2026-10"
    assert ev("지난달()") == "2026-09"
    assert ev("이번주표기()") == "2026-W40"
    assert ev("날짜더하기('2026-10-04', 5)") == "2026-10-09"
    assert ev("달더하기('2026-10', 3)") == "2027-01"
    assert ev("기간('2026-10-01', '2026-10-31')") == {"from": "2026-10-01", "to": "2026-10-31"}


def test_a_bad_date_says_the_shape() -> None:
    with pytest.raises(ExprError, match="YYYY-MM-DD"):
        ev("날짜더하기('10/04/2026', 1)")
    with pytest.raises(ExprError, match="끝이 시작보다"):
        ev("기간('2026-10-31', '2026-10-01')")


def test_the_helper_list_is_the_adr_list() -> None:
    """ADR-0025의 표와 코드가 같아야 한다 — 늘릴 때 둘을 함께 고친다."""
    adr = (Path(__file__).resolve().parent.parent / "docs" / "decisions" / "0025-expression-language.md").read_text(
        encoding="utf-8"
    )
    for name in HELPER_NAMES:
        assert f"`{name}`" in adr or f"`{name}(" in adr, f"ADR에 없는 도우미다: {name}"
    # 식에 두지 않기로 한 것은 **없어야** 한다 (ADR-0025 §식에 두지 않는 것).
    for refused in ("파일목록", "설정", "대사규칙", "전표자료"):
        assert refused not in HELPER_NAMES


# ─────────────────────── 업무 예제 50개의 식 전부 ───────────────────────


def expression_sites() -> list[tuple[str, str, str, str]]:
    """예제가 식을 쓰는 자리 — (파일, 노드, 자리, 본문).

    `dataOutput.path`·`template`는 **템플릿**이라 식 자리가 아니다 (ADR-0025 §1).
    """
    found: list[tuple[str, str, str, str]] = []
    for path in sorted(BPMN_DIR.glob("*.bpmn")):
        process = read_process(path.read_text(encoding="utf-8"))
        for node in process.all_nodes():
            if node.script:
                found.append((path.name, node.id, "script", node.script))
            for name in ("serviceCall", "rule", "call"):
                holder = node.prop(name)
                if holder is None:
                    continue
                for field, source in (holder.input or {}).items():
                    found.append((path.name, node.id, f"{name}.input.{field}", source))
            loop = node.prop("loop")
            if loop is not None and getattr(loop, "over", None):
                found.append((path.name, node.id, "loop.over", loop.over))
        flows = list(process.flows) + [f for n in process.all_nodes() for f in n.child_flows]
        for flow in flows:
            if flow.condition:
                found.append((path.name, flow.id, "condition", flow.condition))
    return found


def template_sites() -> list[tuple[str, str, str, str]]:
    """예제가 템플릿을 쓰는 자리 (`{변수}`)."""
    found: list[tuple[str, str, str, str]] = []
    for path in sorted(BPMN_DIR.glob("*.bpmn")):
        process = read_process(path.read_text(encoding="utf-8"))
        for node in process.all_nodes():
            data_output = node.prop("dataOutput")
            if data_output is not None:
                for field in ("path", "template"):
                    value = getattr(data_output, field, None)
                    if isinstance(value, str) and value:
                        found.append((path.name, node.id, f"dataOutput.{field}", value))
            email = node.prop("email")
            if email is not None:
                for field in ("subject", "body"):
                    value = getattr(email, field, "")
                    if value:
                        found.append((path.name, node.id, f"email.{field}", value))
                for address in list(email.to) + list(email.cc):
                    found.append((path.name, node.id, "email.to", address))
    return found


EXPRESSION_SITES = expression_sites()
TEMPLATE_SITES = template_sites()


def test_the_examples_actually_use_expressions() -> None:
    """시험대가 비어 있지 않은지부터 (예제를 못 읽었는데 통과하면 안 된다)."""
    kinds = {site[2].split(".")[0] for site in EXPRESSION_SITES}
    assert {"script", "condition", "serviceCall", "rule", "call"} <= kinds
    assert len(EXPRESSION_SITES) > 180, len(EXPRESSION_SITES)
    assert len(TEMPLATE_SITES) > 40, len(TEMPLATE_SITES)


@pytest.mark.parametrize(
    ("file", "node", "site", "source"), EXPRESSION_SITES, ids=[f"{s[0]}:{s[1]}:{s[2]}" for s in EXPRESSION_SITES]
)
def test_every_example_expression_parses(file: str, node: str, site: str, source: str) -> None:
    """업무 예제 50개의 식 자리 전부가 `chk-expr` 문법 안에 있어야 한다."""
    if site == "script":
        parse_script(source, where=node)
    else:
        parse(source, where=node)


@pytest.mark.parametrize(
    ("file", "node", "site", "source"), TEMPLATE_SITES, ids=[f"{s[0]}:{s[1]}:{s[2]}" for s in TEMPLATE_SITES]
)
def test_every_example_template_uses_only_names(file: str, node: str, site: str, source: str) -> None:
    """템플릿의 중괄호에는 변수 이름만 (ADR-0025 §1). 이름이 아니면 `fill()`이 거부한다."""
    names = template_names(source)
    filled = fill(source, Scope(variables=dict.fromkeys(names, "값"), helpers=bind(now=NOW), where=node))
    assert "{" not in filled.replace("{{", "").replace("}}", "") or not names
