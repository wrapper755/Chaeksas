"""인증 — 누가 부르는가 (C5 「권한표」).

| 부르는 쪽 | 토큰 | 할 수 있는 것 |
| --- | --- | --- |
| 콘솔 「보기 전용」 계정 | 세션 토큰 (`chk_ses_…`) | **GET만** |
| 콘솔 「관리자」 계정 | 세션 토큰 | 쓰기 전부 — 승인·배포·외부 확장은 Center가 서명한다 (ADR-0090) |
| 자동화(스크립트·시험) | 관리자·읽기 토큰 | 위의 둘과 같다. 설정하지 않으면 그 길이 닫힌다 |
| Bot UI·Studio·서버 실행기 | Center API 키 (종류별) | 자기 일만 |

**「자기 일만」은 키 종류로 가른다.** 토큰이 맞는지만 보는 `require_read`로는 C5 권한표를
지킬 수 없다 — 패키지 쪽은 종류를 보는 관문(`require_upload`·`require_package_read`)과,
배포 표까지 대조하는 관문(`api.package_access.guard_download`)이 따로 있다.

**행위자 이름은 본문에서 받지 않는다** (C5). 세션으로 부르면 **계정 아이디**(로그인이 정한
신원이라 `X-CHK-Actor`를 듣지 않는다), 키로 부르면 키 이름, 관리자·읽기 토큰으로 부르면
`X-CHK-Actor` 헤더 — 그 헤더는 **토큰으로 부를 때만** 믿는다.

**사람 대신 부르는 키**(대리 답용·연동용)는 그 사람을 `X-CHK-On-Behalf-Of`로 싣는다 (ADR-0081).
여기서 **한 번** 풀어 `Caller.on_behalf`에 두고, 결재(담당자 대조)와 작업(`on_behalf_of` 기록)이
읽는다. 대리 답용 키는 **결재 셋뿐**이라 `require_read`도 지나지 못한다.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from urllib.parse import unquote

from fastapi import Request

from chaeksas.center import accounts, enrollments, keys
from chaeksas.center.errors import ApiError
from chaeksas.center.storage import Store, now_iso
from chaeksas.contracts.accounts import ROLE_ADMIN, SESSION_PREFIX
from chaeksas.contracts.approvals import normalize_name
from chaeksas.contracts.center_api import ON_BEHALF_HEADER, on_behalf_violation
from chaeksas.contracts.center_keys import RELAY_KEY_TYPE

#: 콘솔(BFF)이 로그인한 사용자 이름을 싣는 헤더. **값은 UTF-8 퍼센트 인코딩** (C5).
ACTOR_HEADER = "X-CHK-Actor"

#: 패키지를 올리고 목록·정보를 볼 수 있는 Center API 키 종류 (C5 권한표).
#:
#: **Studio만이다.** 실행하는 쪽(Bot UI·서버 실행기)은 배포를 하트비트로 받으므로 목록을 볼
#: 일이 없고(내려받기만 한다), 연동용 키는 작업만 만든다.
PACKAGE_KEY_TYPE = "studio"

#: `X-CHK-On-Behalf-Of`를 읽는 키 종류 (ADR-0081). 다른 쪽이 실어 보내면 **듣지 않는다**.
ON_BEHALF_KEY_TYPES = frozenset({RELAY_KEY_TYPE, "integration"})


@dataclass(frozen=True)
class Caller:
    """부르는 쪽. `kind`는 `admin`·`read`·`key` 중 하나다."""

    kind: str
    actor: str
    key: keys.KeyRecord | None = None
    #: 키가 대신 부르는 사람 (`X-CHK-On-Behalf-Of`, 정규화 뒤). 대리 답용·연동용 키일 때만 있다.
    on_behalf: str | None = None
    #: 세션으로 불렀으면 그 계정 아이디 (ADR-0090). 토큰·키로 부르면 `None`.
    account: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.kind == "admin"

    @property
    def is_relay(self) -> bool:
        return self.key is not None and self.key.type == RELAY_KEY_TYPE


def bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    return value.strip() if scheme.lower() == "bearer" and value.strip() else None


def _console_actor(request: Request, *, fallback: str) -> str:
    """콘솔이 보낸 사용자 이름. 없으면 토큰 이름을 쓴다.

    값은 **UTF-8 퍼센트 인코딩**이다 (C5) — HTTP 헤더에 한글을 그대로 넣을 수 없다. 디코딩이
    안 되면 받은 문자열을 그대로 쓴다 (이름 하나 때문에 요청을 거부하지 않는다).
    """
    raw = request.headers.get(ACTOR_HEADER, "").strip()
    if not raw:
        return fallback
    try:
        return unquote(raw, errors="strict") or fallback
    except (UnicodeDecodeError, ValueError):
        return raw


def _on_behalf(request: Request) -> str | None:
    """`X-CHK-On-Behalf-Of` — 퍼센트 인코딩한 UTF-8 (C5). **틀린 것은 거부한다** (422).

    `X-CHK-Actor`와 달리 받은 글을 그대로 쓰지 않는다 — 이 이름은 담당자와 **대조하는** 값이라
    디코딩되지 않은 글자로 맞춰 보면 엉뚱한 사람과 같아질 수 있다.
    """
    if ON_BEHALF_HEADER.lower() not in request.headers:
        return None
    raw = request.headers.get(ON_BEHALF_HEADER, "")
    try:
        name = normalize_name(unquote(raw.strip(), errors="strict"))
    except (UnicodeDecodeError, ValueError) as e:
        raise ApiError(422, "on_behalf_invalid", f"{ON_BEHALF_HEADER}를 풀 수 없다") from e
    problem = on_behalf_violation(name)
    if problem is not None:
        raise ApiError(422, problem.code or "on_behalf_invalid", problem.message)
    return name


def caller(request: Request, store: Store, *, admin_token: str | None, read_token: str | None) -> Caller:
    """토큰·키를 보고 부르는 쪽을 정한다. 아무것도 맞지 않으면 401."""
    token = bearer(request)
    if token is None:
        raise ApiError(401, "token_missing", "인증 토큰이 없다")

    if token.startswith(SESSION_PREFIX):
        found = accounts.session_of(store, token)
        if found is None:
            raise ApiError(401, "session_expired", "로그인이 끝났습니다 — 다시 로그인하세요")
        kind = "admin" if found.role == ROLE_ADMIN else "read"
        return Caller(kind=kind, actor=found.username, account=found.username)

    # 토큰이 비어 있으면(설정하지 않았으면) 그 권한으로는 부를 수 없다.
    if admin_token and hmac.compare_digest(token, admin_token):
        return Caller(kind="admin", actor=_console_actor(request, fallback="관리자"))
    if read_token and hmac.compare_digest(token, read_token):
        return Caller(kind="read", actor=_console_actor(request, fallback="보기 전용"))

    record = keys.find(store, token)
    if record is None:
        raise ApiError(401, "key_invalid", "모르는 토큰이다")
    state = record.state(now=now_iso())
    if state != "active":
        raise ApiError(403, f"key_{state}", f"키 「{record.name}」은 {state} 상태다")
    keys.touch(store, record.key_id)
    # 회전한 새 키로 첫 요청이면 행을 새 키로 옮긴다 (C4 §키 회전) — 하트비트가 행을 찾기 **전에**.
    enrollments.adopt_successor(store, record)
    # 승인으로 받은 키가 처음 쓰였다 — 봉해 둔 것을 지운다. Studio는 `register`가 없어 이 자리가
    # 받았다는 표시다 (C5 §Studio 등록 요청과 승인). Bot UI·서버 실행기도 여기서 먼저 지워진다.
    if record.enrollment_id:
        enrollments.delivered(store, record, public_key=None)
    # 키로 부를 때는 X-CHK-Actor를 믿지 않는다 (C5). 사람 대신 부르는 키만 On-Behalf-Of를 듣는다.
    on_behalf = _on_behalf(request) if record.type in ON_BEHALF_KEY_TYPES else None
    return Caller(kind="key", actor=record.name, key=record, on_behalf=on_behalf)


def require_admin(found: Caller) -> Caller:
    if not found.is_admin:
        raise ApiError(403, "admin_only", "관리자만 할 수 있다")
    return found


def require_read(found: Caller) -> Caller:
    """GET에 필요한 권한 — 읽기·관리자 토큰, 또는 Center API 키.

    **대리 답용 키는 뺀다** (ADR-0081) — 그 키의 권한은 결재 셋뿐이고, 결재는 제 관문
    (`require_approval_read`)이 담당인 것만 보인다.
    """
    if found.is_relay:
        raise ApiError(403, "forbidden", "대리 답용 키로는 결재만 읽고 답할 수 있다")
    if found.kind in ("admin", "read", "key"):
        return found
    raise ApiError(403, "forbidden", "읽을 권한이 없다")  # pragma: no cover - 방어


def require_approval_read(found: Caller) -> str | None:
    """결재 읽기 (C6). 콘솔 토큰이면 `None`(전부), 대리 답용 키면 **그 사람 이름**(담당인 것만).

    그 밖의 키는 막는다 — 결재에는 검토 자료(업무 값)가 있고, 답은 하트비트로 내려간다.
    """
    if found.kind in ("admin", "read"):
        return None
    if found.is_relay:
        return require_on_behalf(found)
    raise ApiError(403, "forbidden", "결재는 콘솔 토큰이나 대리 답용 키로 읽는다")


def require_on_behalf(found: Caller) -> str:
    """대리 답용 키는 사람 이름을 **반드시** 싣는다 — 없으면 400 `on_behalf_required` (C6)."""
    if not found.on_behalf:
        raise ApiError(400, "on_behalf_required", f"대리 답용 키는 {ON_BEHALF_HEADER}를 실어야 한다")
    return found.on_behalf


def require_console(found: Caller) -> Caller:
    """콘솔 토큰만 (관리자·읽기). **Center API 키는 안 된다** — C5 권한표가 「—」인 자리다.

    `require_read`와 다른 것은 **키를 막는다**는 점이다. 현황 목록(CON-03·CON-12)은 다른
    기계들의 이름·용량·도는 실행 id를 함께 보여 주므로, 현장 키 하나로 **남의 현황**을 읽을
    수 있으면 「자기 일만」이 깨진다. 패키지 쪽의 `require_package_read`와 같은 결이다.
    """
    if found.kind in ("admin", "read"):
        return found
    raise ApiError(
        403, "forbidden", "현황 목록은 콘솔 토큰(관리자·읽기)으로만 볼 수 있다"
    )


def _package_key(found: Caller) -> bool:
    return found.key is not None and found.key.type == PACKAGE_KEY_TYPE


def require_upload(found: Caller) -> Caller:
    """`POST /packages`에 필요한 권한 — 관리자 토큰 **또는 Studio용 키** (C5 권한표).

    관리자 토큰만으로 막지 않는다. 올리는 쪽은 Studio이고, 관리자 토큰을 관문으로 삼으면
    **설계자 PC에 관리자 토큰을 두게 된다** — ADR-0013이 피한 것이다. 승인·배포는 그대로
    서명이 관문이라(C2) 올린 것은 후보로만 앉는다.
    """
    if found.is_admin or _package_key(found):
        return found
    raise ApiError(
        403, "forbidden", "패키지 업로드는 관리자 토큰이나 Studio용 Center API 키로만 된다"
    )


def require_package_read(found: Caller) -> Caller:
    """패키지 목록·정보·참조에 필요한 권한 — 콘솔 토큰 또는 **Studio용 키만** (C5 권한표).

    `require_read`와 다른 것은 **키 종류를 본다**는 점이다. Bot UI 키로 패키지 표 전체를
    읽을 수 있으면 「무엇이 올라와 있나」가 현장 PC에 다 보인다.
    """
    if found.kind in ("admin", "read") or _package_key(found):
        return found
    raise ApiError(
        403,
        "forbidden",
        "패키지 목록·정보는 콘솔 토큰이나 Studio용 Center API 키로만 볼 수 있다",
    )


def require_key_type(found: Caller, wanted: str) -> keys.KeyRecord:
    """그 종류의 Center API 키로 불렀는가 (C4 — Bot UI용 키만 받는다)."""
    if found.key is None:
        raise ApiError(403, "wrong_key_type", f"{wanted} 종류의 Center API 키로 불러야 한다")
    if found.key.type != wanted:
        raise ApiError(
            403, "wrong_key_type", f"키 종류가 {found.key.type}이다 ({wanted} 키가 필요하다)"
        )
    return found.key
