"""비밀 값 — 환경변수가 먼저, 그다음 OS 비밀 저장소 (CLAUDE.md §5).

**서버에서는 환경변수가 주 경로다.** 컨테이너·systemd가 그렇게 준다. 그래도 저장소를 쓸 수
있으면 읽는다 — 개발 PC에서 Bot UI·Studio와 같은 방식으로 다룰 수 있게.

설정 파일·실행 기록·코드에는 넣지 않는다. **쓰기는 저장소가 없으면 분명히 실패한다** (평문으로
흘리지 않는다 — Bot UI와 같은 태도다).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

log = logging.getLogger(__name__)

#: `keyring`의 서비스 이름 (Bot UI·Studio와 가른다 — 한 PC에 셋이 있을 수 있다).
SERVICE = "chaeksas-server-runner"

#: Center API 키 (C12 — 「서버 실행기용」 종류).
CENTER_API_KEY = "center_api_key"
ENV_CENTER_API_KEY = "CHK_SERVER_RUNNER__CENTER_API_KEY"

#: 모델 키 (ADR-0027). **값은 설정·실행 기록에 넣지 않는다** (CLAUDE.md §5).
LLM_API_KEY = "llm-api-key"
ENV_LLM_API_KEY = "CHK_SERVER_RUNNER__LLM__API_KEY"

#: SMTP 비밀번호 (ADR-0059). **설정·실행 기록에 넣지 않는다** (CLAUDE.md §5).
SMTP_PASSWORD = "smtp-password"
ENV_SMTP_PASSWORD = "CHK_SERVER_RUNNER__SMTP__PASSWORD"

#: 서비스 앱 키는 **참조 이름**으로 둔다 (ADR-0013 §3). Bot UI·Studio와 같은 규칙이다.
SERVICE_APP_PREFIX = "svc:"
ENV_SERVICE_APP_PREFIX = "CHK_SERVER_RUNNER__SVC__"


class SecretsUnavailable(RuntimeError):
    """OS 비밀 저장소를 쓸 수 없다 (설치 안 됨·잠김·헤드리스 서버)."""


def _env_name(text: str) -> str:
    """환경변수 이름으로 쓸 수 있게 — 영대문자·숫자·`_`."""
    return "".join(one if one.isalnum() else "_" for one in text).upper()


def service_key_env(ref: str) -> str:
    """그 키 참조를 줄 환경변수 이름 (사전 점검이 사람에게 보여 준다)."""
    return f"{ENV_SERVICE_APP_PREFIX}{_env_name(ref)}"


@dataclass
class Credentials:
    """비밀 창고 하나. 환경변수가 먼저고, 없으면 `keyring`을 본다."""

    service: str = SERVICE

    def _keyring(self) -> object | None:
        try:
            import keyring  # noqa: PLC0415 — 없을 수도 있다 (헤드리스 서버)
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

    @property
    def available(self) -> bool:
        return self._keyring() is not None

    def get(self, name: str, *, env: str | None = None) -> str | None:
        """비밀을 읽는다. **환경변수가 먼저다** (서버의 주 경로)."""
        if env:
            found = os.environ.get(env)
            if found:
                return found
        backend = self._keyring()
        if backend is None:
            return None
        try:
            found = backend.get_password(self.service, name)  # type: ignore[attr-defined]
            return str(found) if found else None
        except Exception as e:  # noqa: BLE001 — 백엔드가 어떤 예외를 낼지 모른다
            log.warning("비밀을 읽지 못했다 (%s): %s", name, e)
            return None

    def set(self, name: str, value: str) -> None:
        """비밀을 저장한다. 저장소가 없으면 **분명히 실패한다**."""
        backend = self._keyring()
        if backend is None:
            raise SecretsUnavailable(
                "이 서버에서 OS 비밀 저장소를 쓸 수 없습니다 — "
                f"환경변수 {ENV_CENTER_API_KEY}로 주세요"
            )
        try:
            backend.set_password(self.service, name, value)  # type: ignore[attr-defined]
        except Exception as e:  # noqa: BLE001
            raise SecretsUnavailable(f"비밀을 저장하지 못했습니다: {e}") from e

    # ── 쓰는 쪽이 이름을 외우지 않게 하는 지름길 ──

    def center_api_key(self) -> str | None:
        return self.get(CENTER_API_KEY, env=ENV_CENTER_API_KEY)

    def llm_api_key(self) -> str | None:
        """모델 키. 환경변수가 먼저다 (개발·CI) — 서버는 대개 그쪽이다."""
        return self.get(LLM_API_KEY, env=ENV_LLM_API_KEY)

    def smtp_password(self) -> str | None:
        """메일 서버 비밀번호. 환경변수가 먼저다 (서버의 주 경로)."""
        return self.get(SMTP_PASSWORD, env=ENV_SMTP_PASSWORD)

    def service_app_key(self, ref: str) -> str | None:
        """서비스 앱 키 하나 (참조 이름 → 값). 키 **값은 실행기만 안다** (ADR-0013)."""
        return self.get(f"{SERVICE_APP_PREFIX}{ref}", env=service_key_env(ref))


__all__ = [
    "CENTER_API_KEY",
    "ENV_CENTER_API_KEY",
    "ENV_LLM_API_KEY",
    "ENV_SERVICE_APP_PREFIX",
    "ENV_SMTP_PASSWORD",
    "LLM_API_KEY",
    "SERVICE",
    "SERVICE_APP_PREFIX",
    "SMTP_PASSWORD",
    "Credentials",
    "SecretsUnavailable",
    "service_key_env",
]
