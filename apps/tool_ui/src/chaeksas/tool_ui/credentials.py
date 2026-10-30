"""Tool UI의 비밀 — 도구의 비밀 설정 칸 (TOL-02, ADR-0013·0077).

**설정 파일에 넣지 않는다** (CLAUDE.md §5). OS 비밀 저장소의 `chaeksas-tool-ui`에 두고, 읽기는
**환경변수가 먼저**다 (`CHK_TOOL_UI__EXT__<확장>__<칸>`, 개발·CI). 저장소가 없으면 저장이 **분명히
실패한다** — 평문으로 흘리지 않는다 (PC 실행기·Studio와 같은 규칙, 이름 공간은 따로다).

PC 실행기에 넣어 두었던 등록 담당자 키는 **옮기지 않는다** — 그쪽 저장소는 다른 사람의 것일 수 있다.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

#: OS 비밀 저장소에서 Tool UI가 쓰는 이름 (PC 실행기는 `chaeksas-bot-ui`, Studio는 `chaeksas-studio`).
SERVICE = "chaeksas-tool-ui"
#: 확장의 비밀 설정 칸 — 확장마다 이름 공간을 가른다 (`ext:<확장>:<칸>`, PC 실행기·Studio와 같은 규칙).
EXTENSION_PREFIX = "ext:"
ENV_EXTENSION_PREFIX = "CHK_TOOL_UI__EXT__"


def env_name(text: str) -> str:
    """환경변수 이름으로 쓸 수 있게 — 영대문자·숫자·`_` (`ui-automation` → `UI_AUTOMATION`)."""
    return "".join(one if one.isalnum() else "_" for one in text).upper()


def extension_secret_env(extension_id: str, key: str) -> str:
    return f"{ENV_EXTENSION_PREFIX}{env_name(extension_id)}__{env_name(key)}"


#: 호출 토큰을 푸는 이름 (C13 예약 비밀 `call_token`, C15).
CALL_TOKEN_SECRET = "call_token"
#: PC 실행기의 비밀 저장소와 그 안의 호출 토큰 이름 — PC 실행기(`credentials.CALL_TOKEN`)와 **같은 규칙**이다.
#: 앱끼리 import하지 않으므로 여기 한 번 더 적고 시험이 대조한다.
BOT_UI_SERVICE = "chaeksas-bot-ui"
BOT_UI_CALL_TOKEN = "call_token"


def bot_ui_call_token() -> str | None:
    """이 PC PC 실행기가 청해 둔 호출 토큰 (C15). 없으면 `None` — PC 실행기가 아직 Center에 붙지 않았다."""
    return ToolCredentials(service=BOT_UI_SERVICE).stored(BOT_UI_CALL_TOKEN)


class SecretsUnavailable(RuntimeError):
    """OS 비밀 저장소를 쓸 수 없다 (설치 안 됨·잠김·헤드리스)."""


@dataclass
class ToolCredentials:
    """비밀 창고 하나. `keyring`을 쓰고, 없으면 환경변수로 **읽기만** 한다."""

    service: str = SERVICE

    def _keyring(self) -> Any | None:
        try:
            import keyring  # noqa: PLC0415 — 없을 수도 있다 (헤드리스 CI)
        except ImportError:  # pragma: no cover - 의존성에 있다
            return None
        try:
            # 저장소가 아예 없으면 keyring이 「fail」 백엔드를 준다 — 그것도 없는 것으로 본다.
            from keyring.backends.fail import Keyring as FailKeyring  # noqa: PLC0415

            if isinstance(keyring.get_keyring(), FailKeyring):
                return None
        except ImportError:  # pragma: no cover - keyring 구조가 바뀐 경우
            pass
        return keyring

    @property
    def available(self) -> bool:
        return self._keyring() is not None

    def stored(self, name: str) -> str | None:
        """비밀 저장소에 **저장된 것만** (환경변수는 보지 않는다)."""
        backend = self._keyring()
        if backend is None:
            return None
        try:
            found = backend.get_password(self.service, name)
        except Exception as e:  # noqa: BLE001 — 백엔드가 어떤 예외를 낼지 모른다
            log.warning("비밀을 읽지 못했다 (%s): %s", name, type(e).__name__)
            return None
        return str(found) if found else None

    def set(self, name: str, value: str) -> None:
        """저장한다. 저장소가 없으면 **분명히 실패한다**."""
        backend = self._keyring()
        if backend is None:
            raise SecretsUnavailable(
                "이 PC에서 OS 비밀 저장소를 쓸 수 없습니다 — 환경변수로 주거나 비밀 저장소를 설정하세요"
            )
        try:
            backend.set_password(self.service, name, value)
        except Exception as e:  # noqa: BLE001
            raise SecretsUnavailable(f"비밀을 저장하지 못했습니다: {e}") from e

    def extension_secret(self, extension_id: str, key: str) -> str | None:
        """확장의 비밀 설정 칸. **환경변수가 먼저**다. 확장마다 이름 공간을 나눈다."""
        found = os.environ.get(extension_secret_env(extension_id, key))
        if found:
            return found
        return self.stored(f"{EXTENSION_PREFIX}{extension_id}:{key}")

    def stored_extension_secret(self, extension_id: str, key: str) -> str | None:
        return self.stored(f"{EXTENSION_PREFIX}{extension_id}:{key}")

    def set_extension_secret(self, extension_id: str, key: str, value: str) -> None:
        self.set(f"{EXTENSION_PREFIX}{extension_id}:{key}", value.strip())


@dataclass(frozen=True)
class ToolSecrets:
    """`extension_api.Secrets` — 확장 하나의 비밀 칸을 푼다. **값을 가진 쪽은 호스트다**."""

    credentials: ToolCredentials
    extension_id: str

    def resolve(self, ref: str) -> str | None:
        if ref == CALL_TOKEN_SECRET:
            # 호출 토큰 — 환경변수가 먼저(자동화·CI), 아니면 **이 PC PC 실행기가 청해 둔 것**을 읽기만 한다
            # (C15). 그 토큰으로 올린 등록 작업은 CON-03 「셀렉터 등록」을 켠 PC에서만 받는다.
            found = os.environ.get(extension_secret_env(self.extension_id, ref))
            return found or bot_ui_call_token()
        return self.credentials.extension_secret(self.extension_id, ref)


__all__ = [
    "ENV_EXTENSION_PREFIX",
    "EXTENSION_PREFIX",
    "SERVICE",
    "SecretsUnavailable",
    "ToolCredentials",
    "ToolSecrets",
    "env_name",
    "extension_secret_env",
]
