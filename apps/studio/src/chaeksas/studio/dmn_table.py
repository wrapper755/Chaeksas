"""STU-04a 결정표 — `.dmn`을 **글자 그대로** 읽고, 고친 결정표 하나만 바꿔 쓴다 (ADR-0109).

판정은 `contracts.dmn`의 일이다. 여기는 그 앞뒤다 — 격자가 칸의 **원문**을 고쳐야 하므로(판정용 모델은 칸을
해석해 버린다) 따로 읽고, 쓸 때는 **고치는 결정표 하나만** 바꾼다. 같은 파일의 다른 결정, 결정표가 아닌 결정,
DRD·DI, 확장 요소, 열의 `inputValues`, 줄의 `annotationEntry`처럼 **모르는 것은 읽은 대로 남기고** 열·줄·칸의
id도 있던 것을 쓴다. 네임스페이스 접두사도 원래 파일의 것이다.

검증은 **`contracts.dmn`과 같은 함수**다 — 입력 칸은 `parse_cell`, 출력 칸은 `parse_value`. 마지막 관문은 지어 쓴
XML을 `read_decisions`가 **다시 읽는가**다 — 저장한 파일을 실행기가 거부하는 일이 없게.

Qt를 모른다 — 창(`decision_dialog.py`)·탭(`rule_editor.py`)이 이것을 쓴다.
"""

from __future__ import annotations

import copy
import io
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from chaeksas.contracts.dmn import (
    BOOLEAN_TYPES,
    HIT_POLICIES,
    NUMBER_TYPES,
    STRING_TYPES,
    Compare,
    DmnReadError,
    Equals,
    Range,
    parse_cell,
    parse_value,
    read_decisions,
)

#: 새 파일의 DMN 네임스페이스 (1.3 — 업무 예제와 같다).
DMN_NS = "https://www.omg.org/spec/DMN/20191111/MODEL/"

#: 적중 정책 — 콤보에 보이는 차례와 뜻 (C14).
HITS: tuple[tuple[str, str], ...] = (
    ("UNIQUE", "맞는 줄이 하나여야 합니다 — 둘 이상이면 실행 오류"),
    ("FIRST", "처음 맞는 줄 하나 — 줄 순서가 뜻입니다"),
    ("ANY", "여럿 맞아도 되지만 결과가 같아야 합니다 — 다르면 실행 오류"),
    ("COLLECT", "맞는 줄을 모두 모읍니다 — 출력이 목록입니다 (없으면 빈 목록)"),
)

#: 열 `typeRef`의 고를 거리 — 엔진이 값을 맞추는 셋과 「없음」 (C14).
TYPES: tuple[tuple[str, str], ...] = (
    ("string", "string — 글"),
    ("number", "number — 수"),
    ("boolean", "boolean — 참거짓"),
    ("", "(없음) — 맞추지 않음"),
)

#: 결정 ID 규칙 — XML id(NCName)의 우리 쪽 부분집합.
ID_RULE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")

CELL_HELP = (
    "입력 칸 (C14): - (무엇이든) · \"글\"·숫자·true/false (같다) · 쉼표는 「또는」 · "
    "< n, <= n, > n, >= n · [a..b] (a..b) [a..b) (a..b] — 대괄호는 포함"
)
VALUE_HELP = "출력 칸: 값 하나 — \"높음\"·0.05·true. 비우면 없음(None). 식은 쓸 수 없습니다."


class DmnTableError(ValueError):
    """`.dmn`을 XML로 읽을 수 없다."""


# ─────────────────────────── 모델 ───────────────────────────


@dataclass
class InputColumn:
    """입력 열. **이름은 `expression`**(`inputExpression` 본문)이다 — `label`은 사람이 읽는 이름."""

    id: str
    expression: str = ""
    label: str = ""
    type: str = ""
    #: 읽은 원래 요소 (쓸 때 모르는 속성·자식을 살린다). 새 열이면 `None`.
    origin: ElementTree.Element | None = field(default=None, repr=False, compare=False)


@dataclass
class OutputColumn:
    id: str
    name: str = ""
    type: str = ""
    origin: ElementTree.Element | None = field(default=None, repr=False, compare=False)


