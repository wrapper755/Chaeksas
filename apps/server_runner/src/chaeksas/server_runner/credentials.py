"""비밀 값 — 환경변수가 먼저, 그다음 OS 비밀 저장소 (CLAUDE.md §5).

**서버에서는 환경변수가 주 경로다.** 컨테이너·systemd가 그렇게 준다. 그래도 저장소를 쓸 수
있으면 읽는다 — 개발 PC에서 PC 실행기·Studio와 같은 방식으로 다룰 수 있게. **운영자가 비밀 폴더
(`CHK_SERVER_RUNNER__SECRETS_DIR`)를 적으면 그것이 저장소 자리에 들어간다** (ADR-0100) — OS 비밀
저장소가 없는 컨테이너에서도 등록 승인·키 회전이 돈다.

설정 파일·실행 기록·코드에는 넣지 않는다. **쓰기는 저장소가 없으면 분명히 실패한다** (평문으로
흘리지 않는다 — PC 실행기와 같은 태도다).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from chaeksas.server_runner import secret_file

log = logging.getLogger(__name__)

#: `keyring`의 서비스 이름 (PC 실행기·Studio와 가른다 — 한 PC에 셋이 있을 수 있다).
SERVICE = "chaeksas-server-runner"

#: Center API 키 (C12 — 「서버 실행기용」 종류).
CENTER_API_KEY = "center_api_key"
ENV_CENTER_API_KEY = "CHK_SERVER_RUNNER__CENTER_API_KEY"
#: 등록 요청에 쓴 키 쌍의 비밀 반쪽 (C12 §등록 요청과 승인).
ENROLL_SECRET = "enroll_secret"

#: 모델 키 (ADR-0027). **값은 설정·실행 기록에 넣지 않는다** (CLAUDE.md §5).
LLM_API_KEY = "llm-api-key"
ENV_LLM_API_KEY = "CHK_SERVER_RUNNER__LLM__API_KEY"

#: SMTP 비밀번호 (ADR-0059). **설정·실행 기록에 넣지 않는다** (CLAUDE.md §5).
SMTP_PASSWORD = "smtp-password"
ENV_SMTP_PASSWORD = "CHK_SERVER_RUNNER__SMTP__PASSWORD"

#: 확장의 설정 칸 (C13 `configuration`, `scope: server_runner`)과 그 비밀 칸.
#: **이름 규칙은 PC 실행기의 것과 같다** (`CHK_BOT_UI__EXT__…` — ADR-0064 §2): 서버에는 설정 파일이
#: 없어 비밀이 아닌 칸도 환경변수로 온다.
EXTENSION_PREFIX = "ext:"
ENV_EXTENSION_PREFIX = "CHK_SERVER_RUNNER__EXT__"


class SecretsUnavailable(RuntimeError):
    """OS 비밀 저장소를 쓸 수 없다 (설치 안 됨·잠김·헤드리스 서버)."""


def _env_name(text: str) -> str:
    """환경변수 이름으로 쓸 수 있게 — 영대문자·숫자·`_`."""
    return "".join(one if one.isalnum() else "_" for one in text).upper()


def extension_config_env(extension_id: str, key: str) -> str:
    """확장의 설정 칸 하나를 줄 환경변수 이름 (C13 `configuration`, ADR-0064 §2).

    확장마다 이름 공간을 나눈다 — 다른 확장의 칸을 가져가지 못한다.
    """
    return f"{ENV_EXTENSION_PREFIX}{_env_name(extension_id)}__{_env_name(key)}"


@dataclass
class Credentials:
    """비밀 창고 하나. 환경변수가 먼저고, 없으면 `keyring`을 본다."""

    service: str = SERVICE

    def _keyring(self) -> object | None:
        # 사람이 적은 비밀 폴더가 이긴다 — 적었는데 OS 저장소로 가면 볼륨 밖에 남는다.
        chosen = secret_file.from_env()
        if chosen is not None:
            return chosen
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

    def set_center_api_key(self, value: str) -> None:
        """승인·회전으로 받은 키 (C12 §등록 요청과 승인). 저장소가 없으면 분명히 실패한다."""
        self.set(CENTER_API_KEY, value)

    def center_key_from_env(self) -> bool:
        """키가 환경변수로 오는가 — 그러면 등록 요청도 회전도 하지 않는다."""
        return bool(os.environ.get(ENV_CENTER_API_KEY))

    def enroll_secret(self) -> str | None:
        """등록 요청에 쓴 키 쌍의 비밀 반쪽 — 비밀 저장소에만 있다 (환경변수 길이 없다)."""
        return self.get(ENROLL_SECRET)

    def set_enroll_secret(self, value: str) -> None:
        self.set(ENROLL_SECRET, value)

    def llm_api_key(self) -> str | None:
        """모델 키. 환경변수가 먼저다 (개발·CI) — 서버는 대개 그쪽이다."""
        return self.get(LLM_API_KEY, env=ENV_LLM_API_KEY)

    def smtp_password(self) -> str | None:
        """메일 서버 비밀번호. 환경변수가 먼저다 (서버의 주 경로)."""
        return self.get(SMTP_PASSWORD, env=ENV_SMTP_PASSWORD)

    def delete(self, name: str) -> None:
        backend = self._keyring()
        if backend is None:
            return
        try:
            backend.delete_password(self.service, name)  # type: ignore[attr-defined]
        except Exception as e:  # noqa: BLE001 — 없는 비밀을 지우는 것은 오류가 아니다
            log.debug("비밀을 지우지 못했다 (%s): %s", name, e)

    def extension_secret(self, extension_id: str, key: str) -> str | None:
        """확장의 비밀 설정 칸 (C13 `configuration[].secret`). PC 실행기와 같은 규칙이다."""
        return self.get(
            f"{EXTENSION_PREFIX}{extension_id}:{key}",
            env=extension_config_env(extension_id, key),
        )



__all__ = [
    "CENTER_API_KEY",
    "ENV_CENTER_API_KEY",
    "ENV_EXTENSION_PREFIX",
    "ENV_LLM_API_KEY",
    "ENV_SMTP_PASSWORD",
    "EXTENSION_PREFIX",
    "LLM_API_KEY",
    "SERVICE",
    "SMTP_PASSWORD",
    "Credentials",
    "SecretsUnavailable",
    "extension_config_env",
]
