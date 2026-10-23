"""Center 연결 — 주소는 설정 파일, 관리자 토큰은 **OS 비밀 저장소** (ADM-05, ADR-0089).

명령줄과 창이 **같은 순서로** 읽는다: 환경변수 → 저장한 것 → 기본값. 창에서 한 번 넣으면
`chk-admin`도 환경변수 없이 돈다.

- 토큰은 설정 파일에 넣지 않는다 (CLAUDE.md §5). 저장소가 없으면 **저장이 분명히 실패한다** —
  평문 파일로 흘리지 않는다.
- 설정 파일이 깨졌으면 없는 것으로 본다 (파일 하나로 Admin이 뜨지 않으면 안 된다).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from chaeksas.admin import keys as keystore

log = logging.getLogger(__name__)

DEFAULT_CENTER_URL = "http://localhost:8800"
ENV_CENTER_URL = f"{keystore.ENV_PREFIX}CENTER_URL"
ENV_ADMIN_TOKEN = f"{keystore.ENV_PREFIX}ADMIN_TOKEN"

#: `keyring`의 서비스 이름 — Bot UI·Studio·Tool UI와 가른다.
SERVICE = "chaeksas-admin"
TOKEN_NAME = "center_admin_token"


class SecretsUnavailable(RuntimeError):
    """OS 비밀 저장소를 쓸 수 없다 (설치 안 됨·잠김·헤드리스)."""


def settings_path() -> Path:
    return keystore.data_dir() / "settings.json"


def _read() -> dict[str, object]:
    found = settings_path()
    if not found.is_file():
        return {}
    try:
        raw = json.loads(found.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _keyring() -> object | None:
    try:
        import keyring  # noqa: PLC0415 — 없을 수도 있다 (헤드리스 CI)
    except ImportError:  # pragma: no cover - 설치되어 있다
        return None
    try:
        # 저장소가 아예 없으면 keyring이 「fail」 백엔드를 준다 — 그것도 없는 것으로 본다.
        from keyring.backends.fail import Keyring as FailKeyring  # noqa: PLC0415

        if isinstance(keyring.get_keyring(), FailKeyring):
            return None
    except ImportError:  # pragma: no cover - keyring 구조가 바뀐 경우
        pass
    return keyring


@dataclass(frozen=True)
class Connection:
    """지금 쓰일 Center 연결과 **어디서 왔는지** (창이 「환경변수가 이깁니다」를 말한다)."""

    url: str
    token: str
    url_from_env: bool = False
    token_from_env: bool = False

    @property
    def has_token(self) -> bool:
        return bool(self.token)


#: 서버 셸 종류 (ADM-05) — 첫 키를 넣을 자리 (C2 — 서버 셸에서만, ADR-0089 §6).
SHELL_NONE = ""
SHELL_LOCAL = "local"
SHELL_SSH = "ssh"
SHELL_KINDS = (SHELL_NONE, SHELL_LOCAL, SHELL_SSH)
DEFAULT_SSH_PORT = 22


@dataclass(frozen=True)
class ServerShell:
    """첫 키를 넣을 서버 셸. **비밀이 없다** — SSH는 키·에이전트로 들어가고 암호를 받지 않는다."""

    kind: str = SHELL_NONE
    ssh_target: str = ""  # 사용자@호스트
    ssh_port: int = DEFAULT_SSH_PORT
    #: 비우면 compose 서비스 `center` 컨테이너를 찾는다. docker 없이 띄운 Center면 그것을 부르는 명령.
    center_command: str = ""

    def where(self) -> str:
        """사람이 읽을 자리 한 마디 (「이 PC」·「SSH wrapper@host」)."""
        if self.kind == SHELL_LOCAL:
            return "이 PC"
        if self.kind == SHELL_SSH:
            port = "" if self.ssh_port == DEFAULT_SSH_PORT else f":{self.ssh_port}"
            return f"SSH {self.ssh_target}{port}"
        return "없음"

    def to_json_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "ssh_target": self.ssh_target,
            "ssh_port": self.ssh_port,
            "center_command": self.center_command,
        }


def stored_shell() -> ServerShell:
    """설정 파일의 서버 셸. 깨졌거나 모르는 종류면 「없음」이다."""
    raw = _read().get("server_shell")
    if not isinstance(raw, dict):
        return ServerShell()
    kind = str(raw.get("kind") or "")
    if kind not in SHELL_KINDS:
        return ServerShell()
    try:
        port = int(raw.get("ssh_port") or DEFAULT_SSH_PORT)
    except (TypeError, ValueError):
        port = DEFAULT_SSH_PORT
    return ServerShell(
        kind=kind,
        ssh_target=str(raw.get("ssh_target") or "").strip(),
        ssh_port=port,
        center_command=str(raw.get("center_command") or "").strip(),
    )


def stored_url() -> str | None:
    found = _read().get("center_url")
    return str(found).strip() or None if isinstance(found, str) else None


def stored_token() -> str | None:
    backend = _keyring()
    if backend is None:
        return None
    try:
        found = backend.get_password(SERVICE, TOKEN_NAME)  # type: ignore[attr-defined]
    except Exception as e:  # noqa: BLE001 — 백엔드가 어떤 예외를 낼지 모른다
        log.warning("토큰을 읽지 못했다: %s", e)
        return None
    return str(found) if found else None


def current() -> Connection:
    """환경변수 → 저장한 것 → 기본값."""
    env_url = os.environ.get(ENV_CENTER_URL, "").strip()
    env_token = os.environ.get(ENV_ADMIN_TOKEN, "").strip()
    return Connection(
        url=env_url or stored_url() or DEFAULT_CENTER_URL,
        token=env_token or stored_token() or "",
        url_from_env=bool(env_url),
        token_from_env=bool(env_token),
    )


def save(*, url: str, token: str | None, shell: ServerShell | None = None) -> None:
    """주소를 적고, 토큰을 주면 비밀 저장소에 넣는다 (`None`이면 토큰은 그대로).

    **토큰을 먼저 넣는다** — 저장소가 없어 실패하면 주소도 바꾸지 않는다(「저장」은 한 번에).
    빈 글자를 주면 토큰을 지운다.
    """
    if token is not None:
        backend = _keyring()
        if token.strip():
            if not token.strip().isascii():
                raise SecretsUnavailable("관리자 토큰에 ASCII가 아닌 글자가 있습니다 — 저장하지 않았습니다")
            if backend is None:
                raise SecretsUnavailable(
                    "이 PC에서 OS 비밀 저장소를 쓸 수 없습니다 — "
                    f"환경변수 {ENV_ADMIN_TOKEN}로 주거나, 비밀 저장소를 설정하세요"
                )
            try:
                backend.set_password(SERVICE, TOKEN_NAME, token.strip())  # type: ignore[attr-defined]
            except Exception as e:  # noqa: BLE001
                raise SecretsUnavailable(f"토큰을 저장하지 못했습니다: {e}") from e
        elif backend is not None:
            try:
                backend.delete_password(SERVICE, TOKEN_NAME)  # type: ignore[attr-defined]
            except Exception as e:  # noqa: BLE001 — 없는 비밀을 지우는 것은 오류가 아니다
                log.debug("토큰을 지우지 못했다: %s", e)
    data = _read()
    data["center_url"] = url.strip() or DEFAULT_CENTER_URL
    if shell is not None:
        data["server_shell"] = shell.to_json_dict()
    target = settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


__all__ = [
    "DEFAULT_CENTER_URL",
    "ENV_ADMIN_TOKEN",
    "ENV_CENTER_URL",
    "SERVICE",
    "Connection",
    "SHELL_KINDS",
    "SHELL_LOCAL",
    "SHELL_NONE",
    "SHELL_SSH",
    "SecretsUnavailable",
    "ServerShell",
    "current",
    "save",
    "settings_path",
    "stored_shell",
    "stored_token",
    "stored_url",
]