@dataclass
class Row:
    """규칙 줄. `cells`는 입력 열 수, `values`는 출력 열 수와 같다 — **칸의 원문**이다."""

    id: str
    cells: list[str] = field(default_factory=list)
    values: list[str] = field(default_factory=list)
    description: str = ""
    #: 열 id → 그 칸 요소의 id (있던 것을 그대로 쓰려고).
    entries: dict[str, str] = field(default_factory=dict, repr=False, compare=False)
    origin: ElementTree.Element | None = field(default=None, repr=False, compare=False)


@dataclass
class Table:
    """결정 하나 (`dmn:decision` + `dmn:decisionTable`)를 격자로."""

    id: str
    name: str = ""
    hit: str = "UNIQUE"
    inputs: list[InputColumn] = field(default_factory=list)
    outputs: list[OutputColumn] = field(default_factory=list)
    rules: list[Row] = field(default_factory=list)

    def copy(self) -> Table:
        return copy.deepcopy(self)

    # ── 고치기 (창이 부른다) ──

    def add_input(self, at: int | None = None) -> InputColumn:
        made = InputColumn(id=self._fresh("Input"), type="string")
        index = len(self.inputs) if at is None else at
        self.inputs.insert(index, made)
        for row in self.rules:
            row.cells.insert(index, "-")
        return made

    def add_output(self, at: int | None = None) -> OutputColumn:
        made = OutputColumn(id=self._fresh("Output"), type="string")
        index = len(self.outputs) if at is None else at
        self.outputs.insert(index, made)
        for row in self.rules:
            row.values.insert(index, "")
        return made

    def remove_input(self, index: int) -> None:
        del self.inputs[index]
        for row in self.rules:
            del row.cells[index]

    def remove_output(self, index: int) -> None:
        del self.outputs[index]
        for row in self.rules:
            del row.values[index]

    def add_rule(self, at: int | None = None) -> Row:
        made = Row(id=self._fresh("Rule"), cells=["-"] * len(self.inputs), values=[""] * len(self.outputs))
        self.rules.insert(len(self.rules) if at is None else at, made)
        return made

    def _fresh(self, kind: str) -> str:
        taken = {self.id, *(c.id for c in self.inputs), *(c.id for c in self.outputs), *(r.id for r in self.rules)}
        n = 1
        while f"{kind}_{self.id}_{n}" in taken:
            n += 1
        return f"{kind}_{self.id}_{n}"


def blank(decision_id: str = "", name: str = "") -> Table:
    """「새 결정표...」 — 입력 열·출력 열·규칙 줄 하나씩."""
    made = Table(id=decision_id, name=name)
    made.add_input()
    made.add_output()
    made.add_rule()
    return made


# ─────────────────────────── 읽기 ───────────────────────────


def _tag(element: ElementTree.Element) -> str:
    return element.tag.rpartition("}")[2] if isinstance(element.tag, str) else ""


def _child(element: ElementTree.Element, name: str) -> ElementTree.Element | None:
    return next((c for c in element if _tag(c) == name), None)


def _text(element: ElementTree.Element | None) -> str:
    return (element.text or "").strip() if element is not None else ""


def _parse(xml: str | bytes) -> ElementTree.Element:
    """주석까지 살려 읽는다 (쓸 때 모르는 것을 버리지 않으려고)."""
    parser = ElementTree.XMLParser(target=ElementTree.TreeBuilder(insert_comments=True))
    try:
        return ElementTree.fromstring(xml, parser=parser)
    except ElementTree.ParseError as e:
        raise DmnTableError(f"XML을 읽을 수 없습니다: {e}") from e


def read_tables(xml: str | bytes) -> dict[str, Table]:
    """파일 하나의 결정표들 — `{결정 id: 표}`. **칸은 해석하지 않는다**(틀린 칸도 열어 고친다)."""
    root = _parse(xml)
    out: dict[str, Table] = {}
    for element in root.iter():
        if _tag(element) != "decision":
            continue
        table = _child(element, "decisionTable")
        if table is None:
            continue  # 결정표가 아닌 결정 — `contracts.dmn`도 건너뛴다
        found = _read_table(element.get("id") or "", element.get("name") or "", table)
        out[found.id] = found
    return out


