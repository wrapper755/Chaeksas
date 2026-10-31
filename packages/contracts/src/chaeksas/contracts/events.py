"""C3. 실행 이벤트 — 실행 한 번(`run_id`)에서 일어난 일.

단일 원본: `docs/03-contracts/C3-run-events.md`.

**`kind`는 열린 문자열이다.** 모르는 종류를 거부하면 `seq`가 단조라서 그 실행의 기록이 영원히
막힌다 (프로토타입에서 실제로 일어남). 그래서 `Literal`을 쓰지 않고, 알려진 값은 아래 표로만 둔다.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any

from pydantic import Field

from chaeksas.contracts._base import ContractModel, SchemaVersioned, Timestamp

#: 한 배치의 한도 (넘으면 413).
MAX_BATCH_LINES = 500
MAX_BATCH_BYTES = 1024 * 1024

RunId = Annotated[str, Field(pattern=r"^(run|test)_\d{8}_\d{6}_[0-9a-f]{6}$")]
"""`run_<YYYYMMDD>_<HHMMSS>_<hex6>` (운영), `test_…` (Studio 시험 실행)."""

#: 종류별 `data` 필수 키. 알려진 종류만 있고, **모르는 종류는 검사하지 않는다**.
REQUIRED_DATA_KEYS: dict[str, frozenset[str]] = {
    "run_started": frozenset({"bpm_process_id", "version", "run_location", "executor", "mode", "source"}),
    "node_state": frozenset({"state"}),
    "log": frozenset({"level", "message"}),
    "agent": frozenset({"step", "action"}),
    "llm_usage": frozenset({"model", "input_tokens", "output_tokens"}),
    "service_call": frozenset(
        {"app_id", "operation", "mode", "mode_used", "status", "duration_ms", "key_ref",
         "node_instance", "attempt", "call_seq"}
    ),
    "human_requested": frozenset({"layer", "request_id", "where"}),
    "human_answered": frozenset({"request_id", "answered_by"}),
    "human_timeout": frozenset({"request_id"}),
    "human_withdrawn": frozenset({"request_id", "reason"}),
    "run_waiting": frozenset({"waiting_for"}),
    "run_resumed": frozenset({"after_s"}),
    "run_finished": frozenset(
        {"status", "duration_s", "ai_tasks", "replayed_tasks", "service_calls", "human_requests"}
    ),
}

KNOWN_KINDS = frozenset(REQUIRED_DATA_KEYS) | {"data"}
"""`data`(업무 값)는 실행 설정에서 명시적으로 켠 경우에만 보낸다 (README 원칙 6)."""

# 아래는 모두 **열린 문자열**의 알려진 값일 뿐이다 (README 원칙 10).
KNOWN_EXECUTORS = frozenset({"bot_ui", "server_runner", "studio"})
KNOWN_MODES = frozenset({"autonomous", "deterministic"})
#: 시작 출처 (C4 `source`와 같은 값). **`delegation`은 PC 위임으로 시작된 PC 실행이다**
#: ([ADR-0062](../decisions/0062-pc-delegation.md) — 예약을 풀었다).
KNOWN_SOURCES = frozenset(
    {"job", "manual", "watch", "schedule", "message", "test", "delegation"}
)
KNOWN_NODE_STATES = frozenset({"started", "completed", "failed", "skipped", "replayed", "waiting"})
KNOWN_RUN_STATUSES = frozenset({"success", "failed", "cancelled"})
#: `run_waiting.waiting_for`. **`delegation`은 PC 위임을 기다리는 것**이고 짝 칸은
#: `job_id`다 (ADR-0062 — 예약을 풀었다). **`external_task`는 긴 외부 작업**이고 짝 칸은 `task_id`다
#: (ADR-0103). C12 `waiting[]`과 **같은 말**이다.
KNOWN_WAITING_FOR = frozenset({"approval", "message", "timer", "delegation", "external_task"})
#: `run_resumed.reason` — **무엇이 깨웠나**. 회수(`withdraw`)도 답은 아니지만 이어 간 것이다
#: (C6·ADR-0038). **`delegation`은 PC 위임의 결과가 돌아온 것**이다 (ADR-0062 — 실패·거절로
#: 돌아와 오류 경계로 가는 길도 이어 간 것이다). 보내는 쪽이 이 밖의 값을 쓰면 화면이 모르는
#: 글을 그대로 보인다.
KNOWN_RESUME_REASONS = frozenset(
    {"answer", "message", "timer", "restart", "withdraw", "delegation", "external_task"}
)
KNOWN_HUMAN_LAYERS = frozenset({"approval", "confirmation"})
KNOWN_UI_RESULTS = frozenset({"success", "escalated", "failed"})


class RunEvent(SchemaVersioned):
    """실행 이벤트 한 줄. 로컬 `runs/<run_id>.jsonl`의 한 줄이자 전송 단위.

    `data`에는 **업무 값·결재 답·비밀·스크린샷을 넣지 않는다** (README 원칙 6).
    """

    run_id: RunId
    seq: int = Field(ge=1, description="실행 안에서 1부터 단조 증가")
    ts: Timestamp
    kind: str = Field(description="열린 문자열 — 모르는 종류도 저장한다")
    node_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


def missing_keys(kind: str, data: Mapping[str, Any]) -> list[str]:
    """줄이 되기 **전에** 보는 것 — 알려진 `kind`인데 빠진 `data` 필수 키들.

    확장이 준 `{kind, data}`를 엔진이 이것으로 본다 (ADR-0041) — 어긋나면 그 줄만 버린다.
    """
    required = REQUIRED_DATA_KEYS.get(kind)
    if required is None:
        return []
    return sorted(required - set(data))


def missing_data_keys(event: RunEvent) -> list[str]:
    """알려진 `kind`인데 `data` 필수 키가 빠졌으면 그 이름들. 모르는 `kind`면 빈 목록.

    Center는 이것으로 **줄 단위** 거부를 만든다 (`200` + `rejected: [{seq, code}]`).
    한 줄 때문에 배치 전체를 거부하지 않는다.
    """
    return missing_keys(event.kind, event.data)


class RejectedLine(ContractModel):
    """받지 못한 줄 하나."""

    seq: int
    code: str


class EventBatchResponse(ContractModel):
    """`POST /api/v1/runs/{run_id}/events`의 응답."""

    run_id: str
    accepted: int
    duplicates: int = 0
    rejected: list[RejectedLine] = Field(default_factory=list)


class RunInfo(ContractModel):
    """실행 하나의 요약 (CON-01 목록·상세). **받을 때 만들어 둔다** — 목록을 그릴 때마다
    이벤트를 다시 읽지 않는다."""

    run_id: str
    status: str = "running"  # running|waiting|success|failed|cancelled (열린 문자열)
    bpm_process_id: str | None = None
    version: str | None = None
    run_location: str | None = None
    executor: str | None = None
    mode: str | None = None
    source: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    duration_s: float | None = None
    error_code: str | None = None
    #: `run_finished`의 셈 그대로 (CON-01 목록 열). **끝나지 않은 실행은 `None`**이다 —
    #: 줄을 다시 읽어 세지 않는다 (요약은 받을 때 만든다).
    ai_tasks: int | None = None
    replayed_tasks: int | None = None
    service_calls: int | None = None
    human_requests: int | None = None
    #: `human_requests` 중 **확인**(`layer: confirmation`)의 수 (CON-02 「확인률」).
    #: **보낸 쪽이 넣었을 때만** 있다 — 없으면 「확인만은 모른다」다(0이 아니다). 결재 수는
    #: `human_requests - confirmations`다.
    confirmations: int | None = None
    #: **이 PC 실행을 맡긴 서버 실행** (C3 `run_started.parent_run_id`, ADR-0062). PC 위임으로
    #: 시작된 실행에만 있다 — CON-01이 이것으로 서버 실행과 오간다. **보낸 쪽이 적은 값**이라
    #: Center는 `run_started`에서 읽어 요약에 담아 둔다 (줄을 다시 읽지 않는다).
    parent_run_id: str | None = None
    #: 어느 PC가 보냈나 (CON-01 「PC 실행기」 필터·열). **Center가 읽을 때 채운다** —
    #: 보내는 쪽은 적지 않는다(신원은 키다, C4). Studio·토큰이 보낸 기록에는 없다.
    bot_ui_id: str | None = None
    events: int = 0


class RunListing(ContractModel):
    """`GET /api/v1/runs`의 응답."""

    runs: list[RunInfo] = Field(default_factory=list)
    total: int = 0


class RunEventsResponse(ContractModel):
    """`GET /api/v1/runs/{run_id}/events`의 응답 — **`seq` 차례로** 전부."""

    run_id: str
    events: list[RunEvent] = Field(default_factory=list)
