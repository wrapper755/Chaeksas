"""Center가 짓는 키를 받는다 (C11 §Center가 발급하는 키, ADR-0094).

- 앱은 설정의 Center 주소(`CHK_SVC_<APP>__CENTER__URL`)에서 **Center 서명 공개키**를 받아 두고
  (`GET <Center>/api/v1/signing-keys`, 인증 없음), 그 키가 서명한 봉투(`kind: service_key`)만 받는다.
  검증은 현장이 배포 봉투를 볼 때와 **같은 `verify()`**다 (`contracts.service_keys.check_claim`).
- **원문은 오지 않는다** — 해시·앞자리만 받아 키 레코드를 만든다. 앱이 스스로 검증하는 것은 그대로다.
- 받은 공개키 목록은 **들고 있다** — Center에 닿지 못해도 그것으로 검증한다(ADR-0007의 결).
  모르는 `key_id`가 오면 5분에 한 번까지 다시 받는다(서명 키를 바꿨다).
- 선택 설정 `CHK_SVC_<APP>__CENTER__KEY_PIN`이 있으면 받은 목록에 그 키가 있을 때만 믿는다.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from chaeksas.contracts.service_app import ServiceAppKey
from chaeksas.contracts.service_keys import (
    ACTION_ISSUE,
    ACTION_REVOKE,
    CENTER_KEY_PREFIX,
    CenterTrust,
    check_claim,
)
from chaeksas.contracts.signing import AdminKey, Envelope
from chaeksas.service_kit.stores import KeyStore

log = logging.getLogger(__name__)

#: 모르는 `key_id`를 보고 다시 받을 때의 최소 간격 (초).
REFETCH_MIN_S = 300
#: 공개키를 받으러 갈 때 기다리는 시간 (초).
FETCH_TIMEOUT_S = 5.0
SIGNING_KEYS_PATH = "/api/v1/signing-keys"

#: 공개키 목록을 받아 오는 함수 — 시험은 바꿔 끼운다. 닿지 못하면 예외.
Fetch = Callable[[str], list[dict[str, Any]]]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def http_fetch(url: str) -> list[dict[str, Any]]:
    import httpx  # noqa: PLC0415 — 부를 때만 든다

    with httpx.Client(timeout=FETCH_TIMEOUT_S, follow_redirects=False) as client:
        answer = client.get(url)
        answer.raise_for_status()
        body = answer.json()
    if not isinstance(body, list):
        raise ValueError("공개키 목록이 배열이 아니다")
    return body


class TrustStore(Protocol):
    """받아 둔 Center 공개키 목록. 앱을 다시 띄워도 남아야 한다 (Center가 잠시 없어도 검증한다)."""

    def load(self) -> tuple[list[AdminKey], str | None]: ...

    def save(self, keys: list[AdminKey], *, fetched_at: str) -> None: ...


@dataclass
class InMemoryTrustStore:
    keys: list[AdminKey] = field(default_factory=list)
    fetched_at: str | None = None

    def load(self) -> tuple[list[AdminKey], str | None]:
        return list(self.keys), self.fetched_at

    def save(self, keys: list[AdminKey], *, fetched_at: str) -> None:
        self.keys = list(keys)
        self.fetched_at = fetched_at


@dataclass
class CenterLink:
    """이 앱이 믿는 Center 하나. `center_url`이 비면 Center 발급을 받지 않는다."""

    center_url: str
    pin: str | None = None
    store: TrustStore = field(default_factory=InMemoryTrustStore)
    fetch: Fetch = http_fetch
    now: Callable[[], str] = _now
    clock: Callable[[], float] = time.monotonic
    _last_try: float | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)
    problem: str | None = None

    @classmethod
    def from_env(
        cls, prefix: str, environ: Mapping[str, str] | None = None, *, store: TrustStore | None = None
    ) -> CenterLink | None:
        """`prefix`는 앱의 접두사 그대로다 (`CHK_SVC_UI_AUTOMATION__`). 주소가 없으면 `None`."""
        env = os.environ if environ is None else environ
        url = (env.get(f"{prefix}CENTER__URL") or "").strip().rstrip("/")
        if not url:
            return None
        pin = (env.get(f"{prefix}CENTER__KEY_PIN") or "").strip() or None
        return cls(center_url=url, pin=pin, store=store or InMemoryTrustStore())

    def keys(self) -> list[AdminKey]:
        found, _ = self.store.load()
        return found

    def refresh(self, *, force: bool = False) -> bool:
        """공개키 목록을 다시 받는다. 받았으면 참. **간격 안이면 묻지 않는다** (`force`가 아니면)."""
        with self._lock:
            at = self.clock()
            if not force and self._last_try is not None and at - self._last_try < REFETCH_MIN_S:
                return False
            self._last_try = at
            try:
                raw = self.fetch(self.center_url + SIGNING_KEYS_PATH)
                got = [AdminKey.model_validate(one) for one in raw]
            except Exception as e:  # 닿지 못함·모양이 틀림 — 들고 있던 것으로 검증한다
                self.problem = f"Center 공개키를 받지 못했다: {type(e).__name__}"
                log.warning("%s (%s)", self.problem, self.center_url)
                return False
            if self.pin and not any(one.key_id == self.pin and not one.revoked for one in got):
                # **믿지 않는다** — 고정한 키가 없는 목록은 다른 Center이거나 바꿔치기다.
                self.problem = f"받은 목록에 고정한 키 {self.pin}이 없다 (CENTER__KEY_PIN)"
                log.warning("%s (%s)", self.problem, self.center_url)
                self.store.save([], fetched_at=self.now())
                return False
            self.problem = None
            self.store.save(got, fetched_at=self.now())
            return True

    def ensure(self) -> None:
        """뜬 뒤 한 번도 묻지 않았으면 지금 묻는다 (첫 요청·첫 `trust` 때). 띄우는 것은 막지 않는다."""
        if self._last_try is None:
            self.refresh(force=True)

    def trust(self) -> CenterTrust:
        found, fetched_at = self.store.load()
        return CenterTrust(
            center_url=self.center_url,
            key_ids=[one.key_id for one in found if not one.revoked],
            fetched_at=fetched_at,
            pinned=bool(self.pin),
        )


def _error(status: int, code: str, message: str, detail: dict[str, Any] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "message": message, "detail": detail or {}})


#: 위반 코드 → (상태, C11 코드).
_REFUSALS: dict[str, tuple[int, str]] = {
    "unknown_key": (401, "center_signature_invalid"),
    "bad_signature": (401, "center_signature_invalid"),
    "unsupported_alg": (401, "center_signature_invalid"),
    "float_in_payload": (401, "center_signature_invalid"),
    "revoked_key": (403, "center_key_revoked"),
    "envelope_expired": (403, "envelope_expired"),
    "wrong_app": (422, "wrong_app"),
    "wrong_kind": (422, "wrong_kind"),
    "input_invalid": (422, "input_invalid"),
}


def create_router(
    *,
    app_id: str,
    keys: KeyStore,
    link: CenterLink | None,
    now: Callable[[], str] = _now,
) -> APIRouter:
    """`/center/v1/trust`·`/center/v1/keys`. `create_app()`이 붙인다."""
    router = APIRouter(prefix="/center/v1", tags=["center"])

    @router.get("/trust")
    def trust() -> Any:
        """인증 없음 — 비밀이 없다. Center가 등록·상태 볼 때 읽는다 (C7 `trust`)."""
        if link is None:
            return CenterTrust()
        link.ensure()
        return link.trust()

    @router.post("/keys")
    async def center_keys(request: Request) -> Any:
        if link is None:
            return _error(503, "center_disabled", "이 앱은 Center 발급을 받지 않는다 (CHK_SVC_<APP>__CENTER__URL)")
        try:
            envelope = Envelope.model_validate(await request.json())
        except ValueError:
            return _error(422, "input_invalid", "본문이 C2 봉투가 아니다")
        link.ensure()
        trusted = link.keys()
        if not any(one.key_id == envelope.key_id for one in trusted):
            # 서명 키를 바꿨을 수 있다 — 한 번 다시 받는다 (간격 안이면 묻지 않는다).
            link.refresh()
            trusted = link.keys()
        claim, problems = check_claim(envelope, keys=trusted, app_id=app_id, now=now())
        if problems or claim is None:
            first = problems[0]
            status, code = _REFUSALS.get(first.code or "", (422, first.code or "input_invalid"))
            return _error(status, code, first.message)
        return _apply(keys, claim, now=now())

    return router


def _find(keys: KeyStore, center_key_id: str) -> ServiceAppKey | None:
    return next((k for k in keys.all_keys() if k.center_key_id == center_key_id), None)


def _apply(keys: KeyStore, claim: Any, *, now: str) -> Any:
    """짓기·고치기·폐기. **멱등**이다 — 같은 id·같은 해시면 같은 답 (Center가 그대로 다시 보낸다)."""
    from chaeksas.contracts.service_app import key_state  # noqa: PLC0415

    found = _find(keys, claim.center_key_id)
    if claim.action == ACTION_ISSUE:
        if found is not None:
            if found.hash != claim.hash:
                return _error(409, "key_conflict", f"{claim.center_key_id}가 다른 해시로 이미 있다")
            return {"center_key_id": claim.center_key_id, "state": key_state(found, now=now)}
        if not claim.center_key_id.startswith(CENTER_KEY_PREFIX):
            return _error(422, "input_invalid", f"Center 키 id는 {CENTER_KEY_PREFIX}로 시작한다")
        record = ServiceAppKey(
            name=claim.center_key_id,
            hash=claim.hash,
            prefix=claim.prefix,
            allowed_operations=list(claim.allowed_operations or ["*"]),
            allowed_modes=list(claim.allowed_modes or ["deterministic"]),
            extra_scopes=list(claim.extra_scopes or []),
            created_at=now,
            expires_at=claim.expires_at,
            issued_by="center",
            center_key_id=claim.center_key_id,
            issued_for=claim.issued_for,
        )
        keys.add(record)
        return {"center_key_id": claim.center_key_id, "state": key_state(record, now=now)}
    if found is None:
        return _error(404, "key_not_found", f"{claim.center_key_id}가 없다")
    if claim.action == ACTION_REVOKE:
        if found.revoked_at is None:
            keys.revoke(found, at=now)
        after = _find(keys, claim.center_key_id) or found
        return {"center_key_id": claim.center_key_id, "state": key_state(after, now=now)}
    # update — 허용 작업·만료만 고친다 (판을 올려도 같은 키, ADR-0094 §3).
    changed = found.model_copy(
        update={
            "allowed_operations": list(claim.allowed_operations or found.allowed_operations),
            "allowed_modes": list(claim.allowed_modes or found.allowed_modes),
            "extra_scopes": list(claim.extra_scopes if claim.extra_scopes is not None else found.extra_scopes),
            "expires_at": claim.expires_at,
        }
    )
    keys.put(changed)
    return {"center_key_id": claim.center_key_id, "state": key_state(changed, now=now)}


__all__ = ["CenterLink", "InMemoryTrustStore", "TrustStore", "create_router", "http_fetch"]