def _read_table(decision_id: str, name: str, table: ElementTree.Element) -> Table:
    inputs: list[InputColumn] = []
    outputs: list[OutputColumn] = []
    rules: list[Row] = []
    for element in table:
        kind = _tag(element)
        if kind == "input":
            expression = _child(element, "inputExpression")
            inputs.append(
                InputColumn(
                    id=element.get("id") or "",
                    expression=_text(_child(expression, "text")) if expression is not None else "",
                    label=element.get("label") or "",
                    type=(expression.get("typeRef") or "") if expression is not None else "",
                    origin=copy.deepcopy(element),
                )
            )
        elif kind == "output":
            outputs.append(
                OutputColumn(
                    id=element.get("id") or "",
                    name=element.get("name") or "",
                    type=element.get("typeRef") or "",
                    origin=copy.deepcopy(element),
                )
            )
    for element in table:
        if _tag(element) != "rule":
            continue
        cells = [c for c in element if _tag(c) == "inputEntry"]
        values = [c for c in element if _tag(c) == "outputEntry"]
        # 칸 수가 어긋난 줄은 모자란 칸을 채워 보인다 — 저장하면 맞춰진다(읽기는 어차피 거부한다).
        entries = {col.id: c.get("id") or "" for col, c in zip(inputs, cells, strict=False)}
        entries.update({col.id: c.get("id") or "" for col, c in zip(outputs, values, strict=False)})
        rules.append(
            Row(
                id=element.get("id") or "",
                cells=[_text(_child(c, "text")) for c in cells[: len(inputs)]]
                + ["-"] * max(0, len(inputs) - len(cells)),
                values=[_text(_child(c, "text")) for c in values[: len(outputs)]]
                + [""] * max(0, len(outputs) - len(values)),
                description=_text(_child(element, "description")),
                entries=entries,
                origin=copy.deepcopy(element),
            )
        )
    hit = (table.get("hitPolicy") or "UNIQUE").strip().upper()
    return Table(id=decision_id, name=name, hit=hit, inputs=inputs, outputs=outputs, rules=rules)


# ─────────────────────────── 쓰기 ───────────────────────────


def _namespaces(xml: str | bytes) -> list[tuple[str, str]]:
    data = xml.encode("utf-8") if isinstance(xml, str) else xml
    found: list[tuple[str, str]] = []
    for _event, pair in ElementTree.iterparse(io.BytesIO(data), events=("start-ns",)):
        found.append(pair)
    return found


def _skeleton(table: Table) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<dmn:definitions xmlns:dmn="{DMN_NS}" id="Defs_{table.id}" '
        f'name="{_attr(table.name or table.id)}" namespace="urn:chaeksas:studio" />\n'
    )


def _attr(text: str) -> str:
    return text.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


def write_table(xml: str | None, table: Table, *, original_id: str | None = None) -> str:
    """`xml`(없으면 새 파일)의 결정 `original_id`(없으면 `table.id`)를 `table`로 바꾼 XML.

    **그 결정표 하나만** 바꾼다. 파일에 그 결정이 없으면 끝에 더한다.
    """
    source = xml if xml is not None else _skeleton(table)
    namespaces = _namespaces(source)
    root = _parse(source)
    ns = root.tag[1:].partition("}")[0] if root.tag.startswith("{") else DMN_NS

    def q(name: str) -> str:
        return f"{{{ns}}}{name}"

    wanted = original_id or table.id
    decision = next(
        (e for e in root.iter() if _tag(e) == "decision" and (e.get("id") or "") == wanted),
        None,
    )
    if decision is None:
        decision = ElementTree.SubElement(root, q("decision"))
    decision.set("id", table.id)
    if table.name:
        decision.set("name", table.name)
    elif "name" in decision.attrib:
        del decision.attrib["name"]
    element = _child(decision, "decisionTable")
    if element is None:
        element = ElementTree.SubElement(decision, q("decisionTable"), {"id": f"DT_{table.id}"})
    element.set("hitPolicy", table.hit)
    _rebuild(element, table, q)

    for prefix, uri in namespaces:
        ElementTree.register_namespace(prefix, uri)
    if not namespaces:
        ElementTree.register_namespace("dmn", ns)
    ElementTree.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ElementTree.tostring(root, encoding="unicode") + "\n"


