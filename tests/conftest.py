"""시험이 함께 쓰는 것. 여기 있는 것은 **제품 코드가 아니다.**"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from chaeksas.bot_ui.credentials import Credentials


@pytest.fixture(autouse=True)
def _bot_ui_data_dir_is_temporary(tmp_path_factory: pytest.TempPathFactory, monkeypatch: Any) -> Iterator[Path]:
    """**어느 시험도 개발 PC의 Bot UI 데이터 폴더를 쓰지 않는다.**

    기본 위치(Windows `%LOCALAPPDATA%` 밑 `chaeksas/bot-ui`)에 쓰면, 그 PC에서 진짜 Bot UI를 띄웠을 때 시험이 남긴
    주소·이름으로 뜬다 (이슈 #3에서 실제로 그랬다). `CHK_BOT_UI__DATA_DIR`는 설정이 읽는 덮어쓰기다.
    """
    path = tmp_path_factory.mktemp("bot-ui-data")
    monkeypatch.setenv("CHK_BOT_UI__DATA_DIR", str(path))
    yield path


class FakeAutostart:
    """작업 스케줄러·`.desktop` 대신 기록만. 시험이 그 PC의 자동 시작을 바꾸지 않게.

    `fail`을 주면 `enable`·`disable`이 그 글로 `RuntimeError`를 낸다 (권한 없는 PC 흉내).
    """

    reason = ""

    def __init__(self, *, enabled: bool = False, fail: str | None = None) -> None:
        self._enabled = enabled
        self.fail = fail
        self.calls: list[str] = []

    @property
    def available(self) -> bool:
        return True

    def enabled(self) -> bool:
        return self._enabled

    def enable(self) -> None:
        self.calls.append("enable")
        if self.fail:
            raise RuntimeError(self.fail)
        self._enabled = True

    def disable(self) -> None:
        self.calls.append("disable")
        if self.fail:
            raise RuntimeError(self.fail)
        self._enabled = False


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
