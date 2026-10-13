"""C12 (서버 실행기 ↔ Center) 모델과 검사.

규칙이 **보내는 쪽과 받는 쪽에서 같아야** 하므로 함수를 계약에 두었다 — 여기가 그 함수를
지킨다. 결정의 까닭은 [ADR-0054](../docs/decisions/0054-server-run-state-and-concurrency.md)와
스파이크 `spikes/s10-server-runner-state/`에 있다.
"""

from __future__ import annotations

import pytest

from chaeksas.contracts import (
    DEFAULT_MAX_CONCURRENCY,
    DEFAULT_PER_BOT_CONCURRENCY,
    KNOWN_RESTORE_REFUSALS,
    KNOWN_RUNNER_STATUSES,
    KNOWN_WAITING_FOR,
    WAITING_REQUIRES,
    Capacity,
    RunnerVersions,
    RunningRun,
    ServerRunnerHeartbeatRequest,
    ServerRunnerHeartbeatResponse,
    ServerRunnerRegisterRequest,
    ServerRunnerRegisterResponse,
    WaitingRun,
    free_slots,
    pick_jobs,
    restorable,
    validate_runner_heartbeat,
)

AT = "2026-10-13T09:00:00+09:00"
MACHINE = "a" * 64


def running(run_id: str, *, bot: str = "finance.invoice-issue") -> RunningRun:
    return RunningRun(run_id=run_id, bpm_process_id=bot, version="1.0.0", started_at=AT)


def waiting(run_id: str, *, kind: str = "approval", **extra: object) -> WaitingRun:
    fields: dict[str, object] = {"request_id": "apr_1"} if kind == "approval" else {}
    body: dict[str, object] = {
        "run_id": run_id, "bpm_process_id": "finance.invoice-issue", "version": "1.0.0",
        "waiting_for": kind, "since": AT, **fields, **extra,
    }
    return WaitingRun.model_validate(body)


def heartbeat(**extra: object) -> ServerRunnerHeartbeatRequest:
    body: dict[str, object] = {
        "schema": 1, "status": "running",
        "capacity": Capacity(max=10, running=0),
        **extra,
    }
    return ServerRunnerHeartbeatRequest.model_validate(body)


# ─────────────────────────── 등록 ───────────────────────────


def test_register_does_not_carry_its_own_id() -> None:
    """신원은 **Center API 키**로 정한다 (C4와 같다) — 본문에 `server_runner_id`가 없다."""
    assert "server_runner_id" not in ServerRunnerRegisterRequest.model_fields


def test_register_defaults_to_the_documented_limit() -> None:
    request = ServerRunnerRegisterRequest(
        schema=1, machine_id=MACHINE, name="srv-1", os="Ubuntu 24.04",
        versions=RunnerVersions(server_runner="0.1.0", core="0.1.0"),
    )
    assert request.max_concurrency == DEFAULT_MAX_CONCURRENCY == 10


def test_register_refuses_a_zero_limit() -> None:
    """상한 0인 실행기는 **등록되지 말아야 한다** — 영원히 빈자리가 없는 행이 남는다."""
    with pytest.raises(ValueError, match="max_concurrency"):
        ServerRunnerRegisterRequest(
            schema=1, machine_id=MACHINE, name="srv-1", os="Ubuntu 24.04",
            versions=RunnerVersions(server_runner="0.1.0", core="0.1.0"), max_concurrency=0,
        )


def test_register_response_has_no_key_expiry_by_default() -> None:
    """**없으면 「만료 없음」**이고 「모른다」가 아니다 (C4·C7과 같다)."""
    response = ServerRunnerRegisterResponse(server_runner_id="srv_1a2b3c4d", server_time=AT)
    assert response.key_expires_at is None
    assert response.heartbeat_interval_s == 10


def test_runner_id_shape() -> None:
    with pytest.raises(ValueError, match="server_runner_id"):
        ServerRunnerRegisterResponse(server_runner_id="bui_1a2b3c4d", server_time=AT)


# ─────────────────────────── 하트비트 검사 ───────────────────────────


def test_a_plain_heartbeat_is_fine() -> None:
    assert validate_runner_heartbeat(heartbeat()) == []