def _rebuild(element: ElementTree.Element, table: Table, q: Any) -> None:
    """`decisionTable`의 열·줄을 다시 짓는다. 그 밖의 자식은 자리를 지켜 남긴다."""
    managed = ("input", "output", "rule", "annotation")
    head = [c for c in list(element) if _tag(c) not in managed and _tag(c) in ("description", "extensionElements")]
    annotations = [c for c in list(element) if _tag(c) == "annotation"]
    tail = [c for c in list(element) if _tag(c) not in managed and c not in head]
    for child in list(element):
        element.remove(child)
    for child in head:
        element.append(child)
    for column in table.inputs:
        element.append(_input_element(column, q))
    for out in table.outputs:
        element.append(_output_element(out, q))
    for child in annotations:
        element.append(child)
    for row in table.rules:
        element.append(_rule_element(row, table, q))
    for child in tail:
        element.append(child)


def _input_element(column: InputColumn, q: Any) -> ElementTree.Element:
    made = copy.deepcopy(column.origin) if column.origin is not None else ElementTree.Element(q("input"))
    made.set("id", column.id)
    if column.label:
        made.set("label", column.label)
    elif "label" in made.attrib:
        del made.attrib["label"]
    expression = _child(made, "inputExpression")
    if expression is None:
        expression = ElementTree.Element(q("inputExpression"), {"id": f"{column.id}_expr"})
        made.insert(0, expression)
    if column.type:
        expression.set("typeRef", column.type)
    elif "typeRef" in expression.attrib:
        del expression.attrib["typeRef"]
    text = _child(expression, "text")
    if text is None:
        text = ElementTree.SubElement(expression, q("text"))
    text.text = column.expression
    return made


def _output_element(column: OutputColumn, q: Any) -> ElementTree.Element:
    made = copy.deepcopy(column.origin) if column.origin is not None else ElementTree.Element(q("output"))
    made.set("id", column.id)
    made.set("name", column.name)
    if column.type:
        made.set("typeRef", column.type)
    elif "typeRef" in made.attrib:
        del made.attrib["typeRef"]
    return made


def _rule_element(row: Row, table: Table, q: Any) -> ElementTree.Element:
    origin = row.origin
    made = ElementTree.Element(q("rule"), dict(origin.attrib) if origin is not None else {})
    made.set("id", row.id)
    kept = (
        [c for c in origin if _tag(c) not in ("description", "inputEntry", "outputEntry")] if origin is not None else []
    )
    had_description = origin is not None and _child(origin, "description") is not None
    if row.description or had_description:
        ElementTree.SubElement(made, q("description")).text = row.description
    for child in kept:
        if _tag(child) == "extensionElements":
            made.append(copy.deepcopy(child))
    entries = [("inputEntry", "I", c.id, text) for c, text in zip(table.inputs, row.cells, strict=True)]
    entries += [("outputEntry", "O", o.id, text) for o, text in zip(table.outputs, row.values, strict=True)]
    counts = {"I": 0, "O": 0}
    for kind, mark, column_id, text in entries:
        entry_id = row.entries.get(column_id) or f"{row.id}_{mark}{counts[mark]}"
        counts[mark] += 1
        entry = ElementTree.SubElement(made, q(kind), {"id": entry_id})
        ElementTree.SubElement(entry, q("text")).text = text
    for child in kept:
        if _tag(child) != "extensionElements":
            made.append(copy.deepcopy(child))
    return made


# ─────────────────────────── 검사 ───────────────────────────


@dataclass(frozen=True)
class CellProblem:
    """틀린 칸 하나 — 격자가 그 칸을 빨갛게 하고 툴팁에 단다."""

    row: int
    column: int  # 입력 0..n-1, 출력 n..n+m-1
    message: str


