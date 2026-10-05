"""Center를 부르는 쪽 (C5) — Admin 명령이 쓴다.

**토큰은 문을 여는 것일 뿐**이다. 무엇이 바뀌는지는 봉투(C2)가 정한다 — 그래서 여기서는
봉투를 그대로 싣고, 토큰은 헤더에 붙일 뿐이다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from chaeksas.contracts.signing import AdminKey, Envelope

ENV_PREFIX = "CHK_ADMIN__"
DEFAULT_CENTER_URL = "http://localhost:8800"
API = "/api/v1"


class CenterProblem(RuntimeError):
    """Center가 거절했거나 닿지 못했다. `code`가 있으면 계약의 사유다."""

    def __init__(self, message: str, *, code: str = "", status: int = 0) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass
class Center:
    """Center 하나. 관리자 토큰은 **환경변수로** 받는다 (명령줄은 기록에 남는다)."""

    base_url: str = ""
    token: str = ""
    timeout_s: float = 30.0
    client: Any = None  # httpx.Client (시험이 끼운다)

    @classmethod
    def from_env(cls) -> Center:
        return cls(
            base_url=os.environ.get(f"{ENV_PREFIX}CENTER_URL") or DEFAULT_CENTER_URL,
            token=os.environ.get(f"{ENV_PREFIX}ADMIN_TOKEN") or "",
        )

    def call(self, method: str, path: str, *, body: Any = None) -> Any:
        import httpx  # noqa: PLC0415 — 부를 때만 든다

        own = self.client is None
        client = self.client or httpx.Client(timeout=self.timeout_s)
        try:
            response = client.request(
                method,
                f"{self.base_url.rstrip('/')}{API}{path}",
                json=body,
                headers={"Authorization": f"Bearer {self.token}"} if self.token else {},
            )
        except httpx.HTTPError as e:
            raise CenterProblem(f"Center에 닿지 못했습니다 ({type(e).__name__})") from e
        finally:
            if own:
                client.close()
        return _checked(response)

    # ── C5 ──

    def packages(self, *, status: str | None = None) -> list[dict[str, Any]]:
        found = self.call("GET", f"/packages{f'?status={status}' if status else ''}")
        return list(found) if isinstance(found, list) else []

    def package(self, package_id: str, version: str) -> dict[str, Any]:
        return dict(self.call("GET", f"/packages/{package_id}/{version}/info"))

    def approve(self, package_id: str, version: str, envelope: Envelope) -> dict[str, Any]:
        return dict(
            self.call("PUT", f"/packages/{package_id}/{version}/signature", body=envelope.to_json_dict())
        )

    def revoke_package(self, package_id: str, version: str, envelope: Envelope) -> dict[str, Any]:
        return dict(
            self.call("POST", f"/packages/{package_id}/{version}/revoke", body=envelope.to_json_dict())
        )

    def deploy(self, envelope: Envelope) -> dict[str, Any]:
        return dict(self.call("POST", "/deployments", body=envelope.to_json_dict()))

    def revoke_deployment(self, envelope: Envelope) -> dict[str, Any]:
        return dict(self.call("DELETE", "/deployments", body=envelope.to_json_dict()))

    def deployments(self, *, bot_ui: str | None = None, active: bool = True) -> list[dict[str, Any]]:
        query = f"?active={'true' if active else 'false'}" + (f"&bot_ui={bot_ui}" if bot_ui else "")
        found = self.call("GET", f"/deployments{query}")
        return list(found) if isinstance(found, list) else []

    def bot_uis(self) -> list[dict[str, Any]]:
        found = self.call("GET", "/bot-uis")
        return list(found) if isinstance(found, list) else []

    def admin_keys(self) -> list[AdminKey]:
        found = self.call("GET", "/admin-keys")
        return [AdminKey.model_validate(one) for one in found] if isinstance(found, list) else []

    def add_admin_key(self, envelope: Envelope) -> AdminKey:
        return AdminKey.model_validate(self.call("POST", "/admin-keys", body=envelope.to_json_dict()))

    def revoke_admin_key(self, envelope: Envelope) -> AdminKey:
        return AdminKey.model_validate(self.call("DELETE", "/admin-keys", body=envelope.to_json_dict()))


def _checked(response: Any) -> Any:
    if response.status_code >= 400:
        body = {}
        try:
            body = response.json()
        except ValueError:
            pass
        raise CenterProblem(
            str(body.get("message") or f"Center가 거절했습니다 ({response.status_code})"),
            code=str(body.get("code") or ""),
            status=response.status_code,
        )
    return response.json() if response.content else {}


__all__ = ["API", "DEFAULT_CENTER_URL", "ENV_PREFIX", "Center", "CenterProblem"]
