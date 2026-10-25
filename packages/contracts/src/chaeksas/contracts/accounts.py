"""C5. 관리자 계정·로그인 세션 (CON-00·CON-14, ADR-0090).

단일 원본: `docs/03-contracts/C5-packages-deployments-jobs.md` 「관리자 계정」.

콘솔은 **계정으로만** 들어온다. Center가 비밀번호를 확인하고 **세션 토큰**을 주면 콘솔 서버(BFF)가
그것을 들고 부른다 (ADR-0017 — 브라우저는 모른다). 세션으로 부르면 행위자는 **계정 아이디**다.

비밀번호는 Center가 `scrypt`로 해시해 둔다 — 원문은 어디에도 남지 않는다.
"""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import Field

from chaeksas.contracts._base import ContractModel, Timestamp, Violation

#: 역할 둘 — 관리자(쓰기 전부)와 보기 전용(GET만, 읽기 토큰이 하던 일).
ROLE_ADMIN = "admin"
ROLE_VIEWER = "viewer"
KNOWN_ROLES = frozenset({ROLE_ADMIN, ROLE_VIEWER})

#: 아이디 — 영문 소문자·숫자·`.`·`_`·`-`, 3~32자. 화면 이름도 아이디 그대로다.
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
Username = Annotated[str, Field(pattern=USERNAME_RE.pattern)]

#: 비밀번호 — 12자 이상, 영문과 숫자를 모두 넣는다.
PASSWORD_MIN = 12
PASSWORD_MAX = 256

#: 세션 토큰 — `chk_ses_` + 무작위. Center는 해시만 둔다.
SESSION_PREFIX = "chk_ses_"
#: 세션은 이만큼 지나면 끝난다 (다시 로그인한다).
SESSION_HOURS = 12

#: 계정 권한 (C5 §계정 권한과 Studio 로그인, ADR-0092). **열린 문자열**이고 알려진 값은 이것뿐이다.
#: 관리자는 모든 권한을 가진다 — `permissions`를 비워 두어도 그렇다.
PERMISSION_DESIGN = "design"
KNOWN_PERMISSIONS = frozenset({PERMISSION_DESIGN})

#: Studio 로그인이 만드는 키의 수명과, Studio가 「곧 끝납니다」를 말하기 시작하는 때.
STUDIO_KEY_DAYS = 30
STUDIO_NOTICE_DAYS = 7
#: 로그인한 PC의 이름 — 사람이 알아볼 만큼.
MACHINE_NAME_MAX = 64

#: 같은 아이디로 이만큼 연달아 틀리면 그 아이디를 잠깐 받지 않는다.
LOGIN_FAILURES_MAX = 5
LOGIN_LOCK_MINUTES = 5


def password_violation(password: str) -> Violation | None:
    """비밀번호 규칙을 어기면 그 까닭 (`password_weak`). 맞으면 `None`."""
    if len(password) < PASSWORD_MIN or len(password) > PASSWORD_MAX:
        return Violation(
            rule="C5", code="password_weak", message=f"비밀번호는 {PASSWORD_MIN}자 이상이어야 합니다"
        )
    if not (re.search(r"[A-Za-z]", password) and re.search(r"[0-9]", password)):
        return Violation(rule="C5", code="password_weak", message="비밀번호에 영문과 숫자를 모두 넣으세요")
    return None


def username_violation(username: str) -> Violation | None:
    if USERNAME_RE.fullmatch(username):
        return None
    return Violation(
        rule="C5",
        code="username_invalid",
        message="아이디는 영문 소문자·숫자·.·_·-로 3~32자입니다 (영문 소문자나 숫자로 시작)",
    )


class LoginRequest(ContractModel):
    """`POST /auth/login` — 인증 없이 부른다."""

    username: str
    password: str


class SessionInfo(ContractModel):
    """로그인 응답. **`token`은 이 응답에만 실린다** — 콘솔 서버가 쿠키에 담고 브라우저에 내려 주지 않는다."""

    token: str
    username: Username
    role: str  # KNOWN_ROLES
    expires_at: Timestamp


