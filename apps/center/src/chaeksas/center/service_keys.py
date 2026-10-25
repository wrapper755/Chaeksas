"""서비스 앱 키를 Center가 짓고 나른다 (ADR-0094).

**배포가 키를 데리고 다닌다.** 사람은 키를 보지 않는다.

- **있어야 할 키**는 활성 배포에서 센다 — (Bot × 배포 대상 × 앱)마다 하나 (`purpose: run`).
  판을 올려도 같은 키를 이어 쓰고 허용 작업·만료만 고친다. 서버의 `"*"` 배포는 실행기마다다.
  CON-03 「셀렉터 등록」을 켠 PC에는 도구용 키(`purpose: utility`)를 하나 더 짓는다.
- **원문은 짓는 자리에서 봉하고 버린다** (C4 §봉함, 받는 쪽 공개키로). 앱에는 해시만 간다
  (C2 봉투 `service_key` → C11 `POST /center/v1/keys`). Center DB에 남는 것은 봉한 덩이뿐이고
  현장이 받았다고 ack하면 그것도 지운다.
- **맞추기(`reconcile`)는 배포·철회 때와 60초마다** 돈다. 하트비트는 나르기만 한다
  (`deliveries`·`apply_acks`) — 하트비트 안에서 서비스 앱을 부르면 느린 앱이 현장을 붙잡는다.
- **외부 앱 키**는 관리자가 한 번 넣는다 (C7 §외부 앱 키). Center가 암호화해 들고 같은 길로
  나른다. 시험용 키는 Studio에만 간다.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
import threading
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

from chaeksas.center import signer
from chaeksas.center.errors import ApiError
from chaeksas.center.storage import Store, dumps, loads, now_iso
from chaeksas.contracts.enrollment import Sealed, seal, valid_public_key
from chaeksas.contracts.extension import ExtensionManifest, takes_key
from chaeksas.contracts.manifest import Manifest
from chaeksas.contracts.resources import AppKeyState, KeySlot
from chaeksas.contracts.service_app import KEY_PREFIX, KEY_RANDOM_LEN, MODE_AUTONOMOUS, MODE_DETERMINISTIC, prefix_of
from chaeksas.contracts.service_keys import (
    ACK_UNSEALABLE,
    ACTION_ISSUE,
    ACTION_REVOKE,
    ACTION_UPDATE,
    CENTER_KEY_PREFIX,
    ENVELOPE_TTL_S,
    EXTERNAL_KEY_PREFIX,
    FOR_DEPLOYMENT,
    FOR_STUDIO,
    FOR_UTILITY,
    KIND,
    PURPOSE_RUN,
    PURPOSE_UTILITY,
    SOURCE_CENTER,
    SOURCE_EXTERNAL,
    ServiceKeyAck,
    ServiceKeyDelivery,
    ServiceKeyStatus,
    StudioServiceKey,
)

log = logging.getLogger(__name__)

#: 맞추기 간격 (초) — 서비스 앱 상태를 보는 주기와 같다 (C7).
RECONCILE_S = 60
#: 만료가 이만큼 남으면 새 키를 짓는다 (Center 키 회전과 같은 14일, C4 §키 회전).
ROTATE_BEFORE = timedelta(days=14)
#: 배포에 유효 기간이 없으면 키는 1년이다.
DEFAULT_LIFETIME = timedelta(days=365)
#: Studio 개발 키 (ADR-0094 §5).
STUDIO_LIFETIME = timedelta(days=7)
#: 현장이 「받지 못함」이라고 하면 다시 짓되 하루 한 번까지.
REISSUE_EVERY = timedelta(days=1)
SEND_TIMEOUT_S = 5.0

PURPOSE_STUDIO = "studio"
SLOT_RUN = "run"
SLOT_TEST = "test"
SLOTS = (SLOT_RUN, SLOT_TEST)

#: 행의 상태. `issuing`은 앱에 맡기기 전(또는 실패해 다시 맡길 것)이고, 현장에는 `active`만 간다.
ISSUING = "issuing"
ACTIVE = "active"
REVOKING = "revoking"
REVOKED = "revoked"

_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"

#: 앱에 봉투를 보낸다 — `(base_url, 봉투) → (HTTP 상태, 오류 코드)`. 닿지 못하면 `(0, "unreachable")`.
Send = Callable[[str, dict[str, Any]], tuple[int, str | None]]


def http_send(base_url: str, envelope: dict[str, Any]) -> tuple[int, str | None]:
    import httpx  # noqa: PLC0415 — 부를 때만 든다

    try:
        with httpx.Client(timeout=SEND_TIMEOUT_S, follow_redirects=False) as client:
            answer = client.post(base_url.rstrip("/") + "/center/v1/keys", json=envelope)
    except httpx.HTTPError:
        return 0, "unreachable"
    if answer.status_code < 400:
        return answer.status_code, None
    try:
        code = str(answer.json().get("code") or "")
    except ValueError:
        code = ""
    return answer.status_code, code or f"http_{answer.status_code}"


# ─────────────────────────── 원문·암호화 ───────────────────────────


def _new_raw() -> str:
    return KEY_PREFIX + "".join(secrets.choice(_ALPHABET) for _ in range(KEY_RANDOM_LEN))


def _hash(raw: str) -> str:
    """앱이 저장하는 것과 같은 해시 (`service_kit.hash_key`) — Center는 `service_kit`을 쓰지 않는다."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _wrap_key(store: Store) -> bytes:
    """외부 앱 키를 감싸는 키. 처음 쓸 때 만든다. **같은 서버에 있다** — Center를 쥔 사람은 읽는다 (ADR-0092)."""
    row = store.row("SELECT value FROM center_secrets WHERE name = 'app_key_wrap'")
    if row is not None:
        return base64.b64decode(str(row["value"]))
    made = ChaCha20Poly1305.generate_key()
    with store.tx() as cur:
        cur.execute(
            "INSERT INTO center_secrets (name, value, created_at) VALUES ('app_key_wrap', ?, ?)"
            " ON CONFLICT (name) DO NOTHING",
            (base64.b64encode(made).decode("ascii"), now_iso()),
        )
    found = store.row("SELECT value FROM center_secrets WHERE name = 'app_key_wrap'")
    assert found is not None
    return base64.b64decode(str(found["value"]))