def cell_problem(text: str, *, output: bool) -> str | None:
    """칸 하나 — `contracts.dmn`과 **같은 함수**로 본다. 맞으면 `None`."""
    try:
        if output:
            parse_value(text, where="칸")
        else:
            parse_cell(text, where="칸")
    except DmnReadError as e:
        return str(e).removeprefix("칸: ")
    return None


def cell_problems(table: Table) -> list[CellProblem]:
    out: list[CellProblem] = []
    width = len(table.inputs)
    for r, row in enumerate(table.rules):
        for c, text in enumerate(row.cells):
            found = cell_problem(text, output=False)
            if found:
                out.append(CellProblem(r, c, found))
        for c, text in enumerate(row.values):
            found = cell_problem(text, output=True)
            if found:
                out.append(CellProblem(r, width + c, found))
    return out


def _type_kind(type_ref: str) -> str:
    kind = type_ref.strip().lower()
    if kind in NUMBER_TYPES:
        return "number"
    if kind in BOOLEAN_TYPES:
        return "boolean"
    if kind in STRING_TYPES:
        return "string"
    return ""


def _mismatch(kind: str, value: Any) -> bool:
    """열의 `typeRef`와 칸의 값이 다른가 — 맞을 일이 없는 칸."""
    if value is None:
        return False
    if kind == "number":
        return isinstance(value, bool) or not isinstance(value, (int, float))
    if kind == "boolean":
        return not isinstance(value, bool)
    if kind == "string":
        return not isinstance(value, str)
    return False


def problems(table: Table, *, taken: Iterable[str] = ()) -> tuple[list[str], list[str]]:
    """`(막는 것, 경고)`. `taken`은 이미 있는 결정 id들(새 결정표에서만 넘긴다)."""
    errors: list[str] = []
    warnings: list[str] = []
    if not table.id.strip():
        errors.append("ID가 비었습니다.")
    elif not ID_RULE.match(table.id):
        errors.append(f"ID는 영문자·_로 시작하고 영문자·숫자·_.-만 씁니다: {table.id}")
    elif table.id in set(taken):
        errors.append(f"이미 있는 결정 ID입니다: {table.id}")
    if table.hit not in HIT_POLICIES:
        errors.append(f"쓸 수 없는 적중 정책입니다: {table.hit} (C14 — {', '.join(h for h, _ in HITS)})")
    for n, column in enumerate(table.inputs, start=1):
        if not column.expression.strip():
            errors.append(f"입력 열 {n}의 식 이름이 비었습니다 — 규칙 태스크가 이 이름으로 값을 넘깁니다.")
    names = [c.expression.strip() for c in table.inputs if c.expression.strip()]
    for name in sorted({x for x in names if names.count(x) > 1}):
        warnings.append(f"입력 식 이름이 겹칩니다: {name} — 같은 값이 두 열에 들어갑니다.")
    if not table.outputs:
        errors.append("출력 열이 없습니다.")
    for n, out in enumerate(table.outputs, start=1):
        if not out.name.strip():
            errors.append(f"출력 열 {n}의 이름이 비었습니다.")
    outs = [o.name.strip() for o in table.outputs if o.name.strip()]
    for name in sorted({x for x in outs if outs.count(x) > 1}):
        errors.append(f"출력 이름이 겹칩니다: {name} — 판정 결과에서 하나가 사라집니다.")
    for found in cell_problems(table):
        errors.append(f"규칙 {found.row + 1} · {_column_name(table, found.column)}: {found.message}")
    if not table.rules:
        warnings.append("규칙 줄이 없습니다 — 늘 「해당 없음」입니다.")
    for type_ref in [*(c.type for c in table.inputs), *(o.type for o in table.outputs)]:
        if type_ref and not _type_kind(type_ref):
            warnings.append(f"typeRef {type_ref}는 맞추지 않습니다 — 값을 바꾸지 않고 견줍니다 (C14의 셋 밖).")
    warnings.extend(_type_warnings(table))
    if not errors:
        try:
            read_decisions(write_table(None, table))
        except (DmnReadError, DmnTableError) as e:  # pragma: no cover — 위 검사가 먼저 잡는다
            errors.append(f"저장하면 읽을 수 없는 결정표입니다: {e}")
    return errors, warnings


