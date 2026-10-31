"""Studio의 호출 토큰 (C15 「정한 것」) — 확장 코드가 Studio를 대신해 외부 작업을 올릴 때 쓴다.

확장은 `ctx.secret("call_token")`으로 이것을 받는다. **Studio가 제 Center API 키로 청한다**(24시간)
— 확장에게 Studio 키 자체를 넘기지 않는다. 받은 토큰은 Studio와 같은 신원이라 `test_…` 실행만
올린다 (C15 §올리기).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from chaeksas.contracts.external_task import CallToken

log = logging.getLogger(__name__)

PATH = "/api/v1/call-tokens"
#: 만료까지 이만큼 남으면 새로 청한다 (C15 — 2시간 전).
RENEW_S = 2 * 3600


@dataclass
class CallTokens:
    """한 Studio의 호출 토큰. 닿지 못하면 들고 있던 것을 준다(아직 살아 있으면)."""

    base_url: str
    api_key: str
    client: Any = None
    _held: CallToken | None = None

    def __call__(self) -> str | None:
        now = datetime.now(UTC)
        held = self._held
        if held is not None and datetime.fromisoformat(held.expires_at) - now > timedelta(seconds=RENEW_S):
            return held.token
        import httpx  # noqa: PLC0415 — 부를 때만 든다

        own = self.client is None
        client = self.client or httpx.Client(timeout=10.0)
        try:
            answer = client.post(
                self.base_url.rstrip("/") + PATH, json={}, headers={"Authorization": f"Bearer {self.api_key}"}
            )
            answer.raise_for_status()
            self._held = CallToken.model_validate(answer.json())
        except Exception as e:  # noqa: BLE001 — Center가 없으면 UI 태스크가 그 자리에서 말한다
            log.warning("호출 토큰을 받지 못했다: %s", e)
            if held is not None and datetime.fromisoformat(held.expires_at) > now:
                return held.token
            return None
        finally:
            if own:
                client.close()
        return self._held.token


def from_settings(settings: Any) -> CallTokens | None:
    """STU-10 설정과 Studio 키로 — 둘 중 하나라도 없으면 `None`(청하지 않는다)."""
    from chaeksas.studio.credentials import StudioCredentials  # noqa: PLC0415 — 순환 피함

    base = str(getattr(settings, "center_url", "") or "").strip()
    key = StudioCredentials().center_api_key()
    if not base or not key:
        return None
    return CallTokens(base_url=base, api_key=key)


__all__ = ["PATH", "RENEW_S", "CallTokens", "from_settings"]
