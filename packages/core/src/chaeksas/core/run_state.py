"""실행의 상태와 수행기 규약 — 엔진(`core.engine`)과 노드 수행기(`core.nodes`)가 함께 쓰는 것.

여기에는 **상태와 약속만** 둔다. 돌리는 것은 `core.engine`, 노드마다 무엇을 하는지는
`core.nodes`다. 셋으로 가른 이유는 순환 import 없이 수행기를 늘려 가기 위해서다 —
수행기는 이 모듈만 보고, 엔진이 수행기를 모아 꽂는다.

**바깥 세계는 `RunEnv` 한 곳으로 모은다** — 파일(`Workspace`), 보내기 어댑터(`Sender`), 같은
패키지의 DMN 결정. 실행하는 쪽(Bot UI·Studio 시험 실행·서버 실행기)이 정해서 준다. 주지 않으면
파일도 못 쓰고 메일도 못 보낸다 — **조용히 아무 데나 쓰거나 안 보내지 않는다** (ADR-0026).

쓰는 쪽은 `chaeksas.core.engine`에서 한꺼번에 들면 된다 (그쪽이 여기 것을 다시 내보낸다).
"""

from __future__ import annotations

import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from chaeksas.contracts.approvals import Form
from chaeksas.contracts.bpmn_ext import BpmnProcess, Flow, Node
from chaeksas.contracts.dmn import Decision
from chaeksas.core.expr import Scope
from chaeksas.core.files import Workspace
from chaeksas.core.run_log import RunLog
from chaeksas.core.senders import NoSender, Sender

if TYPE_CHECKING:  # `Context.engine`의 타입만 쓴다 — 실행 때는 들지 않는다 (순환 import).
    from chaeksas.core.engine import Engine


#: 한 번 `run_until_blocked()`에서 밟을 노드 수 한도 (돌고 도는 그림을 막는 그물).
MAX_STEPS = 10_000

#: 엔진이 늘 주는 변수 (C14 §9). 이름이 늘면 `contracts.bpmn_ext.BUILTIN_VARS`도 함께 고친다.
BUILTIN_TODAY = "오늘"
BUILTIN_NOW = "지금"
BUILTIN_RUN_ID = "run_id"

#: 결재·확인에서 폼을 주지 않았을 때의 답 (C6 — 「없으면 승인 / 반려 두 단추」).
DECISION_KEY = "decision"

#: 오류 경계가 만드는 변수 (C14 §이벤트).
ERROR_CODE_VAR = "error_code"
ERROR_MESSAGE_VAR = "error_message"
FAILED_TASK_VAR = "failed_task"

#: 표준 오류 코드 (C14 §이벤트).
ERROR_TASK_FAILED = "TASK_FAILED"
ERROR_SEND_FAILED = "SEND_FAILED"

#: 실행 폴더 밖을 가리켰다 (ADR-0026). **오류 경계로 받지 않는다** — 그림·설정이 잘못된 것이다.
CODE_PATH_DENIED = "path_denied"
#: 아직 다루지 않는 노드·태스크 (뒤 조각). 실행을 조용히 지나가지 않고 멈춘다.
CODE_UNSUPPORTED = "node_kind_unsupported"

class State(StrEnum):
    """실행의 지금 상태."""

    READY = "ready"
    RUNNING = "running"
    WAITING = "waiting"  # 사람·메시지·타이머를 기다린다
    DONE = "done"
    FAILED = "failed"


class EngineError(RuntimeError):
    """실행을 멈춰야 하는 문제. 노드 id를 달고 나온다."""

    def __init__(self, message: str, *, node_id: str | None = None, code: str = "engine_error") -> None:
        self.node_id = node_id
        self.code = code
        super().__init__(f"[{node_id}] {message}" if node_id else message)


class TaskFailed(EngineError):
    """태스크가 실패했다 — **오류 경계로 받을 수 있는** 실패 (C14 `TASK_FAILED`).

    그림이 잘못된 것(식 오류·흐름 없음)은 경계로 받지 않는다. 그것은 고쳐야 할 버그다.
    """

    def __init__(self, message: str, *, node_id: str, code: str = ERROR_TASK_FAILED) -> None:
        super().__init__(message, node_id=node_id, code=code)


# ─────────────────────────── 토큰·상태 ───────────────────────────


