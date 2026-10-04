"""C14 §규칙 태스크와 DMN — 결정표를 읽고 **한 건을 판정한다**.

규칙 태스크(`businessRuleTask` + `chk:rule`)가 가리키는 `.dmn` 파일이 여기로 들어온다. 형식
해석이므로 계약 쪽에 둔다 (`bpmn_ext`가 BPMN을 읽는 것과 같은 자리). 읽기는 표준 라이브러리
(`xml.etree`)로만 한다.

**FEEL 전체를 들이지 않는다.** 입력 칸(unary test)에서 쓰는 것은 다섯 가지뿐이다 — 무엇이든
(`-`), 같다, 「또는」(쉼표), 견주기(`>= 20`), 범위(`[0..7]`). 그 밖은 **읽기 단계에서 거부**해서
Studio 검사가 미리 잡게 한다. 출력 칸은 값 하나다 (식이 아니다).

판정은 **순수하다** — 같은 입력이면 같은 결과다. 그래서 결정 수행(재생)에서도 다시 판정한다.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree

from chaeksas.contracts.bpmn_ext import DecisionIo

#: 적중 정책 (C14). 그 밖(`RULE ORDER`·`OUTPUT ORDER`·`PRIORITY`)은 schema 1에서 쓰지 않는다.
HIT_POLICIES = frozenset({"UNIQUE", "FIRST", "ANY", "COLLECT"})

#: 「무엇이든」을 뜻하는 입력 칸.
ANY_CELL = "-"

#: `typeRef`를 어떻게 맞추나 (C14 — 없으면 `"25" > 20`이 문자열 비교가 된다).
NUMBER_TYPES = frozenset({"number", "integer", "int", "long", "double", "decimal"})
BOOLEAN_TYPES = frozenset({"boolean", "bool"})
STRING_TYPES = frozenset({"string", "text"})

_COMPARISON = re.compile(r"^(<=|>=|<|>)\s*(.+)$")
_RANGE = re.compile(r"^([\[(])\s*(.+?)\s*\.\.\s*(.+?)\s*([\])])$")


class DmnReadError(ValueError):
    """DMN 파일을 읽을 수 없다 (XML이 깨졌거나, 쓸 수 없는 입력 칸 문법이다)."""


class DmnError(ValueError):
    """판정할 수 없다 (입력이 빠졌거나, 적중 정책이 깨졌다)."""


# ─────────────────────────── 입력 칸 (unary test) ───────────────────────────


@dataclass(frozen=True)
class Equals:
    """`"높음"`·`3`·`true` — 같은지 본다."""

    value: Any

    def holds(self, value: Any) -> bool:
        return _same(value, self.value)


@dataclass(frozen=True)
class Compare:
    """`>= 750` — 견준다. 견줄 수 없는 값(없음·문자열)은 **맞지 않은 것**으로 본다."""

    op: str
    bound: Any

    def holds(self, value: Any) -> bool:
        if not _comparable(value) or not _comparable(self.bound):
            return False
        return bool(
            {
                "<": value < self.bound,
                "<=": value <= self.bound,
                ">": value > self.bound,
                ">=": value >= self.bound,
            }[self.op]
        )


@dataclass(frozen=True)
class Range:
    """`[1..30)` — 대괄호는 포함, 소괄호는 제외."""

    low: Any
    high: Any
    low_closed: bool
    high_closed: bool

    def holds(self, value: Any) -> bool:
        if not _comparable(value) or not _comparable(self.low) or not _comparable(self.high):
            return False
        lower = value >= self.low if self.low_closed else value > self.low
        upper = value <= self.high if self.high_closed else value < self.high
        return bool(lower and upper)


Term = Equals | Compare | Range
#: 한 칸 = 「또는」으로 묶인 항들. `None`이면 무엇이든 맞다 (`-`).
Cell = tuple[Term, ...] | None


def _comparable(value: Any) -> bool:
    """견줄 수 있는 값인가. `True`는 숫자가 아니다 (파이썬에서는 `True == 1`이다)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _same(left: Any, right: Any) -> bool:
    """같은가. 참거짓과 숫자를 섞지 않는다 (`True == 1`을 막는다)."""
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    return bool(left == right)


def _literal(text: str, *, where: str) -> Any:
    """칸에 적힌 값 하나 (`"높음"`·`0.05`·`true`·`null`). 식은 쓸 수 없다. 빈 칸은 「없음」이다."""
    body = text.strip()
    if not body:
        return None
    try:
        return json.loads(body)
    except ValueError:
        raise DmnReadError(f"{where}: 값으로 읽을 수 없다 ({body!r}) — 문자열은 큰따옴표로 감싼다") from None


