"""재생 명세 — 패키지의 `memory/specs.json` (C1 패키지 구성, C14 §재생).

자율 수행(Studio)이 적고, 결정 수행(Bot UI 운영 실행)이 되밟는다
([ADR-0028](../../../../docs/decisions/0028-replay-memory.md)).

**배포된 Bot은 읽기만 한다.** 현장 PC마다 다르게 학습되지 않고, C2 서명으로 무결성이 보장되며,
「어느 판이 무엇을 재생하는가」가 분명하다.

**도구 인자는 값이 아니라 `{변수}` 템플릿**이다 (C14 기본 규칙 7과 같은 모양). 그래야 입력이
달라져도 같은 명세가 맞는다 — 「종류에 따라 달라지는 값은 목표 문장이 아니라 입력으로 받아라」는
예제 BX-37·BX-02의 교훈이 이것으로 지켜진다.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import Field

from chaeksas.contracts._base import ContractModel, SchemaVersioned

#: `chk:aiTask.replay` — 결정 수행에서 무엇을 재사용하나 (C14 §재생).
REPLAY_MODES = frozenset({"plan", "full", "none"})
REPLAY_DEFAULT = "plan"

#: 명세 하나의 열쇠. 노드마다 하나다 (같은 노드가 여러 번 돌아도 같은 명세).
def spec_key(bpm_process_id: str, node_id: str) -> str:
    return f"{bpm_process_id}:{node_id}"


class ReplayStep(ContractModel):
    """되밟을 도구 호출 하나."""

    tool: str
    #: `{변수}`가 섞인 인자. 값이 그 시점 변수와 같았으면 이름으로 적혀 있다.
    arguments: dict[str, Any] = Field(default_factory=dict)


class ReplaySpec(ContractModel):
    """AI 태스크 하나의 재생 명세."""

    bpm_process_id: str
    node_id: str
    #: 적을 때의 BPM 프로세스 판 (사람이 「언제 배운 것인가」를 본다).
    version: str = "0.0.0"
    steps: list[ReplayStep] = Field(default_factory=list)
    #: 마지막 답 (JSON 글 그대로). `replay: full`일 때만 쓰인다.
    answer: str = ""
    #: 적을 때 쓴 모델 (사람이 본다 — 재생에는 쓰이지 않는다).
    model: str = ""

    @property
    def key(self) -> str:
        return spec_key(self.bpm_process_id, self.node_id)


class ReplayMemory(SchemaVersioned):
    """`memory/specs.json` 한 벌."""

    SCHEMA: ClassVar[int] = 1

    specs: list[ReplaySpec] = Field(default_factory=list)

    def find(self, bpm_process_id: str, node_id: str) -> ReplaySpec | None:
        wanted = spec_key(bpm_process_id, node_id)
        return next((s for s in self.specs if s.key == wanted), None)

    def with_spec(self, spec: ReplaySpec) -> ReplayMemory:
        """같은 열쇠가 있으면 **덮어쓴** 새 기억 (Studio가 다시 배울 때)."""
        kept = [s for s in self.specs if s.key != spec.key]
        return ReplayMemory(schema=self.schema_version, specs=[*kept, spec])


__all__ = [
    "REPLAY_DEFAULT",
    "REPLAY_MODES",
    "ReplayMemory",
    "ReplaySpec",
    "ReplayStep",
    "spec_key",
]
