"""실행 기록을 Center로 보내는 로컬 큐 (C3 §전송, M3 조각 3g).

거듭 보는 것 다섯.

1. **파일이 원본이다** — Center가 꺼져 있어도 실행은 돌고 기록이 쌓인다 (ADR-0007).
2. **멱등이다** — 실패하면 같은 배치를 그대로 다시 보낸다. 보낸 자리는 `.sent`에 남는다.
3. **거부된 줄에서 멈추지 않는다** — 다시 보내도 같은 이유로 거부된다 (C3 §오류).
4. **401·403은 멈춘다** — 키 문제는 다시 보낸다고 풀리지 않는다.
5. **값은 담기지 않는다** (원칙 6) — 보내는 것은 `run_log.sanitize()`를 지난 줄이다.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from chaeksas.contracts.events import EventBatchResponse, RejectedLine, RunEvent
from chaeksas.core.run_log import RunLog, log_path, run_dir
from chaeksas.core.run_shipping import (
    HttpUploader,
    Queue,
    ShipError,
    batches,
    read_sent,
    ship_file,
    sink_for,
)

RUN = "run_20261005_101500_a1b2c3"


class FakeCenter:
    """받은 것을 세어 두는 가짜 Center. `fails`를 켜면 그 횟수만큼 실패한다."""

    def __init__(self, *, fails: int = 0, fatal: bool = False, rejects: set[int] | None = None) -> None:
        self.batches: list[list[RunEvent]] = []
        self.fails = fails
        self.fatal = fatal
        self.rejects = rejects or set()
        self.seen: set[tuple[str, int]] = set()

    def send(self, run_id: str, lines: Sequence[RunEvent]) -> EventBatchResponse:
        if self.fails > 0:
            self.fails -= 1
            raise ShipError("Center에 닿지 못했다", fatal=self.fatal)
        self.batches.append(list(lines))
        accepted = duplicates = 0
        rejected = []
        for event in lines:
            if event.seq in self.rejects:
                rejected.append(RejectedLine(seq=event.seq, code="data_missing"))
            elif (run_id, event.seq) in self.seen:
                duplicates += 1
            else:
                self.seen.add((run_id, event.seq))
                accepted += 1
        return EventBatchResponse(
            run_id=run_id, accepted=accepted, duplicates=duplicates, rejected=rejected
        )


def write_log(data_dir: Path, run_id: str = RUN, lines: int = 3) -> Path:
    log = RunLog(run_id=run_id, path=log_path(data_dir, run_id))
    log.emit("run_started", bpm_process_id="fin.invoice", version="1.0.0", run_location="pc",
             executor="bot_ui", mode="autonomous", source="manual")
    for i in range(lines - 1):
        log.emit("log", level="info", message=f"{i}번째 줄")
    return log.path  # type: ignore[return-value]


# ─────────────────────────── 보내기 ───────────────────────────


def test_a_file_is_shipped_once(tmp_path: Path) -> None:
    path = write_log(tmp_path)
    center = FakeCenter()
    found = ship_file(center, path)
    assert found.sent == 3 and found.left == 0 and found.ok
    assert read_sent(path) == 3


def test_shipping_again_sends_nothing(tmp_path: Path) -> None:
    """보낸 자리가 `.sent`에 남는다 — 하트비트마다 전부 다시 보내지 않는다."""
    path = write_log(tmp_path)
    center = FakeCenter()
    ship_file(center, path)
    again = ship_file(center, path)
    assert again.sent == 0 and len(center.batches) == 1


def test_only_the_new_lines_go(tmp_path: Path) -> None:
    path = write_log(tmp_path)
    center = FakeCenter()
    ship_file(center, path)

    log = RunLog(run_id=RUN, path=path)
    log.events = list(RunLog.read(path))
    log.emit("run_finished", status="success", duration_s=1, ai_tasks=0, replayed_tasks=0,
             ui_tasks=0, service_calls=0, human_requests=0)

    found = ship_file(center, path)
    assert found.sent == 1
    assert [e.seq for e in center.batches[-1]] == [4]


def test_a_failed_batch_is_sent_again_whole(tmp_path: Path) -> None:
    """멱등이라 그대로 다시 보내면 된다 — 보낸 자리를 옮기지 않았다."""
    path = write_log(tmp_path)
    center = FakeCenter(fails=1)
    first = ship_file(center, path)
    assert not first.ok and read_sent(path) == 0

    second = ship_file(center, path)
    assert second.ok and second.sent == 3


def test_a_rejected_line_does_not_block_the_rest(tmp_path: Path) -> None:
    """거부된 줄에서 멈추면 그 실행의 기록이 영원히 막힌다 (C3 §오류)."""
    path = write_log(tmp_path)
    center = FakeCenter(rejects={2})
    found = ship_file(center, path)
    assert found.sent == 2 and found.rejected == 1
    assert read_sent(path) == 3, "거부된 줄도 지나간 것으로 친다"


def test_a_key_problem_stops_and_says_so(tmp_path: Path) -> None:
    path = write_log(tmp_path)
    found = ship_file(FakeCenter(fails=1, fatal=True), path)
    assert not found.ok and found.fatal
    assert read_sent(path) == 0


# ─────────────────────────── 큐 ───────────────────────────


def test_the_queue_counts_what_is_unsent(tmp_path: Path) -> None:
    """C4 하트비트의 `unsent_events` — **파일을 읽어 센다** (원본이 파일이다)."""
    write_log(tmp_path, RUN, lines=3)
    write_log(tmp_path, "run_20261005_101600_b2c3d4", lines=2)
    queue = Queue(data_dir=tmp_path)
    assert queue.unsent_count() == 5

    queue.ship(FakeCenter())
    assert queue.unsent_count() == 0


def test_the_queue_stops_at_the_first_problem(tmp_path: Path) -> None:
    """차례를 지킨다 — 막힌 뒤의 파일을 먼저 보내지 않는다."""
    write_log(tmp_path, RUN, lines=2)
    write_log(tmp_path, "run_20261005_101600_b2c3d4", lines=2)
    center = FakeCenter(fails=1)
    found = Queue(data_dir=tmp_path).ship(center)
    assert not found.ok
    assert len(center.batches) == 0


def test_an_empty_queue_is_fine(tmp_path: Path) -> None:
    assert Queue(data_dir=tmp_path).unsent_count() == 0
    assert Queue(data_dir=tmp_path).ship(FakeCenter()).ok


def test_the_log_lands_in_the_queue_folder(tmp_path: Path) -> None:
    queue = Queue(data_dir=tmp_path)
    log = RunLog(run_id=RUN)
    sink_for(log, queue)
    log.emit("log", level="info", message="한 줄")
    assert log.path is not None and log.path.parent == run_dir(tmp_path)
    assert queue.unsent_count() == 1


# ─────────────────────────── 나누기 ───────────────────────────


def test_a_long_run_is_split_into_batches(tmp_path: Path) -> None:
    path = write_log(tmp_path, lines=12)
    made = list(batches(list(RunLog.read(path)), max_lines=5))
    assert [len(b) for b in made] == [5, 5, 2]


def test_the_batches_keep_the_order(tmp_path: Path) -> None:
    path = write_log(tmp_path, lines=7)
    made = list(batches(list(RunLog.read(path)), max_lines=3))
    assert [e.seq for b in made for e in b] == [1, 2, 3, 4, 5, 6, 7]


# ─────────────────────────── HTTP ───────────────────────────


def test_the_uploader_posts_to_the_contract_path() -> None:
    import httpx

    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"run_id": RUN, "accepted": 1, "duplicates": 0, "rejected": []})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    found = HttpUploader(base_url="http://center:8800", api_key="k-1", client=client).send(
        RUN, [RunEvent(schema=1, run_id=RUN, seq=1, ts="2026-10-05T10:00:00+09:00", kind="log",
                       data={"level": "info", "message": "한 줄"})]
    )
    assert found.accepted == 1
    assert seen["url"] == f"http://center:8800/api/v1/runs/{RUN}/events"
    assert seen["auth"] == "Bearer k-1"


@pytest.mark.parametrize(("status", "fatal"), [(401, True), (403, True), (503, False), (500, False)])
def test_the_uploader_tells_apart_what_is_worth_retrying(status: int, fatal: bool) -> None:
    import httpx

    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(status)))
    with pytest.raises(ShipError) as caught:
        HttpUploader(base_url="http://center:8800", api_key="k", client=client).send(RUN, [])
    assert caught.value.fatal is fatal