def _split_terms(text: str) -> list[str]:
    """쉼표로 나눈다. **따옴표 안의 쉼표는 세지 않는다** (`"유흥","골프"`)."""
    out: list[str] = []
    current: list[str] = []
    quoted = False
    for char in text:
        if char == '"':
            quoted = not quoted
        if char == "," and not quoted:
            out.append("".join(current))
            current = []
            continue
        current.append(char)
    out.append("".join(current))
    return [part for part in (p.strip() for p in out) if part]


def parse_cell(text: str, *, where: str) -> Cell:
    """입력 칸 하나를 읽는다 (C14 §규칙 태스크와 DMN의 표). 쓸 수 없는 문법은 거부한다."""
    body = (text or "").strip()
    if not body or body == ANY_CELL:
        return None

    terms: list[Term] = []
    for part in _split_terms(body):
        found = _RANGE.match(part)
        if found is not None:
            open_, low, high, close = found.groups()
            terms.append(
                Range(
                    low=_literal(low, where=where),
                    high=_literal(high, where=where),
                    low_closed=open_ == "[",
                    high_closed=close == "]",
                )
            )
            continue
        found = _COMPARISON.match(part)
        if found is not None:
            terms.append(Compare(op=found.group(1), bound=_literal(found.group(2), where=where)))
            continue
        terms.append(Equals(value=_literal(part, where=where)))
    if not terms:
        return None
    return tuple(terms)


def _holds(cell: Cell, value: Any) -> bool:
    return True if cell is None else any(term.holds(value) for term in cell)


# ─────────────────────────── 결정표 ───────────────────────────


@dataclass(frozen=True)
class DecisionInput:
    """입력 하나. **이름은 `inputExpression`의 본문**이다 (`label`은 사람이 읽는 이름)."""

    name: str
    label: str | None = None
    type: str | None = None


@dataclass(frozen=True)
class DecisionOutput:
    name: str
    type: str | None = None


@dataclass(frozen=True)
class DecisionRule:
    """줄 하나. `cells`는 입력 수와 같고, `values`는 출력 수와 같다."""

    id: str
    cells: tuple[Cell, ...]
    values: tuple[Any, ...]
    description: str | None = None

    def holds(self, values: tuple[Any, ...]) -> bool:
        return all(_holds(cell, value) for cell, value in zip(self.cells, values, strict=True))


@dataclass(frozen=True)
class Decision:
    """결정 하나 (`dmn:decision` + `dmn:decisionTable`)."""

    id: str
    name: str | None
    hit: str
    inputs: tuple[DecisionInput, ...]
    outputs: tuple[DecisionOutput, ...]
    rules: tuple[DecisionRule, ...]

    @property
    def io(self) -> DecisionIo:
        """B14가 규칙 태스크의 `input`·`output`과 대조할 이름들."""
        return DecisionIo(
            inputs=tuple(i.name for i in self.inputs),
            outputs=tuple(o.name for o in self.outputs),
        )

    def decide(self, values: Mapping[str, Any]) -> dict[str, Any]:
        """한 건을 판정한다 — `{출력 이름: 값}`.

        `COLLECT`면 값이 **목록**이다 (맞는 줄이 없으면 빈 목록). 그 밖은 맞는 줄이 없으면
        모든 출력이 `None`이다 — 실패가 아니라 「해당 없음」이고, 게이트웨이로 가른다.
        """
        missing = [i.name for i in self.inputs if i.name not in values]
        if missing:
            raise DmnError(f"[{self.id}] 입력이 빠졌다: {', '.join(missing)}")
        row = tuple(_coerce(values[i.name], i.type) for i in self.inputs)
        hits = [rule for rule in self.rules if rule.holds(row)]

        if self.hit == "COLLECT":
            return {out.name: [hit.values[i] for hit in hits] for i, out in enumerate(self.outputs)}
        if not hits:
            return {out.name: None for out in self.outputs}
        if self.hit == "UNIQUE" and len(hits) > 1:
            raise DmnError(f"[{self.id}] UNIQUE인데 {len(hits)}줄이 맞았다: {', '.join(h.id for h in hits)}")
        if self.hit == "ANY" and any(h.values != hits[0].values for h in hits[1:]):
            raise DmnError(f"[{self.id}] ANY인데 맞은 줄들의 결과가 다르다: {', '.join(h.id for h in hits)}")
        return {out.name: hits[0].values[i] for i, out in enumerate(self.outputs)}


