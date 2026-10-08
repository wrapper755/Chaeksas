"""비밀 값 — **OS 비밀 저장소에만** 둔다 (CLAUDE.md §5, BUI-03·BUI-10).

설정 파일·실행 기록·코드에 넣지 않는다. Windows는 자격 증명 관리자, Linux는 Secret Service,
macOS는 키체인 — `keyring`이 그 차이를 덮는다.

개발·CI에서는 비밀 저장소가 없을 수 있다. 그때는 **환경변수**로 받고, 쓰기는 「저장할 곳이
없다」고 분명히 말한다 (조용히 평문 파일에 적지 않는다).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

log = logging.getLogger(__name__)

#: `keyring`의 서비스 이름. 한 PC에 여러 Bot UI를 두지 않으므로 하나로 충분하다.
SERVICE = "chaeksas-bot-ui"

#: Center API 키 (C4 — 「Bot UI용」 종류). 개발·CI용 환경변수.
CENTER_API_KEY = "center_api_key"
ENV_CENTER_API_KEY = "CHK_BOT_UI__CENTER_API_KEY"

#: 서비스 앱 키는 **참조 이름**으로 저장한다 (BUI-10, ADR-0013 §3).
SERVICE_APP_PREFIX = "svc:"
#: 서비스 앱 키를 환경변수로도 읽는다 (개발·CI). Studio의 `CHK_STUDIO__SVC__…`와 같은 규칙.
ENV_SERVICE_APP_PREFIX = "CHK_BOT_UI__SVC__"

#: 모델 키 (ADR-0027). 실행기에게는 **환경변수로** 건넨다 (명령줄에 두지 않는다).
LLM_API_KEY = "llm-api-key"
ENV_LLM_API_KEY = "CHK_BOT_UI__LLM__API_KEY"


#: 확장 설정 칸의 이름 공간 (확장마다 가른다).
EXTENSION_PREFIX = "ext:"
ENV_EXTENSION_PREFIX = "CHK_BOT_UI__EXT__"


def _env_name(text: str) -> str:
    """환경변수 이름으로 쓸 수 있게 — 영대문자·숫자·`_`."""
    return "".join(one if one.isalnum() else "_" for one in text).upper()


def service_key_env(ref: str) -> str:
    """그 키 참조를 개발·CI에서 줄 환경변수 이름 (BUI-10이 사람에게 보여 준다)."""
    return f"{ENV_SERVICE_APP_PREFIX}{_env_name(ref)}"


class SecretsUnavailable(RuntimeError):
    """OS 비밀 저장소를 쓸 수 없다 (설치 안 됨·잠김·헤드리스)."""


@dataclass
class Credentials:
    """비밀 창고 하나. `keyring`을 쓰지만, 없으면 환경변수로 **읽기만** 한다."""

    service: str = SERVICE

    def _keyring(self) -> object | None:
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

    @property
    def available(self) -> bool:
        return self._keyring() is not None

    def get(self, name: str, *, env: str | None = None) -> str | None:
        """비밀을 읽는다. 환경변수가 **먼저다** (개발·CI에서 덮어쓸 수 있게)."""
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
        """비밀을 저장한다. 저장소가 없으면 **분명히 실패한다** (평문으로 흘리지 않는다)."""
        backend = self._keyring()
        if backend is None:
            raise SecretsUnavailable(
                "이 PC에서 OS 비밀 저장소를 쓸 수 없습니다 — "
                f"환경변수 {ENV_CENTER_API_KEY}로 주거나, 비밀 저장소를 설정하세요"
            )
        try:
            backend.set_password(self.service, name, value)  # type: ignore[attr-defined]
        except Exception as e:  # noqa: BLE001
            raise SecretsUnavailable(f"비밀을 저장하지 못했습니다: {e}") from e

    def delete(self, name: str) -> None:
        backend = self._keyring()
        if backend is None:
            return
        try:
            backend.delete_password(self.service, name)  # type: ignore[attr-defined]
        except Exception as e:  # noqa: BLE001 — 없는 비밀을 지우는 것은 오류가 아니다
            log.debug("비밀을 지우지 못했다 (%s): %s", name, e)

    # ── 쓰는 쪽이 이름을 외우지 않게 하는 지름길 ──

    def center_api_key(self) -> str | None:
        return self.get(CENTER_API_KEY, env=ENV_CENTER_API_KEY)

    def set_center_api_key(self, value: str) -> None:
        self.set(CENTER_API_KEY, value.strip())

    def llm_api_key(self) -> str | None:
        """모델 키 (ADR-0027). **키가 필요 없는 로컬 모델이면 비어 있다** — 그러면 보내지 않는다."""
        return self.get(LLM_API_KEY, env=ENV_LLM_API_KEY)

    def set_llm_api_key(self, value: str) -> None:
        self.set(LLM_API_KEY, value.strip())

    def extension_secret(self, extension_id: str, key: str) -> str | None:
        """확장의 비밀 설정 칸 (C13 `configuration[].secret`, 예: 등록 담당자 키).

        확장마다 이름 공간을 나눈다 — 다른 확장의 키를 가져가지 못한다.
        """
        safe = f"{EXTENSION_PREFIX}{extension_id}:{key}"
        return self.get(safe, env=f"{ENV_EXTENSION_PREFIX}{_env_name(extension_id)}__{_env_name(key)}")

    def set_extension_secret(self, extension_id: str, key: str, value: str) -> None:
        self.set(f"{EXTENSION_PREFIX}{extension_id}:{key}", value.strip())

    def service_app_key(self, ref: str) -> str | None:
        """BPM 프로세스 속성의 **키 참조 이름**으로 찾는다 (ADR-0013 §3).

        읽기는 **환경변수가 먼저다** — `CHK_BOT_UI__SVC__<참조>` (개발·CI). Studio와 같은 규칙.
        """
        return self.get(f"{SERVICE_APP_PREFIX}{ref}", env=service_key_env(ref))

    def stored_service_app_key(self, ref: str) -> str | None:
        """**비밀 저장소에 들어 있는** 값만 (환경변수는 보지 않는다).

        BUI-10이 「저장됨」과 「환경변수」를 가려 말하는 데 쓴다 — 환경변수로 도는 PC에서 「저장됨」
        이라고 하면, 환경변수를 지운 다음에 왜 안 되는지 알 수 없다.
        """
        return self.get(f"{SERVICE_APP_PREFIX}{ref}")

    def set_service_app_key(self, ref: str, value: str) -> None:
        self.set(f"{SERVICE_APP_PREFIX}{ref}", value.strip())

    def delete_service_app_key(self, ref: str) -> None:
        """BUI-10에서 줄을 지웠다 — 저장소에 남겨 두면 보이지 않는 키가 계속 쓰인다."""
        self.delete(f"{SERVICE_APP_PREFIX}{ref}")


__all__ = [
    "CENTER_API_KEY",
    "ENV_SERVICE_APP_PREFIX",
    "ENV_EXTENSION_PREFIX",
    "EXTENSION_PREFIX",
    "ENV_CENTER_API_KEY",
    "ENV_LLM_API_KEY",
    "LLM_API_KEY",
    "SERVICE",
    "SERVICE_APP_PREFIX",
    "Credentials",
    "SecretsUnavailable",
    "service_key_env",
]
