"""실행 기록을 Center로 보낸다 — **로컬 큐가 먼저다** (C3 §전송).

실행하는 쪽(Bot UI·서버 실행기·Studio)이 쓴다. 규칙은 C3가 정한 그대로다.

- **파일이 원본이다.** `runs/<run_id>.jsonl`에 먼저 쓰고, 닿을 때 묶어 보낸다. Center가
  꺼져 있어도 실행은 돈다 — 기록이 쌓일 뿐이다 (ADR-0007 — 바깥에서 들어오는 연결은 없다).
- **멱등이다.** `(run_id, seq)`가 키라서, 실패하면 **같은 배치를 그대로** 다시 보내면 된다.
  보낸 자리는 `runs/<run_id>.sent`에 숫자 하나로 남는다.
- **줄 하나가 거부돼도 멈추지 않는다** (`200` + `rejected[]`) — 그 줄은 건너뛰고 계속 보낸다.
  한 줄이 실행 전체를 막으면 안 된다 (프로토타입에서 그랬다).
- **401·403은 멈춘다.** 키 문제는 다시 보낸다고 풀리지 않는다 — 쌓아 두고 화면이 말한다.
- **값은 여기서 만들지 않는다.** 보낼 줄은 이미 `run_log.sanitize()`를 지난 것이다 (원칙 6).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from chaeksas.contracts.events import MAX_BATCH_BYTES, MAX_BATCH_LINES, EventBatchResponse, RunEvent
from chaeksas.core.run_log import RunLog, run_dir

#: 어디까지 보냈는지 적어 두는 파일 (`runs/<run_id>.sent`).
SENT_SUFFIX = ".sent"

#: 다시 보내기 간격 (초) — C3 §오류 「30초부터 최대 10분」.
FIRST_RETRY_S = 30.0
MAX_RETRY_S = 600.0

#: 다시 보내도 소용없는 상태 (키 문제·버그). 보내기를 멈춘다.
FATAL_STATUS = (400, 401, 403, 422)


class ShipError(RuntimeError):
    """보내지 못했다. `fatal`이면 **다시 보내도 소용없다** (키 문제·버그)."""

    def __init__(self, message: str, *, status: int | None = None, fatal: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.fatal = fatal


class Uploader(Protocol):
    """배치 하나를 Center에 올리는 길. 시험은 가짜를 끼운다."""

    def send(self, run_id: str, lines: Sequence[RunEvent]) -> EventBatchResponse: ...


@dataclass
class HttpUploader:
    """`POST /api/v1/runs/{run_id}/events` (C3 §전송).

    **주소와 키는 여기만 안다** (ADR-0013) — 실행 기록에는 들어가지 않는다.
    """

    base_url: str
    api_key: str
    timeout_s: float = 30.0
    client: Any | None = None  # httpx.Client

    def send(self, run_id: str, lines: Sequence[RunEvent]) -> EventBatchResponse:
        import httpx  # noqa: PLC0415 — 부를 때만 든다

        own = self.client is None
        client = self.client or httpx.Client(timeout=self.timeout_s)
        try:
            response = client.post(
                f"{self.base_url.rstrip('/')}/api/v1/runs/{run_id}/events",
                json=[event.to_json_dict() for event in lines],
                # 키는 ASCII만 (CLAUDE.md §5). 비우면 헤더를 아예 빼지 않는다 — Center가
                # 401로 막아야 「키를 안 넣었다」가 드러난다.
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            )
        except httpx.HTTPError as e:
            raise ShipError(f"Center에 닿지 못했다 ({type(e).__name__})") from e
        finally:
            if own:
                client.close()

        if response.status_code in FATAL_STATUS:
            raise ShipError(
                f"Center가 {response.status_code}로 막았다", status=response.status_code, fatal=True
            )
        if response.status_code >= 400:
            raise ShipError(f"Center가 {response.status_code}를 돌려줬다", status=response.status_code)
        try:
            return EventBatchResponse.model_validate(response.json())
        except ValueError as e:
            raise ShipError(f"응답이 계약과 맞지 않는다: {e}") from e


def sent_path(path: Path) -> Path:
    """그 기록 파일의 「어디까지 보냈나」 파일."""
    return path.with_suffix(path.suffix + SENT_SUFFIX)


def read_sent(path: Path) -> int:
    found = sent_path(path)
    if not found.is_file():
        return 0
    try:
        return int(found.read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        return 0  # 읽지 못하면 처음부터 — 멱등이라 다시 보내도 된다


def write_sent(path: Path, through_seq: int) -> None:
    sent_path(path).write_text(f"{through_seq}\n", encoding="utf-8", newline="\n")


def batches(events: Sequence[RunEvent], *, max_lines: int = MAX_BATCH_LINES) -> Iterator[list[RunEvent]]:
    """크기 한도에 맞춰 나눈다 (C3 — 500줄·1 MB)."""
    made: list[RunEvent] = []
    size = 2  # `[]`
    for event in events:
        raw = len(json.dumps(event.to_json_dict(), ensure_ascii=False).encode("utf-8")) + 1
        if made and (len(made) >= max_lines or size + raw > MAX_BATCH_BYTES):
            yield made
            made, size = [], 2
        made.append(event)
        size += raw
    if made:
        yield made


@dataclass
class Shipment:
    """한 번 보내 본 결과 — 화면이 그대로 읽는다 (BUI-05 「보내지 못한 기록」)."""

    sent: int = 0
    duplicates: int = 0
    rejected: int = 0
    left: int = 0
    error: str = ""
    fatal: bool = False

    @property
    def ok(self) -> bool:
        return not self.error


def ship_file(uploader: Uploader, path: Path) -> Shipment:
    """기록 파일 하나를 **보낸 자리 다음부터** 올린다.

    거부된 줄은 **건너뛴 것으로 친다** — 다시 보내도 같은 이유로 거부된다 (C3 §오류).
    """
    run_id = path.name.removesuffix(".jsonl")
    through = read_sent(path)
    waiting = [event for event in RunLog.read(path) if event.seq > through]
    found = Shipment(left=len(waiting))
    if not waiting:
        return found

    for batch in batches(waiting):
        try:
            answer = uploader.send(run_id, batch)
        except ShipError as e:
            found.error = str(e)
            found.fatal = e.fatal
            return found
        found.sent += answer.accepted
        found.duplicates += answer.duplicates
        found.rejected += len(answer.rejected)
        # 거부된 줄도 **지나간 것으로** 친다 — 안 그러면 그 줄에서 영원히 멈춘다.
        through = max(through, max(event.seq for event in batch))
        write_sent(path, through)
        found.left -= len(batch)
    return found


@dataclass
class Queue:
    """`runs/` 폴더 하나 — 아직 못 보낸 줄을 들고 있다 (C4 하트비트의 `unsent_events`)."""

    data_dir: Path
    #: 오래된 것부터 보낸다 — 끝난 실행의 기록이 먼저 Center에 닿는다.
    sent_through: dict[str, int] = field(default_factory=dict)

    @property
    def folder(self) -> Path:
        return run_dir(self.data_dir)

    def files(self) -> list[Path]:
        if not self.folder.is_dir():
            return []
        return sorted(self.folder.glob("*.jsonl"), key=lambda p: (p.stat().st_mtime, p.name))

    def unsent_count(self) -> int:
        """아직 못 보낸 줄 수 (C4 `unsent_events`). **파일을 읽어 센다** — 원본이 파일이다."""
        total = 0
        for path in self.files():
            through = read_sent(path)
            total += sum(1 for event in RunLog.read(path) if event.seq > through)
        return total

    def ship(self, uploader: Uploader, *, limit: int | None = None) -> Shipment:
        """보낼 수 있는 만큼 보낸다. **막히면 거기서 멈춘다** (차례를 지킨다)."""
        total = Shipment()
        for index, path in enumerate(self.files()):
            if limit is not None and index >= limit:
                break
            found = ship_file(uploader, path)
            total.sent += found.sent
            total.duplicates += found.duplicates
            total.rejected += found.rejected
            total.left += found.left
            if not found.ok:
                total.error, total.fatal = found.error, found.fatal
                break
            self.sent_through[path.name.removesuffix(".jsonl")] = read_sent(path)
        return total


def sink_for(log: RunLog, queue: Queue) -> None:
    """이 실행의 기록이 큐의 폴더에 쌓이게 한다 — 보내기는 **따로** 돈다.

    실행 중에 보내려 하면 느린 Center가 업무를 붙잡는다. 큐는 하트비트 때 비운다 (C4).
    """
    if log.path is None:
        log.path = queue.folder / f"{log.run_id}.jsonl"


def pending(events: Iterable[RunEvent], through: int) -> list[RunEvent]:
    return [event for event in events if event.seq > through]


__all__ = [
    "FATAL_STATUS",
    "FIRST_RETRY_S",
    "MAX_RETRY_S",
    "SENT_SUFFIX",
    "HttpUploader",
    "Queue",
    "ShipError",
    "Shipment",
    "Uploader",
    "batches",
    "pending",
    "read_sent",
    "sent_path",
    "ship_file",
    "sink_for",
    "write_sent",
]
