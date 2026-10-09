"""대기열·ack (C4 「작업 상태 흐름」·「작업이 사라지지 않게」, ADR-0014).

Center를 붙이지 않고 `Agent`에 응답을 직접 먹인다 — 규칙만 보는 시험이다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chaeksas.bot_ui.agent import Agent
from chaeksas.bot_ui.settings import Settings
from chaeksas.bot_ui.store import SEEN_JOBS_MAX, Store
from chaeksas.contracts.bot_ui import HeartbeatResponse, JobDispatch, QueueItem

AT = "2026-10-03T09:00:00+09:00"


def agent(tmp_path: Path, *, queue_max: int = 20) -> Agent:
    return Agent(
        settings=Settings(queue_max=queue_max),
        store=Store.load(tmp_path / "state.json"),
    )


def job(job_id: str, *, bpm: str = "erp.order-entry", inputs: dict[str, object] | None = None) -> JobDispatch:
    return JobDispatch(
        job_id=job_id,
        bpm_process_id=bpm,
        version="2.1.0",
        inputs=inputs or {},
        requested_by="홍길동",
        requested_at=AT,
    )


# ─────────────────────────── 받기 ───────────────────────────


def test_a_job_goes_to_the_queue_and_is_acked_as_queued(tmp_path: Path) -> None:
    found = agent(tmp_path)
    ack = found.take_job(job("job_1"))
    assert (ack.result, ack.position) == ("queued", 1)
    assert [item.bpm_process_id for item in found.queue] == ["erp.order-entry"]
    # ack는 다음 하트비트에 실린다 (아직 Center가 모른다).
    assert [a.job_id for a in found.store.state.pending_acks] == ["job_1"]


def test_the_same_job_twice_is_not_run_twice(tmp_path: Path) -> None:
    """C4 — 이미 받은 `job_id`가 다시 오면 **마지막 ack를 되돌려 보낸다.**"""
    found = agent(tmp_path)
    first = found.take_job(job("job_1"))
    again = found.take_job(job("job_1"))
    assert (again.result, again.position) == (first.result, first.position)
    assert len(found.queue) == 1, "두 번 들어가면 안 된다"


def test_a_full_queue_refuses_with_queue_full(tmp_path: Path) -> None:
    found = agent(tmp_path, queue_max=2)
    for i in range(2):
        assert found.take_job(job(f"job_{i}")).result == "queued"
    ack = found.take_job(job("job_x"))
    assert (ack.result, ack.reason) == ("rejected", "queue_full")
    assert len(found.queue) == 2


def test_inputs_stay_on_the_pc(tmp_path: Path) -> None:
    """입력 값은 실행에 필요해 들고 있지만, 하트비트에는 **값이 실리지 않는다** (C4 대기열 모양)."""
    found = agent(tmp_path)
    found.take_job(job("job_1", inputs={"금액": 1000, "비밀": "x"}))
    item = found.queue[0]
    assert found.store.state.inputs[item.queue_id] == {"금액": 1000, "비밀": "x"}

    sent = found.heartbeat_request().to_json_dict()
    assert "1000" not in str(sent) and "비밀" not in str(sent)


# ─────────────────────────── 취소 ───────────────────────────


def test_cancelling_a_queued_job_takes_it_out(tmp_path: Path) -> None:
    found = agent(tmp_path)
    found.take_job(job("job_1"))
    acks = found.cancel_jobs(["job_1"])
    assert [a.result for a in acks] == ["cancelled"]
    assert found.queue == []


def test_cancelling_a_started_job_is_refused(tmp_path: Path) -> None:
    """**이미 시작했으면 멈추지 않는다** (C4 — schema 1 범위 밖)."""
    found = agent(tmp_path)
    found.take_job(job("job_1"))
    found.claim_slot(found.queue[0])
    assert found.current_run is not None

    acks = found.cancel_jobs(["job_1"])
    assert [(a.result, a.reason) for a in acks] == [("cancel_refused", "already_started")]
    assert found.current_run is not None, "실행 중 Bot을 멈추지 않는다"


def test_cancelling_on_the_pc_tells_center_why(tmp_path: Path) -> None:
    """현장에서 뺀 것은 `rejected` + `cancelled_on_pc`다 (BUI-04)."""
    found = agent(tmp_path)
    found.take_job(job("job_1"))
    ack = found.cancel_queued(found.queue[0].queue_id)
    assert ack is not None
    assert (ack.result, ack.reason) == ("rejected", "cancelled_on_pc")
    assert found.queue == []


def test_cancelling_a_manual_item_needs_no_ack(tmp_path: Path) -> None:
    found = agent(tmp_path)
    item = found.enqueue_manual("erp.order-entry")
    assert found.cancel_queued(item.queue_id) is None
    assert found.queue == []


# ─────────────────────────── 실행 자리 ───────────────────────────


def test_only_one_run_at_a_time(tmp_path: Path) -> None:
    """ADR-0014 — PC 한 대에 실행 중 Bot은 하나다."""
    found = agent(tmp_path)
    found.enqueue_manual("a")
    found.enqueue_manual("b")
    found.claim_slot(found.queue[0])
    with pytest.raises(RuntimeError, match="실행 자리가 이미"):
        found.claim_slot(found.queue[0])


def test_claiming_a_center_job_acks_started_with_the_run_id(tmp_path: Path) -> None:
    found = agent(tmp_path)
    found.take_job(job("job_1"))
    run = found.claim_slot(found.queue[0])
    ack = found.store.state.seen_jobs["job_1"]
    assert (ack.result, ack.run_id) == ("started", run.run_id)


def test_manual_front_goes_first(tmp_path: Path) -> None:
    """BUI-04 「맨 앞에 넣기」."""
    found = agent(tmp_path)
    found.enqueue_manual("first")
    item = found.enqueue_manual("urgent", front=True)
    assert found.next_in_queue() is item


def test_a_full_queue_refuses_manual_runs_too(tmp_path: Path) -> None:
    found = agent(tmp_path, queue_max=1)
    found.enqueue_manual("a")
    with pytest.raises(RuntimeError, match="가득"):
        found.enqueue_manual("b")


# ─────────────────────────── 디스크에 남기 ───────────────────────────


def test_the_queue_survives_a_restart(tmp_path: Path) -> None:
    """C4 — 다시 켜면 대기열을 이어 간다."""
    first = agent(tmp_path)
    first.take_job(job("job_1"))
    first.store.save()

    again = agent(tmp_path)
    assert [item.job_id for item in again.queue] == ["job_1"]
    # 아직 Center가 확인하지 않은 ack도 남아 다시 간다.
    assert [a.job_id for a in again.store.state.pending_acks] == ["job_1"]
    # 이미 본 작업이라 다시 와도 대기열이 늘지 않는다.
    again.take_job(job("job_1"))
    assert len(again.queue) == 1


def test_a_broken_state_file_does_not_stop_the_app(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text("{이건 JSON이 아니다", encoding="utf-8")
    found = Store.load(path)
    assert found.state.queue == [] and found.state.bot_ui_id is None


def test_seen_jobs_do_not_grow_forever(tmp_path: Path) -> None:
    # 대기열은 1칸이라 첫 작업만 들어가고 나머지는 거절된다 — 그래도 **본 작업은 기억한다.**
    found = agent(tmp_path, queue_max=1)
    for i in range(SEEN_JOBS_MAX + 50):
        found.take_job(job(f"job_{i}"))
    assert len(found.store.state.seen_jobs) == SEEN_JOBS_MAX


def test_acks_are_dropped_once_center_has_them(tmp_path: Path) -> None:
    found = agent(tmp_path)
    found.take_job(job("job_1"))
    request = found.heartbeat_request()
    found.store.ack_sent(request.job_acks)
    assert found.store.state.pending_acks == []
    # 기억은 남는다 — 같은 작업이 또 오면 되돌려 보낸다.
    assert "job_1" in found.store.state.seen_jobs


# ─────────────────────────── 응답 전체 ───────────────────────────


def test_apply_handles_cancel_before_new_jobs(tmp_path: Path) -> None:
    """같은 응답에 「새 작업」과 「취소」가 함께 올 수 있다 — 취소를 먼저 본다."""
    found = agent(tmp_path)
    found.store.state.queue.append(
        QueueItem(queue_id="q_old", source="job", bpm_process_id="old", job_id="job_old", requested_at=AT)
    )
    found.apply(HeartbeatResponse(server_time=AT, jobs=[job("job_new")], cancel_jobs=["job_old"]))
    assert [item.job_id for item in found.queue] == ["job_new"]
    assert found.store.state.seen_jobs["job_old"].result == "cancelled"


def test_the_wait_is_measured_from_the_request() -> None:
    """C3 `run_started.queued_s` — 요청 시각부터 띄우는 시각까지 (`waited()`)."""
    from datetime import UTC, datetime, timedelta

    from chaeksas.bot_ui.agent import waited
    from chaeksas.contracts.bot_ui import QueueItem

    asked = datetime(2026, 10, 9, 10, 15, tzinfo=UTC)
    item = QueueItem(
        queue_id="q1", source="job", bpm_process_id="erp.order-entry", requested_at=asked.isoformat()
    )
    assert waited(item, now=asked + timedelta(seconds=42.5)) == 42.5
    # 시계가 거꾸로 간 경우도 음수를 적지 않는다.
    assert waited(item, now=asked - timedelta(seconds=5)) == 0
    # **모르면 `None`** — 0을 넣으면 「기다리지 않았다」가 된다.
    assert waited(item.model_copy(update={"requested_at": "깨진 값"})) is None