def _encrypt(store: Store, raw: str, *, aad: str) -> str:
    nonce = os.urandom(12)
    body = ChaCha20Poly1305(_wrap_key(store)).encrypt(nonce, raw.encode("utf-8"), aad.encode("utf-8"))
    return base64.b64encode(nonce + body).decode("ascii")


def _decrypt(store: Store, text: str, *, aad: str) -> str:
    blob = base64.b64decode(text)
    return ChaCha20Poly1305(_wrap_key(store)).decrypt(blob[:12], blob[12:], aad.encode("utf-8")).decode("utf-8")


# ─────────────────────────── 있어야 할 키 ───────────────────────────


@dataclass(frozen=True)
class Host:
    """키를 받는 쪽. 공개키가 없으면(환경변수로 Center 키를 받은 곳) 봉할 수 없어 짓지 않는다."""

    type: str
    id: str
    name: str
    public_key: str | None
    usable: bool  # 비활성·유실·키 폐기가 아님


@dataclass
class Want:
    source: str
    purpose: str
    app_id: str
    bpm_process_id: str | None
    host: Host
    key_refs: list[str] = field(default_factory=list)
    operations: list[str] = field(default_factory=list)
    extra_scopes: list[str] = field(default_factory=list)
    deployment_id: str | None = None
    expires_at: str | None = None

    @property
    def slot(self) -> tuple[str, str, str, str, str]:
        return (self.purpose, self.app_id, self.bpm_process_id or "", self.host.type, self.host.id)


def _hosts(store: Store) -> dict[tuple[str, str], Host]:
    out: dict[tuple[str, str], Host] = {}
    rows = store.rows(
        "SELECT b.bot_ui_id AS id, b.name, b.disabled, k.public_key, k.revoked_at"
        " FROM bot_uis b LEFT JOIN center_keys k ON k.key_id = b.key_id"
    )
    for row in rows:
        out[("bot_ui", str(row["id"]))] = Host(
            type="bot_ui",
            id=str(row["id"]),
            name=str(row["name"]),
            public_key=row["public_key"],
            usable=not row["disabled"] and row["revoked_at"] is None,
        )
    rows = store.rows(
        "SELECT r.server_runner_id AS id, r.name, r.lost_at, k.public_key, k.revoked_at"
        " FROM server_runners r LEFT JOIN center_keys k ON k.key_id = r.key_id"
    )
    for row in rows:
        out[("server_runner", str(row["id"]))] = Host(
            type="server_runner",
            id=str(row["id"]),
            name=str(row["name"]),
            public_key=row["public_key"],
            usable=row["lost_at"] is None and row["revoked_at"] is None,
        )
    return out


def _external(store: Store) -> dict[str, ExtensionManifest]:
    """등록된(철회되지 않은) 외부 확장 — 같은 id는 나중 것이 이긴다."""
    out: dict[str, ExtensionManifest] = {}
    for row in store.rows("SELECT id, definition_json FROM extensions WHERE revoked_json IS NULL ORDER BY id, at"):
        try:
            out[str(row["id"])] = ExtensionManifest.model_validate(loads(row["definition_json"]))
        except ValueError:  # pragma: no cover — 등록할 때 검증했다
            continue
    return out


def _deployments(store: Store) -> list[dict[str, Any]]:
    """활성 배포와 그 매니페스트 (승인된 패키지만 — 승인 철회된 것은 현장이 어차피 거부한다)."""
    rows = store.rows(
        "SELECT d.deployment_id, d.target_type, d.target_id, d.bpm_process_id, d.version, d.at,"
        " d.envelope_json, p.manifest_json FROM deployments d"
        " JOIN packages p ON p.id = d.bpm_process_id AND p.version = d.version"
        " WHERE d.revoked_json IS NULL AND p.status = 'approved' ORDER BY d.at"
    )
    out = []
    for row in rows:
        payload = (loads(row["envelope_json"], {}) or {}).get("payload") or {}
        try:
            manifest = Manifest.model_validate(loads(row["manifest_json"]))
        except ValueError:  # pragma: no cover — 올릴 때 검증했다
            continue
        out.append(
            {
                "deployment_id": str(row["deployment_id"]),
                "target_type": str(row["target_type"]),
                "target_id": str(row["target_id"]),
                "bpm_process_id": str(row["bpm_process_id"]),
                "expires_at": payload.get("expires_at"),
                "manifest": manifest,
            }
        )
    return out


