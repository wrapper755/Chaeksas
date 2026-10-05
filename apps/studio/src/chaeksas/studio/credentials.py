"""Studio의 비밀 — 모델 키와 서비스 앱 키(개발용) (STU-10, ADR-0013).

**설정 파일에 넣지 않는다** (CLAUDE.md §5). OS 비밀 저장소(`keyring`)의 `chaeksas-studio`에 두고,
읽기는 **환경변수가 먼저**다 (개발·CI). 저장소가 없으면 저장이 **분명히 실패한다** — 평문으로
흘리지 않는다 (Bot UI의 `credentials.py`와 같은 규칙, 이름 공간은 따로다 — 값이 다르다).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

#: OS 비밀 저장소에서 Studio가 쓰는 이름 (Bot UI는 `chaeksas-bot-ui`).
SERVICE = "chaeksas-studio"
#: 모델 키.
LLM_KEY_NAME = "llm"
ENV_LLM_API_KEY = "CHK_STUDIO__LLM__API_KEY"
#: 서비스 앱 키 — 참조 이름마다 하나 (`svc:<참조>`).
SERVICE_KEY_PREFIX = "svc:"
ENV_SERVICE_KEY_PREFIX = "CHK_STUDIO__SVC__"


def env_name(text: str) -> str:
    """환경변수 이름으로 쓸 수 있게 — 영대문자·숫자·`_` (`test-ui` → `TEST_UI`)."""
    return "".join(one if one.isalnum() else "_" for one in text).upper()


def service_key_env(ref: str) -> str:
    return ENV_SERVICE_KEY_PREFIX + env_name(ref)


class SecretsUnavailable(RuntimeError):
    """OS 비밀 저장소를 쓸 수 없다 (설치 안 됨·잠김·헤드리스)."""


@dataclass
class StudioCredentials:
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

    def get(self, name: str, *, env: str | None = None) -> str | None:
        """읽는다. **환경변수가 먼저다**."""
        if env:
            found = os.environ.get(env)
            if found:
                return found
        return self.stored(name)

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

    def delete(self, name: str) -> None:
        backend = self._keyring()
        if backend is None:
            return
        try:
            backend.delete_password(self.service, name)
        except Exception as e:  # noqa: BLE001 — 없는 비밀을 지우는 것은 오류가 아니다
            log.debug("비밀을 지우지 못했다 (%s): %s", name, type(e).__name__)

    # ── 지름길 ──

    def llm_api_key(self) -> str | None:
        return self.get(LLM_KEY_NAME, env=ENV_LLM_API_KEY)

    def set_llm_api_key(self, value: str) -> None:
        self.set(LLM_KEY_NAME, value.strip())

    def service_key(self, ref: str) -> str | None:
        return self.get(f"{SERVICE_KEY_PREFIX}{ref}", env=service_key_env(ref))

    def stored_service_key(self, ref: str) -> str | None:
        return self.stored(f"{SERVICE_KEY_PREFIX}{ref}")

    def set_service_key(self, ref: str, value: str) -> None:
        self.set(f"{SERVICE_KEY_PREFIX}{ref}", value.strip())

    def delete_service_key(self, ref: str) -> None:
        self.delete(f"{SERVICE_KEY_PREFIX}{ref}")


__all__ = [
    "ENV_LLM_API_KEY",
    "ENV_SERVICE_KEY_PREFIX",
    "SERVICE",
    "SecretsUnavailable",
    "StudioCredentials",
    "env_name",
    "service_key_env",
]
