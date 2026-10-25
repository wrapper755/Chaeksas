"""관리자 계정과 로그인 세션 (C5 「관리자 계정」, ADR-0090).

- 비밀번호는 **`scrypt`**(표준 라이브러리)로 해시한다. 원문은 어디에도 남지 않는다.
- 세션 토큰은 `chk_ses_` + 무작위이고 Center는 **SHA-256만** 둔다(Center API 키와 같은 결).
- **계정은 지우지 않고 멈춘다** — 기록에 남은 이름이 가리킬 곳이 사라지지 않게 한다.
- **마지막 관리자는 멈추거나 보기 전용으로 바꿀 수 없다** (409 `last_admin`).
- 같은 아이디로 5번 연달아 틀리면 5분 동안 받지 않는다. 「아이디가 없다」와 「비밀번호가
  틀렸다」는 **같은 답**이다 — 어느 아이디가 있는지 새지 않게.
- **권한**은 역할과 따로 계정마다 켠다 (C5 §계정 권한과 Studio 로그인, ADR-0092). 관리자는 모든
  권한을 가진다. **Studio 로그인**은 세션 대신 그 계정에 묶인 Studio용 키를 준다 — 계정이 멈추거나
  비밀번호·역할이 바뀌거나 권한이 줄면 그 키를 모두 폐기한다(세션이 끝나는 때와 같다).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from chaeksas.center import keys
from chaeksas.center.errors import ApiError
from chaeksas.center.storage import Store, now_iso
from chaeksas.contracts.accounts import (
    KNOWN_PERMISSIONS,
    KNOWN_ROLES,
    LOGIN_FAILURES_MAX,
    LOGIN_LOCK_MINUTES,
    ROLE_ADMIN,
    SESSION_HOURS,
    SESSION_PREFIX,
    STUDIO_KEY_DAYS,
    AccountInfo,
    SessionInfo,
    StudioLogin,
    StudioLoginInfo,
    allows,
    password_violation,
    username_violation,
)

log = logging.getLogger(__name__)

#: 비워 두면 첫 관리자의 아이디.
DEFAULT_FIRST_ADMIN = "admin"
#: 첫 비밀번호를 Center가 만들었을 때 두는 파일 (데이터 폴더). 그 계정이 비밀번호를 바꾸면 지운다.
FIRST_PASSWORD_FILE = "first-admin-password.txt"

# scrypt 매개변수 — 로그인 한 번에 수십 ms. 바꾸면 해시에 적힌 값으로 옛것도 읽는다.
_N, _R, _P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    b64 = base64.b64encode
    return f"scrypt${_N}${_R}${_P}${b64(salt).decode('ascii')}${b64(digest).decode('ascii')}"


def check_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest)
        got = hashlib.scrypt(
            password.encode("utf-8"),
            salt=base64.b64decode(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, expected)


#: 일부러 틀리는 비교에 쓸 해시 — 없는 아이디도 같은 시간을 쓰게 한다.
_DUMMY = hash_password(secrets.token_urlsafe(16))


def _session_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _later(*, days: float = 0, hours: float = 0, minutes: float = 0) -> str:
    return (datetime.fromisoformat(now_iso()) + timedelta(days=days, hours=hours, minutes=minutes)).isoformat()


# ─────────────────────────── 로그인 실패 세기 ───────────────────────────

_failures: dict[str, tuple[int, str | None]] = {}
_failures_lock = threading.Lock()


def _locked(username: str) -> bool:
    with _failures_lock:
        _, until = _failures.get(username, (0, None))
    return until is not None and until > now_iso()


def _failed(username: str) -> None:
    with _failures_lock:
        count, _ = _failures.get(username, (0, None))
        count += 1
        until = _later(minutes=LOGIN_LOCK_MINUTES) if count >= LOGIN_FAILURES_MAX else None
        _failures[username] = (0 if until else count, until)


def _succeeded(username: str) -> None:
    with _failures_lock:
        _failures.pop(username, None)


def reset_failures() -> None:
    """시험용 — 프로세스에 남은 실패 셈을 비운다."""
    with _failures_lock:
        _failures.clear()


# ─────────────────────────── 계정 ───────────────────────────


def _permissions(row: Any) -> list[str]:
    raw = row["permissions_json"]
    try:
        found = json.loads(raw) if raw else []
    except ValueError:
        return []
    return [str(one) for one in found] if isinstance(found, list) else []


def _logins(store: Store, username: str) -> list[StudioLoginInfo]:
    return [
        StudioLoginInfo(
            key_id=one.key_id,
            machine_name=one.machine_name or one.name,
            created_at=one.created_at,
            last_used_at=one.last_used_at,
            expires_at=one.expires_at,
        )
        for one in keys.of_account(store, username)
    ]


def _info(row: Any, store: Store | None = None) -> AccountInfo:
    return AccountInfo(
        username=row["username"],
        role=row["role"],
        state="disabled" if row["disabled_at"] else "active",
        created_at=row["created_at"],
        created_by=row["created_by"],
        password_changed_at=row["password_changed_at"],
        disabled_at=row["disabled_at"],
        last_login_at=row["last_login_at"],
        permissions=_permissions(row),
        studio_logins=_logins(store, str(row["username"])) if store is not None else [],
    )


def _row(store: Store, username: str) -> Any:
    found = store.row("SELECT * FROM accounts WHERE username = ?", (username,))
    if found is None:
        raise ApiError(404, "not_found", f"그 계정이 없습니다: {username}")
    return found


def listing(store: Store) -> list[AccountInfo]:
    return [_info(row, store) for row in store.rows("SELECT * FROM accounts ORDER BY username")]


def get(store: Store, username: str) -> AccountInfo:
    return _info(_row(store, username), store)


def _refuse(problem: Any) -> None:
    if problem is not None:
        raise ApiError(422, problem.code or "input_invalid", problem.message)


def _role(role: str) -> str:
    if role not in KNOWN_ROLES:
        raise ApiError(422, "role_unknown", f"모르는 역할입니다: {role}")
    return role


def _known(permissions: list[str] | None) -> list[str]:
    """쓰는 쪽은 **알려진 권한만** 받는다 — 모르는 이름을 켜 두면 아무것도 열지 못한 채 남는다."""
    wanted = sorted({one.strip() for one in permissions or [] if one.strip()})
    unknown = [one for one in wanted if one not in KNOWN_PERMISSIONS]
    if unknown:
        raise ApiError(422, "permission_unknown", f"모르는 권한입니다: {', '.join(unknown)}")
    return wanted


def create(
    store: Store, *, username: str, password: str, role: str, by: str, permissions: list[str] | None = None
) -> AccountInfo:
    _refuse(username_violation(username))
    _refuse(password_violation(password))
    _role(role)
    granted = _known(permissions)
    if store.row("SELECT 1 FROM accounts WHERE username = ?", (username,)) is not None:
        raise ApiError(409, "account_exists", f"이미 있는 아이디입니다: {username}")
    at = now_iso()
    with store.tx() as cur:
        cur.execute(
            "INSERT INTO accounts (username, password_hash, role, created_at, created_by, disabled_at,"
            " password_changed_at, last_login_at, permissions_json) VALUES (?, ?, ?, ?, ?, NULL, ?, NULL, ?)",
            (username, hash_password(password), role, at, by, at, json.dumps(granted)),
        )
    return get(store, username)


def _active_admins(store: Store) -> int:
    found = store.row(
        "SELECT COUNT(*) AS n FROM accounts WHERE role = ? AND disabled_at IS NULL", (ROLE_ADMIN,)
    )
    return int(found["n"]) if found is not None else 0


def update(
    store: Store,
    username: str,
    *,
    role: str | None = None,
    disabled: bool | None = None,
    password: str | None = None,
    permissions: list[str] | None = None,
    data_dir: Path | None = None,
) -> AccountInfo:
    """역할·멈춤·비밀번호·권한을 바꾼다 (관리자). 비운 칸은 그대로다."""
    row = _row(store, username)
    if role is not None:
        _role(role)
    if password is not None:
        _refuse(password_violation(password))
    granted = _known(permissions) if permissions is not None else None
    # 권한이 **줄면** Studio 로그인을 끝낸다 — 늘어나는 것은 묻지 않는다 (CON-14).
    shrunk = granted is not None and bool(set(_permissions(row)) - set(granted))

    # 이 계정이 **지금 쓰이는 관리자**인데 관리자에서 빠지게 되면 — 마지막 하나면 막는다.
    was_admin = row["role"] == ROLE_ADMIN and not row["disabled_at"]
    stays_admin = (role or row["role"]) == ROLE_ADMIN and not (
        disabled if disabled is not None else bool(row["disabled_at"])
    )
    if was_admin and not stays_admin and _active_admins(store) <= 1:
        raise ApiError(
            409,
            "last_admin",
            "마지막 남은 관리자는 멈추거나 보기 전용으로 바꿀 수 없습니다 — 다른 관리자를 먼저 만드세요",
        )

    at = now_iso()
    with store.tx() as cur:
        if role is not None:
            cur.execute("UPDATE accounts SET role = ? WHERE username = ?", (role, username))
        if disabled is not None:
            cur.execute(
                "UPDATE accounts SET disabled_at = ? WHERE username = ?",
                (at if disabled else None, username),
            )
        if password is not None:
            cur.execute(
                "UPDATE accounts SET password_hash = ?, password_changed_at = ? WHERE username = ?",
                (hash_password(password), at, username),
            )
        if granted is not None:
            cur.execute("UPDATE accounts SET permissions_json = ? WHERE username = ?", (json.dumps(granted), username))
        # 역할·멈춤·비밀번호가 바뀌면 **그 계정의 세션을 그 자리에서 지운다**.
        if role is not None or disabled is not None or password is not None:
            cur.execute("DELETE FROM account_sessions WHERE username = ?", (username,))
    # Studio 로그인도 같은 때에 끝난다 — 세션보다 오래 사는 키라 놓치면 계속 올린다 (C5).
    if role is not None or disabled is not None or password is not None or shrunk:
        keys.revoke_account(store, username)
    if password is not None:
        _forget_first_password(data_dir, username)
    return get(store, username)


def change_own_password(
    store: Store, username: str, *, current: str, new: str, data_dir: Path | None = None
) -> AccountInfo:
    row = _row(store, username)
    if not check_password(current, str(row["password_hash"])):
        raise ApiError(403, "password_wrong", "지금 비밀번호가 맞지 않습니다")
    _refuse(password_violation(new))
    with store.tx() as cur:
        cur.execute(
            "UPDATE accounts SET password_hash = ?, password_changed_at = ? WHERE username = ?",
            (hash_password(new), now_iso(), username),
        )
        cur.execute("DELETE FROM account_sessions WHERE username = ?", (username,))
    keys.revoke_account(store, username)
    _forget_first_password(data_dir, username)
    return get(store, username)


# ─────────────────────────── 세션 ───────────────────────────


def _verify(store: Store, *, username: str, password: str) -> Any:
    """아이디·비밀번호를 본다 — 콘솔 로그인과 Studio 로그인이 **같은 함수**다 (잠금 포함)."""
    wrong = ApiError(401, "login_failed", "아이디나 비밀번호가 맞지 않습니다")
    if _locked(username):
        raise ApiError(
            429, "login_locked", f"로그인을 여러 번 틀렸습니다 — {LOGIN_LOCK_MINUTES}분 뒤에 다시 하세요"
        )
    row = store.row("SELECT * FROM accounts WHERE username = ?", (username,))
    if row is None:
        check_password(password, _DUMMY)  # 없는 아이디도 같은 시간을 쓴다
        _failed(username)
        raise wrong
    if not check_password(password, str(row["password_hash"])):
        _failed(username)
        raise wrong
    if row["disabled_at"]:
        raise ApiError(403, "account_disabled", "멈춘 계정입니다 — 다른 관리자에게 물어보세요")
    _succeeded(username)
    return row


def login(store: Store, *, username: str, password: str) -> SessionInfo:
    row = _verify(store, username=username, password=password)
    token = SESSION_PREFIX + secrets.token_urlsafe(32)
    at = now_iso()
    expires = _later(hours=SESSION_HOURS)
    with store.tx() as cur:
        cur.execute("DELETE FROM account_sessions WHERE expires_at <= ?", (at,))
        cur.execute(
            "INSERT INTO account_sessions (token_hash, username, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (_session_hash(token), username, at, expires),
        )
        cur.execute("UPDATE accounts SET last_login_at = ? WHERE username = ?", (at, username))
    return SessionInfo(token=token, username=username, role=str(row["role"]), expires_at=expires)


def session_of(store: Store, token: str) -> AccountInfo | None:
    """세션 토큰 → 계정. 끝났거나 모르는 토큰이면 `None`."""
    found = store.row(
        "SELECT a.* FROM account_sessions s JOIN accounts a ON a.username = s.username"
        " WHERE s.token_hash = ? AND s.expires_at > ? AND a.disabled_at IS NULL",
        (_session_hash(token), now_iso()),
    )
    return _info(found) if found is not None else None


def logout(store: Store, token: str) -> None:
    with store.tx() as cur:
        cur.execute("DELETE FROM account_sessions WHERE token_hash = ?", (_session_hash(token),))


# ─────────────────────────── 권한·Studio 로그인 ───────────────────────────


def permission_missing(permission: str) -> ApiError:
    return ApiError(
        403,
        "permission_missing",
        f"이 계정에는 「{permission}」 권한이 없습니다 — 관리자에게 켜 달라고 하세요",
        {"permission": permission},
    )


def account_allows(store: Store, username: str, permission: str) -> bool:
    """그 계정이 **지금** 그 권한을 쓸 수 있나 — 멈춘 계정은 아무것도 못 한다."""
    row = store.row("SELECT * FROM accounts WHERE username = ?", (username,))
    if row is None or row["disabled_at"]:
        return False
    return allows(str(row["role"]), _permissions(row), permission)


def studio_login(store: Store, *, username: str, password: str, machine_name: str, permission: str) -> StudioLogin:
    """Studio 로그인 (C5) — 그 계정에 묶인 Studio용 키를 만든다. **원문은 이 응답에만.**

    비밀번호가 맞았는데 권한이 없으면 403 `permission_missing` — 잠금 횟수에 넣지 않는다.
    같은 계정·같은 PC 이름이면 옛 키를 폐기한다(한 PC에 키가 쌓이지 않게).
    """
    row = _verify(store, username=username, password=password)
    if not allows(str(row["role"]), _permissions(row), permission):
        raise permission_missing(permission)
    machine = machine_name.strip()
    keys.revoke_account(store, username, machine_name=machine)
    expires = _later(days=STUDIO_KEY_DAYS)
    record, raw = keys.issue(
        store,
        name=f"{username} · {machine}",
        key_type="studio",
        expires_at=expires,
        account=username,
        machine_name=machine,
    )
    with store.tx() as cur:
        cur.execute("UPDATE accounts SET last_login_at = ? WHERE username = ?", (now_iso(), username))
    return StudioLogin(key=raw, key_id=record.key_id, username=username, expires_at=expires)


# ─────────────────────────── 첫 관리자 ───────────────────────────


class FirstAdminError(RuntimeError):
    """`.env`에 적은 첫 관리자가 규칙에 맞지 않는다 — Center가 뜨지 않는다."""


def ensure_first_admin(
    store: Store, *, username: str | None, password: str | None, data_dir: Path | None
) -> str | None:
    """계정이 **하나도 없을 때만** 첫 관리자를 만든다 (ADR-0090 §2).

    비밀번호를 적지 않았으면 만들어 **로그에 한 번 찍고** 데이터 폴더의 파일에 둔다.
    만든 비밀번호를 돌려준다 (적은 것을 쓰거나 이미 계정이 있으면 `None`).
    """
    if store.row("SELECT 1 FROM accounts LIMIT 1") is not None:
        return None
    name = (username or "").strip() or DEFAULT_FIRST_ADMIN
    problem = username_violation(name)
    if problem is not None:
        raise FirstAdminError(f"첫 관리자 아이디가 규칙에 맞지 않습니다: {problem.message}")
    made: str | None = None
    if password:
        problem = password_violation(password)
        if problem is not None:
            raise FirstAdminError(f"첫 관리자 비밀번호가 규칙에 맞지 않습니다: {problem.message}")
        chosen = password
    else:
        made = chosen = _generated()
    create(store, username=name, password=chosen, role=ROLE_ADMIN, by="설치")
    if made is not None:
        log.warning("첫 관리자 「%s」를 만들었다 — 비밀번호: %s (로그인 뒤 바꾸세요)", name, made)
        if data_dir is not None:
            data_dir.mkdir(parents=True, exist_ok=True)
            target = data_dir / FIRST_PASSWORD_FILE
            target.write_text(f"{name}\n{made}\n", encoding="utf-8")
            target.chmod(0o600)  # Windows에서는 읽기 전용 표시만 바뀐다 — 데이터 폴더가 지킨다
    return made


def _generated() -> str:
    """영문·숫자 20자 — 규칙(12자·영문+숫자)을 늘 지킨다."""
    alphabet = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    while True:
        made = "".join(secrets.choice(alphabet) for _ in range(20))
        if password_violation(made) is None:
            return made


def _forget_first_password(data_dir: Path | None, username: str) -> None:
    """첫 비밀번호 파일이 그 계정의 것이면 지운다 — 바꾼 뒤에는 거짓말이 된다."""
    if data_dir is None:
        return
    target = data_dir / FIRST_PASSWORD_FILE
    try:
        first = target.read_text(encoding="utf-8").splitlines()[0].strip()
    except (OSError, IndexError):
        return
    if first == username:
        target.unlink(missing_ok=True)


__all__ = [
    "DEFAULT_FIRST_ADMIN",
    "FIRST_PASSWORD_FILE",
    "FirstAdminError",
    "change_own_password",
    "check_password",
    "create",
    "ensure_first_admin",
    "get",
    "hash_password",
    "listing",
    "login",
    "logout",
    "account_allows",
    "permission_missing",
    "reset_failures",
    "studio_login",
    "session_of",
    "update",
]