def wanted(store: Store) -> dict[tuple[str, str, str, str, str], Want]:
    """지금 있어야 할 키 (ADR-0094 §3)."""
    hosts = _hosts(store)
    external = _external(store)
    out: dict[tuple[str, str, str, str, str], Want] = {}
    for dep in _deployments(store):
        targets: Iterable[Host]
        if dep["target_type"] == "server_runner" and dep["target_id"] == "*":
            targets = [h for h in hosts.values() if h.type == "server_runner"]
        else:
            found = hosts.get((dep["target_type"], dep["target_id"]))
            targets = [found] if found is not None else []
        manifest: Manifest = dep["manifest"]
        for need in manifest.requires.service_apps:
            if not need.key_ref:
                continue  # 키를 받지 않는 앱 (ADR-0091)
            ext = external.get(need.app_id)
            if ext is not None and not takes_key(ext):
                continue
            source = SOURCE_EXTERNAL if ext is not None else SOURCE_CENTER
            for host in targets:
                if not host.usable or not host.public_key:
                    continue
                want = Want(
                    source, PURPOSE_RUN, need.app_id, dep["bpm_process_id"], host, deployment_id=dep["deployment_id"]
                )
                slot = want.slot
                have = out.setdefault(slot, want)
                # 태스크가 따로 적은 참조(`task_key_refs`)도 **같은 키**다 — 키는 앱마다 하나다.
                have.key_refs = sorted({*have.key_refs, need.key_ref, *need.task_key_refs})
                have.operations = sorted({*have.operations, *need.operations})
                # 유효 기간이 있는 배포만 있으면 가장 늦은 것, 하나라도 없으면 기본(1년)이다.
                if have is want:
                    have.expires_at = dep["expires_at"]
                elif have.expires_at is not None:
                    have.expires_at = (
                        max(have.expires_at, dep["expires_at"]) if dep["expires_at"] else None
                    )
    for want in _utility_wants(store, hosts):
        out[want.slot] = want
    return out


def _utility_wants(store: Store, hosts: dict[tuple[str, str], Host]) -> list[Want]:
    """CON-03 「셀렉터 등록」을 켠 PC — 그 PC에 깔린 확장의 서버 부분 중 추가 권한을 요구하는 작업이
    있는 앱마다 도구용 키 하나 (ADR-0094 §6). 확장 정의는 Center에 없으니 **앱의 manifest**가
    말한다(`required_scopes`)."""
    out = []
    apps = []
    for row in store.rows("SELECT app_id, manifest_json FROM service_apps"):
        manifest = loads(row["manifest_json"], {}) or {}
        scopes = sorted(
            {s for op in manifest.get("operations") or [] for s in op.get("required_scopes") or []}
        )
        ext = (manifest.get("extension") or {}).get("id")
        if scopes and ext:
            apps.append((str(row["app_id"]), str(ext), scopes))
    for row in store.rows("SELECT bot_ui_id, state_json FROM bot_uis WHERE selector_registration = 1"):
        host = hosts.get(("bot_ui", str(row["bot_ui_id"])))
        if host is None or not host.usable or not host.public_key:
            continue
        installed = {str(e.get("id")) for e in (loads(row["state_json"], {}) or {}).get("extensions") or []}
        for app_id, ext, scopes in apps:
            if ext in installed:
                out.append(
                    Want(SOURCE_CENTER, PURPOSE_UTILITY, app_id, None, host, operations=["*"], extra_scopes=scopes)
                )
    return out


# ─────────────────────────── 맞추기 ───────────────────────────

_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_of(store: Store) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(id(store), threading.Lock())


@dataclass
class Summary:
    issued: int = 0
    updated: int = 0
    revoked: int = 0
    errors: list[str] = field(default_factory=list)


def _base_url(store: Store, app_id: str) -> str | None:
    row = store.row("SELECT base_url FROM service_apps WHERE app_id = ?", (app_id,))
    return str(row["base_url"]) if row else None


def _envelope(store: Store, payload: dict[str, Any], *, now: str) -> dict[str, Any]:
    body = {k: v for k, v in payload.items() if v is not None}
    body["kind"] = KIND
    body["not_after"] = (datetime.fromisoformat(now) + timedelta(seconds=ENVELOPE_TTL_S)).isoformat()
    return signer.seal(store, body).to_json_dict()


def _expiry(want_expires: str | None, *, now: str) -> str:
    return want_expires or (datetime.fromisoformat(now) + DEFAULT_LIFETIME).isoformat()


def _issued_for(row: Any) -> dict[str, Any] | None:
    found = loads(row["issued_for_json"])
    return found if isinstance(found, dict) else None


