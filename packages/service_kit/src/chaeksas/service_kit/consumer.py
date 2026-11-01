"""일꾼 — Center에서 일감을 가져가 작업 함수에 주고 끝냈다고 알린다 (C11·C15, ADR-0102).

    consumer = Consumer([service], center_url="http://center:8800", token=TokenFile.at(folder))
    consumer.publish()            # 외부 확장 정의·manifest·카탈로그 올리기 (뜰 때)
    consumer.run(stop_event)      # 가져가기 롱폴링 → 수행 → 끝내기

**들이기는 없다** (ADR-0122) — 일꾼은 Center의 **일꾼 폴더**에 놓인 `<이름>.consumer.json`(토큰 해시)으로만
들어온다. 토큰 원문은 그 파일을 지은 사람이 준다(`bpm-center consumer-file`) — `<접두>CENTER__TOKEN` 환경변수나
토큰 파일 `consumer-token.json`의 `token`.

지키는 것:

- **연결은 늘 Center 쪽으로 나간다.** 앱은 업무 호출을 받는 포트를 열지 않는다.
- **최소 한 번 실행이다** — 잠금이 지나 같은 일감이 다시 오면 `Service`의 멱등 저장소가 막는다
  (`replayed`로 저장된 결과를 다시 끝낸다, 아직 도는 중이면 아무것도 보내지 않는다).
- **잠금은 기한까지 잡는다** (`lock_s`를 비운다 — Center가 작업 `timeout_s`로 정한다). 늘릴 일이 없다.
- 카탈로그는 **`revision`이 바뀌었을 때만** 올린다 (C7 — 같은 판을 다시 쓰면 계획 캐시가 버려진다).
- 토큰은 원문을 파일에만 둔다(`0600` — 서버 쪽 앱이라 OS 비밀 저장소가 없을 수 있다). 환경변수
  `<접두>CENTER__TOKEN`이 있으면 그것이 이긴다 (개발·CI·컨테이너).
- 외부 확장을 맡은 토픽(`extension_definition`이 있는 것)은 **제 정의를 올린다** — Center가 검사·서명한다
  (`PUT /consumers/self/extension`, ADR-0122). 더 높은 판이 이미 있으면(409) 로그만 남기고 이어 간다.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from chaeksas.contracts.enrollment import open_sealed
from chaeksas.contracts.external_task import MAX_WAIT_S, FetchResponse, LockedTask
from chaeksas.contracts.service_app import CenterRegistration
from chaeksas.service_kit.app import TopicService

log = logging.getLogger("chaeksas.service_kit.consumer")

#: 토큰 파일 이름 — 원문과 봉함을 여는 개인키가 들어 있다 (`0600`).
TOKEN_FILE = "consumer-token.json"
#: 닿지 못하면 쉬는 시간 (초). 롱폴링 상한(503)도 같다.
BACKOFF_S = 2.0
#: 카탈로그 판을 다시 보는 간격 (초).
CATALOG_EVERY_S = 30.0


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ─────────────────────────── 토큰 ───────────────────────────


@dataclass
class TokenFile:
    """일꾼 토큰을 두는 곳. 환경변수가 있으면 그것이 이기고 파일은 쓰지 않는다."""

    path: Path | None = None
    env_value: str | None = None

    @classmethod
    def at(cls, folder: Path | None, *, env_prefix: str | None = None) -> TokenFile:
        raw = os.environ.get(f"{env_prefix}CENTER__TOKEN") if env_prefix else None
        return cls(path=(folder / TOKEN_FILE) if folder is not None else None, env_value=raw or None)

    def _read(self) -> dict[str, Any]:
        if self.path is None or not self.path.exists():
            return {}
        try:
            found = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return found if isinstance(found, dict) else {}

    def _write(self, body: dict[str, Any]) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        with contextlib.suppress(OSError):  # Windows에서는 권한 비트가 뜻이 없다
            self.path.chmod(0o600)

    def token(self) -> str | None:
        return self.env_value or self._read().get("token") or None

    def secret(self) -> str | None:
        """봉함을 여는 X25519 개인키 (들일 때·회전할 때)."""
        return self._read().get("secret") or None

    def save(self, *, token: str | None = None, secret: str | None = None, **extra: Any) -> None:
        body = self._read()
        if token is not None:
            body["token"] = token
        if secret is not None:
            body["secret"] = secret
        body.update({k: v for k, v in extra.items() if v is not None})
        self._write(body)

    def get(self, name: str) -> Any:
        return self._read().get(name)


# ─────────────────────────── 가져가기 ───────────────────────────


@dataclass
class Consumer:
    """여러 서비스 앱(토픽 여럿)을 맡을 수 있다 — 모의 앱 열셋이 일꾼 하나다."""

    services: Sequence[TopicService]
    center_url: str
    tokens: TokenFile
    workers: int = 4
    wait_s: int = MAX_WAIT_S
    client: Any | None = None
    now: Callable[[], str] = _now
    _last_fetch: str | None = field(default=None, init=False)
    _published: dict[str, Any] = field(default_factory=dict, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _own: Any = field(default=None, init=False)  # 주입하지 않으면 지어 두고 계속 쓴다 (부를 때마다 지으면 샌다)

    @property
    def topics(self) -> list[str]:
        return [one.app_id for one in self.services]

    def _service(self, topic: str) -> TopicService | None:
        return next((one for one in self.services if one.app_id == topic), None)

    def _http(self) -> Any:
        import httpx  # noqa: PLC0415

        if self.client is not None:
            return self.client
        with self._lock:
            if self._own is None:
                self._own = httpx.Client(base_url=self.center_url, timeout=self.wait_s + 10.0)
            return self._own

    def _headers(self) -> dict[str, str]:
        token = self.tokens.token()
        if not token:
            raise RuntimeError("일꾼 토큰이 없다 — Center 일꾼 폴더의 파일을 지을 때 받은 토큰을 주세요 (ADR-0122)")
        return {"Authorization": f"Bearer {token}"}

    def registration(self) -> CenterRegistration:
        """SVC-01 「Center 연결」 — 들었는가, 마지막으로 가져간 때."""
        return CenterRegistration(
            registered=bool(self.tokens.token()), base_url=self.center_url, last_reported_at=self._last_fetch
        )

    # ── 올리기 ──

    def publish(self, *, force: bool = False) -> None:
        """외부 확장 정의·manifest(뜰 때 한 번)와 카탈로그(판이 바뀌었을 때)를 올린다 (C15)."""
        http = self._http()
        for service in self.services:
            definition = getattr(service, "extension_definition", None)
            slot = f"extension:{service.app_id}"
            if isinstance(definition, dict) and (force or slot not in self._published):
                answer = http.put(
                    "/api/v1/consumers/self/extension", json={"definition": definition}, headers=self._headers()
                )
                if answer.status_code == 409:
                    # 같은 판에 다른 내용·철회된 판·더 높은 판이 이미 있다 — 사람이 판을 올려야 한다.
                    log.warning("외부 확장 %s의 정의를 Center가 받지 않았다: %s", service.app_id, answer.text)
                else:
                    answer.raise_for_status()
                self._published[slot] = True
            key = f"manifest:{service.app_id}"
            if force or key not in self._published:
                answer = http.put(
                    "/api/v1/consumers/self/manifest",
                    json=service.manifest.to_json_dict(),
                    headers=self._headers(),
                )
                answer.raise_for_status()
                self._published[key] = True
            for resource_type, source in service.catalogs.items():
                catalog = source()
                slot = f"catalog:{service.app_id}:{resource_type}"
                if not force and self._published.get(slot) == catalog.revision and catalog.revision is not None:
                    continue
                answer = http.put(
                    f"/api/v1/consumers/self/catalogs/{resource_type}",
                    json={"app_id": service.app_id, "catalog": catalog.to_json_dict()},
                    headers=self._headers(),
                )
                answer.raise_for_status()
                self._published[slot] = catalog.revision

    # ── 한 바퀴 ──

    def fetch(self, *, max_tasks: int, wait_s: int | None = None) -> list[LockedTask]:
        http = self._http()
        answer = http.post(
            "/api/v1/consumers/fetch",
            json={"topics": self.topics, "max_tasks": max_tasks, "wait_s": self.wait_s if wait_s is None else wait_s},
            headers=self._headers(),
        )
        if answer.status_code == 503:
            return []  # 롱폴링 상한 — 잠깐 쉬고 다시 건다
        answer.raise_for_status()
        found = FetchResponse.model_validate(answer.json())
        self._last_fetch = self.now()
        if found.rotated_token is not None:
            self._rotate(found)
        return found.tasks

    def _rotate(self, found: FetchResponse) -> None:
        """만료 14일 전부터 오는 새 토큰 (C4 §키 회전과 같은 봉함 — salt는 `consumer_id`)."""
        secret = self.tokens.secret()
        if secret is None or found.rotated_token is None or not found.consumer_id:
            return
        try:
            raw = open_sealed(secret, found.rotated_token.sealed_key, salt=found.consumer_id)
        except ValueError:
            log.warning("새 일꾼 토큰을 열지 못했다 — 들고 있던 것을 쓴다")
            return
        if not self.tokens.env_value:
            self.tokens.save(token=raw)

    def handle(self, task: LockedTask) -> None:
        """일감 하나 — 수행하고 끝냈다고 알린다. 실패해도 루프를 멈추지 않는다."""
        service = self._service(task.topic)
        if service is None:
            outcome_body: dict[str, Any] = {"code": "operation_not_found", "message": f"토픽 {task.topic}을 모른다"}
            path = f"/api/v1/consumers/tasks/{task.task_id}/fail"
        else:
            outcome = service.execute(task)
            if outcome.skip:
                return
            path = f"/api/v1/consumers/tasks/{task.task_id}/{'complete' if outcome.ok else 'fail'}"
            outcome_body = outcome.complete_body() if outcome.ok else outcome.fail_body()
        answer = self._http().post(path, json=outcome_body, headers=self._headers())
        if answer.status_code == 409:
            return  # 이미 끝났거나 거뒀다 — 멱등이라 같은 일이다 (C15 §끝내기)
        if answer.status_code >= 400:
            log.warning("일감 %s를 끝내지 못했다: %s %s", task.task_id, answer.status_code, answer.text[:200])

    def run_once(self, *, wait_s: int | None = None) -> int:
        """가져가 **차례로** 수행한다 (시험용 — 스레드 없이). 처리한 수."""
        tasks = self.fetch(max_tasks=self.workers, wait_s=wait_s)
        for task in tasks:
            self.handle(task)
        return len(tasks)

    def run(self, stop: threading.Event) -> None:
        """멈추라고 할 때까지 — 빈 일꾼 자리만큼 가져가 스레드에서 수행한다."""
        busy: set[Future[None]] = set()
        last_catalog = 0.0
        with ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="consumer") as pool:
            while not stop.is_set():
                for one in [one for one in busy if one.done()]:
                    if one.exception() is not None:
                        # 끝내지 못한 일감은 잠금이 풀리면 다시 온다 (C15) — 까닭은 여기서만 보인다
                        log.warning("일감을 수행하다 멈췄다 (%s)", type(one.exception()).__name__)
                busy = {one for one in busy if not one.done()}
                free = self.workers - len(busy)
                try:
                    if time.monotonic() - last_catalog >= CATALOG_EVERY_S:
                        self.publish()
                        last_catalog = time.monotonic()
                    if free <= 0:
                        stop.wait(0.1)
                        continue
                    for task in self.fetch(max_tasks=free):
                        busy.add(pool.submit(self.handle, task))
                except Exception as e:  # noqa: BLE001 — Center가 잠시 없어도 일꾼은 산다
                    log.warning("Center에 닿지 못했다 (%s) — %.0f초 뒤 다시", type(e).__name__, BACKOFF_S)
                    stop.wait(BACKOFF_S)


def start_in_thread(consumer: Consumer) -> tuple[threading.Thread, threading.Event]:
    """일꾼을 데몬 스레드에서 돌린다 — 앱(관리 API)과 같은 프로세스에 둘 때."""
    stop = threading.Event()
    thread = threading.Thread(target=consumer.run, args=(stop,), name="consumer", daemon=True)
    thread.start()
    return thread, stop


__all__ = ["BACKOFF_S", "TOKEN_FILE", "Consumer", "TokenFile", "start_in_thread"]
