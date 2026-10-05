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

#: 모델 키 (ADR-0027). 실행기에게는 **환경변수로** 건넨다 (명령줄에 두지 않는다).
LLM_API_KEY = "llm-api-key"
ENV_LLM_API_KEY = "CHK_BOT_UI__LLM__API_KEY"


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

    def service_app_key(self, ref: str) -> str | None:
        """BPM 프로세스 속성의 **키 참조 이름**으로 찾는다 (ADR-0013 §3)."""
        return self.get(f"{SERVICE_APP_PREFIX}{ref}")

    def set_service_app_key(self, ref: str, value: str) -> None:
        self.set(f"{SERVICE_APP_PREFIX}{ref}", value.strip())


__all__ = [
    "CENTER_API_KEY",
    "ENV_CENTER_API_KEY",
    "ENV_LLM_API_KEY",
    "LLM_API_KEY",
    "SERVICE",
    "SERVICE_APP_PREFIX",
    "Credentials",
    "SecretsUnavailable",
]