def _claim_of(row: Any, action: str) -> dict[str, Any]:
    claim: dict[str, Any] = {"action": action, "app_id": row["app_id"], "center_key_id": row["service_key_id"]}
    if action == ACTION_REVOKE:
        claim["reason"] = row["revoke_reason"]
        return claim
    claim["allowed_operations"] = loads(row["allowed_ops_json"], ["*"])
    claim["allowed_modes"] = (
        [MODE_AUTONOMOUS, MODE_DETERMINISTIC] if row["purpose"] == PURPOSE_STUDIO else [MODE_DETERMINISTIC]
    )
    claim["extra_scopes"] = loads(row["extra_scopes_json"], [])
    claim["expires_at"] = row["expires_at"]
    if action == ACTION_ISSUE:
        claim["hash"] = row["key_hash"]
        claim["prefix"] = row["prefix"]
        claim["issued_for"] = _issued_for(row)
    return claim


def _push(store: Store, row: Any, action: str, *, send: Send, now: str) -> tuple[int, str | None]:
    base = _base_url(store, str(row["app_id"]))
    if base is None:
        return 0, "app_not_registered"
    return send(base, _envelope(store, _claim_of(row, action), now=now))


def _note_error(store: Store, key_id: str, error: str | None, *, now: str) -> None:
    with store.tx() as cur:
        cur.execute(
            "UPDATE service_keys SET last_error = ?, last_try_at = ? WHERE service_key_id = ?",
            (error, now, key_id),
        )


def _create(store: Store, want: Want, *, now: str, replaces: str | None = None) -> str | None:
    """행 하나를 짓는다 — 원문은 **봉하고 버린다**. 외부 앱 키는 맡길 앱이 없어 바로 `active`다."""
    assert want.host.public_key
    if want.source == SOURCE_EXTERNAL:
        raw = external_key(store, want.app_id, SLOT_RUN)
        if raw is None:
            return None  # 관리자가 아직 넣지 않았다 — 현장의 준비가 「받지 못함」으로 말한다
        key_id = f"{EXTERNAL_KEY_PREFIX}{secrets.token_hex(4)}"
        key_hash, prefix, state, expires = None, None, ACTIVE, None
    else:
        raw = _new_raw()
        key_id = f"{CENTER_KEY_PREFIX}{secrets.token_hex(4)}"
        key_hash, prefix, state = _hash(raw), prefix_of(raw), ISSUING
        expires = _expiry(want.expires_at, now=now)
    sealed = seal(want.host.public_key, raw, salt=key_id)
    del raw  # 원문은 여기서 끝난다
    issued_for = {
        "kind": FOR_UTILITY if want.purpose == PURPOSE_UTILITY else FOR_DEPLOYMENT,
        "bpm_process_id": want.bpm_process_id,
        "deployment_id": want.deployment_id,
        "target": {"type": want.host.type, "id": want.host.id, "name": want.host.name},
    }
    with store.tx() as cur:
        cur.execute(
            "INSERT INTO service_keys (service_key_id, source, purpose, app_id, bpm_process_id, target_type,"
            " target_id, key_refs_json, issued_for_json, key_hash, prefix, allowed_ops_json, extra_scopes_json,"
            " expires_at, created_at, state, sealed_json, replaces)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                key_id,
                want.source,
                want.purpose,
                want.app_id,
                want.bpm_process_id,
                want.host.type,
                want.host.id,
                dumps(want.key_refs),
                dumps({k: v for k, v in issued_for.items() if v is not None}),
                key_hash,
                prefix,
                dumps(want.operations or ["*"]),
                dumps(want.extra_scopes),
                expires,
                now,
                state,
                dumps(sealed.to_json_dict()),
                replaces,
            ),
        )
    return key_id


def _revoke_row(store: Store, key_id: str, reason: str) -> None:
    with store.tx() as cur:
        cur.execute(
            "UPDATE service_keys SET state = ?, revoke_reason = ?, sealed_json = NULL"
            " WHERE service_key_id = ? AND state IN (?, ?)",
            (REVOKING, reason, key_id, ISSUING, ACTIVE),
        )


def _live_rows(store: Store) -> list[Any]:
    return store.rows(
        "SELECT * FROM service_keys WHERE state IN (?, ?) AND purpose IN (?, ?) ORDER BY created_at",
        (ISSUING, ACTIVE, PURPOSE_RUN, PURPOSE_UTILITY),
    )


def _slot_of(row: Any) -> tuple[str, str, str, str, str]:
    return (
        str(row["purpose"]),
        str(row["app_id"]),
        str(row["bpm_process_id"] or ""),
        str(row["target_type"]),
        str(row["target_id"]),
    )


def reconcile(store: Store, *, send: Send = http_send, now: str | None = None) -> Summary:
    """있어야 할 키와 있는 키를 맞춘다. 배포·철회 때와 60초마다 부른다."""
    with _lock_of(store):
        return _reconcile(store, send=send, now=now or now_iso())


