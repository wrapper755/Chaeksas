"""레지스트리를 부르는 쪽 — TOL-03이 UI 자동화 앱의 등록 작업을 올린다 (C9·C15).

**Worker는 레지스트리를 모른다** (C9) — 브라우저 일만 한다. 등록·삭제·조회는 이 확장의 도구(Tool UI,
ADR-0077)가 **Center에 외부 작업으로** 올린다 (ADR-0102) — 앱의 주소도 키도 모른다. 토큰은 이 PC
PC 실행기가 청한 **호출 토큰**이고, 등록 작업(`registry_write`)은 그 PC에 「셀렉터 등록」(CON-03)이 켜졌을
때만 Center가 받는다.

- **등록은 LLM을 쓰지 않으니 `mode`는 늘 `deterministic`**이다.
- **멱등 칸은 동작마다 새로 만든다** (`reg_<hex8>`). 재시도는 `attempt`를 올려 같은 `run_id`로
  보낸다 — 같은 등록이 두 번 들어가지 않는다.
- **거절은 다시 보내지 않는다** (큐에 쌓지 않는다). 한 번 거부된 것은 다시 보내도 같은 답이다.
- 토큰은 **값으로만** 들고 있고 어디에도 적지 않는다 (원칙 6).
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field
from typing import Any

from chaeksas.contracts.service_app import MODE_DETERMINISTIC
from chaeksas.ext.ui_automation.contracts.registry import (
    DeletionResult,
    PageBrief,
    PageRegistration,
    RegistrationResult,
)
from chaeksas.ext.ui_automation.worker.plans import CenterOps, OpsRefused, OpsUnreachable

log = logging.getLogger(__name__)

#: C9 — 등록·삭제 동작마다 새 `run_id`. 노드 이름은 고정이다.
RUN_PREFIX = "reg"
NODE_ID = "registry"

#: 부르는 쪽 (C11 `caller.type`) — 도구를 띄우는 것은 Tool UI다 (ADR-0077). 실제 값은 호스트가 준
#: `ExtensionContext.host`를 쓴다(`registration_window.registry_client`) — 이것은 그 기본값이다.
CALLER_TOOL_UI = "tool_ui"


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
    """앱에 닿지 못했다 — 등록은 큐에 쌓고 나중에 보낸다 (TOL-03 8번)."""


@dataclass
class RegistryClient:
    """UI 자동화 앱의 C9 네 작업을 Center에 올린다."""

    #: **Center 주소** (C13 `center.url`).
    base_url: str
    #: 호출 토큰 (C15).
    call_token: str
    timeout_s: float = 30.0
    #: 시험이 끼우는 자리 (httpx.Client 또는 TestClient).
    client: Any = None
    caller_version: str | None = None
    caller_type: str = CALLER_TOOL_UI
    _attempts: dict[str, int] = field(default_factory=dict, repr=False)

    # ── C9 작업 ──

    def list_pages(self, *, platform: str | None = None, query: str | None = None) -> list[PageBrief]:
        found = self.call("registry_list_pages", {"platform": platform, "query": query})
        return [PageBrief.model_validate(one) for one in found.get("pages", [])]

    def get_page(self, page_id: str) -> tuple[PageRegistration, list[str]]:
        """화면 하나 전체. **셀렉터가 들어 있다** — 「셀렉터 등록」을 켠 PC만 부를 수 있다 (C9)."""
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

    def call(self, operation: str, payload: dict[str, Any], *, run_id: str | None = None) -> dict[str, Any]:
        """C15 일감 하나. **재시도는 `attempt`를 올린다** — 같은 `run_id`로."""
        run = run_id or new_run_id()
        self._attempts[run] = self._attempts.get(run, 0) + 1
        ops = CenterOps(
            base_url=self.base_url,
            call_token=self.call_token,
            business_key=f"{run}:{NODE_ID}:1:{self._attempts[run]}",
            mode=MODE_DETERMINISTIC,  # 등록은 LLM을 쓰지 않는다 (C9)
            caller_version=self.caller_version,
            caller_type=self.caller_type,
            timeout_s=self.timeout_s,
            client=self.client,
        )
        body = {key: value for key, value in payload.items() if value is not None}
        try:
            return ops.call(operation, body, call_seq=1)
        except OpsRefused as e:
            raise RegistryProblem(str(e), code=e.code, status=e.status, detail=e.detail) from e
        except OpsUnreachable as e:
            raise RegistryUnreachable(f"UI 자동화 앱에 닿지 못했습니다 — {e}", code=e.code) from e


__all__ = [
    "CALLER_TOOL_UI",
    "NODE_ID",
    "RUN_PREFIX",
    "RegistryClient",
    "RegistryProblem",
    "RegistryUnreachable",
    "new_run_id",
]
