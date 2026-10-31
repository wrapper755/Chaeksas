"""외부 작업 — 부르는 쪽이 올리고, 일꾼이 가져가 끝낸다 (C15, ADR-0102).

| 경로 | 인증 |
| --- | --- |
| `POST /external-tasks`, `GET·ack·cancel …/{task_id}` | PC 실행기·서버 실행기·Studio의 Center API 키 |
| `POST /consumers/enroll`, `GET …/enroll/{id}` | 없음 — 토큰은 요청의 공개키로 봉해 내려 준다 |
| `POST /consumers/fetch`, `…/tasks/{id}/complete·fail·extend`, `PUT …/self/manifest` | 일꾼 토큰 |
| `GET /consumers`, `GET /external-topics` | 콘솔 토큰 |

지키는 것:

- **연결은 늘 Center 쪽으로 나간다.** Center는 일꾼에게도, 부르는 쪽에게도 먼저 닿지 않는다.
- **최소 한 번 실행이다** — 잠금이 지나면 다시 나간다. 같은 일을 두 번 하지 않는 것은 일꾼의 몫이다.
- **기한에 실패한다** — 아무도 안 가져가면 `no_consumer`, 가져갔는데 안 끝나면 `timeout`.
- **값은 받을 때까지만** — `ack`가 오면 입력·출력을 지운다. 못 받은 것은 7일에 지운다.
- **「불러도 되나」는 배포가 말한다** — 그 실행의 BPM 프로세스가 그 토픽을 요구하는가(C1). 키마다 허용 작업을
  달던 일(ADR-0094)이 여기 한 자리로 모인다.

시간을 밀어야 하는 판단(만료·잠금 풀기·청소)은 `sweep()` 하나이고 읽는 자리마다 부른다 — 따로 도는
일꾼이 없다 (`enrollments.sweep`과 같은 결).
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from chaeksas.center import enrollments, keys
from chaeksas.center.api import bot_ui, deployments, resources, server_runner
from chaeksas.center.auth import Caller, require_console
from chaeksas.center.errors import ApiError
from chaeksas.center.storage import Store, dumps, loads, now_iso
from chaeksas.contracts.center_keys import BoundTo
from chaeksas.contracts.external_task import (
    CALL_TOKEN,
    CALL_TOKEN_HOURS,
    CODE_NO_CONSUMER,
    CODE_TIMEOUT,
    CONSUMER,
    FINAL_STATES,
    KNOWN_ORIGINS,
    MAX_TASKS_PER_FETCH,
    MAX_VALUE_BYTES,
    MAX_WAIT_S,
    PURGE_AFTER_DAYS,
    RETRYABLE_CODES,
    STATE_CANCELLED,
    STATE_COMPLETED,
    STATE_EXPIRED,
    STATE_FAILED,
    STATE_LOCKED,
    STATE_PENDING,
    TEST_RUN_PREFIX,
    CallToken,
    CompleteRequest,
    ConsumerInfo,
    ExtendRequest,
    ExternalTaskCreate,
    ExternalTaskCreated,
    ExternalTaskInfo,
    ExternalTaskResult,
    FailRequest,
    FetchRequest,
    FetchResponse,
    LockedTask,
    TaskError,
    TopicStatus,
    body_hash,
    missing_outputs,
    task_id_for,
)
from chaeksas.contracts.manifest import Manifest
from chaeksas.contracts.service_app import DEFAULT_TIMEOUT_S, ServiceAppManifest, Usage

router = APIRouter(prefix="/api/v1", tags=["external-tasks"])

#: 부를 수 있는 Center API 키 종류 (C15 §전송). 호출 토큰은 조각 2에서 PC 실행기 키의 신원으로 얹힌다.
POSTER_KEY_TYPES = frozenset({"bot_ui", "server_runner", "studio"})
STUDIO = "studio"
#: 키 종류 → 등록 표 (소유·배포 대조의 대상). Studio는 표가 없다 (C5 §Studio 등록 요청과 승인).
_HOST_IDS = {"bot_ui": bot_ui.id_for_key, "server_runner": server_runner.id_for_key}
#: 한 번 기다릴 때 깨어나 다시 보는 간격 (초) — 잠금이 풀리거나 기한이 지나는 것은 종이 울리지 않는다.
_RECHECK_S = 1.0
#: 본문 한도 — 값 한도(1 MB) 위에 칸 몇 개가 더 붙는다.
_BODY_LIMIT = MAX_VALUE_BYTES + 64 * 1024


# ─────────────────────────── 시간 ───────────────────────────


def _at(text: str) -> datetime:
    return datetime.fromisoformat(text)


def _later(now: str, seconds: float) -> str:
    return (_at(now) + timedelta(seconds=seconds)).isoformat()


def _earlier(a: str, b: str) -> str:
    return a if _at(a) <= _at(b) else b


def _size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))


# ─────────────────────────── 부르는 쪽 ───────────────────────────


@dataclass(frozen=True)
class Poster:
    """올린 쪽. `host_id`는 PC 실행기·서버 실행기의 등록 id이고 Studio는 `None`이다."""

    key_id: str
    kind: str
    host_id: str | None


def poster_of(store: Store, found: Caller) -> Poster:
    """올릴 수 있는 쪽인가 (C15 §전송). 등록되지 않은 PC 실행기·실행기는 409 `not_registered`.

    **호출 토큰은 그것을 청한 쪽으로 본다** — 소유(C3)·배포 대조가 그 PC 실행기(또는 Studio)의 키로 돈다.
    """
    if found.key is not None and found.key.type == CALL_TOKEN:
        bound = found.key.bound_to
        if bound is not None and bound.type == STUDIO:
            parent = keys.get(store, bound.id)
            if parent is None or parent.state(now=now_iso()) != "active":
                raise ApiError(409, "not_registered", "호출 토큰을 청한 Studio 키가 없다")
            return Poster(key_id=parent.key_id, kind=STUDIO, host_id=None)
        row = (
            store.row("SELECT key_id FROM bot_uis WHERE bot_ui_id = ?", (bound.id,)) if bound is not None else None
        )
        if bound is None or row is None or not row["key_id"]:
            raise ApiError(409, "not_registered", "호출 토큰을 청한 PC 실행기가 없다")
        return Poster(key_id=str(row["key_id"]), kind="bot_ui", host_id=bound.id)
    if found.key is None or found.key.type not in POSTER_KEY_TYPES:
        raise ApiError(403, "wrong_key_type", "외부 작업은 PC 실행기·서버 실행기·Studio의 Center API 키로 올린다")
    kind = found.key.type
    if kind == STUDIO:
        return Poster(key_id=found.key.key_id, kind=kind, host_id=None)
    host_id = _HOST_IDS[kind](store, found.key.key_id)
    if host_id is None:
        raise ApiError(409, "not_registered", "등록되지 않은 Center API 키다")
    return Poster(key_id=found.key.key_id, kind=kind, host_id=host_id)


def issue_call_token(store: Store, found: Caller, *, now: str | None = None) -> CallToken:
    """`POST /call-tokens` — PC 실행기·Studio만, 24시간 (C15 「정한 것」). 지난 토큰은 이때 지운다."""
    if found.key is None or found.key.type not in ("bot_ui", STUDIO):
        raise ApiError(403, "wrong_key_type", "호출 토큰은 PC 실행기·Studio의 Center API 키로 청한다")
    if found.key.type == STUDIO:
        bound = BoundTo(type=STUDIO, id=found.key.key_id, name=found.key.name)
    else:
        bot_ui_id = bot_ui.id_for_key(store, found.key.key_id)
        if bot_ui_id is None:
            raise ApiError(409, "not_registered", "등록되지 않은 Center API 키다")
        bound = BoundTo(type="bot_ui", id=bot_ui_id, name=found.key.name)
    at = now or now_iso()
    with store.tx() as cur:
        cur.execute(
            "DELETE FROM center_keys WHERE type = ? AND expires_at <= ?", (CALL_TOKEN, _later(at, -86400))
        )
    record, raw = keys.issue(
        store,
        name=f"호출 토큰 · {found.key.name}",
        key_type=CALL_TOKEN,
        expires_at=_later(at, CALL_TOKEN_HOURS * 3600),
        bound=bound,
    )
    assert record.expires_at is not None
    return CallToken(token=raw, expires_at=record.expires_at)


def _topic_manifest(store: Store, topic: str) -> ServiceAppManifest | None:
    """그 토픽에 들인 일꾼이 올린 manifest (가장 최근에 승인된 것). 없으면 `None` — 그때는 작업을
    대조하지 않는다 (아무도 없으면 기한에 `no_consumer`로 실패한다). 고르는 규칙은 리소스 목록과 같다."""
    found = resources.app_manifests(store).get(topic)
    return found[0] if found is not None else None


def _owns_the_run(store: Store, *, run_id: str, key_id: str) -> bool:
    """그 실행 기록을 보낸 키인가 (C3 소유). **기록이 아직 없으면 받아 준다** — 실행 기록은 하트비트
    뒤에 올라가므로 첫 호출이 먼저 닿는다 (PC 위임과 같은 규칙)."""
    row = store.row("SELECT owner_key_id FROM runs WHERE run_id = ?", (run_id,))
    return row is None or row["owner_key_id"] == key_id


def _bot_requires(store: Store, poster: Poster, *, bot: str | None, version: str | None, topic: str) -> bool:
    """그 BPM 프로세스가 이 호스트에 배포돼 있고 그 판의 매니페스트가 이 토픽을 요구하는가 (C1)."""
    if not bot or not version or poster.host_id is None:
        return False
    if version not in deployments.versions_for(
        store, target_type=poster.kind, target_id=poster.host_id, bpm_process_id=bot
    ):
        return False
    row = store.row("SELECT manifest_json FROM packages WHERE id = ? AND version = ?", (bot, version))
    if row is None:
        return False
    manifest = Manifest.model_validate(json.loads(str(row["manifest_json"] or "{}")))
    wanted = {one.app_id for one in manifest.requires.service_apps} | {one.id for one in manifest.requires.extensions}
    return topic in wanted


def _authorize(store: Store, poster: Poster, task: ExternalTaskCreate) -> int:
    """「불러도 되나」 (C15 §올리기 표). 통과하면 기한(초)을 돌려준다."""
    run_id = task.idempotency.run_id
    if poster.kind == STUDIO:
        if not run_id.startswith(TEST_RUN_PREFIX):
            raise ApiError(403, "run_not_owned", f"Studio는 시험 실행(`{TEST_RUN_PREFIX}…`)으로만 올린다")
    else:
        if run_id.startswith(TEST_RUN_PREFIX) or not _owns_the_run(store, run_id=run_id, key_id=poster.key_id):
            raise ApiError(403, "run_not_owned", "이 키의 실행이 아니다")
        if task.mode == "autonomous":
            raise ApiError(403, "mode_not_allowed", "자율 수행은 Studio에서만 올린다")
        if not _bot_requires(
            store, poster, bot=task.caller.bpm_process_id, version=task.caller.version, topic=task.topic
        ):
            raise ApiError(
                403,
                "topic_not_required",
                f"이 호스트에 배포된 BPM 프로세스가 토픽 「{task.topic}」을 요구하지 않는다",
                {"bpm_process_id": task.caller.bpm_process_id, "version": task.caller.version},
            )
    manifest = _topic_manifest(store, task.topic)
    timeout = task.timeout_s
    if manifest is not None:
        operation = manifest.operation(task.operation)
        if operation is None:
            raise ApiError(422, "operation_not_found", f"「{task.topic}」에 작업 「{task.operation}」이 없다")
        if not operation.supports(task.mode):
            raise ApiError(422, "mode_unsupported", f"작업 「{task.operation}」은 {task.mode}를 받지 않는다")
        if operation.required_scopes:
            # 추가 권한을 주는 길이 지금은 없다 — 그런 작업은 아무도 올리지 못한다 (ADR-0114).
            raise ApiError(
                403, "scope_missing", "이 작업에 필요한 권한을 줄 길이 없다",
                {"scopes": sorted(operation.required_scopes)},
            )
        timeout = timeout or operation.timeout_s
    return timeout or DEFAULT_TIMEOUT_S


def create(
    store: Store, found: Caller, raw: dict[str, Any], *, now: str | None = None
) -> tuple[ExternalTaskCreated, bool]:
    """`POST /external-tasks` (C15 §올리기). `(응답, 새로 만들었나)` — 같은 칸이면 같은 일감이다."""
    poster = poster_of(store, found)
    try:
        task = ExternalTaskCreate.model_validate(raw)
    except ValueError as e:
        higher = isinstance(raw.get("schema"), int) and raw["schema"] > ExternalTaskCreate.SCHEMA
        code = "schema_unsupported" if higher else "input_invalid"
        raise ApiError(422, code, "일감이 계약과 맞지 않는다", {"error": str(e).splitlines()[0]}) from e
    if task.origin not in KNOWN_ORIGINS:
        raise ApiError(422, "input_invalid", f"모르는 origin이다: {task.origin}")
    if _size(task.input) > MAX_VALUE_BYTES:
        raise ApiError(413, "too_large", "입력이 1 MB를 넘는다")
    task_id = task_id_for(task.topic, task.operation, task.idempotency)
    digest = body_hash(task)
    at = now or now_iso()
    sweep(store, now=at)

    existing = store.row(
        "SELECT poster_key_id, body_hash, state, acked_at FROM external_tasks WHERE task_id = ?", (task_id,)
    )
    if existing is not None:
        if existing["poster_key_id"] != poster.key_id or existing["body_hash"] != digest:
            raise ApiError(409, "idempotency_conflict", "같은 멱등 칸에 다른 본문이다", {"task_id": task_id})
        if existing["acked_at"] is None:
            return ExternalTaskCreated(task_id=task_id, state=str(existing["state"])), False
    timeout = _authorize(store, poster, task)
    with store.tx() as cur:
        if existing is not None:
            # **받아 간 뒤에 다시 올렸다** — 값은 이미 지웠으니 옛 일감을 돌려주면 빈 결과다. 다시 줄에
            # 세운다: 일꾼이 멱등 칸으로 저장해 둔 결과를 다시 준다 (C15 「최소 한 번」).
            cur.execute("DELETE FROM external_tasks WHERE task_id = ?", (task_id,))
        cur.execute(
            "INSERT INTO external_tasks (task_id, topic, operation, mode, origin, idempotency_json, caller_json,"
            " business_key, body_hash, poster_key_id, want_result, input_json, state, created_at, deadline)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task_id,
                task.topic,
                task.operation,
                task.mode,
                task.origin,
                dumps(task.idempotency.to_json_dict()),
                dumps(task.caller.to_json_dict()),
                task.business_key,
                digest,
                poster.key_id,
                1 if task.want_result else 0,
                dumps(task.input),
                STATE_PENDING,
                at,
                _later(at, timeout),
            ),
        )
    return ExternalTaskCreated(task_id=task_id, state=STATE_PENDING), True


def _poster_row(store: Store, found: Caller, task_id: str) -> Any:
    """올린 쪽만 본다 — 남의 일감은 **없는 것과 같은 404**다 (있다는 것조차 알리지 않는다)."""
    poster = poster_of(store, found)
    row = store.row("SELECT * FROM external_tasks WHERE task_id = ?", (task_id,))
    if row is None or row["poster_key_id"] != poster.key_id:
        raise ApiError(404, "task_not_found", "그런 일감이 없다")
    return row


def _result_of(row: Any) -> ExternalTaskResult:
    extra = loads(row["result_json"], {}) or {}
    error = extra.get("error")
    usage = extra.get("usage")
    return ExternalTaskResult(
        task_id=row["task_id"],
        state=row["state"],
        output=loads(row["output_json"]) if row["state"] == STATE_COMPLETED else None,
        mode_used=extra.get("mode_used"),
        replayed=bool(extra.get("replayed")),
        usage=Usage.model_validate(usage) if usage else None,
        error=TaskError.model_validate(error) if error else None,
        deliveries=int(row["deliveries"] or 0),
    )


def result(store: Store, found: Caller, task_id: str, *, now: str | None = None) -> ExternalTaskResult:
    """`GET /external-tasks/{task_id}` — 지금 모습 (기다리기는 라우트가 한다)."""
    sweep(store, now=now)
    return _result_of(_poster_row(store, found, task_id))


def ack(store: Store, found: Caller, task_id: str) -> ExternalTaskResult:
    """결과를 받았다 — **값을 지운다** (C15 셋째 규칙). 끝나지 않은 일감은 409 `not_finished`."""
    row = _poster_row(store, found, task_id)
    if row["state"] not in FINAL_STATES:
        raise ApiError(409, "not_finished", "아직 끝나지 않은 일감이다", {"state": row["state"]})
    with store.tx() as cur:
        cur.execute(
            "UPDATE external_tasks SET input_json = NULL, output_json = NULL,"
            " acked_at = COALESCE(acked_at, ?) WHERE task_id = ?",
            (now_iso(), task_id),
        )
    found_row = store.row("SELECT * FROM external_tasks WHERE task_id = ?", (task_id,))
    return _result_of(found_row)


def cancel(store: Store, found: Caller, task_id: str) -> ExternalTaskResult:
    """거둔다 (실행이 취소됐다). 끝난 일감은 그대로 둔다 — 두 번 해도 같은 답이다."""
    row = _poster_row(store, found, task_id)
    if row["state"] not in FINAL_STATES:
        with store.tx() as cur:
            cur.execute(
                "UPDATE external_tasks SET state = ?, input_json = NULL, finished_at = ?,"
                " locked_by = NULL, lock_until = NULL WHERE task_id = ? AND state IN (?, ?)",
                (STATE_CANCELLED, now_iso(), task_id, STATE_PENDING, STATE_LOCKED),
            )
    return _result_of(store.row("SELECT * FROM external_tasks WHERE task_id = ?", (task_id,)))


# ─────────────────────────── 시간이 미는 것 ───────────────────────────


def sweep(store: Store, *, now: str | None = None) -> None:
    """기한·잠금·청소 (C15). 읽는 자리마다 부른다.

    - 기한이 지났다: 아무도 안 가져갔으면 `no_consumer`, 잠겨 있었으면 `timeout` — 둘 다 `expired`.
    - 잠금이 지났다(기한은 아직): `pending`으로 돌려 다시 나가게 한다 (최소 한 번 실행).
    - 끝난 지 7일이 지난 값은 지운다 (못 받은 결과 — 누가·언제·성패는 남는다).
    """
    at = now or now_iso()
    stale = _later(at, -PURGE_AFTER_DAYS * 86400)
    with store.tx() as cur:
        for state, code, message in (
            (STATE_PENDING, CODE_NO_CONSUMER, "기한 안에 이 토픽을 가져간 일꾼이 없다"),
            (STATE_LOCKED, CODE_TIMEOUT, "일꾼이 가져갔지만 기한 안에 끝내지 않았다"),
        ):
            error = dumps({"error": {"code": code, "message": message, "retryable": code in RETRYABLE_CODES}})
            cur.execute(
                "UPDATE external_tasks SET state = ?, result_json = ?, input_json = NULL, finished_at = ?,"
                " locked_by = NULL, lock_until = NULL WHERE state = ? AND deadline <= ?",
                (STATE_EXPIRED, error, at, state, at),
            )
        cur.execute(
            "UPDATE external_tasks SET state = ?, locked_by = NULL, lock_until = NULL"
            " WHERE state = ? AND lock_until <= ?",
            (STATE_PENDING, STATE_LOCKED, at),
        )
        cur.execute(
            "UPDATE external_tasks SET input_json = NULL, output_json = NULL"
            " WHERE finished_at IS NOT NULL AND finished_at <= ?"
            " AND (input_json IS NOT NULL OR output_json IS NOT NULL)",
            (stale,),
        )


# ─────────────────────────── 일꾼 ───────────────────────────


def consumer_of(store: Store, found: Caller) -> Any:
    """일꾼 토큰인가 (키 종류 `consumer`) — 그 행을 준다."""
    if found.key is None or found.key.type != CONSUMER:
        raise ApiError(403, "wrong_key_type", "일꾼 토큰으로 불러야 한다")
    row = store.row("SELECT * FROM consumers WHERE key_id = ?", (found.key.key_id,))
    if row is None:
        raise ApiError(409, "not_registered", "들이지 않은 일꾼이다")
    return row


def _locked_task(row: Any) -> LockedTask:
    return LockedTask(
        task_id=row["task_id"],
        topic=row["topic"],
        operation=row["operation"],
        mode=row["mode"],
        origin=row["origin"],
        idempotency=loads(row["idempotency_json"]),
        caller=loads(row["caller_json"]),
        business_key=row["business_key"],
        input=loads(row["input_json"], {}) or {},
        lock_until=row["lock_until"],
        deadline=row["deadline"],
        delivery=int(row["deliveries"]),
    )


def take(store: Store, consumer: Any, request: FetchRequest, *, now: str | None = None) -> list[LockedTask]:
    """한 번 가져가기 — 잠글 수 있는 것을 **지금** 잠근다 (기다리기는 라우트가 한다)."""
    granted = set(loads(consumer["topics_json"], []) or [])
    outside = sorted(set(request.topics) - granted)
    if outside:
        raise ApiError(403, "topic_not_granted", "승인받지 않은 토픽이다", {"topics": outside})
    at = now or now_iso()
    sweep(store, now=at)
    wanted = min(request.max_tasks, MAX_TASKS_PER_FETCH)
    marks = ", ".join("?" for _ in request.topics)
    consumer_id = str(consumer["consumer_id"])
    taken: list[str] = []
    with store.tx() as cur:
        cur.execute("UPDATE consumers SET last_fetch_at = ? WHERE consumer_id = ?", (at, consumer_id))
        rows = cur.execute(
            f"SELECT task_id, deadline, operation, topic, lockers_json FROM external_tasks"  # noqa: S608 — 자리표만 늘린다
            f" WHERE state = ? AND topic IN ({marks}) ORDER BY created_at LIMIT ?",
            (STATE_PENDING, *request.topics, wanted),
        ).fetchall()
        for one in rows:
            lock = request.lock_s or _operation_timeout(store, str(one["topic"]), str(one["operation"]))
            until = _earlier(_later(at, lock), str(one["deadline"]))
            lockers = set(loads(one["lockers_json"], []) or []) | {consumer_id}
            cur.execute(
                "UPDATE external_tasks SET state = ?, locked_by = ?, lock_until = ?, deliveries = deliveries + 1,"
                " lockers_json = ? WHERE task_id = ? AND state = ?",
                (STATE_LOCKED, consumer_id, until, dumps(sorted(lockers)), one["task_id"], STATE_PENDING),
            )
            if cur.rowcount:
                taken.append(str(one["task_id"]))
    return [_locked_task(store.row("SELECT * FROM external_tasks WHERE task_id = ?", (task_id,))) for task_id in taken]


def _operation_timeout(store: Store, topic: str, operation: str) -> int:
    manifest = _topic_manifest(store, topic)
    found = manifest.operation(operation) if manifest is not None else None
    return found.timeout_s if found is not None else DEFAULT_TIMEOUT_S


def rotation(store: Store, found: Caller, consumer: Any) -> Any:
    """일꾼 토큰 회전 — 만료 14일 전부터 가져가기 답에 싣는다 (C4 §키 회전과 같은 봉함)."""
    assert found.key is not None
    return enrollments.rotation_for(store, found.key, host_id=str(consumer["consumer_id"]))


def _consumer_task(store: Store, consumer: Any, task_id: str) -> Any:
    """끝내기의 대상 — **한 번이라도 잠갔던 일꾼만** 만진다 (아니면 403 `not_locked_by_you`)."""
    row = store.row("SELECT * FROM external_tasks WHERE task_id = ?", (task_id,))
    if row is None or row["topic"] not in set(loads(consumer["topics_json"], []) or []):
        raise ApiError(404, "task_not_found", "그런 일감이 없다")
    if str(consumer["consumer_id"]) not in set(loads(row["lockers_json"], []) or []):
        raise ApiError(403, "not_locked_by_you", "이 일꾼이 잠근 일감이 아니다")
    if row["state"] == STATE_CANCELLED:
        raise ApiError(409, "cancelled", "올린 쪽이 거둔 일감이다 — 하던 일을 멈춰도 된다")
    if row["state"] in FINAL_STATES:
        raise ApiError(409, "already_completed", "이미 끝난 일감이다", {"state": row["state"]})
    return row


def complete(store: Store, consumer: Any, task_id: str, body: CompleteRequest, *, now: str | None = None) -> None:
    """끝냈다 — **먼저 끝낸 쪽이 이긴다**. 잠금이 지난 일꾼의 끝내기도 아직 끝나지 않았으면 받는다."""
    sweep(store, now=now)
    row = _consumer_task(store, consumer, task_id)
    if _size(body.output) > MAX_VALUE_BYTES:
        raise ApiError(413, "too_large", "출력이 1 MB를 넘는다")
    manifest = _topic_manifest(store, str(row["topic"]))
    missing = missing_outputs(manifest.operation(str(row["operation"])) if manifest else None, body.output)
    if missing:
        raise ApiError(422, "output_invalid", "출력에 필수 칸이 빠졌다", {"missing": missing})
    extra = {
        "mode_used": body.mode_used or row["mode"],
        "replayed": body.replayed,
        "usage": body.usage.to_json_dict() if body.usage else None,
    }
    keep = bool(row["want_result"])
    _finish(
        store,
        task_id,
        state=STATE_COMPLETED,
        output=dumps(body.output) if keep else None,
        extra=extra,
        acked=not keep,
        now=now,
    )


def fail(store: Store, consumer: Any, task_id: str, body: FailRequest, *, now: str | None = None) -> None:
    """실패했다. `retryable`은 **아는 코드일 때만** 믿는다 (C15 — 503·429·`timeout`만)."""
    sweep(store, now=now)
    row = _consumer_task(store, consumer, task_id)
    error: dict[str, Any] = {
        "code": body.code, "message": body.message, "retryable": body.retryable and body.code in RETRYABLE_CODES
    }
    # **다시 불러도 안전하면 모름이 아니다** (ADR-0107) — 둘이 함께 참이면 부르는 쪽이 두 길을 다 탄다.
    if body.outcome_unknown and not error["retryable"]:
        error["outcome_unknown"] = True
    if body.detail:
        error["detail"] = body.detail
    _finish(
        store, task_id, state=STATE_FAILED, output=None, extra={"error": error}, acked=not row["want_result"], now=now
    )


def _finish(
    store: Store,
    task_id: str,
    *,
    state: str,
    output: str | None,
    extra: dict[str, Any],
    acked: bool,
    now: str | None,
) -> None:
    at = now or now_iso()
    with store.tx() as cur:
        cur.execute(
            "UPDATE external_tasks SET state = ?, output_json = ?, result_json = ?, input_json = NULL,"
            " finished_at = ?, locked_by = NULL, lock_until = NULL, acked_at = ?"
            " WHERE task_id = ? AND state IN (?, ?)",
            (
                state,
                output,
                dumps({k: v for k, v in extra.items() if v is not None}),
                at,
                at if acked else None,
                task_id,
                STATE_PENDING,
                STATE_LOCKED,
            ),
        )
        if not cur.rowcount:  # pragma: no cover — 그 사이 다른 일꾼이 끝냈다
            raise ApiError(409, "already_completed", "이미 끝난 일감이다")


def extend(store: Store, consumer: Any, task_id: str, body: ExtendRequest, *, now: str | None = None) -> LockedTask:
    """잠금 늘리기 — 지금 잠근 일꾼만, `deadline`을 넘지 않는다."""
    sweep(store, now=now)
    row = _consumer_task(store, consumer, task_id)
    if row["state"] != STATE_LOCKED or row["locked_by"] != consumer["consumer_id"]:
        raise ApiError(403, "not_locked_by_you", "지금 이 일꾼이 잠근 일감이 아니다")
    until = _earlier(_later(now or now_iso(), body.lock_s), str(row["deadline"]))
    with store.tx() as cur:
        cur.execute("UPDATE external_tasks SET lock_until = ? WHERE task_id = ?", (until, task_id))
    return _locked_task(store.row("SELECT * FROM external_tasks WHERE task_id = ?", (task_id,)))


def put_manifest(store: Store, consumer: Any, raw: dict[str, Any]) -> ConsumerInfo:
    """manifest 하나를 다시 올린다 (판이 바뀌었다). `app_id`가 승인된 토픽 밖이면 403."""
    try:
        manifest = ServiceAppManifest.model_validate(raw)
    except ValueError as e:
        raise ApiError(422, "input_invalid", "manifest가 C11과 맞지 않는다", {"error": str(e).splitlines()[0]}) from e
    if manifest.app_id not in set(loads(consumer["topics_json"], []) or []):
        raise ApiError(403, "topic_not_granted", f"승인받지 않은 토픽이다: {manifest.app_id}")
    held = [one for one in _held_manifests(consumer) if one.get("app_id") != manifest.app_id]
    held.append(manifest.to_json_dict())
    with store.tx() as cur:
        cur.execute(
            "UPDATE consumers SET manifest_json = ? WHERE consumer_id = ?",
            (dumps(sorted(held, key=lambda one: str(one.get("app_id")))), consumer["consumer_id"]),
        )
    return _consumer_info(store, store.row("SELECT * FROM consumers WHERE consumer_id = ?", (consumer["consumer_id"],)))


def _held_manifests(row: Any) -> list[dict[str, Any]]:
    found = loads(row["manifest_json"])
    if isinstance(found, dict):
        return [found]
    return [one for one in (found or []) if isinstance(one, dict)]


def _consumer_info(store: Store, row: Any) -> ConsumerInfo:
    record = keys.get(store, str(row["key_id"]))
    return ConsumerInfo(
        consumer_id=row["consumer_id"],
        name=row["name"],
        topics=loads(row["topics_json"], []) or [],
        key_prefix=record.prefix if record else None,
        approved_at=row["approved_at"],
        last_fetch_at=row["last_fetch_at"],
        apps=[f"{one.get('app_id')}@{one.get('version')}" for one in _held_manifests(row)],
    )


def consumers(store: Store) -> list[ConsumerInfo]:
    return [_consumer_info(store, row) for row in store.rows("SELECT * FROM consumers ORDER BY name")]


def topics(store: Store, *, now: str | None = None) -> list[TopicStatus]:
    """토픽 상태 (CON-07 — 일꾼 수·마지막으로 가져간 때·쌓인 일감·가장 오래 기다린 일감)."""
    sweep(store, now=now)
    found: dict[str, TopicStatus] = {}
    for row in store.rows("SELECT topics_json, last_fetch_at FROM consumers"):
        for topic in loads(row["topics_json"], []) or []:
            one = found.setdefault(topic, TopicStatus(topic=topic))
            one.consumers += 1
            seen = row["last_fetch_at"]
            if seen and (one.last_fetch_at is None or _at(seen) > _at(one.last_fetch_at)):
                one.last_fetch_at = seen
    for row in store.rows(
        "SELECT topic, COUNT(*) AS n, MIN(created_at) AS oldest FROM external_tasks WHERE state = ? GROUP BY topic",
        (STATE_PENDING,),
    ):
        one = found.setdefault(str(row["topic"]), TopicStatus(topic=str(row["topic"])))
        one.waiting = int(row["n"])
        one.oldest_waiting_since = row["oldest"]
    return [found[name] for name in sorted(found)]


def for_run(store: Store, *, run_id: str) -> list[ExternalTaskInfo]:
    """그 실행이 올린 일감들, 올린 순 (C15 `GET /external-tasks?run_id=`, CON-01 「외부 작업」).

    **업무 값은 싣지 않는다** (원칙 6) — 입력·출력·오류 글·`detail`은 두고 코드만 옮긴다. 일꾼은 이름으로
    보인다(콘솔은 id로 사람을 찾지 않는다). 실행 id는 멱등 칸에 있어 **글로 찾지 않고 읽어서 가른다**
    — `LIKE`로 JSON을 뒤지면 다른 칸의 같은 글에도 걸린다.
    """
    names = {str(row["consumer_id"]): str(row["name"]) for row in store.rows("SELECT consumer_id, name FROM consumers")}
    out = []
    for row in store.rows("SELECT * FROM external_tasks ORDER BY created_at, task_id"):
        key = loads(row["idempotency_json"], {}) or {}
        if key.get("run_id") != run_id:
            continue
        held = [str(row["locked_by"])] if row["locked_by"] else sorted(loads(row["lockers_json"], []) or [])
        error = loads(row["result_json"], {}) or {}
        error = error.get("error") if isinstance(error, dict) else None
        out.append(
            ExternalTaskInfo(
                task_id=str(row["task_id"]),
                topic=str(row["topic"]),
                operation=str(row["operation"]),
                mode=str(row["mode"]),
                origin=str(row["origin"]),
                node_id=str(key.get("node_id", "")),
                node_instance=int(key.get("node_instance", 1)),
                attempt=int(key.get("attempt", 1)),
                call_seq=int(key.get("call_seq", 1)),
                state=str(row["state"]),
                created_at=row["created_at"],
                finished_at=row["finished_at"],
                acked_at=row["acked_at"],
                deliveries=int(row["deliveries"] or 0),
                consumers=[names.get(one, one) for one in held],
                error_code=str(error["code"]) if isinstance(error, dict) and error.get("code") else None,
                outcome_unknown=bool(isinstance(error, dict) and error.get("outcome_unknown")),
            )
        )
    return out


# ─────────────────────────── 롱폴링 ───────────────────────────


class Waiters:
    """롱폴링을 물고 있는 수와 종 (C15 §전송 — 상한을 넘으면 503 `too_many_waiters`).

    종은 새 일감·끝내기가 울린다. 울리지 않는 변화(잠금이 지남·기한)는 `_RECHECK_S`마다 다시 본다.
    """

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.count = 0
        self._bell = asyncio.Event()

    def ring(self) -> None:
        self._bell.set()
        self._bell = asyncio.Event()

    async def wait(self, timeout: float) -> None:
        bell = self._bell
        try:
            await asyncio.wait_for(bell.wait(), timeout=timeout)
        except TimeoutError:
            pass

    def enter(self) -> None:
        if self.count >= self.limit:
            raise ApiError(503, "too_many_waiters", "기다리는 연결이 너무 많다 — 잠깐 뒤에 다시 건다")
        self.count += 1

    def leave(self) -> None:
        self.count -= 1


def _waiters(request: Request) -> Waiters:
    found: Waiters = request.app.state.external_waiters
    return found


async def _until(request: Request, wait_s: int, check: Any) -> Any:
    """`check()`가 참인 값을 줄 때까지, 길어야 `wait_s`(≤ 25)초 기다린다."""
    got = check()
    seconds = min(max(wait_s, 0), MAX_WAIT_S)
    if got or seconds == 0:
        return got
    waiters = _waiters(request)
    waiters.enter()
    try:
        until = time.monotonic() + seconds
        while True:
            left = until - time.monotonic()
            if left <= 0:
                return check()
            await waiters.wait(min(left, _RECHECK_S))
            got = check()
            if got:
                return got
    finally:
        waiters.leave()


# ─────────────────────────── 경로 ───────────────────────────


def _store(request: Request) -> Store:
    store: Store = request.app.state.store
    return store


def _caller(request: Request) -> Caller:
    found: Caller = request.app.state.authenticate(request)
    return found


async def _body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > _BODY_LIMIT:
        raise ApiError(413, "too_large", "요청이 너무 크다 (값은 1 MB까지)")
    try:
        body = json.loads(raw or b"{}")
    except ValueError as e:
        raise ApiError(422, "input_invalid", "본문이 JSON이 아니다") from e
    if not isinstance(body, dict):
        raise ApiError(422, "input_invalid", "본문의 최상위가 객체가 아니다")
    return body


def _model(model: Any, raw: dict[str, Any]) -> Any:
    try:
        return model.model_validate(raw)
    except ValueError as e:
        raise ApiError(422, "input_invalid", "본문이 계약과 맞지 않는다", {"error": str(e).splitlines()[0]}) from e


@router.post("/call-tokens", status_code=201)
def post_call_token(request: Request) -> Any:
    return issue_call_token(_store(request), _caller(request))


@router.post("/external-tasks")
async def post_task(request: Request) -> Any:
    made, fresh = create(_store(request), _caller(request), await _body(request))
    if fresh:
        _waiters(request).ring()
    return JSONResponse(made.to_json_dict(), status_code=201 if fresh else 200)


@router.get("/external-tasks/{task_id}")
async def get_task(request: Request, task_id: str, wait_s: int = 0) -> Any:
    store = _store(request)
    found = _caller(request)

    def check() -> ExternalTaskResult | None:
        now = result(store, found, task_id)
        return now if now.state in FINAL_STATES else None

    done = await _until(request, wait_s, check)
    return (done or result(store, found, task_id)).to_json_dict()


@router.post("/external-tasks/{task_id}/ack")
async def post_ack(request: Request, task_id: str) -> Any:
    return ack(_store(request), _caller(request), task_id)


@router.post("/external-tasks/{task_id}/cancel")
async def post_cancel(request: Request, task_id: str) -> Any:
    done = cancel(_store(request), _caller(request), task_id)
    _waiters(request).ring()
    return done


@router.post("/consumers/enroll", status_code=201)
async def post_enroll(request: Request) -> Any:
    remote = request.client.host if request.client is not None else None
    return enrollments.request(_store(request), kind=CONSUMER, body=await _body(request), remote_addr=remote)


@router.get("/consumers/enroll/{enrollment_id}")
def get_enroll(request: Request, enrollment_id: str) -> Any:
    return enrollments.status(_store(request), enrollment_id, kind=CONSUMER)


@router.post("/consumers/fetch")
async def post_fetch(request: Request) -> Any:
    store = _store(request)
    found = _caller(request)
    consumer = consumer_of(store, found)
    wanted: FetchRequest = _model(FetchRequest, await _body(request))
    tasks = await _until(request, wanted.wait_s, lambda: take(store, consumer, wanted))
    return FetchResponse(
        tasks=tasks or [], consumer_id=str(consumer["consumer_id"]), rotated_token=rotation(store, found, consumer)
    )


@router.post("/consumers/tasks/{task_id}/complete")
async def post_complete(request: Request, task_id: str) -> Any:
    store = _store(request)
    consumer = consumer_of(store, _caller(request))
    complete(store, consumer, task_id, _model(CompleteRequest, await _body(request)))
    _waiters(request).ring()
    return {"task_id": task_id, "state": STATE_COMPLETED}


@router.post("/consumers/tasks/{task_id}/fail")
async def post_fail(request: Request, task_id: str) -> Any:
    store = _store(request)
    consumer = consumer_of(store, _caller(request))
    fail(store, consumer, task_id, _model(FailRequest, await _body(request)))
    _waiters(request).ring()
    return {"task_id": task_id, "state": STATE_FAILED}


@router.post("/consumers/tasks/{task_id}/extend")
async def post_extend(request: Request, task_id: str) -> Any:
    store = _store(request)
    consumer = consumer_of(store, _caller(request))
    return extend(store, consumer, task_id, _model(ExtendRequest, await _body(request)))


@router.put("/consumers/self/manifest")
async def put_self_manifest(request: Request) -> Any:
    store = _store(request)
    consumer = consumer_of(store, _caller(request))
    return put_manifest(store, consumer, await _body(request))


@router.put("/consumers/self/catalogs/{resource_type}")
async def put_self_catalog(request: Request, resource_type: str) -> Any:
    store = _store(request)
    consumer = consumer_of(store, _caller(request))
    return resources.put_catalog(store, consumer=consumer, resource_type=resource_type, raw=await _body(request))


@router.get("/consumers")
def get_consumers(request: Request) -> Any:
    require_console(_caller(request))
    return consumers(_store(request))


@router.get("/external-tasks")
def get_tasks_of_run(request: Request, run_id: str = "") -> Any:
    require_console(_caller(request))
    if not run_id:
        raise ApiError(422, "input_invalid", "`run_id`가 있어야 한다 — 일감을 한 번에 다 주지 않는다")
    return for_run(_store(request), run_id=run_id)


@router.get("/external-topics")
def get_topics(request: Request) -> Any:
    require_console(_caller(request))
    return topics(_store(request))


__all__ = [
    "POSTER_KEY_TYPES",
    "Poster",
    "Waiters",
    "ack",
    "cancel",
    "complete",
    "consumer_of",
    "consumers",
    "create",
    "extend",
    "fail",
    "poster_of",
    "put_manifest",
    "result",
    "router",
    "sweep",
    "take",
    "topics",
]