@dataclass
class LoopState:
    """반복(다중 인스턴스) 한 묶음 (C14 §반복)."""

    items: list[Any]
    item_name: str
    result_name: str | None
    collect_into: str
    index: int = 0
    results: list[Any] = field(default_factory=list)
    sequential: bool = True

    @property
    def finished(self) -> bool:
        return self.index >= len(self.items)


@dataclass
class Token:
    """실행 중인 자리 하나."""

    id: str
    node_id: str
    #: 하위 프로세스 안이면 그 노드 id들 (범위 경로). 비면 맨 바깥이다.
    scope: tuple[str, ...] = ()
    #: 기다리는 것의 열쇠 (결재 `request_id`, 하위 프로세스 `sub:<노드>`).
    waiting_for: str | None = None
    loop: LoopState | None = None

    @property
    def waiting(self) -> bool:
        return self.waiting_for is not None


@dataclass
class Pending:
    """사람을 기다리는 중인 요청 (결재·확인)."""

    request_id: str
    node_id: str
    layer: str  # approval | confirmation
    title: str
    form: Form | None
    #: 결재자에게 보여 줄 값 (C6 `review` — 원칙 6의 예외다).
    review: dict[str, Any] = field(default_factory=dict)
    where: str = "field"  # field | center
    node_instance: int = 1


@dataclass(frozen=True)
class RunEnv:
    """실행이 **바깥 세계에 닿는 자리**. 실행하는 쪽이 정해서 준다.

    기본값은 아무것도 못 하는 것이다 — 파일을 쓰려면 출력 폴더가, 메일을 보내려면 어댑터가
    있어야 한다. 「없으면 조용히 넘어간다」로 두면 보냈는지 썼는지 아무도 모른다.
    """

    #: 파일을 읽고 쓸 수 있는 범위 (C14 §파일 경로, ADR-0026).
    workspace: Workspace = field(default_factory=Workspace)
    #: 메일·웹훅 보내기 (C14 §보내기). 기본은 **보내지 않고 실패한다**.
    sender: Sender = field(default_factory=NoSender)
    #: 같은 패키지의 DMN 결정 (`결정 id` → 결정). 규칙 태스크가 찾는다.
    decisions: Mapping[str, Decision] = field(default_factory=dict)


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_token_id() -> str:
    return f"t_{secrets.token_hex(3)}"


@dataclass
class Run:
    """실행 하나. 토큰·변수·기록을 들고 있다."""

    run_id: str
    process: BpmnProcess
    log: RunLog
    #: 바깥 세계 (파일·보내기·DMN). 주지 않으면 아무것도 못 한다.
    env: RunEnv = field(default_factory=RunEnv)
    variables: dict[str, Any] = field(default_factory=dict)
    state: State = State.READY
    tokens: list[Token] = field(default_factory=list)
    #: 기다리는 사람 요청 (`request_id` → 요청). 병렬 가지면 여럿일 수 있다.
    pendings: dict[str, Pending] = field(default_factory=dict)
    #: 합류 게이트웨이에 도착한 토큰 (`범위:노드` → 토큰 id 묶음).
    arrivals: dict[str, set[str]] = field(default_factory=dict)
    #: 포함 분기가 실제로 띄운 가지 수 (`범위:합류` → 수). 포함 합류가 이만큼 기다린다.
    expected: dict[str, int] = field(default_factory=dict)
    mode: str = "autonomous"
    started: datetime = field(default_factory=utc_now)
    error: EngineError | None = None
    #: 노드마다 몇 번째 수행인지 (C6 `node_instance`·C10 `business_key`).
    instances: dict[str, int] = field(default_factory=dict)
    helpers: Mapping[str, Callable[..., Any]] = field(default_factory=dict)

    # ── 자주 쓰는 것 ──

    def node(self, node_id: str) -> Node:
        found = next((n for n in self.process.all_nodes() if n.id == node_id), None)
        if found is None:
            raise EngineError(f"노드를 찾지 못했다: {node_id}", code="node_missing")
        return found

    def scope(self, node_id: str | None = None, **extra: Any) -> Scope:
        """식이 볼 것. **변수를 그대로 넘긴다** — 스크립트가 여기에 대입한다.

        반복의 `item`처럼 그 노드에서만 보이는 이름은 `extra`로 얹는다.
        """
        found = Scope(variables=self.variables, helpers=self.helpers, where=node_id)
        return found.child(**extra) if extra else found

    def flows(self, scope: tuple[str, ...] = ()) -> list[Flow]:
        """그 범위의 흐름 (맨 바깥이면 프로세스의 흐름, 안쪽이면 그 하위 프로세스의 흐름)."""
        if not scope:
            return list(self.process.flows)
        return list(self.node(scope[-1]).child_flows)

    def outgoing(self, node_id: str, scope: tuple[str, ...] = ()) -> list[Flow]:
        return [f for f in self.flows(scope) if f.source == node_id]

    def incoming(self, node_id: str, scope: tuple[str, ...] = ()) -> list[Flow]:
        return [f for f in self.flows(scope) if f.target == node_id]

    def boundaries(self, node_id: str) -> list[Node]:
        """그 노드에 붙은 경계 이벤트."""
        return [n for n in self.process.all_nodes() if n.attached_to == node_id]

    @property
    def pending(self) -> Pending | None:
        """기다리는 요청 하나 (대개 하나다 — 병렬 가지면 `pendings`를 본다)."""
        return next(iter(self.pendings.values()), None)

    @property
    def finished(self) -> bool:
        return self.state in (State.DONE, State.FAILED)

    def runnable(self) -> Token | None:
        return next((t for t in self.tokens if not t.waiting), None)