def _reconcile(store: Store, *, send: Send, now: str) -> Summary:
    done = Summary()
    want = wanted(store)
    by_slot: dict[tuple[str, str, str, str, str], list[Any]] = {}
    for row in _live_rows(store):
        by_slot.setdefault(_slot_of(row), []).append(row)

    # 1. 있어야 하는데 없다 → 짓는다. 있으면 허용 작업·참조·만료를 맞추고, 만료가 가까우면 갈아 준다.
    for slot, one in want.items():
        rows = by_slot.get(slot, [])
        if not rows:
            if _create(store, one, now=now) is not None:
                done.issued += 1
            continue
        newest = rows[-1]
        _sync(store, newest, one, now=now, send=send, done=done)
        if _due_for_rotation(store, newest, one, now=now):
            if _create(store, one, now=now, replaces=str(newest["service_key_id"])) is not None:
                done.issued += 1

    # 2. 없어야 하는데 있다 → 거둔다.
    for slot, rows in by_slot.items():
        if slot not in want:
            for row in rows:
                _revoke_row(store, str(row["service_key_id"]), _gone_reason(store, row))
                done.revoked += 1

    # 3. 앱에 맡기지 못한 것을 맡긴다 (짓기·거두기).
    for row in store.rows("SELECT * FROM service_keys WHERE state = ? AND source = ?", (ISSUING, SOURCE_CENTER)):
        status, code = _push(store, row, ACTION_ISSUE, send=send, now=now)
        if 200 <= status < 300:
            with store.tx() as cur:
                cur.execute(
                    "UPDATE service_keys SET state = ?, last_error = NULL, last_try_at = ? WHERE service_key_id = ?",
                    (ACTIVE, now, row["service_key_id"]),
                )
        else:
            _note_error(store, str(row["service_key_id"]), code, now=now)
            done.errors.append(f"{row['service_key_id']}: {code}")
    for row in store.rows("SELECT * FROM service_keys WHERE state = ?", (REVOKING,)):
        if row["source"] == SOURCE_CENTER and row["key_hash"]:
            status, code = _push(store, row, ACTION_REVOKE, send=send, now=now)
            if not (200 <= status < 300 or status == 404):
                _note_error(store, str(row["service_key_id"]), code, now=now)
                done.errors.append(f"{row['service_key_id']}: {code}")
                continue
        with store.tx() as cur:
            cur.execute(
                "UPDATE service_keys SET state = ?, revoked_at = ?, last_error = NULL WHERE service_key_id = ?",
                (REVOKED, now, row["service_key_id"]),
            )
    return done


def _gone_reason(store: Store, row: Any) -> str:
    if row["purpose"] == PURPOSE_UTILITY:
        return "utility_off"
    host = _hosts(store).get((str(row["target_type"]), str(row["target_id"])))
    if host is None or not host.usable:
        return "target_disabled"
    return "deployment_revoked"


def _sync(store: Store, row: Any, want: Want, *, now: str, send: Send, done: Summary) -> None:
    """같은 키를 이어 쓴다 — 참조 이름은 Center만의 것, 허용 작업·만료는 앱에도 고친다."""
    refs = loads(row["key_refs_json"], [])
    ops = loads(row["allowed_ops_json"], [])
    expires = row["expires_at"]
    new_ops = want.operations or ["*"]
    new_expires = _expiry(want.expires_at, now=now) if want.expires_at else expires
    changes: list[tuple[str, Any]] = []
    if refs != want.key_refs:
        changes.append(("key_refs_json", dumps(want.key_refs)))
    app_side = row["source"] == SOURCE_CENTER and (ops != new_ops or expires != new_expires)
    if app_side and row["state"] == ACTIVE:
        status, code = send_update(store, row, ops=new_ops, expires_at=new_expires, send=send, now=now)
        if 200 <= status < 300:
            changes += [("allowed_ops_json", dumps(new_ops)), ("expires_at", new_expires)]
            done.updated += 1
        elif status == 404:
            _revoke_row(store, str(row["service_key_id"]), "reissued")  # 앱에서 사라졌다 — 다시 짓는다
            return
        else:
            done.errors.append(f"{row['service_key_id']}: {code}")
    elif app_side:
        # 아직 앱에 맡기지 못했다 — 맡길 때 새 값으로 간다.
        changes += [("allowed_ops_json", dumps(new_ops)), ("expires_at", new_expires)]
    if row["source"] == SOURCE_EXTERNAL and _external_changed(store, row):
        _revoke_row(store, str(row["service_key_id"]), "rotated")
        _create(store, want, now=now, replaces=str(row["service_key_id"]))
        done.issued += 1
        return
    if changes:
        with store.tx() as cur:
            sets = ", ".join(f"{name} = ?" for name, _ in changes)
            cur.execute(
                f"UPDATE service_keys SET {sets} WHERE service_key_id = ?",  # noqa: S608 — 칸 이름은 위에서 정했다
                (*[value for _, value in changes], row["service_key_id"]),
            )


def send_update(
    store: Store, row: Any, *, ops: list[str], expires_at: str | None, send: Send, now: str
) -> tuple[int, str | None]:
    base = _base_url(store, str(row["app_id"]))
    if base is None:
        return 0, "app_not_registered"
    claim = {
        "action": ACTION_UPDATE,
        "app_id": row["app_id"],
        "center_key_id": row["service_key_id"],
        "allowed_operations": ops,
        "allowed_modes": [MODE_DETERMINISTIC],
        "extra_scopes": loads(row["extra_scopes_json"], []),
        "expires_at": expires_at,
    }
    return send(base, _envelope(store, claim, now=now))


def _due_for_rotation(store: Store, row: Any, want: Want, *, now: str) -> bool:
    if row["source"] != SOURCE_CENTER or row["state"] != ACTIVE or not row["acked_at"] or not row["expires_at"]:
        return False
    if datetime.fromisoformat(row["expires_at"]) - datetime.fromisoformat(now) > ROTATE_BEFORE:
        return False
    if want.expires_at and want.expires_at <= row["expires_at"]:
        return False  # 배포 자체가 거기서 끝난다 — 새 키를 지어도 같이 끝난다
    successor = store.row(
        "SELECT 1 FROM service_keys WHERE replaces = ? AND state IN (?, ?)",
        (row["service_key_id"], ISSUING, ACTIVE),
    )
    return successor is None


