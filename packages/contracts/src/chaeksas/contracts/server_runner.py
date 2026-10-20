"""C12. Center API: 서버 실행기 등록·하트비트·메시지.

단일 원본: `docs/03-contracts/C12-server-runner-center.md`.

**C4(Bot UI)와 같은 틀이고 다른 것은 셋이다** (ADR-0015·ADR-0054 —
`docs/decisions/0054-server-run-state-and-concurrency.md`).

| | C4 Bot UI | C12 서버 실행기 |
| --- | --- | --- |
| 실행 자리 | `current_run` 하나 (ADR-0014) | `capacity` + `running[]` — 상한까지 여럿 |
| 기다리는 실행 | 자리를 쥔다 | **`waiting[]`로 빠져 자리를 놓는다** |
| 대기열 | Bot UI가 가진다 (`queue`) | **Center가 가진다** — 실행기는 빈자리만큼만 받는다 |

그래서 **같은 모양인 칸은 C4의 모델을 그대로 쓴다** — `JobAck`·`ApprovalAck`·
`DeploymentResult`·`Readiness`·`ExtensionState`·`JobDispatch`·`ApprovalDispatch`. 베끼면 한쪽만
고쳐져 두 길이 갈라진다.

**상태·사유 값은 열린 문자열**이다 (C4와 같다) — 모르는 값 하나로 하트비트 전체를 거부하지
않는다. 알려진 값은 `KNOWN_*`로만 둔다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Any

from pydantic import Field

from chaeksas.contracts._base import ContractModel, SchemaVersioned, Timestamp
from chaeksas.contracts.bot_ui import (
    ApprovalAck,
    ApprovalDispatch,
    DeploymentResult,
    ExtensionState,
    JobAck,
    JobDispatch,
    MachineId,
    Readiness,
)
from chaeksas.contracts.signing import AdminKey

#: 하트비트 기본 간격과 오프라인 판정 (C12 §재시작과 유실 — PC보다 촘촘하다).
DEFAULT_HEARTBEAT_S = 10
OFFLINE_AFTER_S = 180

#: 실행기 하나가 **한 번에 도는** 실행 수의 기본 상한 (`CHK_SERVER_RUNNER__MAX_CONCURRENCY`).
DEFAULT_MAX_CONCURRENCY = 10
#: BPM 프로세스 하나가 한 번에 도는 수의 기본 상한 (배포의 `max_concurrency`, ADR-0016).
DEFAULT_PER_BOT_CONCURRENCY = 5

ServerRunnerId = Annotated[str, Field(pattern=r"^srv_[0-9a-f]{8}$")]

# 알려진 값 (모두 열린 문자열).
KNOWN_RUNNER_STATUSES = frozenset({"running", "paused", "draining", "error"})
#: `waiting[].waiting_for` — C3 `run_waiting.waiting_for`와 **같은 말**이다.
WAITING_DELEGATION = "delegation"
KNOWN_WAITING_FOR = frozenset({"approval", "message", "timer", WAITING_DELEGATION})
#: 위임 결과의 `state` — 작업 ack와 **같은 값**이다 (C4). `finished`가 아니면 업무 실패다.
KNOWN_DELEGATION_STATES = frozenset({"finished", "failed", "cancelled", "expired", "rejected"})
KNOWN_MESSAGE_ACK_REASONS = frozenset({"no_receiver", "run_ended", "not_waiting", "duplicate"})
#: 되살리지 못한 실행의 사유 (ADR-0054 — C5 `run_status`의 `error_code`로도 간다).
KNOWN_RESTORE_REFUSALS = frozenset({"runner_restarted", "runner_version_changed", "snapshot_unreadable"})
#: `POST /api/v1/messages`의 응답 `delivered_to`.
KNOWN_MESSAGE_TARGETS = frozenset({"run", "new_job"})

__all__ = [  # C4·C2가 소유한 것 — 여기서는 다시 내보내기만 (C12 「C4와 같다」)
    "AdminKey",
    "ApprovalAck",
    "ApprovalDispatch",
    "DeploymentResult",
    "ExtensionState",
    "JobAck",
    "JobDispatch",
    "Readiness",
]


class RunnerVersions(ContractModel):
    """C4 `Versions`와 **칸이 다르다** — 서버에는 Worker가 없다."""

    server_runner: str
    core: str


class ServerRunnerRegisterRequest(SchemaVersioned):
    """`POST /api/v1/server-runner/register`.

    `server_runner_id`를 본문에 넣지 않는다 — **신원은 Center API 키로 정한다** (C4와 같다).
    키 묶기도 같다: 키 하나 ↔ 서버 하나 ↔ 실행기 행 하나.
    """

    machine_id: MachineId
    name: str
    os: str
    versions: RunnerVersions
    #: 이 실행기가 한 번에 도는 실행 수의 상한. 설정값이라 **실행기가 정한다**.
    max_concurrency: int = Field(default=DEFAULT_MAX_CONCURRENCY, ge=1)
    extensions: list[ExtensionState] = Field(default_factory=list)


class ServerRunnerRegisterResponse(ContractModel):
    server_runner_id: ServerRunnerId
    admin_keys: list[AdminKey] = Field(default_factory=list)
    heartbeat_interval_s: int = DEFAULT_HEARTBEAT_S
    server_time: Timestamp
    #: 이 키의 만료 (C7). **없으면 「만료 없음」**이고 「모른다」가 아니다 (C4와 같다).
    key_expires_at: Timestamp | None = None


class Capacity(ContractModel):
    """자리 셈. **`running`은 기다리는 실행을 뺀 수**다 (ADR-0054 §5).

    Center가 빈자리를 `max - running`으로 계산한다 (C12 §Center가 작업을 나누는 규칙).
    """

    max: int = Field(ge=1)
    running: int = Field(ge=0)


class RunningRun(ContractModel):
    """지금 도는 실행 하나 — 스레드를 쥐고 있다."""

    run_id: str
    bpm_process_id: str
    version: str
    node_id: str | None = None
    started_at: Timestamp
    job_id: str | None = None


class WaitingRun(ContractModel):
    """상태만 남고 **일꾼을 놓은** 실행 (ADR-0054 §1·§3).

    `waiting_for`에 따라 **짝이 되는 칸이 있어야 한다** — 결재는 `request_id`, 메시지는
    `message_name`, 타이머는 `until`, **PC 위임은 `job_id`**. `validate_heartbeat()`가 그것을 본다.
    """

    run_id: str
    bpm_process_id: str
    version: str
    waiting_for: str  # 열린 문자열 (KNOWN_WAITING_FOR)
    request_id: str | None = None
    message_name: str | None = None
    correlation: Any = None
    #: 타이머가 울릴 시각. **절대 시각이라 재시작을 넘어 간다** (ADR-0054 §1·§6).
    until: Timestamp | None = None
    #: **PC 위임**으로 기다릴 때 그 작업 (ADR-0062). 짝 칸이라 그때는 비울 수 없다.
    job_id: str | None = None
    since: Timestamp


class MessageAck(ContractModel):
    """내려온 메시지 하나를 어떻게 했나 (C12 §메시지)."""

    message_id: str
    accepted: bool
    run_id: str | None = None
    reason: str | None = None  # 열린 문자열 (KNOWN_MESSAGE_ACK_REASONS)


class DelegationAck(ContractModel):
    """위임 결과 하나를 **받았다** (C12 §PC 위임, ADR-0062).

    받으면 Center가 그 값을 지운다 — 업무 값이 Center에 남는 시간을 줄인다 (원칙 6의 예외는
    **좁게** 쓴다). ack가 오기 전에는 매번 다시 내려온다 (작업·메시지와 같다).
    """

    job_id: str
    accepted: bool = True


class DelegationResult(ContractModel):
    """끝난 PC 위임 하나 (C12 §PC 위임) — 하트비트 응답으로 내려간다.

    **`outputs`가 업무 값이다** — 원칙 6의 명시한 예외이고, 올라오는 것은 그 Bot이 **선언한
    `outputs`만**이다 (C1). `state`가 `finished`가 아니면 실행기가 오류 경계로 넘긴다.
    """

    job_id: str
    #: 맡긴 **서버 실행** (어느 실행으로 돌려줄지 — C3 소유로 대조한 그 실행이다).
    run_id: str
    state: str  # 열린 문자열 (KNOWN_DELEGATION_STATES)
    #: PC 실행이 돌려준 값. 실패·거절이면 비어 있다.
    outputs: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None
    #: PC 쪽 실행 (CON-01에서 오갈 수 있게 — C3 `parent_run_id`의 반대 방향).
    pc_run_id: str | None = None


class ServerRunnerHeartbeatRequest(SchemaVersioned):
    """`POST /api/v1/server-runner/heartbeat` — 기본 10초.

    **`restored[]`는 재시작 직후 첫 하트비트에만** 싣는다 — 저장소에서 되살려 **정말 이어 가는**
    실행만이다. 되살리지 못한 것은 여기 넣지 않고 C5 `run_status`에 사유와 함께 적는다
    (ADR-0054 §4 — `runner_restarted`·`runner_version_changed`).
    """

    status: str  # 열린 문자열 (KNOWN_RUNNER_STATUSES)
    capacity: Capacity
    running: list[RunningRun] = Field(default_factory=list)
    waiting: list[WaitingRun] = Field(default_factory=list)
    versions: RunnerVersions | None = None  # 바뀌었을 때만
    readiness: list[Readiness] = Field(default_factory=list)  # 바뀌었을 때만
    job_acks: list[JobAck] = Field(default_factory=list)
    approval_acks: list[ApprovalAck] = Field(default_factory=list)
    message_acks: list[MessageAck] = Field(default_factory=list)
    delegation_acks: list[DelegationAck] = Field(default_factory=list)
    deployment_results: list[DeploymentResult] = Field(default_factory=list)
    extensions: list[ExtensionState] = Field(default_factory=list)  # 바뀌었을 때만
    restored: list[str] = Field(default_factory=list)
    unsent_events: int | None = None


class MessageDispatch(ContractModel):
    """내려온 메시지 하나 — 기다리는 실행을 깨우거나 메시지 시작으로 새 실행을 만든다."""

    message_id: str
    name: str
    correlation: Any = None
    payload: dict[str, Any] = Field(default_factory=dict)
    received_at: Timestamp


class ServerRunnerHeartbeatResponse(ContractModel):
    """지시는 모두 여기 실려 내려온다 (ADR-0007).

    `deployments`는 **저장된 JSON 그대로** 다룬다 — C2 봉투를 모델로 바꿔 다시 직렬화하면
    서명이 깨진다 (C4와 같은 이유로 `dict`다).

    `jobs`는 **빈자리만큼만** 실린다 (C12 §Center가 작업을 나누는 규칙).
    """

    server_time: Timestamp
    next_heartbeat_s: int = DEFAULT_HEARTBEAT_S
    deployments: list[dict[str, Any]] = Field(default_factory=list)
    admin_keys: list[AdminKey] | None = None  # 생략 = 그대로
    jobs: list[JobDispatch] = Field(default_factory=list)
    cancel_jobs: list[str] = Field(default_factory=list)
    approvals: list[ApprovalDispatch] = Field(default_factory=list)
    messages: list[MessageDispatch] = Field(default_factory=list)
    #: 끝난 **PC 위임**의 결과. ack가 올 때까지 다시 싣는다 (ADR-0062).
    delegations: list[DelegationResult] = Field(default_factory=list)
    #: 참이면 **새 작업을 받지 않는다** (CON-12 「일시 중지」). 도는 것은 끝까지 간다.
    paused: bool = False
    #: 이 키의 만료 (C7). **주기마다 싣는다** (C4와 같다).
    key_expires_at: Timestamp | None = None


# ─────────────────────────── 메시지 (외부 시스템 → Center) ───────────────────────────


class MessageRequest(SchemaVersioned):
    """`POST /api/v1/messages` — 연동용 키 또는 관리자 토큰.

    `correlation`이 없으면 **메시지 시작만** 된다 (기다리는 실행을 찾을 열쇠가 없다).
    """

    name: str
    correlation: Any = None
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None


class DelegationRequest(SchemaVersioned):
    """`POST /api/v1/server-runner/delegations` — **PC 위임을 맡긴다** (ADR-0062).

    **멱등 키와 `requested_by`는 본문에서 받지 않는다** — Center가 `run_id`·`node_id`·
    `node_instance`로 짓는다(`dlg_…`). 부르는 쪽마다 짓는 규칙이 갈라지면 되살린 실행이
    **같은 자리에서 작업을 두 번 만든다**.
    """

    #: 맡기는 서버 실행. **보낸 키의 실행이어야 한다** (C3 소유와 같은 대조).
    run_id: str
    node_id: str
    node_instance: int = 1
    #: **반복 차례**(0부터) — 반복이 붙은 호출일 때만 (ADR-0082). 멱등 키에 들어간다:
    #: 엔진은 반복 중에 `node_instance`를 올리지 않으므로 이것이 없으면 2건째부터 같은 작업이다.
    loop_index: int | None = Field(default=None, ge=0)
    bpm_process_id: str
    #: 비우면 **배포된 판** (작업 지시와 같은 규칙 — 둘 이상이면 422).
    version: str | None = None
    #: 적으면 **그 PC로만** (그림의 `bot_ui` 식을 실행기가 값으로 푼 것). 서버 대상이면 422.
    bot_ui: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)


class DelegationResponse(ContractModel):
    """맡긴 결과 — **201이 새 작업, 200이 이미 만든 것**이다."""

    job_id: str
    #: 대상 종류 — 대상 패키지의 `run_location`이 정한다 (ADR-0082). `bot_ui` | `server_runner`.
    target_type: str = "bot_ui"
    #: Center가 고른 PC (또는 요청이 지정한 PC). **서버 대상이면 없다** — 실행기는 내려줄 때 고른다.
    bot_ui_id: str | None = None
    state: str  # C5 작업 상태 (열린 문자열)


class MessageResponse(ContractModel):
    message_id: str
    delivered_to: str  # 열린 문자열 (KNOWN_MESSAGE_TARGETS)
    run_id: str | None = None
    job_id: str | None = None


# ─────────────────────────── 운영 API (CON-12, 관리자 토큰) ───────────────────────────


class ServerRunnerInfo(ContractModel):
    """`GET /api/v1/server-runners` 한 줄 (CON-12).

    `queued`는 **Center의 대기열**이다 — 실행기가 보내는 값이 아니라 Center가 센 것이다
    (C12 — 서버 쪽 대기열은 Center가 가진다).
    """

    server_runner_id: ServerRunnerId
    name: str
    os: str
    status: str  # 열린 문자열 (KNOWN_RUNNER_STATUSES)
    online: bool
    paused: bool = False
    capacity: Capacity
    running: list[RunningRun] = Field(default_factory=list)
    waiting: list[WaitingRun] = Field(default_factory=list)
    queued: int = 0
    #: 배포된 서버 Bot별 준비 상태 — 실행기가 보고한 것 그대로 (CON-12 「Bot별 상한」).
    readiness: list[Readiness] = Field(default_factory=list)
    #: 이 서버에 깔린 확장 (C12 — 등록·하트비트가 보고한다).
    extensions: list[ExtensionState] = Field(default_factory=list)
    #: **Center가 쌓아 둔** 최근 배치 결정 (C4·C12 — 한 주기만 올라오는 값이라 받아 둔다).
    deployment_results: list[DeploymentResult] = Field(default_factory=list)
    versions: RunnerVersions | None = None
    last_heartbeat_at: Timestamp | None = None
    registered_at: Timestamp | None = None
    #: 이 실행기가 쓰는 Center API 키의 **앞자리**. 원문·해시는 주지 않는다 (C7 `BotUiKey`와 같은 결).
    #: 만료만 보이면 운영자가 CON-11의 어느 줄인지 못 찾는다 — 키가 여럿이면 만료일이 겹친다.
    key_prefix: str | None = None
    key_expires_at: Timestamp | None = None
    unsent_events: int | None = None


# ─────────────────────────── 검사 ───────────────────────────

#: `waiting_for` → 그 줄에 반드시 있어야 하는 칸 (C12 `waiting[]`).
WAITING_REQUIRES = {
    "approval": "request_id",
    "message": "message_name",
    "timer": "until",
    WAITING_DELEGATION: "job_id",
}


def free_slots(capacity: Capacity, *, paused: bool = False) -> int:
    """이 실행기에 실어 보낼 수 있는 작업 수 (C12 §Center가 작업을 나누는 규칙 2).

    **기다리는 실행은 세지 않는다** — `capacity.running`이 이미 그것을 뺀 수다 (ADR-0054 §5).
    """
    if paused:
        return 0
    return max(0, capacity.max - capacity.running)


def validate_heartbeat(request: ServerRunnerHeartbeatRequest) -> list[str]:
    """하트비트 본문이 **스스로 앞뒤가 맞나**. 문제 설명을 모아 돌려준다 (빈 목록이면 맞다).

    보내는 쪽(실행기)과 받는 쪽(Center)이 **같은 함수**로 본다 — 베끼면 두 규칙이 갈라진다.
    열린 문자열은 **모르는 값으로 거부하지 않는다**(C4와 같다). 여기서 보는 것은 모양이다.
    """
    problems: list[str] = []

    if request.capacity.running > request.capacity.max:
        problems.append(
            f"capacity.running({request.capacity.running})이 max({request.capacity.max})보다 크다"
        )
    if len(request.running) != request.capacity.running:
        problems.append(
            f"capacity.running({request.capacity.running})과 running[] 길이"
            f"({len(request.running)})가 다르다"
        )

    running_ids = [r.run_id for r in request.running]
    waiting_ids = [w.run_id for w in request.waiting]
    both = sorted(set(running_ids) & set(waiting_ids))
    if both:
        # 쥐면서 놓을 수는 없다 — 자리 셈이 틀어진다.
        problems.append(f"running[]과 waiting[]에 같이 있는 실행이다: {', '.join(both)}")
    for where, ids in (("running", running_ids), ("waiting", waiting_ids)):
        twice = sorted({i for i in ids if ids.count(i) > 1})
        if twice:
            problems.append(f"{where}[]에 같은 실행이 두 번 있다: {', '.join(twice)}")

    for found in request.waiting:
        needed = WAITING_REQUIRES.get(found.waiting_for)
        if needed and getattr(found, needed) is None:
            problems.append(
                f"{found.run_id}는 waiting_for={found.waiting_for}인데 {needed}가 없다"
            )
    return problems


def restorable(
    snapshot_process_id: str,
    snapshot_version: str,
    *,
    installed_process_id: str | None,
    installed_version: str | None,
    had_wait: bool,
) -> tuple[bool, str | None]:
    """되살려도 되나 — `(된다, 안 되는 사유)` (ADR-0054 §2·§4).

    판정을 **계약에 둔다**: 실행기와 Center가 같은 말을 써야 CON-12의 「왜 안 이어졌나」가
    실행 기록의 `error_code`와 맞는다.

    - 그림이 없거나 **판이 다르면** 되살리지 않는다 — 없는 노드를 밟는다.
    - **기다린 적이 없는 실행**은 되살리지 않는다 — 처음부터 다시 돌리면 메일·웹훅을 두 번
      보낸다 (멱등이 아니다). 다시 돌릴지는 운영자가 작업을 다시 내 정한다.
    """
    if installed_process_id is None or installed_version is None:
        return False, "runner_version_changed"
    if (installed_process_id, installed_version) != (snapshot_process_id, snapshot_version):
        return False, "runner_version_changed"
    if not had_wait:
        return False, "runner_restarted"
    return True, None


def message_matches(waiting: WaitingRun, *, name: str, correlation: Any = None) -> bool:
    """그 메시지를 **이 실행이 받나** (C12 §메시지).

    규칙은 **엔진의 것을 그대로 옮긴 것이다** (C14 메시지 상관, `Engine.message_target()`) —
    이름이 같고, **둘 중 한쪽이라도 상관 키가 없으면** 맞는 것으로 본다. 양쪽에 있으면 같아야
    한다. 두 함수가 **같은 답을 내는지 시험이 대조한다** — 어긋나면 Center가 「전달했다」고 하고
    실행기가 `no_receiver`로 돌려보낸다.

    **「상관 키 없는 메시지는 기다리는 실행을 찾지 않는다」는 여기 없다** (C12 §메시지) — 그것은
    *고를 것인가*의 규칙이라 부르는 쪽(Center)에 있다. 여기 넣으면 엔진과 규칙이 갈라져,
    Center가 고른 실행에 실행기가 넣지 못하는 일이 생긴다.
    """
    if waiting.waiting_for != "message" or waiting.message_name != name:
        return False
    if waiting.correlation is None or correlation is None:
        return True
    return bool(waiting.correlation == correlation)


def pick_message_target(
    waiting: Sequence[WaitingRun], *, name: str, correlation: Any = None
) -> WaitingRun | None:
    """받을 실행 하나 — 여럿이면 **가장 오래 기다린 것** (C12 §메시지).

    한 메시지는 **한 실행에만** 간다. 오래 기다린 쪽부터 주는 것은 사람이 보는 순서와 같다
    (CON-12 「기다리는 실행」이 기다린 시간으로 줄을 세운다).
    """
    found = [one for one in waiting if message_matches(one, name=name, correlation=correlation)]
    if not found:
        return None
    return sorted(found, key=lambda one: (one.since, one.run_id))[0]


def pick_jobs(
    queued: Sequence[tuple[str, str]],
    *,
    slots: int,
    running_per_bot: dict[str, int],
    per_bot_limit: dict[str, int] | None = None,
) -> tuple[list[str], dict[str, str]]:
    """대기열에서 실어 보낼 작업을 고른다 (C12 §Center가 작업을 나누는 규칙 1~3).

    `queued`는 들어온 순서의 `(job_id, bpm_process_id)`다. **BPM 프로세스별 상한을 넘는 작업은
    건너뛰고 다음 것을 본다** — 막아 세우면 상한에 걸린 Bot 하나가 대기열 전체를 멈춘다.

    돌려주는 것은 `(고른 job_id 목록, 건너뛴 job_id → 사유)`다. 사유는 CON-12 「대기 이유」가
    보이는 값이고 지금은 `per_bot_limit` 하나다.
    """
    limits = per_bot_limit or {}
    taken: list[str] = []
    skipped: dict[str, str] = {}
    counts = dict(running_per_bot)
    for job_id, bot in queued:
        if len(taken) >= slots:
            break
        cap = limits.get(bot, DEFAULT_PER_BOT_CONCURRENCY)
        if counts.get(bot, 0) >= cap:
            skipped[job_id] = "per_bot_limit"
            continue
        taken.append(job_id)
        counts[bot] = counts.get(bot, 0) + 1
    return taken, skipped


__all__ += [
    "DEFAULT_HEARTBEAT_S",
    "DEFAULT_MAX_CONCURRENCY",
    "DEFAULT_PER_BOT_CONCURRENCY",
    "KNOWN_DELEGATION_STATES",
    "KNOWN_MESSAGE_ACK_REASONS",
    "KNOWN_MESSAGE_TARGETS",
    "KNOWN_RESTORE_REFUSALS",
    "KNOWN_RUNNER_STATUSES",
    "KNOWN_WAITING_FOR",
    "OFFLINE_AFTER_S",
    "WAITING_DELEGATION",
    "WAITING_REQUIRES",
    "Capacity",
    "DelegationAck",
    "DelegationRequest",
    "DelegationResponse",
    "DelegationResult",
    "MessageAck",
    "MessageDispatch",
    "MessageRequest",
    "MessageResponse",
    "RunnerVersions",
    "RunningRun",
    "ServerRunnerHeartbeatRequest",
    "ServerRunnerHeartbeatResponse",
    "ServerRunnerId",
    "ServerRunnerInfo",
    "ServerRunnerRegisterRequest",
    "ServerRunnerRegisterResponse",
    "WaitingRun",
    "free_slots",
    "message_matches",
    "pick_message_target",
    "pick_jobs",
    "restorable",
    "validate_heartbeat",
]
