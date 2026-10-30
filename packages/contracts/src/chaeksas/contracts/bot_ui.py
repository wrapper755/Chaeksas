"""C4. Center API: PC 실행기 등록·하트비트.

단일 원본: `docs/03-contracts/C4-bot-ui-center.md`.

두 가지가 계약으로 강제된다.

- **실행 자리는 최대 1건.** `current_run`이 단일 객체라 2건을 표현할 수 없다 (ADR-0014).
- **상태 값은 열린 문자열.** 모르는 값 하나로 하트비트 전체를 422로 거부하지 않는다
  (프로토타입 결함). 알려진 값은 `KNOWN_*`로만 둔다.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from chaeksas.contracts._base import ContractModel, SchemaVersioned, Timestamp
from chaeksas.contracts.bpmn_ext import VirtualWorkerIdentity
from chaeksas.contracts.enrollment import PublicKey, RotatedKey
from chaeksas.contracts.signing import AdminKey

#: 하트비트 기본 간격과 온라인 판정 (CON-03).
DEFAULT_HEARTBEAT_S = 30
ONLINE_WITHIN_S = 90

BotUiId = Annotated[str, Field(pattern=r"^bui_[0-9a-f]{8}$")]
MachineId = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
"""PC 고유값의 SHA-256. **원값은 보내지 않는다.**"""

__all__ = [  # AdminKey는 C2가 소유한다 — 여기서는 다시 내보내기만 (C4 `admin_keys`)
    "AdminKey",
]

# 알려진 값 (모두 열린 문자열).
KNOWN_BOT_UI_STATUSES = frozenset(
    {"idle", "running", "waiting_approval", "waiting_confirmation", "selector_registration", "error"}
)
KNOWN_RUN_STATES = frozenset({"running", "waiting_approval", "waiting_confirmation"})
#: 실행이 시작된 까닭. **`delegation`은 PC 위임으로 받은 작업**이다
#: ([ADR-0062](../decisions/0062-pc-delegation.md) — 예약을 풀었다). C3와 같은 목록이다.
KNOWN_SOURCES = frozenset(
    {"job", "manual", "watch", "schedule", "message", "delegation"}
)
KNOWN_WORKER_STATES = frozenset({"running", "off", "restarting", "stopped"})
KNOWN_WORKER_SESSIONS = frozenset({"idle", "bot", "studio", "selector_registration"})
KNOWN_JOB_ACK_RESULTS = frozenset({"queued", "started", "rejected", "expired", "cancelled", "cancel_refused"})
KNOWN_JOB_ACK_REASONS = frozenset(
    {"queue_full", "no_deployment", "not_ready", "bot_ui_shutdown", "server_location",
     "cancelled_on_pc", "already_started"}
)
KNOWN_DEPLOYMENT_RESULTS = frozenset({"applied", "rejected"})
KNOWN_APPROVAL_STATES = frozenset({"answered", "expired", "withdrawn"})


class BuildStamp(ContractModel):
    """묶은 산출물의 표시 (C4 `versions.build`, [ADR-0067](../../../../../docs/decisions/0067-build-stamp.md)).

    **있으면 묶은 것에서 돈다.** 없으면 묶지 않은 것(소스·`uv sync`)이다 — 「모른다」가 아니다.
    판 자체는 `Versions.bot_ui`에 있다(빌드가 찍은 것).
    """

    commit: str
    built_at: Timestamp


class Versions(ContractModel):
    bot_ui: str
    core: str
    worker: str | None = None
    build: BuildStamp | None = None


class ExtensionState(ContractModel):
    """설치된 확장 하나 (C13).

    **`enabled`와 `off`는 다른 것을 말한다** ([ADR-0043](../../../../../docs/decisions/0043-turned-off-extensions.md)):
    `off`는 **사람이 껐다**(멀쩡한데 일부러 안 쓴다), `enabled=false`인데 `off`가 아니면 **흠이
    있다**(정의·판이 맞지 않는다). 화면이 「꺼짐」과 「호환 안 됨」을 가르는 자리다. 뜻을 바꾸지
    않고 칸을 더한 것이라 옛 PC 실행기가 보낸 값(`off` 없음)도 그대로 읽힌다.
    """

    id: str
    version: str
    definition_hash: str | None = None
    enabled: bool = True
    off: bool = False


class Runtimes(ContractModel):
    browsers: list[str] = Field(default_factory=list)
    desktop_backend: str | None = None
    extensions: list[ExtensionState] = Field(default_factory=list)


class RegisterRequest(SchemaVersioned):
    """`POST /api/v1/bot-ui/register` — 처음 한 번, 그리고 이름·버전이 바뀔 때.

    `bot_ui_id`를 본문에 넣지 않는다. **신원은 Center API 키로 정한다.**
    """

    machine_id: MachineId
    name: str
    os: str
    versions: Versions
    runtimes: Runtimes | None = None
    #: X25519 공개키 (C4 §키 회전). 보내면 Center가 이 PC의 키를 **회전해 준다**. 등록 요청으로
    #: 들어온 PC는 Center가 이미 안다.
    public_key: PublicKey | None = None


class EnrollRequest(RegisterRequest):
    """`POST /api/v1/bot-ui/enroll` — 키가 없을 때 **등록 요청** (C4 §등록 요청과 승인, 인증 없음).

    `RegisterRequest`와 같은 칸에 `public_key`가 **필수**다 — 승인된 키를 이것으로 봉해 내려 준다.
    """

    public_key: PublicKey


class RegisterResponse(ContractModel):
    bot_ui_id: BotUiId
    admin_keys: list[AdminKey] = Field(default_factory=list)
    heartbeat_interval_s: int = DEFAULT_HEARTBEAT_S
    server_time: Timestamp
    #: 이 키의 만료 (C7). **없으면 「만료 없음」**이고 「모른다」가 아니다 — 만료일은
    #: Center만 알아서 내려 준다 (BUI-05 「Center API 키 만료 임박」).
    key_expires_at: Timestamp | None = None


class CurrentRun(ContractModel):
    """실행 자리 1건 (ADR-0014)."""

    run_id: str
    bpm_process_id: str
    version: str
    node_id: str | None = None
    state: str  # 열린 문자열 (KNOWN_RUN_STATES)
    started_at: Timestamp
    source: str  # 열린 문자열 (KNOWN_SOURCES)
    job_id: str | None = None


class QueueItem(ContractModel):
    queue_id: str
    source: str
    bpm_process_id: str
    version: str | None = None
    job_id: str | None = None
    requested_at: Timestamp
    expires_at: Timestamp | None = None


class Queue(ContractModel):
    """대기열. `items`는 순서대로."""

    max: int
    items: list[QueueItem] = Field(default_factory=list)


class WorkerState(ContractModel):
    """Worker 프로세스 상태. `off`는 "필요할 때 시작, 아직 안 띄움"."""

    state: str  # 열린 문자열 (KNOWN_WORKER_STATES)
    version: str | None = None
    restarts: int = 0
    session: str | None = None  # 열린 문자열 (KNOWN_WORKER_SESSIONS)
    reserved_for: str | None = None  # C10 예약 run_id


class Readiness(ContractModel):
    """설치된 BPM 프로세스 하나의 준비 상태."""

    bpm_process_id: str
    version: str
    ready: bool
    missing_key_refs: list[str] = Field(default_factory=list)
    blocked: list[str] = Field(default_factory=list)


class JobAck(ContractModel):
    """이번 주기에 처리한 작업 하나."""

    job_id: str
    result: str  # 열린 문자열 (KNOWN_JOB_ACK_RESULTS)
    position: int | None = None  # queued일 때 대기열 순번
    run_id: str | None = None  # started일 때
    reason: str | None = None  # rejected·cancel_refused일 때 (KNOWN_JOB_ACK_REASONS)
    #: **PC 위임이 돌려주는 값** (C12 §PC 위임, [ADR-0062](../decisions/0062-pc-delegation.md)).
    #: 원칙 6의 **명시한 예외**라 좁게 쓴다: **그 BPM 프로세스가 선언한 `outputs`만**(C1), **끝났을
    #: 때만**(`finished`·`failed`…), 그리고 **위임으로 받은 작업만**이다. 평범한 작업은 비운다 —
    #: Center는 위임이 아닌 작업의 `outputs`를 **버린다**.
    outputs: dict[str, Any] = Field(default_factory=dict)


class ApprovalAck(ContractModel):
    request_id: str
    accepted: bool
    reason: str | None = None


class DeploymentResult(ContractModel):
    """배포 적용 결정 (CON-03 「최근 배치 결정」). 실행이 아니므로 C3로 보내지 않는다."""

    deployment_id: str
    bpm_process_id: str
    version: str
    result: str  # 열린 문자열 (KNOWN_DEPLOYMENT_RESULTS)
    at: Timestamp
    reason: str | None = None


class HeartbeatRequest(SchemaVersioned):
    """`POST /api/v1/bot-ui/heartbeat` — 30초마다 (응답의 `next_heartbeat_s`를 따름)."""

    status: str  # 열린 문자열 (KNOWN_BOT_UI_STATUSES)
    current_run: CurrentRun | None  # 필수 필드이지만 비어 있을 수 있다 (실행 자리 없음)
    queue: Queue
    worker: WorkerState
    versions: Versions | None = None  # 바뀌었을 때만
    readiness: list[Readiness] = Field(default_factory=list)
    job_acks: list[JobAck] = Field(default_factory=list)
    deployment_results: list[DeploymentResult] = Field(default_factory=list)
    extensions: list[ExtensionState] = Field(default_factory=list)
    approval_acks: list[ApprovalAck] = Field(default_factory=list)
    unsent_events: int | None = None


class JobDispatch(ContractModel):
    """내려온 작업 하나. ack가 올 때까지 매번 실린다."""

    job_id: str
    bpm_process_id: str
    version: str | None = None  # 없으면 배포된 버전
    inputs: dict[str, Any] = Field(default_factory=dict)
    requested_by: str  # 사람. 예약: `server_bot:<run_id>` (PC 위임)
    requested_at: Timestamp
    expires_at: Timestamp | None = None
    note: str | None = None
    #: **가상 직원 신원** — 그 BPM 프로세스가 가상 직원의 접수 BPM 프로세스이면 Center가 내려줄 때 붙인다 (C12,
    #: ADR-0098). 저장하지 않는다. 접수 BPM 프로세스는 서버에서만 돌아 **PC 실행기에는 오지 않는다**.
    virtual_worker: VirtualWorkerIdentity | None = None


class ApprovalDispatch(ContractModel):
    """답이 정해진 결재 (C6)."""

    request_id: str
    state: str  # 열린 문자열 (KNOWN_APPROVAL_STATES)
    answer: Any = None
    answered_by: str | None = None
    answered_at: Timestamp | None = None
    answered_via: str | None = None  # 대리 답이면 그 키 이름 (C6, ADR-0081) — C3 human_answered에 남긴다


class HeartbeatResponse(ContractModel):
    """하트비트 응답 — 지시는 모두 여기 실려 내려온다 (ADR-0007).

    `deployments`는 **저장된 JSON 그대로** 다룬다. C2 봉투를 모델로 바꿔 다시 직렬화하면
    `canonical_json`이 달라져 서명이 깨지므로, 일부러 `dict`로 둔다.
    """

    server_time: Timestamp
    next_heartbeat_s: int = DEFAULT_HEARTBEAT_S
    deployments: list[dict[str, Any]] = Field(default_factory=list)
    admin_keys: list[AdminKey] | None = None  # 생략 = 그대로
    jobs: list[JobDispatch] = Field(default_factory=list)
    cancel_jobs: list[str] = Field(default_factory=list)
    approvals: list[ApprovalDispatch] = Field(default_factory=list)
    disabled: bool = False
    #: 만료 14일 전부터 새 키 (C4 §키 회전). 새 키로 첫 요청이 올 때까지 주기마다 싣는다.
    rotated_key: RotatedKey | None = None
    #: 이 키의 만료 (C7). **주기마다 싣는다** — 「생략 = 그대로」로 두면 운영자가 기간을
    #: 늘려 줘도 PC 실행기가 그것을 모른다.
    key_expires_at: Timestamp | None = None