def _external_changed(store: Store, row: Any) -> bool:
    found = store.row(
        "SELECT set_at FROM external_app_keys WHERE extension_id = ? AND slot = ?", (row["app_id"], SLOT_RUN)
    )
    return found is None or str(found["set_at"]) > str(row["created_at"])


# ─────────────────────────── 하트비트 (나르기만) ───────────────────────────


def deliveries(store: Store, *, target_type: str, target_id: str) -> tuple[list[ServiceKeyDelivery], list[str]]:
    """그 대상에 실을 봉한 키와 지울 id. **ack가 올 때까지** 매번 실린다."""
    rows = store.rows(
        "SELECT * FROM service_keys WHERE target_type = ? AND target_id = ? AND state = ?"
        " AND sealed_json IS NOT NULL ORDER BY created_at",
        (target_type, target_id, ACTIVE),
    )
    keys = [
        ServiceKeyDelivery(
            service_key_id=str(row["service_key_id"]),
            purpose=str(row["purpose"]),
            source=str(row["source"]),
            app_id=str(row["app_id"]),
            bpm_process_id=row["bpm_process_id"],
            key_refs=loads(row["key_refs_json"], []),
            sealed_key=Sealed.model_validate(loads(row["sealed_json"])),
            expires_at=row["expires_at"],
            replaces=row["replaces"],
        )
        for row in rows
    ]
    drops = [
        str(row["service_key_id"])
        for row in store.rows(
            "SELECT service_key_id FROM service_keys WHERE target_type = ? AND target_id = ?"
            " AND state IN (?, ?) AND dropped_at IS NULL AND acked_at IS NOT NULL",
            (target_type, target_id, REVOKING, REVOKED),
        )
    ]
    return keys, drops


def apply_acks(store: Store, *, target_type: str, target_id: str, acks: Sequence[ServiceKeyAck]) -> None:
    """받았다 → 봉한 덩이를 지운다. 지웠다 → 다시 보내지 않는다. 열지 못했다 → 다시 짓는다."""
    now = now_iso()
    for ack in acks:
        row = store.row(
            "SELECT * FROM service_keys WHERE service_key_id = ? AND target_type = ? AND target_id = ?",
            (ack.service_key_id, target_type, target_id),
        )
        if row is None:
            continue  # 남의 것이거나 모르는 id — 아무것도 하지 않는다
        if row["state"] in (REVOKING, REVOKED):
            with store.tx() as cur:
                cur.execute(
                    "UPDATE service_keys SET dropped_at = ? WHERE service_key_id = ?", (now, row["service_key_id"])
                )
            continue
        if ack.accepted:
            with store.tx() as cur:
                cur.execute(
                    "UPDATE service_keys SET sealed_json = NULL, acked_at = COALESCE(acked_at, ?)"
                    " WHERE service_key_id = ?",
                    (now, row["service_key_id"]),
                )
            if row["replaces"]:
                _revoke_row(store, str(row["replaces"]), "rotated")
        elif ack.reason == ACK_UNSEALABLE:
            _revoke_row(store, str(row["service_key_id"]), "reissued")


def note_missing(store: Store, *, target_type: str, target_id: str, readiness: Sequence[Any]) -> None:
    """현장이 「받지 못함」이라는데 Center는 이미 ack를 받았다 → 거두고 다시 짓는다 (하루 한 번까지)."""
    now = datetime.fromisoformat(now_iso())
    for one in readiness:
        missing = set(getattr(one, "missing_key_refs", None) or [])
        if not missing:
            continue
        rows = store.rows(
            "SELECT * FROM service_keys WHERE target_type = ? AND target_id = ? AND bpm_process_id = ?"
            " AND state = ? AND acked_at IS NOT NULL",
            (target_type, target_id, one.bpm_process_id, ACTIVE),
        )
        for row in rows:
            if not missing & set(loads(row["key_refs_json"], [])):
                continue
            if now - datetime.fromisoformat(str(row["acked_at"])) < REISSUE_EVERY:
                continue
            _revoke_row(store, str(row["service_key_id"]), "reissued")


def status_of(store: Store, *, target_type: str, target_id: str) -> list[ServiceKeyStatus]:
    """CON-03·CON-12 「준비」 툴팁 — 키마다 지금 어디까지 왔나 (원문·해시 없음)."""
    rows = store.rows(
        "SELECT service_key_id, purpose, source, app_id, bpm_process_id, key_refs_json, state, acked_at,"
        " last_error, expires_at FROM service_keys WHERE target_type = ? AND target_id = ? AND state IN (?, ?)"
        " ORDER BY created_at",
        (target_type, target_id, ISSUING, ACTIVE),
    )
    out = []
    for row in rows:
        if row["state"] == ISSUING:
            stage = "app_pending"
        elif row["acked_at"]:
            stage = "received"
        else:
            stage = "sent"
        out.append(
            ServiceKeyStatus(
                service_key_id=str(row["service_key_id"]),
                purpose=str(row["purpose"]),
                source=str(row["source"]),
                app_id=str(row["app_id"]),
                bpm_process_id=row["bpm_process_id"],
                key_refs=loads(row["key_refs_json"], []),
                stage=stage,
                error=row["last_error"],
                expires_at=row["expires_at"],
            )
        )
    return out


