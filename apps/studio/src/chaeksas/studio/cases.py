"""시험 케이스의 **값과 검증** (STU-07의 속). 창은 `case_dialog.py`.

표 한 칸 ↔ 케이스 JSON 한 값을 서로 바꾸는 것(`pack_*`/`unpack_*`)과, 저장 전 검증이 여기
있다. **창 없이도 시험할 수 있게** 갈라 두었다 — 왕복이 어긋나면 저장할 때마다 값이 바뀐다.

결재 답은 **엔진과 같은 검증기** `validate_answer`로 본다 (C6).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from chaeksas.contracts.approvals import Form, validate_answer
from chaeksas.contracts.bpmn_ext import Case, CaseFile
from chaeksas.studio.workspace import BpmProcess, Definition

#: 입력 값의 타입 (STU-07 — 「지금부터」는 `$now_plus`, 「시험 수신기」는 `$test_receiver`).
VALUE_KINDS = ("string", "number", "bool", "json", "지금부터", "시험 수신기")
#: 기대 결과의 비교 (C14 「기대 결과 비교 규칙」).
COMPARISONS = {
    "같음": "",
    "값이 있음": "*",
    "이상": "$gte",
    "초과": "$gt",
    "이하": "$lte",
    "미만": "$lt",
    "포함": "$contains",
}

NO_APPROVALS = "이 정의에는 결재가 없습니다."


def pack_value(kind: str, raw: str) -> Any:
    """표의 한 칸 → 케이스 입력 값."""
    if kind == "지금부터":
        return {"$now_plus": raw}
    if kind == "시험 수신기":
        return {"$test_receiver": raw or "reply"}
    if kind == "bool":
        return raw.strip().lower() in ("1", "true", "yes", "참")
    if kind == "number":
        try:
            return float(raw) if "." in raw else int(raw)
        except ValueError:
            return raw
    if kind == "json":
        try:
            return json.loads(raw)
        except ValueError:
            return raw
    return raw


def unpack_value(value: Any) -> tuple[str, str]:
    """케이스 입력 값 → `(타입, 글)`."""
    if isinstance(value, dict) and len(value) == 1:
        (key, argument), = value.items()
        if key == "$now_plus":
            return "지금부터", str(argument)
        if key == "$test_receiver":
            return "시험 수신기", str(argument)
    if isinstance(value, bool):
        return "bool", "true" if value else "false"
    if isinstance(value, int | float):
        return "number", str(value)
    if isinstance(value, str):
        return "string", value
    return "json", json.dumps(value, ensure_ascii=False)


def pack_expected(comparison: str, kind: str, raw: str) -> Any:
    operator = COMPARISONS.get(comparison, "")
    if operator == "*":
        return "*"
    value = pack_value(kind, raw)
    return {operator: value} if operator else value


def unpack_expected(value: Any) -> tuple[str, str, str]:
    """기대 결과 값 → `(비교, 타입, 글)`."""
    if value == "*":
        return "값이 있음", "string", ""
    if isinstance(value, dict) and len(value) == 1:
        (key, argument), = value.items()
        found = next((name for name, op in COMPARISONS.items() if op == key), None)
        if found is not None:
            kind, text = unpack_value(argument)
            return found, kind, text
    kind, text = unpack_value(value)
    return "같음", kind, text


def approvals_of(definition: Definition) -> dict[str, Form]:
    """그 정의의 결재·확인 (`노드 id → 폼`). 폼이 없으면 빈 `Form`이다 (C6 — `decision` 하나)."""
    if definition.process is None:
        return {}
    out: dict[str, Form] = {}
    for node in definition.process.all_nodes():
        approval = node.prop("approval")
        if approval is not None:
            out[node.id] = Form(fields=list(approval.fields))
    return out


def messages_of(definition: Definition) -> list[str]:
    """그 정의가 받는 메시지 이름 (받기 태스크·경계·중간 받기)."""
    if definition.process is None:
        return []
    return sorted(name for name in definition.process.messages if name)


def declared_inputs(definition: Definition) -> list[str]:
    """`chk:process.inputs`에 적힌 입력 이름 — 이름 콤보에 미리 나온다 (STU-07)."""
    if definition.process is None:
        return []
    return [i.name for i in definition.process.info.inputs]


def check_cases(cases: Sequence[Case], definition: Definition) -> list[str]:
    """저장 전 검증 (STU-07). 틀린 것을 사람 말로 돌려준다."""
    problems: list[str] = []
    seen: set[str] = set()
    forms = approvals_of(definition)
    messages = set(messages_of(definition))
    for case in cases:
        if not case.name.strip():
            problems.append("이름이 빈 케이스가 있습니다.")
        elif case.name in seen:
            problems.append(f"이름이 겹칩니다: {case.name}")
        seen.add(case.name)
        for node_id, answer in case.approvals.items():
            if node_id not in forms:
                problems.append(f"{case.name}: 결재 노드가 없습니다 — {node_id}")
                continue
            if case.manual:
                continue  # 수동 케이스는 자동 응답을 쓰지 않는다
            # **엔진과 같은 검증기**를 쓴다 (C6) — 돌려 보고야 아는 일을 없앤다.
            for problem in validate_answer(forms[node_id], answer):
                # 어느 **칸**인지 붙인다 — 「답이 없다」만 보고는 무엇을 적을지 모른다.
                key = f"/{problem.items[0]}" if problem.items else ""
                problems.append(f"{case.name}/{node_id}{key}: {problem.message}")
        for message in case.messages:
            if messages and message.name not in messages:
                problems.append(f"{case.name}: 받는 곳이 없는 메시지 — {message.name}")
    return problems


@dataclass
class Edited:
    """편집 중인 케이스 한 벌과 그것이 사는 파일."""

    path: Path
    cases: list[Case]


def read(process: BpmProcess, definition: Definition) -> Edited:
    path = process.case_file(definition)
    if not path.is_file():
        return Edited(path=path, cases=[])
    try:
        return Edited(path=path, cases=list(CaseFile.model_validate_json(path.read_text(encoding="utf-8")).cases))
    except ValueError:
        return Edited(path=path, cases=[])


def write(edited: Edited, *, process_id: str = "") -> Path:
    body = CaseFile(schema=1, process=process_id or None, cases=list(edited.cases))
    edited.path.parent.mkdir(parents=True, exist_ok=True)
    edited.path.write_text(
        json.dumps(body.to_json_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return edited.path


__all__ = [
    "COMPARISONS",
    "NO_APPROVALS",
    "VALUE_KINDS",
    "Edited",
    "approvals_of",
    "check_cases",
    "declared_inputs",
    "messages_of",
    "pack_expected",
    "pack_value",
    "read",
    "unpack_expected",
    "unpack_value",
    "write",
]