def _coerce(value: Any, type_ref: str | None) -> Any:
    """`typeRef`에 맞춰 값을 바꾼다. 바꿀 수 없으면 **그대로 둔다** (맞는 줄이 없어질 뿐이다)."""
    if value is None or not type_ref:
        return value
    kind = type_ref.strip().lower()
    if kind in NUMBER_TYPES and not _comparable(value):
        if isinstance(value, bool):
            return value
        try:
            return float(value) if isinstance(value, str) and "." in value else int(value)
        except (TypeError, ValueError):
            return value
    if kind in BOOLEAN_TYPES and not isinstance(value, bool):
        if isinstance(value, str) and value.strip().lower() in ("true", "false"):
            return value.strip().lower() == "true"
        return value
    if kind in STRING_TYPES and not isinstance(value, str):
        return value if isinstance(value, bool) else str(value)
    return value


# ─────────────────────────── 읽기 ───────────────────────────


def _tag(element: ElementTree.Element) -> str:
    """네임스페이스를 뗀 요소 이름. DMN 네임스페이스는 판(1.1·1.3)마다 다르다."""
    return element.tag.rpartition("}")[2]


def _child(element: ElementTree.Element, name: str) -> ElementTree.Element | None:
    return next((c for c in element if _tag(c) == name), None)


def _children(element: ElementTree.Element, name: str) -> list[ElementTree.Element]:
    return [c for c in element if _tag(c) == name]


def _text(element: ElementTree.Element | None) -> str:
    return (element.text or "").strip() if element is not None else ""


def read_decisions(xml: str | bytes) -> dict[str, Decision]:
    """DMN 파일 하나를 읽는다 — `{결정 id: 결정}`. 결정이 여럿이어도 된다.

    결정표가 없는 결정(다른 모양의 `decisionLogic`)은 **건너뛴다** — 우리가 쓰는 것은
    결정표뿐이고, 모르는 것을 거부하면 bpmn-js로 그린 파일을 통째로 못 읽는다.
    """
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as e:
        raise DmnReadError(f"XML을 읽을 수 없다: {e}") from e

    out: dict[str, Decision] = {}
    for element in root.iter():
        if _tag(element) != "decision":
            continue
        table = _child(element, "decisionTable")
        if table is None:
            continue
        decision_id = element.get("id") or ""
        out[decision_id] = _read_table(decision_id, element.get("name"), table)
    return out


def _read_table(decision_id: str, name: str | None, table: ElementTree.Element) -> Decision:
    hit = (table.get("hitPolicy") or "UNIQUE").strip().upper()
    if hit not in HIT_POLICIES:
        raise DmnReadError(f"[{decision_id}] 쓸 수 없는 적중 정책이다: {hit} ({', '.join(sorted(HIT_POLICIES))})")

    inputs = []
    for element in _children(table, "input"):
        expression = _child(element, "inputExpression")
        text = _text(_child(expression, "text")) if expression is not None else ""
        if not text:
            raise DmnReadError(f"[{decision_id}] 입력 {element.get('id')}에 inputExpression 본문이 없다")
        inputs.append(
            DecisionInput(
                name=text,
                label=element.get("label"),
                type=expression.get("typeRef") if expression is not None else None,
            )
        )
    outputs = [
        DecisionOutput(name=element.get("name") or "", type=element.get("typeRef"))
        for element in _children(table, "output")
    ]
    if not outputs:
        raise DmnReadError(f"[{decision_id}] 출력이 없다")
    if any(not o.name for o in outputs):
        raise DmnReadError(f"[{decision_id}] 이름 없는 출력이 있다")

    rules = []
    for element in _children(table, "rule"):
        rule_id = element.get("id") or ""
        where = f"{decision_id}/{rule_id}"
        cells = _children(element, "inputEntry")
        values = _children(element, "outputEntry")
        if len(cells) != len(inputs) or len(values) != len(outputs):
            raise DmnReadError(
                f"[{where}] 칸 수가 맞지 않는다 (입력 {len(cells)}/{len(inputs)}, 출력 {len(values)}/{len(outputs)})"
            )
        rules.append(
            DecisionRule(
                id=rule_id,
                cells=tuple(parse_cell(_text(_child(c, "text")), where=where) for c in cells),
                values=tuple(_literal(_text(_child(v, "text")), where=where) for v in values),
                description=_text(_child(element, "description")) or None,
            )
        )
    return Decision(
        id=decision_id, name=name, hit=hit, inputs=tuple(inputs), outputs=tuple(outputs), rules=tuple(rules)
    )


def decision_io(decisions: Iterable[Decision]) -> dict[str, DecisionIo]:
    """`validate(..., dmn_decisions=…)`에 넘길 표 (B14의 DMN 대조)."""
    return {decision.id: decision.io for decision in decisions}


__all__ = [
    "ANY_CELL",
    "HIT_POLICIES",
    "Cell",
    "Compare",
    "Decision",
    "DecisionInput",
    "DecisionOutput",
    "DecisionRule",
    "DmnError",
    "DmnReadError",
    "Equals",
    "Range",
    "Term",
    "decision_io",
    "parse_cell",
    "read_decisions",
]