def test_running_count_must_match_the_list() -> None:
    """Center가 빈자리를 `max - running`으로 세므로 **둘이 어긋나면 상한이 거짓이 된다**."""
    found = validate_runner_heartbeat(
        heartbeat(capacity=Capacity(max=10, running=3), running=[running("run_a")])
    )
    assert any("running[] 길이" in p for p in found)


def test_running_cannot_exceed_the_limit() -> None:
    found = validate_runner_heartbeat(heartbeat(capacity=Capacity(max=2, running=3)))
    assert any("max(2)보다 크다" in p for p in found)


def test_a_run_cannot_be_running_and_waiting_at_once() -> None:
    """쥐면서 놓을 수는 없다 — 기다리는 실행은 **자리를 놓는다** (ADR-0054 §5)."""
    found = validate_runner_heartbeat(
        heartbeat(
            capacity=Capacity(max=10, running=1),
            running=[running("run_a")], waiting=[waiting("run_a")],
        )
    )
    assert any("같이 있는 실행" in p for p in found)


def test_the_same_run_cannot_appear_twice() -> None:
    found = validate_runner_heartbeat(
        heartbeat(capacity=Capacity(max=10, running=0), waiting=[waiting("run_a"), waiting("run_a")])
    )
    assert any("두 번 있다" in p for p in found)


@pytest.mark.parametrize(("kind", "needed"), sorted(WAITING_REQUIRES.items()))
def test_waiting_needs_its_partner_field(kind: str, needed: str) -> None:
    """`waiting_for`마다 짝이 되는 칸이 있어야 한다 — 없으면 **무엇을 기다리는지 모른다**."""
    bare = WaitingRun(
        run_id="run_a", bpm_process_id="b", version="1.0.0", waiting_for=kind, since=AT
    )
    found = validate_runner_heartbeat(heartbeat(waiting=[bare]))
    assert any(needed in p for p in found)

    filled = waiting("run_a", kind=kind, **{needed: "x" if needed != "until" else AT})
    assert validate_runner_heartbeat(heartbeat(waiting=[filled])) == []


def test_unknown_status_is_not_refused() -> None:
    """상태는 **열린 문자열**이다 — 모르는 값 하나로 하트비트 전체를 거부하지 않는다 (원칙 10)."""
    assert "frozen" not in KNOWN_RUNNER_STATUSES
    assert validate_runner_heartbeat(heartbeat(status="frozen")) == []


def test_unknown_waiting_for_is_not_refused() -> None:
    assert "signal" not in KNOWN_WAITING_FOR  # 신호는 한 실행 안의 가지 사이에서만 간다 (C14)
    odd = WaitingRun(
        run_id="run_a", bpm_process_id="b", version="1.0.0", waiting_for="signal", since=AT
    )
    assert validate_runner_heartbeat(heartbeat(waiting=[odd])) == []


def test_restored_is_empty_unless_the_runner_says_so() -> None:
    assert heartbeat().restored == []
    assert heartbeat(restored=["run_20261013_090000_aa11bb"]).restored == [
        "run_20261013_090000_aa11bb"
    ]


def test_unknown_fields_are_kept() -> None:
    """받는 쪽은 관대하게 (원칙 3) — 모르는 선택 칸은 버리지 않고 보관한다."""
    parsed = heartbeat(future_field={"a": 1})
    assert parsed.to_json_dict()["future_field"] == {"a": 1}


# ─────────────────────────── 자리 셈 ───────────────────────────


def test_free_slots_counts_what_is_running() -> None:
    assert free_slots(Capacity(max=10, running=3)) == 7


def test_waiting_runs_do_not_take_slots() -> None:
    """상한 3에 기다리는 3건을 들고도 **새 작업 3건을 더 받는다** (C12 — PC와 거꾸로다)."""
    capacity = Capacity(max=3, running=0)  # 셋 다 `waiting[]`에 있다
    assert free_slots(capacity) == 3


def test_paused_runner_gets_nothing() -> None:
    assert free_slots(Capacity(max=10, running=0), paused=True) == 0


def test_no_negative_slots() -> None:
    assert free_slots(Capacity(max=2, running=5)) == 0


# ─────────────────────────── 작업 고르기 ───────────────────────────


def test_jobs_come_in_arrival_order() -> None:
    taken, skipped = pick_jobs(
        [("job_1", "a"), ("job_2", "a"), ("job_3", "b")], slots=2, running_per_bot={}
    )
    assert taken == ["job_1", "job_2"]
    assert skipped == {}


