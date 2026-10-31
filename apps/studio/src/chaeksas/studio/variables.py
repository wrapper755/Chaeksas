"""STU-01 아래 탭 「변수」의 값 다루기 — **Qt를 모른다** (탭은 `variables_tab.py`).

이 BPM 프로세스가 **받는 것(입력)·내놓는 것(출력)의 정의**는 그림의 `bpm:process.inputs`·
`outputs`(C14)에 산다. 그래서 고치는 자리는 「BPM 프로세스 정보」(STU-06)가 아니라 캔버스 쪽이고,
쓰기는 **캔버스를 거친다** (ADR-0022 — `bpm:process`를 통째로 되돌려 써서 실행 취소가 한 걸음).

여기 있는 것: 표 한 줄(`InputRow`)과 그 검사·짓기, 그림이 만드는 변수와 「만드는 곳」, 다른 화면이
고를 거리로 쓰는 이름 목록, 「지금 값」 칸의 글.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from chaeksas.contracts.bpmn_ext import (
    INPUT_SOURCE_CALLER,
    INPUT_SOURCE_TYPES,
    BpmnProcess,
    InputDecl,
    ProcessInfo,
    is_var_name,
    produced_vars,
)

#: 타입 콤보의 차례 (C14 `VALUE_TYPES`).
INPUT_TYPES = ("string", "int", "number", "bool", "list", "dict", "date")
#: 값 출처 콤보 — (값, 화면 글). 부르는 쪽이 맨 앞이고 기본값이다 (ADR-0099).
INPUT_SOURCES = (
    (INPUT_SOURCE_CALLER, "부르는 쪽"),
    ("virtual_worker.id", "가상 직원 — id"),
    ("virtual_worker.name", "가상 직원 — 이름"),
    ("virtual_worker.supervisors", "가상 직원 — 감독자"),
)
#: 「지금 값」 칸에 보이는 글의 길이 — 긴 목록 하나가 칸을 다 차지하면 나머지를 못 본다.
MAX_VALUE = 200
#: 값이 아직 없을 때 (U2).
NONE = "—"


@dataclass(frozen=True)
class InputRow:
    """「입력」 줄 하나 — 화면에서 읽은 글 그대로 (Qt 없이 검사하고 짓는다)."""

    name: str
    type: str = "string"
    required: bool = False
    default: str = ""
    source: str = INPUT_SOURCE_CALLER
    description: str = ""
    #: 읽어 온 그 줄 — 표가 모르는 칸을 **그 줄에 남긴다** (모델이 모르는 칸을 보관한다).
    original: InputDecl | None = None

    @classmethod
    def of(cls, decl: InputDecl) -> InputRow:
        return cls(
            name=decl.name,
            type=decl.type,
            required=decl.required,
            default=default_text(decl.type, decl.default),
            source=decl.source or INPUT_SOURCE_CALLER,
            description=decl.description or "",
            original=decl,
        )


def source_label(source: str | None) -> str:
    """값 출처 → 화면 글. 모르는 출처는 **글자 그대로** 보인다 (B8이 말한다)."""
    written = source or INPUT_SOURCE_CALLER
    return next((label for value, label in INPUT_SOURCES if value == written), written)


def default_text(kind: str, value: Any) -> str:
    """기본값 → 칸에 보일 글. 글자는 그대로, 나머지는 JSON이다."""
    if value is None:
        return ""
    if kind in ("string", "date") and isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def parse_default(kind: str, text: str) -> tuple[Any, str]:
    """칸의 글 → 기본값과 흠 (흠이 빈 글이면 괜찮다). 비우면 기본값이 없다."""
    raw = text.strip()
    if not raw:
        return None, ""
    if kind in ("string", "date"):
        return raw, ""
    try:
        value = json.loads(raw)
    except ValueError:
        return None, f"기본값 「{raw}」을 {kind}로 읽지 못했습니다"
    fits = {
        "int": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, int | float) and not isinstance(value, bool),
        "bool": isinstance(value, bool),
        "list": isinstance(value, list),
        "dict": isinstance(value, dict),
    }.get(kind, True)
    return (value, "") if fits else (None, f"기본값 「{raw}」은 {kind}가 아닙니다")


def _name_problem(kind: str, names: Iterable[str]) -> str:
    seen: set[str] = set()
    for raw in names:
        name = raw.strip()
        if not name:
            return f"{kind}의 이름을 적으세요."
        if not is_var_name(name):
            return f"{kind} 이름으로 쓸 수 없습니다: {name}"
        if name in seen:
            return f"같은 이름의 {kind}이 둘입니다: {name}"
        seen.add(name)
    return ""


def problem(inputs: Sequence[InputRow], outputs: Sequence[str]) -> str:
    """「적용」을 막는 흠 — **첫 하나만** (C14 B2·B8과 같은 규칙). 빈 글이면 괜찮다.

    입력과 출력에 같은 이름은 된다 — 받은 값을 고쳐 내놓는 BPM 프로세스가 있다.
    """
    found = _name_problem("입력", (row.name for row in inputs))
    if found:
        return found
    for row in inputs:
        wanted = INPUT_SOURCE_TYPES.get(row.source)
        if wanted is not None and row.type != wanted:
            return f"입력 {row.name.strip()}은 값 출처가 가상 직원이라 타입이 {wanted}여야 합니다"
        _value, bad = parse_default(row.type, row.default)
        if bad:
            return f"입력 {row.name.strip()}: {bad}"
    return _name_problem("출력", outputs)


def build_inputs(rows: Sequence[InputRow]) -> list[InputDecl]:
    """표 → `bpm:process.inputs`. 읽어 온 줄은 **모르는 칸을 남긴 채** 고친다."""
    out: list[InputDecl] = []
    for row in rows:
        value, _bad = parse_default(row.type, row.default)
        fields = {
            "name": row.name.strip(),
            "type": row.type,
            "required": row.required,
            "description": row.description.strip() or None,
            "default": value,
            # 부르는 쪽은 **적지 않는다** — 비우면 그것이다 (옛 그림과 같은 모양).
            "source": None if row.source == INPUT_SOURCE_CALLER else row.source,
        }
        out.append(row.original.model_copy(update=fields) if row.original is not None else InputDecl(**fields))
    return out


def process_patch(info: ProcessInfo, inputs: Sequence[InputRow], outputs: Sequence[str]) -> str:
    """캔버스에 넘길 `bpm:process` 본문 (JSON 글 — `setProperties`의 규약).

    **읽은 것을 통째로 되돌려 쓴다** — `run_location`·`extensions`처럼 이 탭이
    모르는 칸이 사라지지 않게 (STU-06·STU-15와 같은 자리).
    """
    made = info.model_copy(deep=True)
    made.inputs = build_inputs(inputs)
    made.outputs = [name.strip() for name in outputs]
    return json.dumps(made.to_json_dict(), ensure_ascii=False, indent=2)


def changed(info: ProcessInfo, inputs: Sequence[InputRow], outputs: Sequence[str]) -> bool:
    """표가 그림과 다른가 — 「적용」을 켤지, 적용 안 한 편집이 있나 (화면의 글 그대로 견준다)."""
    return list(inputs) != [InputRow.of(decl) for decl in info.inputs] or list(outputs) != list(info.outputs)


def made_by(process: BpmnProcess) -> dict[str, list[str]]:
    """그림이 만드는 변수 → 만드는 노드(이름, 없으면 id). **계약의 `produced_vars`** 그대로다.

    검사(B11)와 같은 함수라 「여기는 있다는데 검사는 모른다」가 생기지 않는다.
    """
    out: dict[str, list[str]] = {}
    for node in process.all_nodes():
        for name in sorted(produced_vars(node)):
            out.setdefault(name, []).append(node.name or node.id)
    return out


def known_names(info: ProcessInfo | None, made: Mapping[str, Sequence[str]]) -> list[str]:
    """다른 화면의 고를 거리 — 출력, 그다음 그림이 만드는 변수, 그다음 입력 (겹치면 한 번).

    시험 케이스의 「기대 결과」가 이 차례로 보인다 (STU-07) — 비교하는 것은 대개 출력이다.
    """
    names: list[str] = []
    if info is not None:
        names += list(info.outputs)
    names += sorted(made)
    if info is not None:
        names += [decl.name for decl in info.inputs]
    return list(dict.fromkeys(name for name in names if name))


def value_text(value: Any) -> str:
    """「지금 값」 칸의 글 — 글자는 따옴표째, 나머지는 JSON. 잘라 보인다."""
    shown = json.dumps(value, ensure_ascii=False, default=str)
    return shown if len(shown) <= MAX_VALUE else shown[:MAX_VALUE] + "…"


def caption(variables: Mapping[str, Any]) -> str:
    """실행 중 안내 줄 (STU-09)."""
    return f"시험 실행 값 · 변수 {len(variables)}개"


__all__ = [
    "INPUT_SOURCES",
    "INPUT_TYPES",
    "MAX_VALUE",
    "NONE",
    "InputRow",
    "build_inputs",
    "caption",
    "changed",
    "default_text",
    "known_names",
    "made_by",
    "parse_default",
    "problem",
    "process_patch",
    "source_label",
    "value_text",
]