# ─────────────────────────── 수행기가 돌려주는 것 ───────────────────────────


@dataclass
class Go:
    """다음으로 간다. `targets`가 비면 **나가는 흐름**을 따른다 (여럿이면 갈라진다)."""

    targets: list[str] | None = None


@dataclass
class Wait:
    """이 토큰은 멈춘다. `key`로 무엇을 기다리는지 가린다 (결재 `request_id` 등)."""

    key: str


@dataclass
class Consume:
    """이 토큰은 여기서 사라진다 (합류가 아직 안 찼거나, 끝났다)."""


Outcome = Go | Wait | Consume


@dataclass
class Context:
    """수행기가 받는 것 — 실행·토큰·노드."""

    engine: Engine
    run: Run
    token: Token
    node: Node

    @property
    def node_id(self) -> str:
        return self.node.id

    def scope(self) -> Scope:
        """식이 볼 것.

        반복의 `item`은 **프로세스 변수로 넣어 둔다** (`_prepare_iteration`) — 자식 스코프에
        넣으면 스크립트의 대입이 사본으로 들어가 사라진다.
        """
        return self.run.scope(self.node.id)

    def emit(self, kind: str, **data: Any) -> None:
        self.run.log.emit(kind, node_id=self.node.id, **data)

    def instance(self) -> int:
        return self.run.instances.get(self.node.id, 1)


Handler = Callable[[Context], Outcome]


# ─────────────────────────── 노드에 대해 아는 것 ───────────────────────────


def task_type(node: Node) -> str | None:
    """C3 `node_state.task_type`."""
    if node.kind == "serviceTask" and node.prop("fileList") is not None:
        return "file_list"
    if node.kind == "intermediateThrowEvent":
        # 이벤트 정의가 없는 중간 던지기가 **이정표**다 (C14 §이벤트). 신호·메시지는 다른 것이다.
        return "milestone" if not node.event_definitions else None
    return {
        "serviceTask": "service_task",
        "userTask": "approval",
        "manualTask": "confirmation",
        "scriptTask": "script",
        "businessRuleTask": "rule",
        "callActivity": "call",
        "sendTask": "send",
        "receiveTask": "receive",
        "subProcess": "subprocess",
    }.get(node.kind)


def new_run_id(*, now: datetime | None = None, test: bool = False) -> str:
    """C3 `run_id` — `run_<YYYYMMDD>_<HHMMSS>_<hex6>` (시험 실행은 `test_`)."""
    at = (now or utc_now()).strftime("%Y%m%d_%H%M%S")
    return f"{'test' if test else 'run'}_{at}_{secrets.token_hex(3)}"


__all__ = [
    "BUILTIN_NOW",
    "BUILTIN_RUN_ID",
    "BUILTIN_TODAY",
    "CODE_PATH_DENIED",
    "CODE_UNSUPPORTED",
    "DECISION_KEY",
    "ERROR_CODE_VAR",
    "ERROR_MESSAGE_VAR",
    "ERROR_SEND_FAILED",
    "ERROR_TASK_FAILED",
    "FAILED_TASK_VAR",
    "MAX_STEPS",
    "Consume",
    "Context",
    "EngineError",
    "Go",
    "Handler",
    "LoopState",
    "Outcome",
    "Pending",
    "Run",
    "RunEnv",
    "State",
    "TaskFailed",
    "Token",
    "Wait",
    "new_run_id",
    "new_token_id",
    "task_type",
    "utc_now",
]