def _column_name(table: Table, column: int) -> str:
    if column < len(table.inputs):
        found = table.inputs[column]
        return f"입력 {found.label or found.expression or column + 1}"
    out = table.outputs[column - len(table.inputs)]
    return f"출력 {out.name or column - len(table.inputs) + 1}"


def _type_warnings(table: Table) -> list[str]:
    out: list[str] = []
    for r, row in enumerate(table.rules, start=1):
        for column, text in zip(table.inputs, row.cells, strict=True):
            kind = _type_kind(column.type)
            if not kind or cell_problem(text, output=False):
                continue
            parsed = parse_cell(text, where="칸") or ()
            bounds: list[Any] = []
            for term in parsed:
                if isinstance(term, Equals):
                    bounds.append(term.value)
                elif isinstance(term, Compare):
                    bounds.append(term.bound)
                elif isinstance(term, Range):
                    bounds.extend((term.low, term.high))
            if any(_mismatch(kind, b) for b in bounds):
                where = column.label or column.expression
                out.append(f"규칙 {r} · 입력 {where}: {kind} 열인데 값이 다릅니다 — 맞을 일이 없습니다.")
    return out


# ─────────────────────────── 작업 폴더의 결정표들 ───────────────────────────


@dataclass(frozen=True)
class DecisionFile:
    """결정 하나가 사는 곳 — STU-04 「규칙」 탭의 고를 거리."""

    path: Path
    received: bool  # `libs/` — 읽기 전용 (ADR-0048)
    table: Table


def catalog(files: Iterable[tuple[Path, bool]]) -> tuple[dict[str, DecisionFile], dict[Path, str]]:
    """`Workspace.decision_files()` 차례대로 읽는다 — **뒤의 것이 이긴다**(내 `process/`).

    `({결정 id: 사는 곳}, {읽지 못한 파일: 까닭})`.
    """
    found: dict[str, DecisionFile] = {}
    broken: dict[Path, str] = {}
    for path, received in files:
        try:
            tables = read_tables(path.read_text(encoding="utf-8"))
        except (OSError, DmnTableError) as e:
            broken[path] = str(e)
            continue
        for decision_id, table in tables.items():
            found[decision_id] = DecisionFile(path=path, received=received, table=table)
    return found, broken


@dataclass(frozen=True)
class Decisions:
    """열린 BPM 프로세스의 결정표들 — 「규칙」 탭이 고를 때마다 새로 읽는다 (저장·설치 뒤에도 맞게)."""

    found: Mapping[str, DecisionFile]
    broken: Mapping[Path, str]
    #: 「새 결정표...」가 쓰는 곳 (`process/`).
    process_dir: Path


def decisions_of(owner: Any) -> Decisions | None:
    """`Workspace` 하나 → `Decisions`. 열린 것이 없으면 `None`(모른다 — 대조를 건너뛴다)."""
    if owner is None:
        return None
    found, broken = catalog(owner.decision_files())
    return Decisions(found=found, broken=broken, process_dir=Path(owner.folder) / "process")


def summary(table: Table) -> str:
    """「COLLECT · 입력 4 · 출력 1 · 규칙 4」."""
    return f"{table.hit} · 입력 {len(table.inputs)} · 출력 {len(table.outputs)} · 규칙 {len(table.rules)}"


def io_names(table: Table) -> tuple[list[str], list[str]]:
    """규칙 태스크가 맞출 이름들 — `(입력 식 이름들, 출력 이름들)` (B14와 같은 것)."""
    return [c.expression for c in table.inputs if c.expression], [o.name for o in table.outputs if o.name]


def hit_help() -> Mapping[str, str]:
    return dict(HITS)


__all__ = [
    "CELL_HELP",
    "DMN_NS",
    "HITS",
    "ID_RULE",
    "TYPES",
    "VALUE_HELP",
    "CellProblem",
    "DecisionFile",
    "Decisions",
    "DmnTableError",
    "InputColumn",
    "OutputColumn",
    "Row",
    "Table",
    "blank",
    "catalog",
    "decisions_of",
    "cell_problem",
    "cell_problems",
    "hit_help",
    "io_names",
    "problems",
    "read_tables",
    "summary",
    "write_table",
]
