"""서비스 앱 키를 Center가 짓고 나른다 (C11 §Center가 발급하는 키, C4 §서비스 앱 키 전달).

단일 원본: `docs/03-contracts/C11-service-app-common.md`·`C4-bot-ui-center.md`,
[ADR-0094](../../../../../docs/decisions/0094-service-app-keys-ride-the-deployment.md).

- **원문은 Center가 짓고 앱에는 해시만** 간다 — `ServiceKeyClaim`(C2 봉투 `kind: service_key`).
  앱은 현장이 배포 봉투를 볼 때와 **같은 `verify()`**에 셋(종류·앱·`not_after`)을 더 본다
  (`check_claim`).
- 원문은 짓는 자리에서 **배포 대상의 공개키로 봉하고**(C4 §봉함 — `enrollment.seal`) 버린다.
  현장에는 `ServiceKeyDelivery`로 가고 `ServiceKeyAck`로 받았다고 알린다.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from pydantic import Field

from chaeksas.contracts._base import ContractModel, Timestamp, Violation
from chaeksas.contracts.enrollment import Sealed
from chaeksas.contracts.signing import AdminKey, Envelope, verify

#: C2 Claim 종류.
KIND = "service_key"

ACTION_ISSUE = "issue"
ACTION_UPDATE = "update"
ACTION_REVOKE = "revoke"
KNOWN_ACTIONS = frozenset({ACTION_ISSUE, ACTION_UPDATE, ACTION_REVOKE})

#: 봉투를 받아도 되는 시간 (지은 때 + 10분). 새어 나간 봉투를 오래 쓰지 못하게.
ENVELOPE_TTL_S = 600

#: Center가 지은 키의 id 앞붙이. **관리 API의 이름으로 쓸 수 없다** (409 `name_reserved`).
CENTER_KEY_PREFIX = "svk_"
#: 관리자가 넣은 외부 앱 키를 나를 때의 id 앞붙이 (C7 §외부 앱 키).
EXTERNAL_KEY_PREFIX = "xak_"

PURPOSE_RUN = "run"
PURPOSE_UTILITY = "utility"
SOURCE_CENTER = "center"
SOURCE_EXTERNAL = "external"

#: `issued_for.kind` (열린 문자열).
FOR_DEPLOYMENT = "deployment"
FOR_STUDIO = "studio"
FOR_UTILITY = "utility"
KNOWN_ISSUED_FOR = frozenset({FOR_DEPLOYMENT, FOR_STUDIO, FOR_UTILITY})

#: 폐기 사유 (열린 문자열).
KNOWN_REVOKE_REASONS = frozenset(
    {
        "deployment_revoked",
        "target_disabled",
        "target_unbound",
        "rotated",
        "reissued",
        "studio_key_revoked",
        "utility_off",
    }
)

#: `ServiceKeyAck.reason` (열린 문자열).
ACK_UNSEALABLE = "unsealable"
ACK_STORE_UNAVAILABLE = "store_unavailable"

#: C7 `ServiceAppResource.trust.state` (열린 문자열).
TRUST_TRUSTED = "trusted"
TRUST_NOT_CONFIGURED = "not_configured"
TRUST_OTHER_CENTER = "other_center"
TRUST_STALE_KEY = "stale_key"
TRUST_PIN_MISMATCH = "pin_mismatch"
TRUST_UNKNOWN = "unknown"


class ServiceKeyTarget(ContractModel):
    """키를 받는 쪽 — 배포 대상 하나. `name`은 SVC-02에 보일 이름이다 (앱은 PC 이름을 모른다)."""

    type: str  # bot_ui / server_runner
    id: str
    name: str | None = None


class IssuedFor(ContractModel):
    """누구를 위해 지은 키인가 (C11 키 레코드). SVC-02 「발급」 열이 이것을 읽는다."""

    kind: str  # 열린 문자열 (KNOWN_ISSUED_FOR)
    bpm_process_id: str | None = None
    deployment_id: str | None = None
    target: ServiceKeyTarget | None = None
    center_key: dict[str, str] | None = None  # studio일 때 {key_id, name}


class ServiceKeyClaim(ContractModel):
    """C2 봉투 `kind: service_key`의 payload. **원문은 없다** — `hash`·`prefix`만."""

    kind: str = KIND
    action: str
    app_id: str
    center_key_id: str
    not_after: Timestamp
    hash: str | None = None
    prefix: str | None = None
    allowed_operations: list[str] | None = None
    allowed_modes: list[str] | None = None
    extra_scopes: list[str] | None = None
    expires_at: Timestamp | None = None
    issued_for: IssuedFor | None = None
    reason: str | None = None


class ServiceKeyDelivery(ContractModel):
    """하트비트 답에 실린 봉한 키 하나 (C4 §서비스 앱 키 전달)."""

    service_key_id: str
    purpose: str = PURPOSE_RUN
    source: str = SOURCE_CENTER
    app_id: str
    bpm_process_id: str | None = None
    key_refs: list[str] = Field(default_factory=list)
    sealed_key: Sealed
    expires_at: Timestamp | None = None
    replaces: str | None = None


class ServiceKeyAck(ContractModel):
    """받았다(또는 지웠다). `accepted: false`면 `reason`."""

    service_key_id: str
    accepted: bool
    reason: str | None = None


class CenterTrust(ContractModel):
    """C11 `GET /center/v1/trust` — 이 앱이 Center 발급을 받나."""

    center_url: str | None = None
    key_ids: list[str] = Field(default_factory=list)
    fetched_at: Timestamp | None = None
    pinned: bool = False


class ServiceKeyStatus(ContractModel):
    """CON-03·CON-12 「준비」 툴팁 — 그 대상의 키 하나가 어디까지 왔나. **원문·해시는 없다.**

    `stage`: `app_pending`(앱에 아직 맡기지 못함 — `error`가 까닭) / `sent`(봉해 실었다, 현장이
    받기를 기다림) / `received`(현장이 받았다). 열린 문자열.
    """

    service_key_id: str
    purpose: str
    source: str
    app_id: str
    bpm_process_id: str | None = None
    key_refs: list[str] = Field(default_factory=list)
    stage: str
    error: str | None = None
    expires_at: Timestamp | None = None


class StudioServiceKeyRequest(ContractModel):
    """C5 `POST /studio/service-keys` — 그 앱의 개발 키 하나 (ADR-0094 §5)."""

    app_id: str
    public_key: str


class StudioServiceKey(ContractModel):
    """그 응답. `sealed_key`는 요청의 공개키로 봉했다 (salt는 `service_key_id`)."""

    app_id: str
    service_key_id: str
    sealed_key: Sealed
    expires_at: Timestamp | None = None
    source: str = SOURCE_CENTER


def check_claim(
    envelope: Envelope,
    *,
    keys: Sequence[AdminKey],
    app_id: str,
    now: str,
) -> tuple[ServiceKeyClaim | None, list[Violation]]:
    """앱이 받은 봉투를 본다 — C2 V1~V4 + 이 앱의 것인가 + `not_after`.

    통과하면 `(claim, [])`. 위반 코드는 C11 오류 표의 이름으로 옮기기 쉽게 그대로 둔다
    (`wrong_kind`·`unknown_key`·`revoked_key`·`bad_signature`·`wrong_app`·`envelope_expired`).
    """
    problems = verify(envelope, keys=keys, expect_kind=KIND)
    if problems:
        return None, problems
    try:
        claim = ServiceKeyClaim.model_validate(envelope.payload)
    except ValueError as e:
        return None, [Violation(rule="C11", code="input_invalid", message=str(e).splitlines()[0])]
    if claim.app_id != app_id:
        return None, [Violation(rule="C11", code="wrong_app", message=f"{claim.app_id}의 봉투다 (나는 {app_id})")]
    if datetime.fromisoformat(claim.not_after) < datetime.fromisoformat(now):
        return None, [Violation(rule="C11", code="envelope_expired", message=f"봉투가 {claim.not_after}에 지났다")]
    if claim.action not in KNOWN_ACTIONS:
        return None, [Violation(rule="C11", code="input_invalid", message=f"모르는 action {claim.action!r}")]
    if claim.action == ACTION_ISSUE and not (claim.hash and claim.prefix):
        return None, [Violation(rule="C11", code="input_invalid", message="issue에는 hash·prefix가 있어야 한다")]
    return claim, []


__all__ = [
    "ACK_STORE_UNAVAILABLE",
    "ACK_UNSEALABLE",
    "ACTION_ISSUE",
    "ACTION_REVOKE",
    "ACTION_UPDATE",
    "CENTER_KEY_PREFIX",
    "ENVELOPE_TTL_S",
    "EXTERNAL_KEY_PREFIX",
    "FOR_DEPLOYMENT",
    "FOR_STUDIO",
    "FOR_UTILITY",
    "KIND",
    "PURPOSE_RUN",
    "PURPOSE_UTILITY",
    "SOURCE_CENTER",
    "SOURCE_EXTERNAL",
    "CenterTrust",
    "IssuedFor",
    "ServiceKeyAck",
    "ServiceKeyClaim",
    "ServiceKeyDelivery",
    "ServiceKeyStatus",
    "ServiceKeyTarget",
    "StudioServiceKey",
    "StudioServiceKeyRequest",
    "check_claim",
]
