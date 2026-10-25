"""Studio 개발 키 — 승인된 Studio 키로 Center에 청한다 (C5 §Studio 개발 키, ADR-0094 §5).

설계자는 서비스 앱 키를 붙여 넣지 않는다. 시험 실행·「연결 테스트」·편집기 시험이 앱을 부를 때
**그 앱 하나의 개발 키**(자율·결정, 7일)를 Center에 청하고, 받은 것은 OS 비밀 저장소에 둔다.

- **앱마다 키 하나다** — 참조 이름으로 찾지 않는다. 시험 실행이 어느 참조를 풀든 그 앱의 개발 키다.
- 찾는 순서: 환경변수 `CHK_STUDIO__SVC__<참조>`(자동화·CI) → 사람이 넣어 둔 옛 자리(`svc:<참조>`)
  → **그 앱의 개발 키**(`dev:<앱>`). 개발 키는 만료 하루 전부터 다음에 쓸 때 다시 청한다.
- 외부 앱은 관리자가 넣은 **시험용 키**가 온다 (ADR-0094 §7). 없으면 Center가 404로 말한다.
- **Qt를 모른다** — 창은 결과(`problems`)만 보인다.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from chaeksas.contracts.enrollment import SealError, new_keypair, open_sealed
from chaeksas.contracts.service_keys import StudioServiceKey
from chaeksas.studio.credentials import StudioCredentials, service_key_env

log = logging.getLogger(__name__)

PREFIX = "dev:"
#: 만료가 이만큼 남으면 다음에 쓸 때 다시 청한다.
RENEW_BEFORE = timedelta(days=1)
PATH = "/api/v1/studio/service-keys"
TIMEOUT_S = 10.0

#: `(app_id, public_key) → StudioServiceKey`. 닿지 못하거나 거절되면 `DevKeyRefused`.
Fetch = Callable[[str, str], StudioServiceKey]


class DevKeyRefused(RuntimeError):
    """Center가 개발 키를 주지 않았다 — `code`는 Center가 준 그대로 (`no_test_key`·`app_not_trusting_center`…)."""

    def __init__(self, message: str, *, code: str = "") -> None:
        super().__init__(message)
        self.code = code


def http_fetch(base_url: str, api_key: str) -> Fetch:
    def go(app_id: str, public_key: str) -> StudioServiceKey:
        import httpx  # noqa: PLC0415 — 부를 때만 든다

        try:
            with httpx.Client(timeout=TIMEOUT_S, follow_redirects=False) as client:
                answer = client.post(
                    base_url.rstrip("/") + PATH,
                    json={"app_id": app_id, "public_key": public_key},
                    headers={"Authorization": f"Bearer {api_key}"},
                )
        except httpx.HTTPError as e:
            raise DevKeyRefused(f"Center에 닿지 못했습니다 — {type(e).__name__}", code="unreachable") from e
        if answer.status_code >= 400:
            try:
                body = answer.json()
            except ValueError:
                body = {}
            raise DevKeyRefused(str(body.get("message") or answer.status_code), code=str(body.get("code") or ""))
        return StudioServiceKey.model_validate(answer.json())

    return go


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class DevKeys:
    """앱마다 개발 키 하나. `fetch`가 없으면(Center 주소·키가 없다) 들고 있던 것만 쓴다."""

    credentials: StudioCredentials = field(default_factory=StudioCredentials)
    fetch: Fetch | None = None
    now: Callable[[], datetime] = _now
    #: 받지 못한 앱과 그 까닭 — 창이 그대로 보인다 (STU-10 「서비스 앱」·STU-08).
    problems: dict[str, str] = field(default_factory=dict)

    def held(self, app_id: str) -> tuple[str, str | None] | None:
        """들고 있는 `(키, 만료)`. 없으면 `None`. 키 값은 이 함수 밖으로 나가지 않게 쓴다."""
        raw = self.credentials.stored(PREFIX + app_id)
        if not raw:
            return None
        try:
            body = json.loads(raw)
            return str(body["key"]), body.get("expires_at")
        except (ValueError, KeyError, TypeError):
            return None

    def _fresh(self, expires_at: str | None) -> bool:
        if not expires_at:
            return True
        return datetime.fromisoformat(expires_at) - self.now() > RENEW_BEFORE

    def key_for(self, app_id: str) -> str | None:
        """그 앱의 개발 키. 없거나 만료가 가까우면 Center에 청한다. 받지 못하면 `problems`에 까닭."""
        found = self.held(app_id)
        if found is not None and self._fresh(found[1]):
            return found[0]
        if self.fetch is None:
            self.problems.setdefault(app_id, "Center 키가 없습니다 — Center에 연결하세요")
            return found[0] if found is not None and not self._expired(found[1]) else None
        private, public = new_keypair()
        try:
            got = self.fetch(app_id, public)
            raw = open_sealed(private, got.sealed_key, salt=got.service_key_id)
        except (DevKeyRefused, SealError) as e:
            self.problems[app_id] = str(e)
            log.warning("%s의 개발 키를 받지 못했다: %s", app_id, e)
            return found[0] if found is not None and not self._expired(found[1]) else None
        try:
            self.credentials.set(PREFIX + app_id, json.dumps({"key": raw, "expires_at": got.expires_at}))
        except Exception as e:  # 비밀 저장소가 없다 — 이번 실행에만 쓰고 다음에 또 청한다
            log.warning("개발 키를 비밀 저장소에 두지 못했다: %s", e)
        self.problems.pop(app_id, None)
        return raw

    def _expired(self, expires_at: str | None) -> bool:
        return bool(expires_at) and datetime.fromisoformat(str(expires_at)) <= self.now()

    def resolver(self, apps_of_refs: Mapping[str, str]) -> Callable[[str], str | None]:
        """참조 이름 → 키. `apps_of_refs`는 그 BPM 프로세스의 `{참조: 앱}`이다 (C1 `requires.service_apps`)."""

        def resolve(ref: str) -> str | None:
            found = self.credentials.get(f"svc:{ref}", env=service_key_env(ref))
            if found:
                return found
            app_id = apps_of_refs.get(ref)
            return self.key_for(app_id) if app_id else None

        return resolve


def from_settings(settings: Any, credentials: StudioCredentials | None = None) -> DevKeys:
    """STU-10 설정의 Center 주소와 승인된 Studio 키로 청하는 한 벌."""
    store = credentials or StudioCredentials()
    base = str(getattr(settings, "center_url", "") or "").strip()
    key = store.center_api_key()
    return DevKeys(credentials=store, fetch=http_fetch(base, key) if base and key else None)


__all__ = ["DevKeyRefused", "DevKeys", "from_settings", "http_fetch"]
