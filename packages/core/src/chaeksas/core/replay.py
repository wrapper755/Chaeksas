"""재생 명세를 적고 되밟는다 — C14 §재생, [ADR-0028](../../../../docs/decisions/0028-replay-memory.md).

자율 수행(Studio)이 적고, 결정 수행(Bot UI 운영 실행)이 되밟는다. 명세는 패키지 안
`memory/specs.json`이고 **배포된 Bot은 읽기만** 한다.

핵심은 **도구 인자를 값이 아니라 `{변수}` 템플릿으로 적는 것**이다. 그래야 입력이 달라져도 같은
명세가 맞는다 (예제 BX-37·BX-02의 교훈). 되돌려 적는 일은 **어림**이라, 문자열이 변수 값과
**그대로 같을 때만** 바꾸고 짧은 값·참거짓·수는 건드리지 않는다.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from chaeksas.contracts.replay import ReplayMemory, ReplaySpec, ReplayStep
from chaeksas.core.agent import AgentError, Step, Tool, Trace
from chaeksas.core.expr import NAME_RE, TEMPLATE_RE

#: 이보다 짧은 글은 변수 이름으로 되돌리지 않는다 (「네」·「ok」가 어쩌다 묶이는 것을 막는다).
MIN_TEMPLATED = 3

#: 재생 명세가 들어가는 패키지 안 자리 (C1 패키지 구성).
MEMORY_PATH = "memory/specs.json"


def read_memory(package_dir: Path) -> ReplayMemory:
    """패키지 폴더에서 `memory/specs.json`을 읽는다. 없으면 빈 기억이다."""
    found = package_dir / "memory" / "specs.json"
    if not found.is_file():
        return ReplayMemory(schema=1)
    return ReplayMemory.model_validate_json(found.read_text(encoding="utf-8"))


def write_memory(package_dir: Path, memory: ReplayMemory) -> Path:
    """Studio가 배운 것을 적는다. **배포된 Bot은 이 길을 쓰지 않는다** (읽기만, ADR-0028)."""
    found = package_dir / "memory" / "specs.json"
    found.parent.mkdir(parents=True, exist_ok=True)
    found.write_text(
        json.dumps(memory.to_json_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return found


# ─────────────────────────── 적기 ───────────────────────────


def to_spec(
    trace: Trace,
    *,
    bpm_process_id: str,
    node_id: str,
    version: str = "0.0.0",
    variables: Mapping[str, Any] | None = None,
) -> ReplaySpec:
    """자율 수행의 궤적 → 재생 명세. **인자를 `{변수}`로 되돌려 적는다.**"""
    return ReplaySpec(
        bpm_process_id=bpm_process_id,
        node_id=node_id,
        version=version,
        steps=[
            ReplayStep(tool=step.tool, arguments=templated(step.arguments, variables or {}))
            for step in trace.steps
        ],
        answer=trace.answer,
        model=trace.model,
    )


def templated(arguments: Mapping[str, Any], variables: Mapping[str, Any]) -> dict[str, Any]:
    """인자 값이 그 시점 변수 값과 **그대로 같으면** 이름으로 바꾼다 (ADR-0028 §4)."""
    by_value = {
        value: name
        for name, value in variables.items()
        if isinstance(value, str) and len(value) >= MIN_TEMPLATED and NAME_RE.match(name)
    }
    out: dict[str, Any] = {}
    for key, value in arguments.items():
        name = by_value.get(value) if isinstance(value, str) else None
        out[key] = f"{{{name}}}" if name else value
    return out


def filled(arguments: Mapping[str, Any], variables: Mapping[str, Any]) -> dict[str, Any]:
    """되밟을 때 `{변수}`를 지금 값으로 채운다. 모르는 이름이면 **글 그대로** 둔다.

    모르는 이름을 오류로 삼지 않는 것은, 그림이 바뀌어 변수가 사라졌어도 재생이 **도구에서**
    실패해 오류 경계로 가게 하기 위해서다 (재생 실패를 사람이 보는 길, BX-36).
    """
    out: dict[str, Any] = {}
    for key, value in arguments.items():
        if not isinstance(value, str):
            out[key] = value
            continue
        names = [m.group(1) for m in TEMPLATE_RE.finditer(value) if m.group(1)]
        if len(names) == 1 and value == f"{{{names[0]}}}" and names[0].strip() in variables:
            out[key] = variables[names[0].strip()]  # 통째로 한 변수면 **값 그대로** (수·목록도 된다)
        else:
            out[key] = _fill_text(value, variables)
    return out


def _fill_text(text: str, variables: Mapping[str, Any]) -> str:
    def one(match: re.Match[str]) -> str:
        whole = match.group(0)
        if whole in ("{{", "}}"):
            return whole[0]
        name = (match.group(1) or "").strip()
        if name not in variables:
            return whole
        value = variables[name]
        return "" if value is None else str(value)

    return str(TEMPLATE_RE.sub(one, text))


# ─────────────────────────── 되밟기 ───────────────────────────


def replay_steps(
    spec: ReplaySpec,
    *,
    tools: Mapping[str, Tool],
    variables: Mapping[str, Any],
) -> Trace:
    """적어 둔 도구 차례를 **모델 없이** 다시 밟는다.

    도구가 이 PC에 없거나 실패하면 `AgentError(business=True)`다 — 오류 경계가 받아 사람에게
    넘어간다. **몰래 자율 수행으로 넘어가지 않는다** (ADR-0010·ADR-0028 §6).
    """
    trace = Trace(answer=spec.answer, model=spec.model)
    for step in spec.steps:
        tool = tools.get(step.tool)
        if tool is None:
            raise AgentError(f"기억에 적힌 도구가 이 PC에 없다: {step.tool}", business=True)
        arguments = filled(step.arguments, variables)
        try:
            result = str(tool(**arguments))
        except Exception as e:  # noqa: BLE001 — 도구가 무엇을 낼지 모른다
            raise AgentError(f"재생 중 도구 {step.tool}이 실패했다: {e}", business=True) from e
        trace.steps.append(Step(tool=step.tool, arguments=arguments, result=result))
    return trace


__all__ = [
    "MEMORY_PATH",
    "MIN_TEMPLATED",
    "filled",
    "read_memory",
    "replay_steps",
    "templated",
    "to_spec",
    "write_memory",
]
