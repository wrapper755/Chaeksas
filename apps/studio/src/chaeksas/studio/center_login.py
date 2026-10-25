"""STU-10 「Center」 — Studio 로그인·로그아웃 (C5 §계정 권한과 Studio 로그인, ADR-0092).

Studio는 Center API 키를 사람에게서 받지 않는다. 아이디·비밀번호로 로그인하면 Center가 **그 계정에
묶인 Studio용 키**를 만들어 내려 주고, 그 키를 OS 비밀 저장소에 둔다(그다음은 지금처럼 그 키로
올리고 읽는다). **비밀번호는 어디에도 남기지 않는다.**

화면을 모르는 함수라 Qt 없이 시험한다. 결과는 사람에게 보일 한 줄이고 **키 값은 들어가지 않는다**.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass
from typing import Any

from chaeksas.contracts.accounts import MACHINE_NAME_MAX, StudioLogin
from chaeksas.studio.credentials import CENTER_KEY_NAME, SecretsUnavailable, StudioCredentials

TIMEOUT_S = 10.0
LOGIN_PATH = "/api/v1/auth/studio-login"
LOGOUT_PATH = "/api/v1/auth/studio-logout"

#: Center의 오류 코드 → 사람에게 할 말 (STU-10 표).
MESSAGES = {
    "login_failed": "아이디나 비밀번호가 맞지 않습니다",
    "login_locked": "여러 번 틀려 5분 동안 막혔습니다",
    "account_disabled": "멈춘 계정입니다",
    "permission_missing": (
        "이 계정에는 「설계」 권한이 없습니다 — 관리자에게 콘솔 「관리자 계정」에서 켜 달라고 하세요"
    ),
}


@dataclass(frozen=True)
class LoginResult:
    """로그인 한 번의 결과. `ok`이면 키는 이미 비밀 저장소에 들어갔다."""

    ok: bool
    message: str
    username: str = ""
    expires_at: str = ""


def machine_name() -> str:
    """이 PC의 이름 — 콘솔 CON-14가 「어느 PC에 로그인돼 있나」로 보인다."""
    return (socket.gethostname() or "Studio")[:MACHINE_NAME_MAX]


def _post(url: str, *, json: dict[str, Any] | None, headers: dict[str, str], client: Any) -> Any:
    import httpx  # noqa: PLC0415 — 누를 때만 든다

    if client is not None:
        return client.post(url, json=json, headers=headers)
    with httpx.Client(timeout=TIMEOUT_S) as made:
        return made.post(url, json=json, headers=headers)


def _code(answer: Any) -> str:
    try:
        return str(answer.json().get("code") or "")
    except ValueError:
        return ""


def login(
    base_url: str,
    username: str,
    password: str,
    *,
    credentials: StudioCredentials,
    client: Any = None,
    machine: str | None = None,
) -> LoginResult:
    """로그인해 받은 키를 비밀 저장소에 둔다. 실패하면 아무것도 바꾸지 않는다."""
    import httpx  # noqa: PLC0415

    if not base_url.strip():
        return LoginResult(False, "Center 주소가 비었습니다.")
    if not username.strip() or not password:
        return LoginResult(False, "아이디와 비밀번호를 넣으세요.")
    body = {"username": username.strip(), "password": password, "machine_name": machine or machine_name()}
    try:
        answer = _post(f"{base_url.rstrip('/')}{LOGIN_PATH}", json=body, headers={}, client=client)
    except httpx.HTTPError as e:
        return LoginResult(False, f"닿지 못함 — {type(e).__name__}")
    if answer.status_code >= 400:
        code = _code(answer)
        return LoginResult(False, MESSAGES.get(code, f"Center가 {answer.status_code}로 답했습니다"))
    found = StudioLogin.model_validate(answer.json())
    try:
        credentials.set_center_api_key(found.key)
    except SecretsUnavailable as e:
        return LoginResult(False, f"받은 키를 둘 곳이 없습니다 — {e}")
    return LoginResult(True, f"{found.username}로 로그인됨", username=found.username, expires_at=found.expires_at)


def logout(base_url: str, *, credentials: StudioCredentials, client: Any = None) -> str:
    """Center에 알려 키를 폐기하고 이 PC에서도 지운다 — **닿지 못해도 이 PC에서는 지운다**."""
    import httpx  # noqa: PLC0415

    key = credentials.stored_center_api_key()
    said = "로그아웃했습니다."
    if key and base_url.strip():
        try:
            answer = _post(
                f"{base_url.rstrip('/')}{LOGOUT_PATH}",
                json=None,
                headers={"Authorization": f"Bearer {key}"},
                client=client,
            )
            if answer.status_code >= 400 and answer.status_code not in (401, 403):
                said = f"Center가 {answer.status_code}로 답했지만 이 PC에서는 로그아웃했습니다."
        except httpx.HTTPError:
            said = "Center에 닿지 못했지만 이 PC에서는 로그아웃했습니다 (키는 만료되면 저절로 끝납니다)."
    credentials.delete(CENTER_KEY_NAME)
    return said


__all__ = ["MESSAGES", "LoginResult", "login", "logout", "machine_name"]