def test_per_bot_limit_is_skipped_not_blocking() -> None:
    """상한에 걸린 Bot 하나가 **대기열 전체를 멈추지 않는다** (C12 §3 — 건너뛰고 다음을 본다)."""
    taken, skipped = pick_jobs(
        [("job_1", "busy"), ("job_2", "free")],
        slots=5,
        running_per_bot={"busy": DEFAULT_PER_BOT_CONCURRENCY},
    )
    assert taken == ["job_2"]
    assert skipped == {"job_1": "per_bot_limit"}


def test_picking_counts_what_it_just_picked() -> None:
    """같은 Bot을 연달아 고를 때 **고른 것도 센다** — 아니면 한 번에 상한을 넘겨 보낸다."""
    queued = [(f"job_{i}", "a") for i in range(1, 8)]
    taken, skipped = pick_jobs(queued, slots=7, running_per_bot={}, per_bot_limit={"a": 2})
    assert taken == ["job_1", "job_2"]
    assert set(skipped) == {f"job_{i}" for i in range(3, 8)}


def test_slots_bound_the_pick() -> None:
    taken, _ = pick_jobs([("job_1", "a"), ("job_2", "b")], slots=0, running_per_bot={})
    assert taken == []


# ─────────────────────────── 되살리기 판정 (ADR-0054) ───────────────────────────


def test_a_waiting_run_of_the_same_version_resumes() -> None:
    assert restorable(
        "finance.invoice-issue", "1.0.0",
        installed_process_id="finance.invoice-issue", installed_version="1.0.0", had_wait=True,
    ) == (True, None)


def test_a_different_version_does_not_resume() -> None:
    """다른 판으로 이어 가면 **없는 노드를 밟는다** — 그림은 담지 않고 다시 읽기 때문이다."""
    ok, why = restorable(
        "finance.invoice-issue", "1.0.0",
        installed_process_id="finance.invoice-issue", installed_version="1.1.0", had_wait=True,
    )
    assert (ok, why) == (False, "runner_version_changed")


def test_an_uninstalled_package_does_not_resume() -> None:
    ok, why = restorable(
        "finance.invoice-issue", "1.0.0",
        installed_process_id=None, installed_version=None, had_wait=True,
    )
    assert (ok, why) == (False, "runner_version_changed")


def test_a_run_that_never_waited_does_not_resume() -> None:
    """처음부터 다시 돌리면 메일·웹훅을 **두 번 보낸다** (멱등이 아니다)."""
    ok, why = restorable(
        "finance.invoice-issue", "1.0.0",
        installed_process_id="finance.invoice-issue", installed_version="1.0.0", had_wait=False,
    )
    assert (ok, why) == (False, "runner_restarted")


def test_every_refusal_reason_is_a_known_value() -> None:
    """사유는 C5 `run_status`의 `error_code`로도 가므로 **목록과 맞아야** 한다."""
    reasons = {
        restorable("a", "1", installed_process_id=None, installed_version=None, had_wait=True)[1],
        restorable("a", "1", installed_process_id="a", installed_version="1", had_wait=False)[1],
    }
    assert reasons <= KNOWN_RESTORE_REFUSALS


# ─────────────────────────── 응답 ───────────────────────────


def test_deployments_stay_as_plain_json() -> None:
    """C2 봉투를 모델로 바꿔 다시 직렬화하면 **서명이 깨진다** (C4와 같은 이유)."""
    envelope = {"schema": 1, "kind": "deployment", "payload": {"x": 1}, "sig": "QUJD"}
    response = ServerRunnerHeartbeatResponse(server_time=AT, deployments=[envelope])
    assert response.deployments[0] == envelope


def test_paused_is_false_by_default() -> None:
    assert ServerRunnerHeartbeatResponse(server_time=AT).paused is False


def test_admin_keys_omitted_means_unchanged() -> None:
    """생략 = 그대로 (C4와 같다). 빈 목록과 **다른 뜻**이다 — 빈 목록은 「하나도 없다」다."""
    response = ServerRunnerHeartbeatResponse(server_time=AT)
    assert response.admin_keys is None
    assert "admin_keys" not in response.to_json_dict()
