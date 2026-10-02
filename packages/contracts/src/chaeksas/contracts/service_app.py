"""C11. 서비스 앱 공통 — 모든 서비스 앱이 지키는 계약.

단일 원본: `docs/03-contracts/C11-service-app-common.md`. 구현 뼈대는 `packages/service_kit/`.

**서비스 앱은 확장의 서버 부분이다** (ADR-0018). 부르는 쪽이 앱마다 다른 방식을 배우지 않도록
`/healthz`·`/manifest`·`POST /v1/ops/{작업}` 세 가지로 고정한다.

두 가지가 이 계약의 핵심이다.

- **키는 앱이 스스로 발급·검증한다** (ADR-0013). Center는 서비스 앱 키를 모른다.
- **수행 모드는 받는 쪽이 바꾸지 않는다** (README 원칙 7). 유일한 예외가 폴백이고, 그것도
  **호출한 키가 자율 수행을 허용할 때만** 일어나며 응답 `mode_used`로 드러난다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from pydantic import Field

from chaeksas.contracts._base import ContractModel, SchemaVersioned, Timestamp, Violation

#: 서비스 앱 API 키 — `chk_svc_` + 무작위 40자. 앞자리 16자만 화면·기록에 남긴다.
#: 앱 id를 키에 넣지 않는다 (앞자리가 키마다 달라야 구별된다).
KEY_PREFIX = "chk_svc_"
KEY_RANDOM_LEN = 40
PREFIX_LEN = 16

#: 기본값들.
DEFAULT_TIMEOUT_S = 60
MAX_BODY_MB = 1
IDEMPOTENCY_DAYS = 7

#: 수행 모드 (ADR-0010).
MODE_AUTONOMOUS = "autonomous"
MODE_DETERMINISTIC = "deterministic"
MODES = frozenset({MODE_AUTONOMOUS, MODE_DETERMINISTIC})

#: 작업 이름 규칙.
OPERATION_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"

KNOWN_CALLER_TYPES = frozenset({"bot_ui", "server_runner", "studio", "worker"})
KNOWN_CATEGORIES = frozenset({"business", "system"})
KNOWN_HEALTH_STATUSES = frozenset({"ok", "degraded"})

#: 오류 코드 (C11 「오류」 표). 부르는 쪽의 재시도 판단이 이 값에 걸려 있다.
NO_RETRY_CODES = frozenset(
    {"key_missing", "key_invalid", "key_revoked", "key_expired", "operation_not_allowed",
     "mode_not_allowed", "operation_not_found", "idempotency_conflict", "input_invalid",
     "mode_unsupported", "schema_unsupported"}
)
RETRY_CODES = frozenset({"in_progress", "rate_limited", "dependency_down", "timeout"})

OperationName = Annotated[str, Field(pattern=OPERATION_PATTERN)]


def prefix_of(key: str) -> str:
    """키 원문 → 화면·기록에 남기는 앞자리 (`chk_svc_` + 무작위 8자)."""
    return key[:PREFIX_LEN]


class HealthResponse(ContractModel):
    """`GET /healthz` — 인증 없음."""

    status: str  # KNOWN_HEALTH_STATUSES
    version: str | None = None
    reasons: list[str] = Field(default_factory=list)  # degraded면 이유 (예: neo4j_unreachable)


class Operation(ContractModel):
    """작업 하나. Studio가 이것만 보고 서비스 앱 태스크 편집기(STU-14)를 만든다."""

    name: OperationName
    description: str | None = None
    modes: list[str] = Field(default_factory=list)  # MODES
    # 기본 none — 운영에서 LLM이 몰래 개입하지 않게 (CLAUDE.md §5).
    fallback: str = "none"
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    timeout_s: int = DEFAULT_TIMEOUT_S
    server_ok: bool = True  # 서버 실행기에서 불러도 되는가 (C1 R8)

    def supports(self, mode: str) -> bool:
        return mode in self.modes


class ExtensionRef(ContractModel):
    """이 서비스 앱이 어느 확장의 서버 부분인가 (C13). 내장·사내 확장이면 넣는다."""

    id: str
    version: str


class ServiceAppManifest(SchemaVersioned):
    """`GET /manifest` — 인증 없음 (비밀이 없다). Center가 리소스 목록에 쓴다 (C7)."""

    app_id: str
    name: str
    version: str
    category: str  # KNOWN_CATEGORIES
    console_url: str
    operations: list[Operation] = Field(default_factory=list)
    extension: ExtensionRef | None = None

    def operation(self, name: str) -> Operation | None:
        return next((o for o in self.operations if o.name == name), None)


class Caller(ContractModel):
    """누가 부르는가. `type`은 열린 문자열 (KNOWN_CALLER_TYPES)."""

    type: str
    host: str | None = None
    bpm_process_id: str | None = None
    version: str | None = None


class Usage(ContractModel):
    """LLM 사용량. 이름은 C3 `llm_usage`와 같다. **금액은 넣지 않는다.**"""

    model: str
    input_tokens: int = 0
    output_tokens: int = 0


class OpRequest(SchemaVersioned):
    """`POST /v1/ops/{operation}` 요청."""

    mode: str  # MODES. **받는 쪽은 바꾸지 않는다** (원칙 7)
    run_id: str
    node_id: str
    node_instance: int = Field(ge=1)  # 이 실행에서 이 노드의 몇 번째 실행인가
    attempt: int = Field(ge=1)  # 재시도마다 +1
    call_seq: int = Field(default=1, ge=1)  # 한 노드 인스턴스·시도 안에서 여러 번 부를 때
    caller: Caller
    business_key: str | None = None  # UI 자동화처럼 세션을 잇는 키 (C10)
    input: dict[str, Any] = Field(default_factory=dict)


class OpResponse(ContractModel):
    """`POST /v1/ops/{operation}` 응답 (200)."""

    status: str = "ok"
    output: dict[str, Any] = Field(default_factory=dict)
    mode_used: str  # 폴백이 일어났을 때만 요청의 `mode`와 다르다
    replayed: bool = False  # 이전 호출 결과를 돌려준 것인가 (멱등)
    usage: Usage | None = None


class ServiceAppKey(ContractModel):
    """앱 안의 키 레코드. **원문은 저장하지 않는다** (해시만).

    `GET /v1/keys/self`는 이 중 원문·해시를 뺀 것을 돌려준다 (「연결 테스트」용).
    """

    name: str
    hash: str
    prefix: str
    allowed_operations: list[str] = Field(default_factory=lambda: ["*"])
    # 운영(Bot UI·서버 실행기)은 deterministic만, 개발(Studio)은 둘 다.
    allowed_modes: list[str] = Field(default_factory=lambda: [MODE_DETERMINISTIC])
    extra_scopes: list[str] = Field(default_factory=list)  # 앱별 추가 권한 (예: registry_write)
    created_at: Timestamp | None = None
    expires_at: Timestamp | None = None
    last_used_at: Timestamp | None = None
    revoked_at: Timestamp | None = None

    def allows_operation(self, name: str) -> bool:
        return "*" in self.allowed_operations or name in self.allowed_operations

    def allows_mode(self, mode: str) -> bool:
        return mode in self.allowed_modes


class KeySelfResponse(ContractModel):
    """`GET /v1/keys/self` — 키 원문·해시는 돌려주지 않는다."""

    name: str
    prefix: str
    allowed_operations: list[str] = Field(default_factory=list)
    allowed_modes: list[str] = Field(default_factory=list)
    extra_scopes: list[str] = Field(default_factory=list)
    expires_at: Timestamp | None = None


class UsageRecord(ContractModel):
    """사용 기록 한 줄 (앱 안, SVC-03). **입력·출력 값은 기록하지 않는다.**"""

    at: Timestamp
    key_name: str
    operation: str
    mode: str
    status: int  # HTTP 코드
    duration_ms: int
    run_id: str | None = None
    caller_type: str | None = None
    usage: Usage | None = None


IdempotencyKey = tuple[str, str, str, int, int, int]
"""`(operation, run_id, node_id, node_instance, attempt, call_seq)` — C11 멱등 키."""


def idempotency_key(operation: str, req: OpRequest) -> IdempotencyKey:
    """멱등 키. 같은 키로 다시 오면 수행하지 않고 저장된 결과를 돌려준다 (`replayed: true`).

    **부르는 쪽은 `node_instance`·`attempt`·`call_seq`를 호출 전에 저장한다.** 그래야 서버
    실행기가 재시작한 뒤 같은 키로 다시 불러도 한 번만 수행된다 (README 원칙 9).
    """
    return (operation, req.run_id, req.node_id, req.node_instance, req.attempt, req.call_seq)


def key_state(key: ServiceAppKey, *, now: str) -> str:
    """`active` / `revoked` / `expired`. 폐기가 만료보다 앞선다."""
    if key.revoked_at is not None:
        return "revoked"
    if key.expires_at is not None and datetime.fromisoformat(key.expires_at) <= datetime.fromisoformat(now):
        return "expired"
    return "active"


def authorize(
    key: ServiceAppKey,
    *,
    operation: str,
    mode: str,
    now: str,
) -> list[Violation]:
    """키가 이 작업·모드를 부를 수 있나. 비어 있으면 통과.

    - 폐기·만료 → `key_revoked` / `key_expired` (403)
    - 작업이 키 권한 밖 → `operation_not_allowed` (403)
    - 모드가 키 권한 밖 → `mode_not_allowed` (403). **운영 키로 자율 수행을 부르는 것을 막는다.**
    """
    state = key_state(key, now=now)
    if state != "active":
        return [Violation(rule="C11", code=f"key_{state}", message=f"키 {key.prefix}는 {state} 상태다")]
    out = []
    if not key.allows_operation(operation):
        out.append(
            Violation(
                rule="C11",
                code="operation_not_allowed",
                message=f"키 「{key.name}」은 작업 {operation}을 부를 수 없다",
                items=sorted(key.allowed_operations),
            )
        )
    if not key.allows_mode(mode):
        out.append(
            Violation(
                rule="C11",
                code="mode_not_allowed",
                message=f"키 「{key.name}」은 {mode} 수행을 허용하지 않는다",
                items=sorted(key.allowed_modes),
            )
        )
    return out


def resolve_mode(op: Operation, *, requested: str, key: ServiceAppKey) -> tuple[str | None, Violation | None]:
    """실제로 쓸 모드를 정한다. `(모드, None)` 또는 `(None, 위반)`.

    - 작업이 요청한 모드를 지원하면 그대로 쓴다 (받는 쪽은 모드를 바꾸지 않는다).
    - 지원하지 않으면 `mode_unsupported` (422). **단 하나의 예외**가 폴백이다:
      결정 수행을 요청했는데 작업이 `fallback="autonomous"`이고 **키가 자율 수행을 허용하면**
      자율 수행으로 넘어간다. 운영 키(결정 수행만)면 폴백하지 않고 실패한다.
    """
    if op.supports(requested):
        return requested, None
    if (
        requested == MODE_DETERMINISTIC
        and op.fallback == MODE_AUTONOMOUS
        and op.supports(MODE_AUTONOMOUS)
        and key.allows_mode(MODE_AUTONOMOUS)
    ):
        return MODE_AUTONOMOUS, None
    return None, Violation(
        rule="C11",
        code="mode_unsupported",
        message=f"작업 {op.name}은 {requested} 수행을 지원하지 않는다",
        items=sorted(op.modes),
    )