class WhoAmI(ContractModel):
    """`GET /auth/me` — 지금 부르는 쪽. 세션이면 계정, 토큰이면 `account`가 없다."""

    actor: str
    role: str  # KNOWN_ROLES
    account: Username | None = None


def allows(role: str, permissions: list[str] | None, wanted: str) -> bool:
    """그 역할·권한으로 `wanted`를 할 수 있나 — 관리자는 늘 된다 (C5)."""
    return role == ROLE_ADMIN or wanted in (permissions or [])


class StudioLoginInfo(ContractModel):
    """그 계정이 로그인해 있는 Studio 하나 — 살아 있는 Studio 키 (CON-14 「Studio 로그인」)."""

    key_id: str
    machine_name: str
    created_at: Timestamp
    last_used_at: Timestamp | None = None
    expires_at: Timestamp | None = None


class AccountInfo(ContractModel):
    """`GET /accounts`의 한 줄. **비밀번호 해시는 나가지 않는다.**"""

    username: Username
    role: str
    state: str  # active | disabled
    created_at: Timestamp
    created_by: str
    password_changed_at: Timestamp
    disabled_at: Timestamp | None = None
    last_login_at: Timestamp | None = None
    #: 켜 둔 권한 (KNOWN_PERMISSIONS). 관리자는 비어 있어도 모든 권한을 가진다.
    permissions: list[str] = Field(default_factory=list)
    #: 로그인해 있는 Studio (살아 있는 키만).
    studio_logins: list[StudioLoginInfo] = Field(default_factory=list)


class AccountCreateRequest(ContractModel):
    """`POST /accounts` — 관리자만."""

    username: str
    password: str
    role: str = ROLE_ADMIN
    permissions: list[str] | None = None


class AccountUpdateRequest(ContractModel):
    """`PUT /accounts/{username}` — 관리자만. 비운 칸은 그대로 둔다.

    `password`는 **새로 정해 주는 것**이다(지금 비밀번호를 묻지 않는다). 자기 비밀번호를 바꾸는
    길은 `PUT /auth/password`다.
    """

    role: str | None = None
    disabled: bool | None = None
    password: str | None = None
    #: 통째로 바꾼다. **줄면** 그 계정의 Studio 로그인이 모두 끝난다.
    permissions: list[str] | None = None


class StudioLoginRequest(ContractModel):
    """`POST /auth/studio-login` — 인증 없이 부른다 (C5 §계정 권한과 Studio 로그인)."""

    username: str
    password: str
    machine_name: str = Field(min_length=1, max_length=MACHINE_NAME_MAX)


class StudioLogin(ContractModel):
    """Studio 로그인 응답. **`key`는 이 응답에만 실린다** — Studio는 OS 비밀 저장소에 둔다."""

    key: str
    key_id: str
    username: Username
    expires_at: Timestamp


class PasswordChangeRequest(ContractModel):
    """`PUT /auth/password` — 자기 비밀번호. 지금 비밀번호가 맞아야 한다."""

    current_password: str
    new_password: str


__all__ = [
    "KNOWN_PERMISSIONS",
    "KNOWN_ROLES",
    "MACHINE_NAME_MAX",
    "PERMISSION_DESIGN",
    "STUDIO_KEY_DAYS",
    "STUDIO_NOTICE_DAYS",
    "StudioLogin",
    "StudioLoginInfo",
    "StudioLoginRequest",
    "allows",
    "LOGIN_FAILURES_MAX",
    "LOGIN_LOCK_MINUTES",
    "PASSWORD_MIN",
    "ROLE_ADMIN",
    "ROLE_VIEWER",
    "SESSION_HOURS",
    "SESSION_PREFIX",
    "AccountCreateRequest",
    "AccountInfo",
    "AccountUpdateRequest",
    "LoginRequest",
    "PasswordChangeRequest",
    "SessionInfo",
    "WhoAmI",
    "password_violation",
    "username_violation",
]
