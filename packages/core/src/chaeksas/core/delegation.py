"""PC 위임을 맡기는 자리 ([ADR-0062](../decisions/0062-pc-delegation.md), C12 §PC 위임).

**엔진이 바깥 세계에 닿는 길은 `RunEnv` 하나다** — 위임도 포트 하나로 나간다 (`senders`·
`services`와 같은 결). 엔진은 **어디에 맡기는지 모른다**: 서버 실행기는 Center에 요청하는 것을,
Studio 시험 실행은 **케이스가 적어 둔 결과를 돌려주는 것**을 꽂는다.

**기본값은 아무것도 못 한다.** 그리고 「맡길 곳이 없다」와 「맡겼는데 거절당했다」는 **다른
예외**다 — 앞은 **그림·설치 오류**(고쳐야 할 버그)이고 뒤는 **업무 실패**(오류 경계가 받는다)다.
뭉치면 운영자가 배포를 뒤지는 동안 설계자는 그림을 못 고친다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class DelegationCall:
    """맡기는 한 번 — 엔진이 그림과 실행에서 모은 것 (C12 `DelegationRequest`와 같은 칸들).

    `node_instance`가 있어 **같은 자리는 한 번만** 작업이 된다 (멱등 키를 받는 쪽이 짓는다).
    """

    run_id: str
    node_id: str
    node_instance: int
    bpm_process_id: str
    version: str | None = None
    #: 어느 PC인가 — **식을 푼 값**이다 (비우면 받는 쪽이 고른다).
    bot_ui: str | None = None
    inputs: Mapping[str, Any] = field(default_factory=dict)


class DelegationError(RuntimeError):
    """맡기지 못했다 — **업무 실패**다 (오류 경계가 받는다).

    배포된 PC가 없거나(`no_deployment`) 판이 여럿이거나, Center에 닿지 못한 것이다.
    """

    def __init__(self, message: str, *, code: str = "delegation_failed") -> None:
        super().__init__(message)
        self.code = code


class DelegationUnsupported(RuntimeError):
    """맡길 곳이 **아예 없다** — 그림·설치 오류다 (재시도로 풀리지 않는다)."""


@runtime_checkable
class Delegator(Protocol):
    """위임을 맡는 쪽. 돌려주는 것은 **그 작업의 id**다 (기다릴 때 그것으로 찾는다)."""

    def delegate(self, call: DelegationCall) -> str: ...


class NoDelegator:
    """기본 — **맡기지 못한다.** 실행하는 쪽이 꽂아야 위임이 선다.

    여기서 「안쪽을 그 자리에서 돌리는」 폴백을 두지 않는다 — 부르는 대상은 **다른 패키지**라
    이 패키지 안에 그 정의가 없다 (ADR-0062 §2). 돌릴 것이 없으니 되는 척할 수 없다.
    """

    def delegate(self, call: DelegationCall) -> str:
        raise DelegationUnsupported(
            f"PC 위임을 맡길 곳이 없다: {call.bpm_process_id} — 실행하는 쪽이 끼워야 한다"
        )


@dataclass
class RecordingDelegator:
    """시험·Studio용 — 맡긴 것을 담아 두고 **정해 둔 작업 id**를 돌려준다.

    `fails`에 `node_id`를 넣으면 그 자리만 맡기기에 실패한다 (오류 경계 시험).
    """

    calls: list[DelegationCall] = field(default_factory=list)
    fails: Mapping[str, str] = field(default_factory=dict)
    next_id: int = 1

    def delegate(self, call: DelegationCall) -> str:
        self.calls.append(call)
        reason = self.fails.get(call.node_id)
        if reason is not None:
            raise DelegationError(f"맡기지 못했다: {reason}", code=reason)
        job_id = f"job_dlg{self.next_id:03d}"
        self.next_id += 1
        return job_id


__all__ = [
    "DelegationCall",
    "DelegationError",
    "DelegationUnsupported",
    "Delegator",
    "NoDelegator",
    "RecordingDelegator",
]
