"""C10. Worker 로컬 API — **UI 자동화 확장이 소유한다** (ADR-0018).

단일 원본: `docs/03-contracts/C10-worker-local-api.md`.

이 경계의 규칙 넷이 모델에 그대로 박혀 있다.

- **부르는 쪽은 시맨틱 키로만 말한다.** 셀렉터(물리 로케이터)는 이 경계를 넘지 않는다 —
  예외는 셀렉터 등록(C10 §5)뿐이다.
- **토큰은 파일로만 넘긴다** (명령줄은 프로세스 목록에 뜬다). 사용 토큰과 관리 토큰 둘이고,
  Worker를 다시 띄우면 둘 다 바뀐다.
- **세션은 한 번에 하나** (ADR-0014 §4) — 다른 쪽이 열면 409 `worker_busy`.
- **전환(`escalated`)은 오류가 아니다** — 사람 확인으로 넘어갈 거리다.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import Field

from chaeksas.contracts._base import ContractModel, SchemaVersioned, Timestamp

#: 주소는 바꿀 수 없다 (C10 §전송) — 포트만 바꾼다.
LOCAL_HOST = "127.0.0.1"
DEFAULT_PORT = 8899
PORT_ENV = "CHK_WORKER__LOCAL_API__PORT"

#: 토큰 파일 (사용자 데이터 폴더, 현재 사용자만 읽는다).
TOKEN_FILE = "worker.token"
ADMIN_TOKEN_FILE = "worker.admin.token"
TOKEN_HEADER = "X-CHK-Local-Token"
ADMIN_HEADER = "X-CHK-Local-Admin"
SESSION_HEADER = "X-CHK-Session"

#: 세션에 요청이 없으면 Worker가 닫는다 (부르는 쪽이 죽어도 세션이 남지 않게).
SESSION_IDLE_S = 600
SESSION_IDLE_ENV = "CHK_WORKER__SESSION_IDLE_S"
#: 스텝 하나의 기본 시간 제한.
STEP_TIMEOUT_S = 60

#: 누가 세션을 쥐나 (열린 문자열).
CALLER_BOT = "bot"
CALLER_STUDIO = "studio"
CALLER_REGISTRATION = "selector_registration"
KNOWN_CALLERS = frozenset({CALLER_BOT, CALLER_STUDIO, CALLER_REGISTRATION})

#: 조작하는 동작과 **읽기만 하는** 동작 (읽기에 `value`를 주면 422).
MUTATING_ACTIONS = ("fill", "click", "press", "select")
READING_ACTIONS = ("read", "read_table", "read_options", "read_selection")
KNOWN_ACTIONS = frozenset(MUTATING_ACTIONS) | frozenset(READING_ACTIONS)

#: UI 세션 한 번의 결말 (C3 `ui_session.result`와 같은 말).
RESULT_SUCCESS = "success"
RESULT_ESCALATED = "escalated"
RESULT_FAILED = "failed"

#: 오류 코드 (C10 §오류). 열린 문자열이지만 아는 것은 여기 둔다.
TOKEN_INVALID = "token_invalid"
SESSION_SECRET_INVALID = "session_secret_invalid"
ADMIN_ONLY = "admin_only"
SESSION_NOT_FOUND = "session_not_found"
WORKER_BUSY = "worker_busy"
RESERVED = "reserved"
INSTRUCTION_NOT_ALLOWED = "instruction_not_allowed"
VALUE_REQUIRED = "value_required"
VALUE_NOT_ALLOWED = "value_not_allowed"
UNKNOWN_SEMANTIC_KEY = "unknown_semantic_key"
UI_AUTOMATION_UNREACHABLE = "ui_automation_unreachable"
BROWSER_UNAVAILABLE = "browser_unavailable"
SESSION_LOCKED = "session_locked"
SCHEMA_UNSUPPORTED = "schema_unsupported"

#: **다시 불러 볼 만한** 것 (잠금 화면은 풀릴 수 있다).
RETRYABLE_CODES = frozenset({SESSION_LOCKED, UI_AUTOMATION_UNREACHABLE})


class Caller(ContractModel):
    """세션을 여는 쪽. `selector_registration`이면 실행 필드는 비운다."""

    type: str  # KNOWN_CALLERS (열린 문자열)
    run_id: str | None = None
    node_id: str | None = None
    node_instance: int = 1
    attempt: int = 1
    bpm_process_id: str | None = None
    version: str | None = None


class SessionRequest(SchemaVersioned):
    """`POST /v1/sessions` — 세션 열기.

    `service_key`는 **값**이다 (부르는 쪽이 키 참조를 풀어 넣는다, ADR-0013). Worker는 세션
    동안 메모리에만 두고 디스크·로그에 남기지 않는다.
    """

    SCHEMA: ClassVar[int] = 1

    caller: Caller
    mode: str  # autonomous | deterministic
    #: `<run_id>:<node_id>:<node_instance>:<attempt>` (등록이면 `reg_<hex8>`).
    business_key: str
    page_id: str | None = None
    start_url: str | None = None
    browser_profile: str | None = None
    headed: bool = False
    heal: bool = True
    service_key: str | None = None


class SessionInfo(ContractModel):
    """열린 세션 하나. `session_secret`은 **연 쪽만** 안다."""

    session_id: str
    session_secret: str
    page_id: str | None = None
    current_url: str | None = None
    plan_source: str = "server"  # server | cache
    steps_run: int = 0
    #: 성공한 **조작** 스텝 수 — Worker가 다시 떴을 때 다시 해도 되는지 가른다 (C10 §3).
    mutating_steps_ok: int = 0
    last_step: dict[str, Any] | None = None


class StepRequest(ContractModel):
    """스텝 하나. `semantic_key`와 `instruction`은 **둘 중 하나만**."""

    semantic_key: str | None = None
    #: 자율 수행에서만. 결정 수행 세션에서 보내면 422 `instruction_not_allowed`.
    instruction: str | None = None
    action: str  # KNOWN_ACTIONS
    value: Any = None
    timeout_s: int | None = None


class StepResult(ContractModel):
    """스텝 하나의 결과.

    **`escalated`는 오류가 아니다** — 자가 치유 한도를 넘어 사람 확인이 필요하다는 뜻이다.
    `data`는 읽기 결과의 구조이고 **UI 자동화 앱으로 보내지 않는다** (업무 값이다).
    """

    ok: bool
    semantic_key: str | None = None
    action: str | None = None
    text: str | None = None
    data: dict[str, Any] | None = None
    fallback_depth: int = 0
    healed: bool = False
    escalated: bool = False
    error_code: str | None = None
    error: str | None = None
    current_url: str | None = None
    duration_ms: int = 0


class SessionSummary(ContractModel):
    """세션 한 번의 요약 — 부르는 쪽이 이것으로 C3 `ui_session`을 만든다."""

    result: str = RESULT_SUCCESS  # success | escalated | failed
    steps: int = 0
    fallback_depth_max: int = 0
    healed: bool = False
    escalated: bool = False


class CloseResult(ContractModel):
    """`DELETE /v1/sessions/{id}`."""

    steps_run: int = 0
    summary: SessionSummary = Field(default_factory=SessionSummary)
    #: UI 자동화 앱에 보고를 보냈나 (`queued`면 닿지 못해 쌓아 뒀다 — C8).
    report: str = "queued"  # sent | queued


class Holder(ContractModel):
    """지금 세션을 쥔 쪽 (409 `worker_busy`의 `detail.holder`)."""

    type: str
    run_id: str | None = None
    bpm_process_id: str | None = None


class SessionBrief(ContractModel):
    """최근 세션 한 줄 (BUI-09)."""

    session_id: str
    business_key: str
    page_id: str | None = None
    result: str = RESULT_SUCCESS
    steps: int = 0
    at: Timestamp | None = None


class Health(ContractModel):
    """`GET /v1/health` — **토큰 없이도** 답한다 (기동 확인용)."""

    status: str = "ok"
    version: str = "0.1.0"
    #: `idle` 또는 지금 세션을 쥔 쪽의 종류.
    session: str = "idle"


class Status(Health):
    """`GET /v1/status` — BUI-09가 읽는다."""

    pid: int = 0
    uptime_s: float = 0.0
    reserved_for: str | None = None
    holder: Holder | None = None
    recent_sessions: list[SessionBrief] = Field(default_factory=list)
    unsent_reports: int = 0


class WorkerError(ContractModel):
    """공통 오류 본문 `{code, message, detail}`."""

    code: str
    message: str
    detail: dict[str, Any] = Field(default_factory=dict)


def business_key(run_id: str, node_id: str, node_instance: int = 1, attempt: int = 1) -> str:
    """`<run_id>:<node_id>:<node_instance>:<attempt>` (C10·C8·C3이 같은 키를 쓴다)."""
    return f"{run_id}:{node_id}:{node_instance}:{attempt}"


def check_step(request: StepRequest, *, deterministic: bool) -> str | None:
    """요청 모양 검사 — 맞지 않으면 422로 돌려줄 코드.

    **Worker와 부르는 쪽이 같은 함수를 본다** — 돌려 보고야 아는 일을 없앤다.
    """
    if request.semantic_key and request.instruction:
        return INSTRUCTION_NOT_ALLOWED
    if request.instruction and deterministic:
        # 결정 수행은 **자연어로 지시하지 않는다** (ADR-0010 — 몰래 자율로 넘어가지 않는다).
        return INSTRUCTION_NOT_ALLOWED
    if not request.semantic_key and not request.instruction:
        return UNKNOWN_SEMANTIC_KEY
    if request.action in MUTATING_ACTIONS and request.action != "click" and request.value is None:
        return VALUE_REQUIRED
    if request.action in READING_ACTIONS and request.value is not None:
        return VALUE_NOT_ALLOWED
    return None


def can_retry_whole_task(info: SessionInfo) -> bool:
    """Worker가 다시 떴을 때 **그 UI 태스크를 처음부터 다시 해도 되나** (C10 §3).

    성공한 조작 스텝이 하나라도 있으면 다시 하면 안 된다 — 같은 입력이 두 번 들어간다.
    그때는 확인(`confirmation`)으로 사람에게 넘긴다.
    """
    return info.mutating_steps_ok == 0


__all__ = [
    "ADMIN_HEADER",
    "ADMIN_ONLY",
    "ADMIN_TOKEN_FILE",
    "BROWSER_UNAVAILABLE",
    "CALLER_BOT",
    "CALLER_REGISTRATION",
    "CALLER_STUDIO",
    "DEFAULT_PORT",
    "INSTRUCTION_NOT_ALLOWED",
    "KNOWN_ACTIONS",
    "KNOWN_CALLERS",
    "LOCAL_HOST",
    "MUTATING_ACTIONS",
    "PORT_ENV",
    "READING_ACTIONS",
    "RESERVED",
    "RESULT_ESCALATED",
    "RESULT_FAILED",
    "RESULT_SUCCESS",
    "RETRYABLE_CODES",
    "SESSION_HEADER",
    "SESSION_IDLE_ENV",
    "SESSION_IDLE_S",
    "SESSION_LOCKED",
    "SESSION_NOT_FOUND",
    "SESSION_SECRET_INVALID",
    "STEP_TIMEOUT_S",
    "SCHEMA_UNSUPPORTED",
    "TOKEN_FILE",
    "TOKEN_HEADER",
    "TOKEN_INVALID",
    "UI_AUTOMATION_UNREACHABLE",
    "UNKNOWN_SEMANTIC_KEY",
    "VALUE_NOT_ALLOWED",
    "VALUE_REQUIRED",
    "WORKER_BUSY",
    "Caller",
    "CloseResult",
    "Health",
    "Holder",
    "SessionBrief",
    "SessionInfo",
    "SessionRequest",
    "SessionSummary",
    "Status",
    "StepRequest",
    "StepResult",
    "WorkerError",
    "business_key",
    "can_retry_whole_task",
    "check_step",
]
