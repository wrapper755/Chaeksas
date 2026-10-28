"""UI 자동화 앱과 말하는 길 — 계획·치유·보고 (C8). **Center의 외부 작업으로 오간다** (C15, ADR-0102).

세 번만 오간다. 그 사이의 사다리는 **로컬에서** 돈다 (`ladder.py`).

- **계획은 캐시한다.** 열쇠는 `(page_id, platform, steps 해시, revision)`이다. 서버에 닿지
  못하면 캐시를 쓴다 (C10 `plan_source: "cache"`). **자율 수행(`goal`)은 캐시하지 않는다** —
  목표가 같아도 그때그때 다른 계획이 나온다.
- **보고는 디스크 큐에 둔다.** 5xx·연결 실패면 같은 것을 다시 보내고, **4xx면 다시 보내지
  않고** 「보내지 못한 보고」로 옮긴다 (BUI-09). 한 번 거부된 것을 영원히 다시 보내면 큐가
  막힌다.
- **업무 값은 나가지 않는다** (원칙 6) — 보고에 읽은 값이 없고, 치유 스냅샷은 가려서 간다.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from chaeksas.ext.ui_automation.contracts.plan import (
    ExecutionPlan,
    HealRequest,
    HealResponse,
    PlanStep,
    SessionReport,
)

log = logging.getLogger(__name__)

#: C8의 세 작업 (C11 서비스 앱 작업 — 토픽 `ui-automation`의 작업이다).
OP_PLAN = "plan"
OP_HEAL = "heal"
OP_REPORT = "report"

#: 앱이 **이미 받은** 보고 (C11). 다시 보낸 것이니 버려도 된다.
IDEMPOTENCY_CONFLICT = "idempotency_conflict"

#: 보고를 쌓아 두는 곳과, 다시 보내도 소용없는 것을 옮기는 곳 (BUI-09 「밀린 보고」).
QUEUE_DIR = "reports"
DEAD_DIR = "reports-rejected"


class Ops(Protocol):
    """UI 자동화 앱의 작업을 부르는 길 (C11). 닿지 못하면 `OpsUnreachable`."""

    def call(self, operation: str, body: dict[str, Any], *, call_seq: int) -> dict[str, Any]: ...


#: 계획·치유·보고가 걸리는 토픽 (C8·C15) — UI 자동화 앱이 일꾼으로 가져간다.
TOPIC = "ui-automation"
#: 결과를 한 번 기다릴 때 물고 있는 시간 (초, C15 상한).
_WAIT_S = 25


@dataclass
class CenterOps:
    """C15 외부 작업으로 UI 자동화 앱의 작업을 올린다 (Worker 쪽, ADR-0102).

    - **Worker는 앱의 주소도 키도 모른다** — Center 주소(`CHK_RUNTIME__CENTER_URL`)와 세션이 준
      **호출 토큰**(C10 `call_token`)뿐이다. 토큰은 세션 동안 메모리에만 둔다.
    - 멱등 칸은 `(run_id, node_id, node_instance, attempt, call_seq)`다 (C11·C15). UI 세션 하나가
      한 `business_key`를 쓰므로 그것을 `run_id`·`node_id`로 쪼개 싣는다.
    - **닿지 못함·Center 상한·일꾼 없음·다시 해 볼 만한 실패는 `OpsUnreachable`**(캐시·큐로 간다),
      **거절·고칠 실패는 `OpsRefused`**(다시 보내도 소용없다).
    - `report`는 **결과를 기다리지 않는다** (`want_result: false`) — Center가 받으면 보낸 것이다.
    """

    base_url: str
    call_token: str
    business_key: str
    mode: str = "deterministic"
    caller_version: str | None = None
    #: C11 `caller.type` — Worker가 올리면 `worker`, 도구(TOL-03)가 올리면 그 호스트 (`tool_ui`).
    caller_type: str = "worker"
    bpm_process_id: str | None = None
    version: str | None = None
    timeout_s: float = 120.0
    client: Any = None  # httpx.Client (시험이 끼운다)

    def ids(self) -> tuple[str, str, int, int]:
        """`<run_id>:<node_id>:<node_instance>:<attempt>` (C10 `business_key`)."""
        parts = self.business_key.split(":")
        run_id = parts[0] if parts else self.business_key
        node_id = parts[1] if len(parts) > 1 else "ui"
        instance = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1
        attempt = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 1
        return run_id, node_id, instance, attempt

    def call(self, operation: str, body: dict[str, Any], *, call_seq: int) -> dict[str, Any]:
        import httpx  # noqa: PLC0415 — 부를 때만 든다

        run_id, node_id, instance, attempt = self.ids()
        wait = operation != OP_REPORT
        payload = {
            "schema": 1,
            "topic": TOPIC,
            "operation": operation,
            "mode": self.mode,
            "idempotency": {
                "run_id": run_id,
                "node_id": node_id,
                "node_instance": instance,
                "attempt": attempt,
                "call_seq": call_seq,
            },
            "caller": {
                "type": self.caller_type,
                "version": self.version or self.caller_version,
                "bpm_process_id": self.bpm_process_id,
            },
            "business_key": self.business_key,
            "input": body,
            "want_result": wait,
            "origin": "test" if run_id.startswith("test_") else "run",
        }
        headers = {"Authorization": f"Bearer {self.call_token}"}
        own = self.client is None
        client = self.client or httpx.Client(base_url=self.base_url, timeout=_WAIT_S + 15.0)
        try:
            made = client.post("/api/v1/external-tasks", json=payload, headers=headers)
            _raise_for(made)
            if not wait:
                return {}
            task_id = str(made.json()["task_id"])
            until = time.monotonic() + self.timeout_s
            while True:
                got = client.get(f"/api/v1/external-tasks/{task_id}", params={"wait_s": _WAIT_S}, headers=headers)
                _raise_for(got)
                result = got.json()
                if result.get("state") in ("completed", "failed", "expired", "cancelled"):
                    break
                if time.monotonic() > until:
                    raise OpsUnreachable(f"UI 자동화 앱이 {operation}을 끝내지 않았다 (기한)", code="timeout")
            with contextlib.suppress(httpx.HTTPError):
                client.post(f"/api/v1/external-tasks/{task_id}/ack", headers=headers)
        except httpx.HTTPError as e:
            raise OpsUnreachable(f"Center에 닿지 못했다 ({type(e).__name__})") from e
        finally:
            if own:
                client.close()
        state = result.get("state")
        if state == "completed":
            return dict(result.get("output") or {})
        error = result.get("error") or {}
        code = str(error.get("code") or state or "")
        message = str(error.get("message") or f"{operation}: {state}")
        if state == "expired" or error.get("retryable"):
            raise OpsUnreachable(message, code=code)
        detail = error.get("detail")
        raise OpsRefused(message, status=422, code=code, detail=detail if isinstance(detail, dict) else None)


def _raise_for(response: Any) -> None:
    """Center의 거절 — 4xx는 `OpsRefused`, 5xx(롱폴링 상한 등)는 `OpsUnreachable`."""
    if 400 <= response.status_code < 500:
        raise OpsRefused(_message(response), status=response.status_code, code=_code(response))
    if response.status_code >= 500:
        raise OpsUnreachable(_message(response), code=_code(response))


def _code(response: Any) -> str:
    try:
        body = response.json()
    except ValueError:
        return ""
    return str(body.get("code") or "")


def _message(response: Any) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"앱이 {response.status_code}로 답했다"
    return str(body.get("message") or f"앱이 {response.status_code}로 답했다")


class OpsUnreachable(RuntimeError):
    """앱에 닿지 못했다 — 계획은 캐시로, 보고는 큐로 간다.

    `code`는 앱이 5xx로 **답했을 때**의 C11 코드다 (`llm_unavailable`·`dependency_down` …).
    연결부터 실패했으면 비어 있다.
    """

    def __init__(self, message: str, *, code: str = "") -> None:
        super().__init__(message)
        self.code = code


class OpsRefused(RuntimeError):
    """앱이 4xx로 거부했다 — **다시 보내도 소용없다**."""

    def __init__(
        self, message: str, *, status: int = 400, code: str = "", detail: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.detail = detail or {}


def plan_key(page_id: str, platform: str, steps: list[PlanStep], revision: int) -> str:
    """계획 캐시 열쇠 (C8). **스텝이 바뀌면 다른 계획**이다."""
    shape = json.dumps(
        [[one.semantic_key, one.action, one.expect_navigation] for one in steps],
        ensure_ascii=False,
        sort_keys=True,
    )
    digest = hashlib.sha256(shape.encode("utf-8")).hexdigest()[:16]
    return f"{page_id}|{platform}|{digest}|{revision}"


@dataclass
class PlanCache:
    """계획 캐시 (오프라인). 파일 하나에 계획 하나."""

    folder: Path

    def path(self, key: str) -> Path:
        name = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
        return self.folder / f"{name}.json"

    def get(self, key: str) -> ExecutionPlan | None:
        found = self.path(key)
        if not found.is_file():
            return None
        try:
            return ExecutionPlan.model_validate_json(found.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None  # 깨진 캐시는 없는 것으로 본다

    def put(self, key: str, plan: ExecutionPlan) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path(key).write_text(
            json.dumps(plan.to_json_dict(), ensure_ascii=False), encoding="utf-8", newline="\n"
        )


@dataclass
class ReportQueue:
    """보고를 쌓아 두고 보낸다 (C8 §보고 재전송 규칙)."""

    folder: Path

    @property
    def dead(self) -> Path:
        return self.folder.parent / DEAD_DIR

    def add(self, report: SessionReport) -> Path:
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / f"{report.business_key.replace(':', '_')}.json"
        path.write_text(
            json.dumps(report.to_json_dict(), ensure_ascii=False), encoding="utf-8", newline="\n"
        )
        return path

    def waiting(self) -> list[Path]:
        return sorted(self.folder.glob("*.json")) if self.folder.is_dir() else []

    def flush(self, ops: Ops, *, call_seq: Callable[[], int] = lambda: 1) -> tuple[int, int]:
        """쌓인 것을 보낸다 → `(보낸 수, 버린 수)`.

        **4xx는 다시 보내지 않는다** — 한 번 거부된 것이 큐를 영원히 막는다.
        """
        sent = rejected = 0
        for path in self.waiting():
            body = json.loads(path.read_text(encoding="utf-8"))
            try:
                ops.call(OP_REPORT, body, call_seq=call_seq())
            except OpsRefused as e:
                log.warning("보고가 거부됐다 (%s) — 다시 보내지 않는다: %s", path.name, e)
                self.dead.mkdir(parents=True, exist_ok=True)
                path.replace(self.dead / path.name)
                rejected += 1
                continue
            except OpsUnreachable:
                break  # 차례를 지킨다 — 다음 주기에 같은 것부터
            path.unlink(missing_ok=True)
            sent += 1
        return sent, rejected


@dataclass
class PlanService:
    """C8의 세 작업을 부르는 쪽. **세션마다 작업별 일련번호**를 센다 (C11 멱등 키)."""

    ops: Ops
    cache: PlanCache
    queue: ReportQueue
    _seqs: dict[str, int] = field(default_factory=dict)

    def next_seq(self, operation: str) -> int:
        self._seqs[operation] = self._seqs.get(operation, 0) + 1
        return self._seqs[operation]

    def plan(
        self,
        *,
        page_id: str,
        platform: str,
        steps: list[PlanStep],
        start_url: str | None = None,
        revision: int = 1,
        goal: str | None = None,
        values: list[str] | None = None,
        results: list[str] | None = None,
    ) -> tuple[ExecutionPlan, str]:
        """계획을 받아 온다 → `(계획, "server" | "cache")`.

        닿지 못하면 캐시를 쓴다. **자율 수행은 캐시하지 않는다** (같은 목표라도 계획이 다르다).
        """
        key = plan_key(page_id, platform, steps, revision)
        body: dict[str, Any] = {
            "page_id": page_id,
            "platform": platform,
            "start_url": start_url,
            "steps": [one.to_json_dict() for one in steps],
        }
        if goal:
            # **이름만** 싣는다 — 값은 수행기가 채운다 (C8, ADR-0035).
            body["goal"] = goal
            body["values"] = list(values or [])
            body["results"] = list(results or [])
        try:
            answer = self.ops.call(OP_PLAN, body, call_seq=self.next_seq(OP_PLAN))
        except OpsUnreachable:
            found = None if goal else self.cache.get(key)
            if found is None:
                raise
            log.info("계획을 캐시에서 쓴다 (%s)", page_id)
            return found, "cache"

        made = ExecutionPlan.model_validate(answer)
        if not goal:
            self.cache.put(key, made)
        return made, "server"

    def heal(self, request: HealRequest) -> HealResponse | None:
        """치유를 한 번 묻는다. **닿지 못하면 `None`** — 사다리가 전환으로 넘긴다."""
        try:
            answer = self.ops.call(
                OP_HEAL, request.to_json_dict(), call_seq=self.next_seq(OP_HEAL)
            )
        except (OpsUnreachable, OpsRefused):
            return None
        return HealResponse.model_validate(answer)

    def report(self, report: SessionReport) -> str:
        """보고를 보낸다 → `"sent"` 또는 `"queued"` (C10 `CloseResult.report`).

        **먼저 디스크에 쓰고** 보낸다 — 보내다 죽어도 보고가 사라지지 않는다.
        """
        path = self.queue.add(report)
        try:
            self.ops.call(OP_REPORT, report.to_json_dict(), call_seq=self.next_seq(OP_REPORT))
        except OpsRefused as e:
            if e.code == IDEMPOTENCY_CONFLICT:
                # **앱이 이미 받은 것이다** (같은 멱등 키). 보고는 들어갔으니 버린다 —
                # 「보내지 못한 보고」로 쌓아 두면 사람이 없는 문제를 쫓는다.
                path.unlink(missing_ok=True)
                return "sent"
            self.queue.dead.mkdir(parents=True, exist_ok=True)
            path.replace(self.queue.dead / path.name)
            return "queued"
        except OpsUnreachable:
            return "queued"
        path.unlink(missing_ok=True)
        return "sent"


__all__ = [
    "DEAD_DIR",
    "OP_HEAL",
    "OP_PLAN",
    "OP_REPORT",
    "QUEUE_DIR",
    "TOPIC",
    "CenterOps",
    "Ops",
    "OpsRefused",
    "OpsUnreachable",
    "PlanCache",
    "PlanService",
    "ReportQueue",
    "plan_key",
]
