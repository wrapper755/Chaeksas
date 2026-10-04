"""실행 기록 — C3 이벤트를 **로컬 jsonl에 먼저 쓰고**, 보낼 수 있을 때 묶어 보낸다.

C3 §전송: 「실행하는 쪽은 로컬 파일(`runs/<run_id>.jsonl`)에 먼저 쓰고, Center에 닿을 때 묶어서
보낸다.」 그래서 보내기는 **기록과 떼어** 둔다 — Center가 꺼져 있어도 실행은 계속되고 줄은 남는다.

`seq`는 실행 안에서 1부터 1씩 는다 (C3). 보내는 쪽이 재시도하면 같은 배치를 그대로 다시 보내면
되므로(멱등은 `(run_id, seq)`), 여기서는 **보낸 데까지**만 기억한다.

**업무 값·결재 답·비밀은 넣지 않는다** (계약 원칙 6). `data`에 무엇을 담을지는 부르는 쪽이
정하지만, 값으로 보이는 큰 것은 `sanitize()`가 걸러 낸다.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from chaeksas.contracts.events import MAX_BATCH_LINES, RunEvent

log = logging.getLogger(__name__)

#: `data`의 한 값이 이보다 길면 줄여서 담는다 (업무 값이 새어 들어오는 것을 막는 그물).
MAX_DATA_TEXT = 200


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def sanitize(data: Mapping[str, Any] | None) -> dict[str, Any]:
    """`data`를 **작고 안전한 것만** 남긴다 (계약 원칙 6).

    수·참거짓·짧은 문자열은 그대로, 긴 문자열은 잘라서, 목록·사전은 **개수만** 남긴다 —
    업무 값이 실수로 실려 나가지 않게.
    """
    out: dict[str, Any] = {}
    for key, value in (data or {}).items():
        if value is None or isinstance(value, bool | int | float):
            out[key] = value
        elif isinstance(value, str):
            out[key] = value if len(value) <= MAX_DATA_TEXT else value[:MAX_DATA_TEXT] + "…"
        elif isinstance(value, Mapping):
            out[key] = {"개수": len(value)}
        elif isinstance(value, Sequence):
            out[key] = {"개수": len(value)}
        else:
            out[key] = {"형": type(value).__name__}
    return out


class EventSink(Protocol):
    """이벤트를 받는 곳 (파일·Center 보내기·화면)."""

    def __call__(self, event: RunEvent) -> None: ...


@dataclass
class RunLog:
    """한 실행의 기록. `emit()`이 `seq`를 붙여 파일과 구독자에게 보낸다.

    `path`가 없으면 메모리에만 둔다 (Studio 시험 실행·단위 시험).
    """

    run_id: str
    path: Path | None = None
    #: 파일 말고 더 보낼 곳 (Center 보내기·Bot UI 화면).
    sinks: list[EventSink] = field(default_factory=list)
    clock: Callable[[], str] = now_iso

    events: list[RunEvent] = field(default_factory=list)
    #: Center가 받았다고 확인한 마지막 `seq`.
    sent_through: int = 0

    @property
    def seq(self) -> int:
        return len(self.events)

    def emit(self, kind: str, *, node_id: str | None = None, **data: Any) -> RunEvent:
        """이벤트 하나를 남긴다. `seq`·`ts`는 여기서 붙인다."""
        event = RunEvent(
            schema=1,
            run_id=self.run_id,
            seq=self.seq + 1,
            ts=self.clock(),
            kind=kind,
            node_id=node_id,
            data=sanitize(data),
        )
        self.events.append(event)
        self._write(event)
        for sink in self.sinks:
            try:
                sink(event)
            except Exception:  # noqa: BLE001 — 구독자 때문에 실행이 멈추면 안 된다
                log.exception("실행 기록 구독자가 실패했다 (%s)", kind)
        return event

    def _write(self, event: RunEvent) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event.to_json_dict(), ensure_ascii=False, separators=(",", ":"))
        # 한 줄씩 붙여 쓴다 (jsonl). 실행 중에 꺼져도 그때까지가 남는다.
        with self.path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(line + "\n")

    # ── 보내기 (Center) ──

    def unsent(self) -> list[RunEvent]:
        """아직 Center가 확인하지 않은 줄 (한 배치 한도까지, C3)."""
        return self.events[self.sent_through : self.sent_through + MAX_BATCH_LINES]

    def mark_sent(self, through_seq: int) -> None:
        self.sent_through = max(self.sent_through, through_seq)

    @property
    def unsent_count(self) -> int:
        """C4 하트비트의 `unsent_events`."""
        return max(0, len(self.events) - self.sent_through)

    # ── 읽기 ──

    @classmethod
    def read(cls, path: Path) -> Iterator[RunEvent]:
        """jsonl을 다시 읽는다 (Bot UI 「실행 기록」·Studio 로그 탭)."""
        with path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield RunEvent.model_validate_json(line)


def run_dir(data_dir: Path) -> Path:
    """`runs/` — 실행 기록이 쌓이는 곳 (`docs/01-architecture.md` §7)."""
    return data_dir / "runs"


def log_path(data_dir: Path, run_id: str) -> Path:
    return run_dir(data_dir) / f"{run_id}.jsonl"


def summarize(events: Iterable[RunEvent]) -> dict[str, Any]:
    """`run_finished`의 셈 (C3 — `ai_tasks`·`service_calls` …)."""
    counts = {"ai_tasks": 0, "replayed_tasks": 0, "ui_tasks": 0, "service_calls": 0, "human_requests": 0}
    for event in events:
        if event.kind == "service_call":
            counts["service_calls"] += 1
        elif event.kind == "ui_session":
            counts["ui_tasks"] += 1
        elif event.kind == "human_requested":
            counts["human_requests"] += 1
        elif event.kind == "node_state":
            if event.data.get("task_type") == "ai_task" and event.data.get("state") == "completed":
                counts["ai_tasks"] += 1
            if event.data.get("state") == "replayed":
                counts["replayed_tasks"] += 1
    return counts


__all__ = [
    "MAX_DATA_TEXT",
    "EventSink",
    "RunLog",
    "log_path",
    "now_iso",
    "run_dir",
    "sanitize",
    "summarize",
]
