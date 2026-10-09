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
    "ui_session": frozenset({"business_key", "page_id", "result", "steps", "fallback_depth_max", "healed"}),
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
        {"status", "duration_s", "ai_tasks", "replayed_tasks", "ui_tasks", "service_calls", "human_requests"}
    ),
}

KNOWN_KINDS = frozenset(REQUIRED_DATA_KEYS) | {"data"}
"""`data`(업무 값)는 실행 설정에서 명시적으로 켠 경우에만 보낸다 (README 원칙 6)."""

# 아래는 모두 **열린 문자열**의 알려진 값일 뿐이다 (README 원칙 10).
KNOWN_EXECUTORS = frozenset({"bot_ui", "server_runner", "studio"})
KNOWN_MODES = frozenset({"autonomous", "deterministic"})
KNOWN_SOURCES = frozenset({"job", "manual", "watch", "schedule", "message", "test"})
RESERVED_SOURCES = frozenset({"delegation"})
KNOWN_NODE_STATES = frozenset({"started", "completed", "failed", "skipped", "replayed", "waiting"})
KNOWN_RUN_STATUSES = frozenset({"success", "failed", "cancelled"})
KNOWN_WAITING_FOR = frozenset({"approval", "message", "timer"})
RESERVED_WAITING_FOR = frozenset({"delegation"})
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
    events: int = 0


class RunListing(ContractModel):
    """`GET /api/v1/runs`의 응답."""

    runs: list[RunInfo] = Field(default_factory=list)
    total: int = 0


class RunEventsResponse(ContractModel):
    """`GET /api/v1/runs/{run_id}/events`의 응답 — **`seq` 차례로** 전부."""

    run_id: str
    events: list[RunEvent] = Field(default_factory=list)
