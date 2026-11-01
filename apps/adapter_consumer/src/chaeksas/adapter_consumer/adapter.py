"""외부 확장 하나를 일꾼의 토픽으로 — HTTP 어댑터를 돌린다 (C13 §4·C15, ADR-0102).

**주소·키는 이 일꾼의 설정만 안다.** Center도 BPM 프로세스도 모른다. 확장마다 환경변수로 받는다:

| 환경변수 | 뜻 |
| --- | --- |
| `BPM_ADAPTER__EXT__<확장>__BASE_URL` | 운영 주소 (없으면 정의의 `base_url`) |
| `BPM_ADAPTER__EXT__<확장>__KEY` | 운영 키 (키를 받는 앱만 — C13 `auth`) |
| `BPM_ADAPTER__EXT__<확장>__TEST_BASE_URL` · `…__TEST_KEY` | 시험 일감(`origin: test`)에 쓴다. 없으면 운영 쪽 |
| `BPM_ADAPTER__ALLOW_PRIVATE_NETWORK` | `1`이면 정의가 허용한 사설망으로 나간다 (기본 닫힘 — 둘 다 열어야 한다) |

해석기는 실행하는 쪽이 쓰던 `core.http_adapter.AdapterCaller` 그대로다 — 막는 규칙(허용 호스트·https·
DNS 고정·리다이렉트 금지·크기 상한)이 한 벌이다.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from chaeksas.contracts.extension import Catalog, ExtensionManifest
from chaeksas.contracts.external_task import ORIGIN_TEST, LockedTask
from chaeksas.contracts.service_app import MODE_DETERMINISTIC, Operation, OpResponse, ServiceAppManifest, Usage
from chaeksas.core.http_adapter import AdapterCaller
from chaeksas.core.services import OpCall, ServiceCallError
from chaeksas.service_kit.app import CatalogSource, Outcome
from chaeksas.service_kit.stores import InMemoryIdempotencyStore, body_hash

ENV_PREFIX = "BPM_ADAPTER__"


def _env_name(text: str) -> str:
    return "".join(one if one.isalnum() else "_" for one in text).upper()


def ext_env(extension_id: str, name: str) -> str:
    """확장 하나의 설정 칸 → 환경변수 이름 (`BPM_ADAPTER__EXT__EXT_CREDIT__BASE_URL`)."""
    return f"{ENV_PREFIX}EXT__{_env_name(extension_id)}__{name}"


@dataclass(frozen=True)
class Place:
    """일감 하나가 갈 곳 — `AdapterCaller`의 `addresses`. 키 참조는 보지 않는다 (확장마다 하나다)."""

    url: str | None
    secret: str | None

    def base_url(self, app_id: str) -> str | None:
        del app_id
        return self.url

    def key(self, key_ref: str) -> str | None:
        del key_ref
        return self.secret


def manifest_of(definition: ExtensionManifest) -> ServiceAppManifest:
    """정의의 어댑터 작업 → C11 manifest 모양 (C15 — Center가 작업·모드를 대조한다)."""
    adapter = definition.service.adapter if definition.service is not None else None
    operations = [
        Operation(
            name=one.name,
            description=one.description,
            modes=list(one.modes),
            input_schema=one.input_schema,
            output_schema=one.output_schema,
            server_ok=one.server_ok,
        )
        for one in (adapter.operations if adapter is not None else [])
    ]
    return ServiceAppManifest.model_validate(
        {
            "schema": 1,
            "app_id": definition.id,
            "name": definition.name or definition.id,
            "version": definition.version,
            "category": "business",
            "console_url": "",
            "operations": [one.to_json_dict() for one in operations],
        }
    )


@dataclass
class AdapterService:
    """외부 확장 하나 = 일꾼의 토픽 하나 (`service_kit.TopicService`)."""

    definition: ExtensionManifest
    environ: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))
    #: 정의 파일에서 읽은 **그대로**의 정의 — Center에 올린다 (해시가 원문에서 나오므로 모델로 다시 쓰지 않는다).
    raw: dict[str, Any] | None = None
    client: Any = None  # httpx.Client (시험이 끼운다)
    resolver: Any = None  # 호스트 → IP (시험이 끼운다)
    idempotency: InMemoryIdempotencyStore = field(default_factory=InMemoryIdempotencyStore)
    _manifest: ServiceAppManifest | None = None

    @property
    def app_id(self) -> str:
        return self.definition.id

    @property
    def extension_definition(self) -> dict[str, Any] | None:
        """일꾼이 Center에 올릴 외부 확장 정의 (`service_kit.Consumer.publish`, ADR-0122)."""
        return self.raw

    @property
    def manifest(self) -> ServiceAppManifest:
        if self._manifest is None:
            self._manifest = manifest_of(self.definition)
        return self._manifest

    @property
    def catalogs(self) -> Mapping[str, CatalogSource]:
        """정의가 선언한 카탈로그 (C13 §5) — 외부 앱에서 읽어 Center에 올린다 (C7)."""
        out: dict[str, CatalogSource] = {}
        for one in self.definition.contributes.resources:
            if one.catalog_url:
                out[one.type] = self._catalog_reader(one.catalog_url)
        return out

    def _catalog_reader(self, path: str) -> Callable[[], Catalog]:
        def read() -> Catalog:
            import httpx  # noqa: PLC0415

            base = self.place(test=False).url or ""
            answer = (self.client or httpx).get(base.rstrip("/") + path, timeout=10.0, follow_redirects=False)
            answer.raise_for_status()
            return Catalog.model_validate(answer.json())

        return read

    def _setting(self, name: str) -> str | None:
        found = self.environ.get(ext_env(self.app_id, name))
        return found.strip() if found and found.strip() else None

    def place(self, *, test: bool) -> Place:
        """운영 또는 시험 쪽 — 시험 칸이 비면 운영 쪽을 쓴다 (ADR-0102 §6)."""
        url = (self._setting("TEST_BASE_URL") if test else None) or self._setting("BASE_URL")
        key = (self._setting("TEST_KEY") if test else None) or self._setting("KEY")
        return Place(url=url, secret=key)

    def _definition_for_run(self) -> ExtensionManifest:
        """정의가 사설망을 허용해도 **이 일꾼 설정도 열어야** 나간다 (C13 「어댑터 일꾼」)."""
        allowed = self.environ.get(f"{ENV_PREFIX}ALLOW_PRIVATE_NETWORK", "").strip() in ("1", "true", "yes")
        service = self.definition.service
        if allowed or service is None or service.adapter is None or not service.adapter.allow_private_network:
            return self.definition
        closed = service.adapter.model_copy(update={"allow_private_network": False})
        return self.definition.model_copy(update={"service": service.model_copy(update={"adapter": closed})})

    def execute(self, task: LockedTask) -> Outcome:
        """일감 하나 — 같은 멱등 칸이면 저장된 결과를 다시 준다 (최소 한 번 실행, C15)."""
        key = ("adapter", task.operation, task.idempotency.run_id, task.idempotency.node_id,
               task.idempotency.node_instance, task.idempotency.attempt, task.idempotency.call_seq)
        digest = body_hash_of(task)
        outcome, stored = self.idempotency.begin(key, body=digest)
        if outcome == "conflict":
            return Outcome(code="idempotency_conflict", message="같은 멱등 칸인데 본문이 다르다")
        if outcome == "in_progress":
            return Outcome(skip=True)
        if outcome == "replay" and stored is not None:
            return Outcome(response=stored.model_copy(update={"replayed": True}))
        call = OpCall(
            app_id=self.app_id,
            operation=task.operation,
            mode=task.mode or MODE_DETERMINISTIC,
            input=dict(task.input),
            run_id=task.idempotency.run_id,
            node_id=task.idempotency.node_id,
            node_instance=task.idempotency.node_instance,
            attempt=task.idempotency.attempt,
            call_seq=task.idempotency.call_seq,
            key_ref="adapter",
            bpm_process_id=task.caller.bpm_process_id or "",
            version=task.caller.version or "0.0.0",
        )
        caller = AdapterCaller(
            definitions={self.app_id: self._definition_for_run()},
            addresses=self.place(test=task.origin == ORIGIN_TEST),
            client=self.client,
            resolver=self.resolver,
        )
        try:
            found = caller.call(call)
        except ServiceCallError as e:
            self.idempotency.abandon(key)
            return Outcome(
                code=e.code or "operation_failed", message=str(e), retryable=e.retryable,
                outcome_unknown=e.outcome_unknown,
            )
        except Exception:
            # 자리를 비워 두지 않으면 다시 온 일감이 모두 「수행 중」으로 건너뛰어진다
            self.idempotency.abandon(key)
            raise
        response = OpResponse(
            status="ok",
            output=dict(found.output),
            mode_used=found.mode_used,
            replayed=False,
            usage=Usage.model_validate(found.usage) if found.usage else None,
        )
        self.idempotency.finish(key, response=response)
        return Outcome(response=response)


def body_hash_of(task: LockedTask) -> str:
    """C11과 같은 규칙 — 입력·모드의 해시 (`service_kit.body_hash`가 받는 모양으로)."""
    from chaeksas.contracts.service_app import OpRequest  # noqa: PLC0415

    return body_hash(
        OpRequest.model_validate(
            {
                "schema": 1,
                "mode": task.mode,
                "run_id": task.idempotency.run_id,
                "node_id": task.idempotency.node_id,
                "node_instance": task.idempotency.node_instance,
                "attempt": task.idempotency.attempt,
                "caller": task.caller.to_json_dict(),
                "input": task.input,
            }
        )
    )


__all__ = ["ENV_PREFIX", "AdapterService", "Place", "body_hash_of", "ext_env", "manifest_of"]
