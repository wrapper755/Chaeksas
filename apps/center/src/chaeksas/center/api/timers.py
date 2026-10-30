"""타이머 시작의 일정 — 배포된 매니페스트의 `triggers[kind=timer]`를 쓸어 작업으로 만든다 (ADR-0110, C5 §일정).

**밀지 않는다** (ADR-0007) — 작업을 만들 뿐이고 받아 가는 길은 하트비트다. 그래서 쓸기도 하트비트에서
돈다 (결재 값 지우기·위임 값 지우기와 같은 결 — 따로 도는 일꾼을 두지 않는다). **분마다 한 번**이다
(`timer_sweeps` 한 줄을 고쳐 잡는다 — 하트비트마다 매니페스트를 다시 읽지 않는다).

규칙은 ADR-0110 그대로다.

- 서버 Bot은 **(Bot, 버전)마다 차례 하나에 작업 하나**이고 실행기는 Center가 고른다. PC Bot은 배포된 PC마다다.
- 놓친 차례는 **가장 최근 한 번만** 쏘고 나머지는 `missed`로 센다. 배포 전의 차례는 차례가 아니다.
- 작업의 `expires_at`은 **다음 차례**다.
- 차례는 `timer_fires`의 기본 키로 **먼저 잡고** 작업을 만든다. 작업의 멱등 키도 일정·차례로 짓는다 —
  잡은 뒤 죽으면 다음 쓸기가 같은 키로 마저 만든다.
- 만들지 못하면(Center가 거부하면) 그 차례에 코드를 적고 넘어간다.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

from chaeksas.center.api import jobs
from chaeksas.center.api.signing import STATUS_APPROVED
from chaeksas.center.auth import Caller
from chaeksas.center.errors import ApiError
from chaeksas.center.settings import DEFAULT_TIMEZONE
from chaeksas.center.storage import Store
from chaeksas.contracts.center_api import ScheduleInfo, timer_requester
from chaeksas.contracts.manifest import Manifest
from chaeksas.contracts.schedule import Cycle, CycleError, parse_cycle

log = logging.getLogger(__name__)

#: 쓸기 사이 — 식의 단위가 분이다.
SWEEP_EVERY = timedelta(minutes=1)

#: 잡았는데 작업이 없는 차례를 마저 만드는 끝 — 이보다 오래된 것은 다음 차례가 이미 덮었다.
FINISH_WITHIN = timedelta(days=1)

#: 시간대를 받지 못한 자리(하트비트를 직접 부르는 시험)의 시간대 — 설정의 기본값과 같다.
DEFAULT_ZONE: tzinfo = ZoneInfo(DEFAULT_TIMEZONE)

#: 서버 Bot의 일정은 실행기마다가 아니라 **하나**다 (Center가 실행기를 고른다).
ANY_RUNNER = "*"


@dataclass(frozen=True)
class Plan:
    """일정 하나 — (대상, Bot, 버전, 식). `anchor`는 그 대상에 지금 살아 있는 배포 중 **가장 이른 때**다."""

    key: str
    bpm_process_id: str
    version: str
    target_type: str
    target_id: str  # 서버는 `ANY_RUNNER`
    expression: str
    cycle: Cycle | None  # 읽지 못한 식이면 `None` — 쏘지 않고 `problem`을 보인다
    anchor: datetime
    problem: str | None = None


def _when(text: str) -> datetime:
    found = datetime.fromisoformat(text)
    return found if found.tzinfo else found.replace(tzinfo=UTC)


def _iso(at: datetime) -> str:
    """차례 시각은 **UTC로** 적는다 — 글자로 줄 세워도 시각 순이다."""
    return at.astimezone(UTC).isoformat()


def plans(store: Store, *, readable_only: bool = True) -> list[Plan]:
    """살아 있는 배포(승인된 패키지의 철회되지 않은 배포)의 타이머 시작들.

    고르는 기준은 `deployments.envelopes_for`와 같다 — 내려가지 않는 배포의 일정이 돌면 받을 데가 없다.
    읽지 못하는 식은 **쏘지 않는다** (R13이 올릴 때 막으므로 R13 전에 올라간 것뿐이다). 콘솔(`schedules`)은
    그것도 받아 까닭을 보인다 (`readable_only=False`).
    """
    rows = store.rows(
        "SELECT d.target_type AS target_type, d.target_id AS target_id, d.bpm_process_id AS bot,"
        " d.version AS version, d.at AS at, p.manifest_json AS body FROM deployments d"
        " JOIN packages p ON p.id = d.bpm_process_id AND p.version = d.version"
        " WHERE d.revoked_json IS NULL AND p.status = ? ORDER BY d.at",
        (STATUS_APPROVED,),
    )
    found: dict[str, Plan] = {}
    for row in rows:
        manifest = Manifest.model_validate(json.loads(str(row["body"] or "{}")))
        target_type = str(row["target_type"])
        target_id = ANY_RUNNER if target_type == "server_runner" else str(row["target_id"])
        for trigger in manifest.triggers:
            if trigger.kind != "timer" or not trigger.expression:
                continue
            key = f"{target_type}:{target_id}:{row['bot']}@{row['version']}:{trigger.expression}"
            if key in found:
                continue  # 줄은 `at` 순이라 처음 본 것이 가장 이른 배포다
            cycle: Cycle | None = None
            problem: str | None = None
            try:
                cycle = parse_cycle(trigger.expression)
            except CycleError as e:
                if readable_only:
                    log.warning("일정을 읽지 못해 건너뛴다 — %s@%s: %s", row["bot"], row["version"], e)
                    continue
                problem = str(e)
            found[key] = Plan(
                key=key,
                bpm_process_id=str(row["bot"]),
                version=str(row["version"]),
                target_type=target_type,
                target_id=target_id,
                expression=trigger.expression,
                cycle=cycle,
                anchor=_when(str(row["at"])),
                problem=problem,
            )
    return list(found.values())


def schedules(store: Store, *, tz: tzinfo, now: datetime | None = None) -> list[ScheduleInfo]:
    """`GET /schedules` (C5 §일정, CON-02 「일정」) — 일정마다 다음 차례와 마지막 차례.

    「다음 차례」는 **쓸 때와 같은 함수**로 센다 — 화면이 따로 세면 일정과 어긋난다.
    """
    at = now or datetime.now(UTC)
    zone = getattr(tz, "key", str(tz))
    out = []
    for plan in plans(store, readable_only=False):
        last = store.row(
            "SELECT slot, job_id, missed, error FROM timer_fires WHERE trigger_key = ? ORDER BY slot DESC",
            (plan.key,),
        )
        following = None
        if plan.cycle is not None:
            since = max(at, plan.anchor)
            following = plan.cycle.next_after(since, tz, anchor=plan.anchor)
        out.append(
            ScheduleInfo(
                bpm_process_id=plan.bpm_process_id,
                version=plan.version,
                target_type=plan.target_type,
                target_id=None if plan.target_type == "server_runner" else plan.target_id,
                expression=plan.expression,
                timezone=zone,
                problem=plan.problem,
                next_at=_iso(following) if following is not None else None,
                last_slot=str(last["slot"]) if last is not None else None,
                last_job_id=str(last["job_id"]) if last is not None and last["job_id"] else None,
                last_missed=int(last["missed"]) if last is not None else 0,
                last_error=str(last["error"]) if last is not None and last["error"] else None,
            )
        )
    return sorted(out, key=lambda one: (one.bpm_process_id, one.version, one.target_id or ""))


def _claim_sweep(store: Store, now: datetime) -> bool:
    """이 분의 쓸기를 잡는다 — 다른 하트비트가 이미 잡았으면 `False`."""
    edge = _iso(now - SWEEP_EVERY)
    with store.tx() as cur:
        cur.execute("INSERT INTO timer_sweeps (id, at) VALUES (1, '') ON CONFLICT (id) DO NOTHING")
        cur.execute("UPDATE timer_sweeps SET at = ? WHERE id = 1 AND at <= ?", (_iso(now), edge))
        return cur.rowcount == 1


def sweep(store: Store, *, tz: tzinfo, now: datetime | None = None, force: bool = False) -> list[str]:
    """차례가 된 일정을 작업으로 만든다. 만든(또는 멱등으로 돌려받은) 작업 id들.

    `force`는 시험만 쓴다 — 분마다 한 번의 관문을 건너뛴다.
    """
    at = now or datetime.now(UTC)
    if not force and not _claim_sweep(store, at):
        return []
    found = plans(store)
    made = _finish_claimed(store, found, tz=tz, now=at)
    for plan in found:
        job_id = _fire(store, plan, tz=tz, now=at)
        if job_id:
            made.append(job_id)
    return made


def _last_slot(store: Store, key: str) -> datetime | None:
    row = store.row("SELECT MAX(slot) AS slot FROM timer_fires WHERE trigger_key = ?", (key,))
    return _when(str(row["slot"])) if row is not None and row["slot"] else None


def _fire(store: Store, plan: Plan, *, tz: tzinfo, now: datetime) -> str | None:
    if plan.cycle is None:
        return None
    last = _last_slot(store, plan.key)
    # **배포 전의 차례는 차례가 아니다** — 거뒀다 다시 배포해도 옛 차례를 쏘지 않는다 (ADR-0110 §4).
    since = max(plan.anchor, last) if last is not None else plan.anchor
    slots = plan.cycle.between(since, now, tz, anchor=plan.anchor)
    if not slots:
        return None
    slot = slots[-1]
    with store.tx() as cur:
        cur.execute(
            "INSERT INTO timer_fires (trigger_key, slot, bpm_process_id, version, target_type, target_id,"
            " expression, missed, fired_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (trigger_key, slot) DO NOTHING",
            (
                plan.key,
                _iso(slot),
                plan.bpm_process_id,
                plan.version,
                plan.target_type,
                plan.target_id,
                plan.expression,
                len(slots) - 1,
                _iso(now),
            ),
        )
        claimed = cur.rowcount == 1
    if not claimed:
        return None  # 다른 쓸기가 먼저 잡았다
    if len(slots) > 1:
        log.info("일정 %s — 놓친 차례 %d개는 건너뛰고 %s만 쏜다", plan.key, len(slots) - 1, _iso(slot))
    return _make_job(store, plan, slot=slot, tz=tz)


def _finish_claimed(store: Store, found: list[Plan], *, tz: tzinfo, now: datetime) -> list[str]:
    """잡았는데 작업도 오류도 없는 차례 — 잡은 뒤 죽었다. **같은 멱등 키로** 마저 만든다."""
    by_key = {plan.key: plan for plan in found}
    out = []
    for row in store.rows(
        "SELECT trigger_key, slot FROM timer_fires WHERE job_id IS NULL AND error IS NULL AND fired_at >= ?",
        (_iso(now - FINISH_WITHIN),),
    ):
        plan = by_key.get(str(row["trigger_key"]))
        if plan is None:
            continue  # 그사이 배포가 거둬졌다 — 받을 데가 없다
        job_id = _make_job(store, plan, slot=_when(str(row["slot"])), tz=tz)
        if job_id:
            out.append(job_id)
    return out


def idempotency_key(key: str, slot: datetime) -> str:
    """일정·차례 → 작업 멱등 키 (ADR-0110 §6). 같은 차례는 늘 같은 키다."""
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return f"tmr_{digest}_{slot.astimezone(UTC):%Y%m%dT%H%MZ}"


def _make_job(store: Store, plan: Plan, *, slot: datetime, tz: tzinfo) -> str | None:
    key = plan.key
    following = plan.cycle.next_after(slot, tz, anchor=plan.anchor) if plan.cycle is not None else None
    target: dict[str, Any] = {"type": plan.target_type}
    if plan.target_type != "server_runner":
        target["id"] = plan.target_id
    body: dict[str, Any] = {
        "schema": 1,
        "bpm_process_id": plan.bpm_process_id,
        "version": plan.version,
        "target": target,
        # **입력은 비운다** — 기본값과 값 출처가 채운다 (ADR-0110 §7, ADR-0099).
        "inputs": {},
        "note": f"일정 {plan.expression} — {slot.astimezone(tz):%Y-%m-%d %H:%M}",
        "idempotency_key": idempotency_key(key, slot),
    }
    if following is not None:
        # **차례는 다음 차례까지만 산다** (ADR-0110 §5) — 어제 것과 오늘 것을 둘 다 돌지 않는다.
        body["expires_at"] = _iso(following)
    caller = Caller(kind="center", actor=timer_requester(plan.expression))
    try:
        info, _made = jobs.create(store, caller, body, by_center=True)
    except ApiError as e:
        log.warning("일정 %s의 작업을 만들지 못했다 — %s: %s", key, e.code, e.message)
        with store.tx() as cur:
            cur.execute(
                "UPDATE timer_fires SET error = ? WHERE trigger_key = ? AND slot = ?",
                (e.code, key, _iso(slot)),
            )
        return None
    with store.tx() as cur:
        cur.execute(
            "UPDATE timer_fires SET job_id = ? WHERE trigger_key = ? AND slot = ?",
            (info.job_id, key, _iso(slot)),
        )
    return info.job_id
