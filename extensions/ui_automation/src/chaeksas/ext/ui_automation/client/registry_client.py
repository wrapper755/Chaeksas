"""레지스트리를 부르는 쪽 — BUI-06이 UI 자동화 앱을 직접 부른다 (C9·C11).

**Worker는 레지스트리를 모른다** (C9) — 브라우저 일만 한다. 등록·삭제·조회는 이 확장의
Bot UI 유틸리티가 자기 키(등록 담당자 키, C13 `registrar_key`)로 직접 부른다.

- 작업 호출은 C11 그대로다 — `POST /v1/ops/<작업>`에 `{schema, mode, run_id, node_id, …}`.
  **등록은 LLM을 쓰지 않으니 `mode`는 늘 `deterministic`**이다.
- **멱등 키는 동작마다 새로 만든다** (`reg_<hex8>`). 재시도는 `attempt`를 올려 같은 `run_id`로
  보낸다 — 같은 등록이 두 번 들어가지 않는다.
- **4xx는 다시 보내지 않는다** (큐에 쌓지 않는다). 한 번 거부된 것은 다시 보내도 같은 답이다.
- 키는 **값으로만** 들고 있고 어디에도 적지 않는다 (ADR-0013·원칙 6).
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field
from typing import Any

from chaeksas.contracts.service_app import MODE_DETERMINISTIC, Caller, OpRequest, OpResponse
from chaeksas.ext.ui_automation.contracts.registry import (
    DeletionResult,
    PageBrief,
    PageRegistration,
    RegistrationResult,
)

log = logging.getLogger(__name__)

#: C9 — 등록·삭제 동작마다 새 `run_id`. 노드 이름은 고정이다.
RUN_PREFIX = "reg"
NODE_ID = "registry"

#: 부르는 쪽 (C11 `caller.type`).
CALLER_BOT_UI = "bot_ui"


def new_run_id() -> str:
    return f"{RUN_PREFIX}_{secrets.token_hex(4)}"


class RegistryProblem(RuntimeError):
    """앱이 거부했다. `code`가 있으면 **다시 보내도 같은 답**인지 판단할 수 있다."""

    def __init__(self, message: str, *, code: str = "", status: int = 0, detail: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.detail = detail or {}

    @property
    def permanent(self) -> bool:
        """**4xx는 다시 보내지 않는다** — 보낸 내용을 고쳐야 한다."""
        return 400 <= self.status < 500


class RegistryUnreachable(RegistryProblem):
    """앱에 닿지 못했다 — 등록은 큐에 쌓고 나중에 보낸다 (BUI-06 8번)."""


@dataclass
class RegistryClient:
    """UI 자동화 앱 하나를 부른다 (C9의 네 작업)."""

    base_url: str
    api_key: str
    timeout_s: float = 15.0
    #: 시험이 끼우는 자리 (httpx.Client 또는 TestClient).
    client: Any = None
    caller_version: str | None = None
    _attempts: dict[str, int] = field(default_factory=dict, repr=False)

    # ── C9 작업 ──

    def list_pages(self, *, platform: str | None = None, query: str | None = None) -> list[PageBrief]:
        found = self.call("registry_list_pages", {"platform": platform, "query": query})
        return [PageBrief.model_validate(one) for one in found.get("pages", [])]

    def get_page(self, page_id: str) -> tuple[PageRegistration, list[str]]:
        """화면 하나 전체. **셀렉터가 들어 있다** — `registry_write` 키만 부를 수 있다 (C9)."""
        found = self.call("registry_get_page", {"page_id": page_id})
        return PageRegistration.model_validate(found["page"]), list(found.get("warnings", []))

    def register(self, page: PageRegistration) -> RegistrationResult:
        found = self.call("registry_register", {"page": page.to_json_dict()})
        return RegistrationResult.model_validate(found)

    def delete(self, page_id: str, semantic_key: str | None = None, *, force: bool = False) -> DeletionResult:
        found = self.call(
            "registry_delete", {"page_id": page_id, "semantic_key": semantic_key, "force": force}
        )
        return DeletionResult.model_validate(found)

    # ── 부르기 ──

    def request(self, operation: str, payload: dict[str, Any], *, run_id: str) -> OpRequest:
        """C11 요청 하나. **재시도는 `attempt`를 올린다** — 같은 `run_id`로."""
        self._attempts[run_id] = self._attempts.get(run_id, 0) + 1
        return OpRequest(
            schema=1,
            mode=MODE_DETERMINISTIC,  # 등록은 LLM을 쓰지 않는다 (C9)
            run_id=run_id,
            node_id=NODE_ID,
            node_instance=1,
            attempt=self._attempts[run_id],
            call_seq=1,
            caller=Caller(type=CALLER_BOT_UI, version=self.caller_version),
            input={key: value for key, value in payload.items() if value is not None},
        )

    def call(self, operation: str, payload: dict[str, Any], *, run_id: str | None = None) -> dict[str, Any]:
        import httpx  # noqa: PLC0415 — 부를 때만 든다

        body = self.request(operation, payload, run_id=run_id or new_run_id())
        own = self.client is None
        client = self.client or httpx.Client(timeout=self.timeout_s)
        try:
            response = client.post(
                f"{self.base_url.rstrip('/')}/v1/ops/{operation}",
                json=body.to_json_dict(),
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
        except httpx.HTTPError as e:
            raise RegistryUnreachable(f"UI 자동화 앱에 닿지 못했습니다 ({type(e).__name__})") from e
        finally:
            if own:
                client.close()
        return _checked(response)


def _checked(response: Any) -> dict[str, Any]:
    """C11 응답 → 출력. 오류는 **코드를 들고** 올린다 (다시 보낼지 판단해야 한다)."""
    if response.status_code >= 400:
        body = _body(response)
        raise RegistryProblem(
            str(body.get("message") or f"앱이 거부했습니다 ({response.status_code})"),
            code=str(body.get("code") or ""),
            status=response.status_code,
            detail=body.get("detail"),
        )
    found = OpResponse.model_validate(_body(response))
    return dict(found.output)


def _body(response: Any) -> dict[str, Any]:
    try:
        found = response.json()
    except ValueError:
        return {}
    return dict(found) if isinstance(found, dict) else {}


__all__ = [
    "CALLER_BOT_UI",
    "NODE_ID",
    "RUN_PREFIX",
    "RegistryClient",
    "RegistryProblem",
    "RegistryUnreachable",
    "new_run_id",
]
