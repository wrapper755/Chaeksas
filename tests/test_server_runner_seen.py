"""멱등 기억이 **무한히 자라지 않고, 닿지 않은 ack를 잃지 않는다** (C4·C12, ADR-0056).

이 자리가 있는 까닭은 하나다 — Center는 ack가 올 때까지 같은 지시를 하트비트마다 다시 싣고
(C4·ADR-0007), 받는 쪽은 **두 번 돌리지 않고 마지막 ack를 되돌려 보내야** 한다. 그래서 여기서
보는 것도 둘이다: **자라지 않는가**와 **되돌려 보낼 것을 잃지 않는가**.

키는 그냥 글자라서 `Seen`은 **무엇의 ack인지 모른다** — 그래서 이 시험은 작업(`job_id`)으로
쓰지만 메시지(`message_id`, C12 §메시지)에도 그대로 적용된다. 규칙을 한 자리에 둔 까닭이다.
"""

from __future__ import annotations

from chaeksas.contracts.bot_ui import JobAck
from chaeksas.server_runner.seen import CAP, GRACE_CYCLES, Seen


def ack(job_id: str, result: str = "started") -> JobAck:
    return JobAck(job_id=job_id, result=result, run_id=f"run_{job_id}")


# ─────────────────────────── 자라지 않는다 ───────────────────────────


def test_a_long_stream_of_ids_does_not_grow_the_map() -> None:
    """바깥 시스템이 밀어 넣는 긴 줄 — **상한 안에 머문다** (C12 §메시지는 수가 크다)."""
    found: Seen[JobAck] = Seen()
    for n in range(CAP * 5):
        found.remember(f"msg_{n}", ack(f"msg_{n}"))
        # 한 주기에 하나씩 내려와 ack가 닿는 흐름 (평상시 모습).
        found.delivered([f"msg_{n}"])

    assert len(found) <= GRACE_CYCLES + 1, (
        "닿은 뒤 두 주기면 잊는다 — 들고 있는 것은 최근 몇 개뿐이다"
    )
    assert found.get("msg_0") is None, "맨 처음 것은 잊었다"


def test_a_burst_bigger_than_the_cap_is_trimmed() -> None:
    """한 주기에 상한을 넘게 와도 **상한 근처에 머문다** (규칙 3 — 그물)."""
    found: Seen[JobAck] = Seen()
    ids = [f"msg_{n}" for n in range(CAP * 2)]
    for one in ids:
        found.remember(one, ack(one))
    # 아직 하나도 닿지 않았다 — 규칙 2가 **버리지 않는다** (그래서 상한을 넘어 있다).
    assert len(found) == CAP * 2

    found.delivered(ids)  # 한 하트비트가 다 실어 올렸다
    assert len(found) <= CAP, "닿은 것은 오래된 것부터 잘린다"


def test_the_map_shrinks_back_after_the_acks_land() -> None:
    """닿지 않은 동안 늘어난 것은 **닿은 뒤 주기가 지나면 모두 빠진다**."""
    found: Seen[JobAck] = Seen()
    ids = [f"job_{n}" for n in range(50)]
    for one in ids:
        found.remember(one, ack(one))

    found.delivered(ids)
    for _ in range(GRACE_CYCLES):
        found.delivered([])
    assert len(found) == 0


# ─────────────────────────── 되돌려 보낼 것을 잃지 않는다 ───────────────────────────


def test_an_unacked_dispatch_is_still_remembered() -> None:
    """**ack가 닿기 전에는 버리지 않는다** — 그것이 이 자리가 있는 까닭이다 (규칙 2).

    긴 줄이 지나가도(그 동안 다른 ack는 다 닿아 잊혔다) 아직 올리지 못한 하나는 남아 있다.
    잃으면 다시 내려온 지시가 「처음 본 것」이 되어 **업무가 두 번 일어난다**.
    """
    found: Seen[JobAck] = Seen()
    found.remember("job_stuck", ack("job_stuck", result="started"))

    for n in range(CAP * 3):
        found.remember(f"msg_{n}", ack(f"msg_{n}"))
        found.delivered([f"msg_{n}"])  # 다른 것들의 ack는 닿는다

    kept = found.get("job_stuck")
    assert kept is not None, "닿지 않은 ack는 아무리 오래되어도 버리지 않는다"
    assert kept.result == "started" and kept.run_id == "run_job_stuck", (
        "되돌려 보낼 것은 마지막 ack 그대로다"
    )


def test_the_grace_window_is_two_more_cycles() -> None:
    """닿은 그 주기에 바로 버리지 않는다 — **두 주기를 더** 들고 있는다 (그물 한 겹)."""
    found: Seen[JobAck] = Seen()
    found.remember("job_1", ack("job_1"))

    found.delivered(["job_1"])  # 닿았다
    assert "job_1" in found, "닿은 그 주기에는 아직 들고 있다"
    found.delivered([])
    assert "job_1" in found, f"{GRACE_CYCLES}주기가 지나기 전에는 들고 있다"
    found.delivered([])
    assert "job_1" not in found, "두 주기가 지났으면 잊는다"


def test_a_new_ack_starts_the_window_over() -> None:
    """ack가 바뀌면 **나이가 처음으로 돌아간다** — 바뀐 ack도 닿아야 한다.

    작업은 `started` → `finished`로 ack가 바뀐다 (C4). 처음 ack가 닿은 지 오래되었다고
    잊으면 끝나는 순간의 ack를 되돌려 줄 수 없다.
    """
    found: Seen[JobAck] = Seen()
    found.remember("job_1", ack("job_1", result="started"))
    found.delivered(["job_1"])
    found.delivered([])  # 잊기 직전까지 왔다

    found.remember("job_1", ack("job_1", result="finished"))
    for _ in range(GRACE_CYCLES + 1):
        found.delivered([])  # 새 ack는 아직 닿지 않았다 — 주기가 가도 버리지 않는다
    kept = found.get("job_1")
    assert kept is not None and kept.result == "finished"

    found.delivered(["job_1"])
    for _ in range(GRACE_CYCLES):
        found.delivered([])
    assert "job_1" not in found, "새 ack도 닿았으면 그때부터 두 주기다"


def test_delivered_ignores_keys_it_never_saw() -> None:
    """모르는 키를 닿았다고 해도 **만들지 않는다** (기억은 `remember`만 늘린다)."""
    found: Seen[JobAck] = Seen()
    found.delivered(["job_nobody"])
    assert "job_nobody" not in found and len(found) == 0