# ─────────────────────────── 외부 앱 키 (C7 §외부 앱 키) ───────────────────────────


def _external_definition(store: Store, extension_id: str) -> ExtensionManifest:
    found = _external(store).get(extension_id)
    if found is None:
        raise ApiError(404, "not_found", f"등록된 외부 확장이 아니다: {extension_id}")
    return found


def set_external_key(store: Store, extension_id: str, slot: str, key: str, *, by: str) -> AppKeyState:
    if slot not in SLOTS:
        raise ApiError(404, "not_found", f"모르는 칸: {slot}")
    if not takes_key(_external_definition(store, extension_id)):
        raise ApiError(422, "takes_no_key", "이 외부 앱은 키를 받지 않는다 (ADR-0091)")
    value = key.strip()
    if not value or not value.isascii() or any(ch in value for ch in "\r\n"):
        raise ApiError(422, "key_not_ascii", "키는 한 줄의 ASCII여야 한다 — 어댑터가 실을 수 없다 (C13 §4)")
    with store.tx() as cur:
        cur.execute(
            "INSERT INTO external_app_keys (extension_id, slot, ciphertext, set_at, set_by) VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT (extension_id, slot) DO UPDATE SET ciphertext = excluded.ciphertext,"
            " set_at = excluded.set_at, set_by = excluded.set_by",
            (extension_id, slot, _encrypt(store, value, aad=f"{extension_id}:{slot}"), now_iso(), by),
        )
    return external_state(store, extension_id)


def delete_external_key(store: Store, extension_id: str, slot: str) -> AppKeyState:
    if slot not in SLOTS:
        raise ApiError(404, "not_found", f"모르는 칸: {slot}")
    _external_definition(store, extension_id)
    with store.tx() as cur:
        cur.execute("DELETE FROM external_app_keys WHERE extension_id = ? AND slot = ?", (extension_id, slot))
    if slot == SLOT_RUN:
        # 쓰는 곳 모두에서 지운다 — 맞추기가 새로 짓지 못하므로 여기서 거둔다.
        for row in store.rows(
            "SELECT service_key_id FROM service_keys WHERE source = ? AND app_id = ? AND state IN (?, ?)",
            (SOURCE_EXTERNAL, extension_id, ISSUING, ACTIVE),
        ):
            _revoke_row(store, str(row["service_key_id"]), "deployment_revoked")
    return external_state(store, extension_id)


def external_key(store: Store, extension_id: str, slot: str) -> str | None:
    row = store.row(
        "SELECT ciphertext FROM external_app_keys WHERE extension_id = ? AND slot = ?", (extension_id, slot)
    )
    if row is None:
        return None
    return _decrypt(store, str(row["ciphertext"]), aad=f"{extension_id}:{slot}")


def external_state(store: Store, extension_id: str) -> AppKeyState:
    slots: dict[str, KeySlot] = {}
    for row in store.rows(
        "SELECT slot, set_at, set_by FROM external_app_keys WHERE extension_id = ?", (extension_id,)
    ):
        slots[str(row["slot"])] = KeySlot(set=True, set_at=row["set_at"], set_by=row["set_by"])
    return AppKeyState(run=slots.get(SLOT_RUN, KeySlot()), test=slots.get(SLOT_TEST, KeySlot()))


def forget_external(store: Store, extension_id: str) -> None:
    """외부 확장을 등록 해제하면 그 키도 지운다 (C7)."""
    with store.tx() as cur:
        cur.execute("DELETE FROM external_app_keys WHERE extension_id = ?", (extension_id,))


# ─────────────────────────── Studio 개발 키 (C5 §Studio 개발 키) ───────────────────────────


