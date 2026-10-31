"""C15. Center API: 외부 작업 — 부르는 쪽 ↔ Center ↔ 일꾼 (ADR-0102).

단일 원본: `docs/03-contracts/C15-external-tasks.md`.

먼저 알아야 할 셋 (계약 맨 앞):

1. **최소 한 번 실행이다.** 잠금이 지나면 일감이 다시 나간다. 일꾼이 `idempotency`로 스스로 한 번만
   수행한다 — Center는 바깥에서 일어난 일을 모른다.
2. **아무도 가져가지 않으면 기한에 실패한다** (`no_consumer`). 조용히 쌓아 두지 않는다.
3. **업무 값은 결과를 부른 쪽이 받을 때까지만 있다** (`ack` — 원칙 6의 예외, ADR-0062와 같은 자리).
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any

from pydantic import Field

from chaeksas.contracts._base import ContractModel, SchemaVersioned, Timestamp
from chaeksas.contracts.enrollment import PublicKey, RotatedKey
from chaeksas.contracts.extension import Catalog
from chaeksas.contracts.service_app import Caller, Operation, ServiceAppManifest, Usage

#: 롱폴링 한 번이 물고 있는 가장 긴 시간 (초). 더 길게 달라고 하면 이것으로 깎는다.
MAX_WAIT_S = 25
#: 한 번 가져가기에 잠글 수 있는 일감 수 (C15 「정한 것」). 더 달라고 하면 이것으로 깎는다.
MAX_TASKS_PER_FETCH = 10
#: 결과를 받지 못한 값을 지우는 날 수 (ADR-0062 위임 결과와 같다).
PURGE_AFTER_DAYS = 7
#: 입력·출력 한도 (C11과 같다).
MAX_VALUE_BYTES = 1024 * 1024

STATE_PENDING = "pending"
STATE_LOCKED = "locked"
STATE_COMPLETED = "completed"
STATE_FAILED = "failed"
STATE_EXPIRED = "expired"
STATE_CANCELLED = "cancelled"
#: 열린 문자열이다 (원칙 10) — 받는 쪽은 모르는 값도 저장·표시한다.
KNOWN_STATES = frozenset({STATE_PENDING, STATE_LOCKED, STATE_COMPLETED, STATE_FAILED, STATE_EXPIRED, STATE_CANCELLED})
#: 끝난 상태 — 이 뒤로는 바뀌지 않는다.
FINAL_STATES = frozenset({STATE_COMPLETED, STATE_FAILED, STATE_EXPIRED, STATE_CANCELLED})

ORIGIN_RUN = "run"
ORIGIN_TEST = "test"
KNOWN_ORIGINS = frozenset({ORIGIN_RUN, ORIGIN_TEST})

#: 기한이 지났을 때의 사유 — 아무도 안 가져갔다 / 가져갔는데 안 끝났다.
CODE_NO_CONSUMER = "no_consumer"
CODE_TIMEOUT = "timeout"
#: `retryable: true`일 수 있는 코드. C14 `retry.on`의 HTTP 숫자는 `RETRY_STATUS_CODES`로 읽는다.
RETRYABLE_CODES = frozenset({"dependency_down", "rate_limited", CODE_TIMEOUT})
RETRY_STATUS_CODES: dict[int, str] = {503: "dependency_down", 429: "rate_limited"}

#: 일꾼을 들이는 요청 종류 (`contracts.enrollment.ENROLLMENT_TYPES`에 더한다).
CONSUMER = "consumer"
#: 호출 토큰 (C15 「정한 것」) — PC 실행기가 제 키로 청해 실행 프로세스에 넘긴다.
CALL_TOKEN = "call_token"
CALL_TOKEN_HOURS = 24
#: 호출 토큰이 열 수 있는 경로의 앞자리 — 밖은 403 `call_token_scope`.
CALL_TOKEN_PATH = "/api/v1/external-tasks"
#: 호출 토큰이 **읽을** 수 있는 곳 — 리소스 목록(C7, 카탈로그를 읽는다). GET만.
CALL_TOKEN_READ_PATH = "/api/v1/resources"

#: Studio 시험 실행의 `run_id` 앞자리 (C11 `run_id` — 「Studio 단독 시험이면 `test_<hex>`」).
TEST_RUN_PREFIX = "test_"

Topic = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9.-]{0,63}$")]
TaskId = Annotated[str, Field(pattern=r"^xt_[0-9a-f]{24}$")]


class Idempotency(ContractModel):
    """C11 멱등 키에서 `operation`을 뺀 다섯 칸 (`operation`은 일감에 따로 있다)."""

    run_id: str
    node_id: str
    node_instance: int = Field(ge=1)
    attempt: int = Field(ge=1)
    call_seq: int = Field(default=1, ge=1)


def task_id_for(topic: str, operation: str, key: Idempotency) -> str:
    """멱등 칸 → `task_id`. **Center가 짓는다** — 같은 칸이면 같은 id라 되살린 실행이 다시 올려도
    같은 일감이다 (C15 §올리기)."""
    parts = [topic, operation, key.run_id, key.node_id, str(key.node_instance), str(key.attempt), str(key.call_seq)]
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"xt_{digest[:24]}"


def body_hash(request: ExternalTaskCreate) -> str:
    """같은 멱등 칸에 다른 본문이 왔나를 보는 해시 (409 `idempotency_conflict`) — 입력과 모드만 본다.

    C11과 같은 규칙이다 (「같은 키인데 본문(`input`·`mode`)의 해시가 다르면 409」).
    """
    text = json.dumps({"input": request.input, "mode": request.mode}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def missing_outputs(operation: Operation | None, output: dict[str, Any]) -> list[str]:
    """`output_schema.required`의 칸 중 빠진 것 (C15 「정한 것」 — 그보다 깊이 보지 않는다)."""
    if operation is None or not operation.output_schema:
        return []
    required = operation.output_schema.get("required") or []
    return [str(name) for name in required if name not in output]


class ExternalTaskCreate(SchemaVersioned):
    """`POST /api/v1/external-tasks` — 일감 올리기 (C15 §올리기)."""

    topic: Topic
    operation: str
    mode: str  # MODES (C11)
    idempotency: Idempotency
    caller: Caller
    business_key: str | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    timeout_s: int | None = Field(default=None, ge=1)
    want_result: bool = True
    origin: str = ORIGIN_RUN  # KNOWN_ORIGINS


class CallToken(ContractModel):
    """`POST /api/v1/call-tokens`의 응답. **원문은 이때만** 실린다 (Center에는 해시만)."""

    token: str
    expires_at: Timestamp


class ExternalTaskCreated(ContractModel):
    """올리기 응답. 같은 칸으로 다시 올리면 같은 `task_id`·지금 상태가 온다."""

    task_id: str
    state: str


class TaskError(ContractModel):
    """실패·만료의 사유. 코드는 C11 오류 코드 그대로 오거나 `no_consumer`·`timeout`이다."""

    code: str
    message: str = ""
    retryable: bool = False
    #: 요청이 상대에게 닿았을 수 있는데 답을 받지 못했다 — `retryable`과 함께 참이 아니다 (ADR-0107).
    outcome_unknown: bool = False
    detail: dict[str, Any] | None = None  # C11 오류의 `detail` 그대로 (업무 값을 넣지 않는다)


class ExternalTaskResult(ContractModel):
    """`GET /api/v1/external-tasks/{task_id}` — 결과 기다리기 (C15 §결과)."""

    task_id: str
    state: str  # KNOWN_STATES
    output: dict[str, Any] | None = None
    mode_used: str | None = None
    replayed: bool = False
    usage: Usage | None = None
    error: TaskError | None = None
    deliveries: int = 0


class FetchRequest(ContractModel):
    """`POST /api/v1/consumers/fetch` — 가져가기 (롱폴링)."""

    topics: list[Topic] = Field(min_length=1)
    max_tasks: int = Field(default=1, ge=1)
    wait_s: int = Field(default=MAX_WAIT_S, ge=0)
    #: 잠금 시간. 없으면 작업의 `timeout_s`. 어느 쪽이든 `deadline`을 넘지 않는다.
    lock_s: int | None = Field(default=None, ge=1)


class LockedTask(ContractModel):
    """일꾼이 받은 일감 하나."""

    task_id: str
    topic: str
    operation: str
    mode: str
    origin: str
    idempotency: Idempotency
    caller: Caller
    business_key: str | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    lock_until: Timestamp
    deadline: Timestamp
    #: 몇 번째로 나가는가 (1부터). 2 이상이면 앞의 잠금이 지났다 — 멱등 저장소를 먼저 본다.
    delivery: int = 1


class FetchResponse(ContractModel):
    tasks: list[LockedTask] = Field(default_factory=list)
    #: 이 일꾼의 id — 봉한 새 토큰을 열 때의 salt다 (키 회전과 같은 봉함).
    consumer_id: str | None = None
    #: 일꾼 토큰 만료 14일 전부터 — 봉한 새 토큰 (C4 §키 회전과 같은 규칙).
    rotated_token: RotatedKey | None = None


class CompleteRequest(ContractModel):
    output: dict[str, Any] = Field(default_factory=dict)
    mode_used: str | None = None
    replayed: bool = False
    usage: Usage | None = None


class FailRequest(ContractModel):
    code: str
    message: str = ""
    retryable: bool = False
    #: 결과 모름 (ADR-0107) — 어댑터 일꾼이 `idempotent: false` 작업에서 보낸 뒤 답을 못 받았을 때.
    outcome_unknown: bool = False
    detail: dict[str, Any] | None = None  # C11 오류의 `detail` — 부르는 쪽까지 그대로 간다


class ExtendRequest(ContractModel):
    lock_s: int = Field(ge=1)


class ConsumerVersions(ContractModel):
    """일꾼의 판 — 무엇을 돌리는가는 열린 사전이다 (앱 판·`service_kit` 판 등)."""

    consumer: str


class ConsumerEnrollRequest(SchemaVersioned):
    """`POST /api/v1/consumers/enroll` — 일꾼 들이기 요청 (C15 §일꾼 들이기, ADR-0092 §1과 같은 결).

    `manifests`는 들일 때 함께 올린다(토픽마다 하나, `app_id` = 토픽) — Center가 앱을 읽으러 가지
    않는다 (ADR-0102 §3). 외부 확장 토픽은 비워도 된다(작업 목록은 등록된 정의에서 온다).
    """

    machine_id: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    name: str
    os: str
    versions: ConsumerVersions
    public_key: PublicKey
    topics: list[Topic] = Field(min_length=1)
    manifests: list[ServiceAppManifest] = Field(default_factory=list)


class ExternalTaskInfo(ContractModel):
    """`GET /api/v1/external-tasks?run_id=`의 한 줄 — 콘솔이 보는 일감 (CON-01 「외부 작업」).

    **업무 값은 없다** (원칙 6) — 입력·출력·오류 글은 싣지 않고 코드만 싣는다. 자리(`node_id`·
    `node_instance`·`attempt`·`call_seq`)는 멱등 칸에서 온다.
    """

    task_id: str
    topic: str
    operation: str
    mode: str
    origin: str
    node_id: str
    node_instance: int = 1
    attempt: int = 1
    call_seq: int = 1
    state: str  # KNOWN_STATES
    created_at: Timestamp
    finished_at: Timestamp | None = None
    acked_at: Timestamp | None = None
    deliveries: int = 0
    #: 쥐었던 일꾼의 이름 — 지금 쥔 것이 있으면 그것 하나, 아니면 한 번이라도 쥔 것들.
    consumers: list[str] = Field(default_factory=list)
    error_code: str | None = None
    outcome_unknown: bool = False


class ConsumerInfo(ContractModel):
    """`GET /api/v1/consumers`의 한 줄 (CON-07 「일꾼」)."""

    consumer_id: str
    name: str
    topics: list[str] = Field(default_factory=list)
    key_prefix: str | None = None
    approved_at: Timestamp | None = None
    last_fetch_at: Timestamp | None = None
    #: 이 일꾼이 올린 manifest들의 `app_id@version`.
    apps: list[str] = Field(default_factory=list)


class CatalogUpload(ContractModel):
    """`PUT /api/v1/consumers/self/catalogs/{resource_type}` — 그 토픽의 카탈로그 (C13 §5)."""

    app_id: str
    catalog: Catalog


class TopicStatus(ContractModel):
    """`GET /api/v1/external-topics`의 한 줄 (C15 「정한 것」의 제안 — CON-07 토픽 상태)."""

    topic: str
    consumers: int = 0
    last_fetch_at: Timestamp | None = None
    waiting: int = 0
    oldest_waiting_since: Timestamp | None = None


__all__ = [
    "CALL_TOKEN",
    "CALL_TOKEN_HOURS",
    "CALL_TOKEN_PATH",
    "CALL_TOKEN_READ_PATH",
    "CODE_NO_CONSUMER",
    "CODE_TIMEOUT",
    "CONSUMER",
    "FINAL_STATES",
    "KNOWN_ORIGINS",
    "KNOWN_STATES",
    "MAX_TASKS_PER_FETCH",
    "MAX_VALUE_BYTES",
    "MAX_WAIT_S",
    "ORIGIN_RUN",
    "ORIGIN_TEST",
    "PURGE_AFTER_DAYS",
    "RETRYABLE_CODES",
    "RETRY_STATUS_CODES",
    "STATE_CANCELLED",
    "STATE_COMPLETED",
    "STATE_EXPIRED",
    "STATE_FAILED",
    "STATE_LOCKED",
    "STATE_PENDING",
    "TEST_RUN_PREFIX",
    "CallToken",
    "CatalogUpload",
    "CompleteRequest",
    "ConsumerEnrollRequest",
    "ConsumerInfo",
    "ExternalTaskInfo",
    "ConsumerVersions",
    "ExtendRequest",
    "ExternalTaskCreate",
    "ExternalTaskCreated",
    "ExternalTaskResult",
    "FailRequest",
    "FetchRequest",
    "FetchResponse",
    "Idempotency",
    "LockedTask",
    "TaskError",
    "TopicStatus",
    "body_hash",
    "missing_outputs",
    "task_id_for",
]
