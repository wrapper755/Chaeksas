"""그림의 식 자리를 값 없이 검사한다 — C14 B15.

`validate()`(계약)는 **도우미 함수를 모른다** — 구현이 `core.helpers`에 있고 계약은 그것을
import하지 않는다 (의존 방향, `docs/01-architecture.md` §5). 그래서 B15만 여기 있고,
Studio 「실행 전 검사」가 `validate()` 결과에 이어 붙인다.

보는 자리는 **엔진이 실제로 `evaluate`·`run_script`를 부르는 자리**와 같다 (아래 `SITES`).
템플릿(`dataOutput.path`·`email.body`)은 식이 아니라 `{변수}`라서 여기 없다 (ADR-0025 §1).
"""

from __future__ import annotations

from collections.abc import Iterator

from chaeksas.contracts import SEVERITY_ERROR, Violation
from chaeksas.contracts.bpmn_ext import BpmnProcess
from chaeksas.core.expr import ExprError, parse, parse_script

#: 식을 들고 있는 `chk:*` 속성과 그 안의 입력 사전 (`serviceCall.input` 등).
SITES = ("serviceCall", "rule", "call")


def expression_sites(process: BpmnProcess) -> Iterator[tuple[str, str, str]]:
    """`(노드·흐름 id, 자리, 본문)` — 그림이 식·스크립트를 쓰는 자리 전부.

    자리 이름(`script`·`condition`·`serviceCall.input.기간`)은 사람이 어디를 고칠지 알게
    하는 것이라 화면·시험이 그대로 보인다.
    """
    for node in process.all_nodes():
        if node.script:
            yield (node.id, "script", node.script)
        for name in SITES:
            holder = node.prop(name)
            if holder is None:
                continue
            for field, source in (holder.input or {}).items():
                yield (node.id, f"{name}.input.{field}", source)
        loop = node.prop("loop")
        if loop is not None and loop.collection:
            # 엔진이 `evaluate(spec.collection)`으로 푸는 식이다 (`core.engine`).
            yield (node.id, "loop.collection", loop.collection)
    flows = list(process.flows) + [f for n in process.all_nodes() for f in n.child_flows]
    for flow in flows:
        if flow.condition:
            yield (flow.id, "condition", flow.condition)


def check_expressions(process: BpmnProcess) -> list[Violation]:
    """B15 — 식 자리마다 파싱하고 도우미 호출의 인자 모양을 본다.

    **값을 넣지 않는다** — 그래서 「변수가 없다」·「0으로 나눴다」는 여기서 나오지 않고,
    문법과 호출 모양만 본다. 한 자리에서 한 줄씩 낸다 (첫 오류에서 멈추지 않는다 — 사람은
    한 번에 다 보고 고치고 싶다).
    """
    out: list[Violation] = []
    for where, site, source in expression_sites(process):
        try:
            if site == "script":
                parse_script(source, where=where)
            else:
                parse(source, where=where)
        except ExprError as e:
            out.append(
                Violation(
                    rule="B15",
                    message=f"{where}: {site} — {e.reason}",
                    items=[where],
                    severity=SEVERITY_ERROR,
                )
            )
    return out


__all__ = ["SITES", "check_expressions", "expression_sites"]