def studio_key(
    store: Store, *, center_key_id: str, center_key_name: str, app_id: str, public_key: str, send: Send = http_send
) -> StudioServiceKey:
    """승인된 Studio 키로 청한 그 앱의 개발 키 하나. 원문은 응답에만 봉해 실린다."""
    if not valid_public_key(public_key):
        raise ApiError(422, "public_key_invalid", "공개키가 X25519(base64url, 32바이트)가 아니다")
    now = now_iso()
    external = _external(store).get(app_id)
    if external is not None:
        raw = external_key(store, app_id, SLOT_TEST)
        if raw is None:
            raise ApiError(404, "no_test_key", "관리자가 이 외부 앱의 시험용 키를 넣지 않았다 (CON-07)")
        key_id = f"{EXTERNAL_KEY_PREFIX}{secrets.token_hex(4)}"
        return StudioServiceKey(
            app_id=app_id,
            service_key_id=key_id,
            sealed_key=seal(public_key, raw, salt=key_id),
            expires_at=(datetime.fromisoformat(now) + STUDIO_LIFETIME).isoformat(),
            source=SOURCE_EXTERNAL,
        )
    if _base_url(store, app_id) is None:
        raise ApiError(404, "app_not_registered", f"Center에 등록되지 않은 서비스 앱이다: {app_id}")
    with _lock_of(store):
        old = store.rows(
            "SELECT service_key_id FROM service_keys WHERE purpose = ? AND app_id = ? AND target_id = ?"
            " AND state IN (?, ?)",
            (PURPOSE_STUDIO, app_id, center_key_id, ISSUING, ACTIVE),
        )
        raw = _new_raw()
        key_id = f"{CENTER_KEY_PREFIX}{secrets.token_hex(4)}"
        expires = (datetime.fromisoformat(now) + STUDIO_LIFETIME).isoformat()
        issued_for = {"kind": FOR_STUDIO, "center_key": {"key_id": center_key_id, "name": center_key_name}}
        with store.tx() as cur:
            cur.execute(
                "INSERT INTO service_keys (service_key_id, source, purpose, app_id, target_type, target_id,"
                " issued_for_json, key_hash, prefix, allowed_ops_json, extra_scopes_json, expires_at, created_at,"
                " state, acked_at) VALUES (?, ?, ?, ?, 'studio', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    key_id,
                    SOURCE_CENTER,
                    PURPOSE_STUDIO,
                    app_id,
                    center_key_id,
                    dumps(issued_for),
                    _hash(raw),
                    prefix_of(raw),
                    dumps(["*"]),
                    dumps([]),
                    expires,
                    now,
                    ISSUING,
                    now,
                ),
            )
        row = store.row("SELECT * FROM service_keys WHERE service_key_id = ?", (key_id,))
        status, code = _push(store, row, ACTION_ISSUE, send=send, now=now)
        if not 200 <= status < 300:
            with store.tx() as cur:
                cur.execute(
                    "UPDATE service_keys SET state = ?, revoked_at = ?, last_error = ? WHERE service_key_id = ?",
                    (REVOKED, now, code, key_id),
                )
            if code in ("center_disabled", "center_signature_invalid"):
                raise ApiError(
                    409,
                    "app_not_trusting_center",
                    "이 앱이 Center 발급을 받지 않는다 — 앱 설정에 Center 주소를 넣으세요",
                )
            raise ApiError(503, "app_unreachable", f"앱에 키를 맡기지 못했다 ({code})")
        with store.tx() as cur:
            cur.execute("UPDATE service_keys SET state = ? WHERE service_key_id = ?", (ACTIVE, key_id))
        for one in old:
            _revoke_row(store, str(one["service_key_id"]), "reissued")
    sealed = seal(public_key, raw, salt=key_id)
    del raw
    return StudioServiceKey(app_id=app_id, service_key_id=key_id, sealed_key=sealed, expires_at=expires)


def revoke_for_studio_key(store: Store, center_key_id: str) -> None:
    """Studio 키를 폐기하면 그 개발 키도 모두 거둔다."""
    for row in store.rows(
        "SELECT service_key_id FROM service_keys WHERE purpose = ? AND target_id = ? AND state IN (?, ?)",
        (PURPOSE_STUDIO, center_key_id, ISSUING, ACTIVE),
    ):
        _revoke_row(store, str(row["service_key_id"]), "studio_key_revoked")


# ─────────────────────────── 셀렉터 등록 (CON-03, ADR-0094 §6) ───────────────────────────


def set_selector_registration(store: Store, bot_ui_id: str, *, on: bool) -> bool:
    with store.tx() as cur:
        cur.execute(
            "UPDATE bot_uis SET selector_registration = ? WHERE bot_ui_id = ?", (1 if on else 0, bot_ui_id)
        )
        return cur.rowcount > 0


def selector_registration(store: Store, bot_ui_id: str) -> dict[str, Any]:
    row = store.row("SELECT selector_registration FROM bot_uis WHERE bot_ui_id = ?", (bot_ui_id,))
    keys = [
        {"app_id": one.app_id, "stage": one.stage, "error": one.error}
        for one in status_of(store, target_type="bot_ui", target_id=bot_ui_id)
        if one.purpose == PURPOSE_UTILITY
    ]
    return {"selector_registration": bool(row and row["selector_registration"]), "keys": keys}


# ─────────────────────────── 60초마다 ───────────────────────────


class Reconciler:
    """맞추기를 배경 스레드 하나로 돌린다. `kick()`은 기다리지 않고 바로 한 번 더 돌게 한다."""

    def __init__(self, store: Store, *, send: Send = http_send, every_s: float = RECONCILE_S) -> None:
        self.store = store
        self.send = send
        self.every_s = every_s
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="service-keys", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def kick(self) -> None:
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                found = reconcile(self.store, send=self.send)
                for line in found.errors:
                    log.warning("서비스 앱 키를 앱에 맡기지 못했다: %s", line)
            except Exception:  # 한 번 터져도 다음 주기에 다시 돈다
                log.exception("서비스 앱 키 맞추기가 실패했다")
            self._wake.wait(self.every_s)
            self._wake.clear()


__all__ = [
    "Reconciler",
    "apply_acks",
    "delete_external_key",
    "deliveries",
    "external_key",
    "external_state",
    "forget_external",
    "http_send",
    "note_missing",
    "reconcile",
    "revoke_for_studio_key",
    "selector_registration",
    "set_external_key",
    "set_selector_registration",
    "status_of",
    "studio_key",
    "wanted",
]
