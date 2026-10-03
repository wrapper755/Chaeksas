"""시험이 함께 쓰는 것. 여기 있는 것은 **제품 코드가 아니다.**"""

from __future__ import annotations

from chaeksas.bot_ui.credentials import Credentials


class FakeCredentials(Credentials):
    """OS 비밀 저장소 대신 메모리. 시험이 개발 PC의 키링을 건드리지 않게."""

    def __init__(self, key: str | None = None) -> None:
        super().__init__()
        self._values: dict[str, str] = {"center_api_key": key} if key else {}

    @property
    def available(self) -> bool:
        return True

    def get(self, name: str, *, env: str | None = None) -> str | None:
        return self._values.get(name)

    def set(self, name: str, value: str) -> None:
        self._values[name] = value

    def delete(self, name: str) -> None:
        self._values.pop(name, None)
