"""시험이 함께 쓰는 것. 여기 있는 것은 **제품 코드가 아니다.**"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from ci_scope import SERVER_SIDE

from chaeksas.bot_ui.credentials import Credentials


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """서버 쪽 파일의 시험에 `server` 표시를 붙인다 — Windows CI가 뺀다 (`ci_scope.py`, ADR-0104)."""
    for item in items:
        if item.path.stem in SERVER_SIDE:
            item.add_marker(pytest.mark.server)


@pytest.fixture(autouse=True)
def _bot_ui_data_dir_is_temporary(tmp_path_factory: pytest.TempPathFactory, monkeypatch: Any) -> Iterator[Path]:
    """**어느 시험도 개발 PC의 PC 실행기 데이터 폴더를 쓰지 않는다.**

    기본 위치(Windows `%LOCALAPPDATA%` 밑 `chaeksas/bot-ui`)에 쓰면, 그 PC에서 진짜 PC 실행기를 띄웠을 때 시험이 남긴
    주소·이름으로 뜬다 (이슈 #3에서 실제로 그랬다). `CHK_BOT_UI__DATA_DIR`는 설정이 읽는 덮어쓰기다.
    """
    path = tmp_path_factory.mktemp("bot-ui-data")
    monkeypatch.setenv("CHK_BOT_UI__DATA_DIR", str(path))
    yield path


@pytest.fixture(autouse=True)
def _studio_data_dir_is_temporary(tmp_path_factory: pytest.TempPathFactory, monkeypatch: Any) -> Iterator[Path]:
    """**어느 시험도 개발 PC의 Studio 데이터 폴더를 쓰지 않는다.** (위 PC 실행기와 같은 까닭)

    STU-15가 끈 확장 목록을 `settings.json`에 **그 자리에서** 저장하면서 시험이 설정 파일을 쓰게
    됐다 (ADR-0043). 막지 않으면 그 PC에서 진짜 Studio를 띄웠을 때 시험이 꺼 둔 확장이 빠진 채로
    뜬다 — PC 실행기에서 이미 겪은 이슈 #3과 같은 꼴이다.
    """
    path = tmp_path_factory.mktemp("studio-data")
    monkeypatch.setenv("CHK_STUDIO__DATA_DIR", str(path))
    yield path


@pytest.fixture(autouse=True)
def _admin_data_dir_is_temporary(tmp_path_factory: pytest.TempPathFactory, monkeypatch: Any) -> Iterator[Path]:
    """**어느 시험도 개발 PC의 Admin 키 폴더를 쓰지 않는다.** (위 PC 실행기와 같은 까닭)

    한 시험이 없는 환경변수 이름(`CHK_ADMIN__HOME`)으로 돌려 놓은 탓에 돌릴 때마다 진짜 폴더에
    「첫 키」가 두 개씩 쌓였다 — Admin이 `--key`로 열두 개 중 하나를 골라야 했고, 그 키들의 암호는
    시험의 것이라 아무도 쓸 수 없었다. 파일마다 덮어쓰는 시험은 그대로 돈다(나중 것이 이긴다).
    """
    path = tmp_path_factory.mktemp("admin-data")
    monkeypatch.setenv("CHK_ADMIN__DATA_DIR", str(path))
    yield path


@pytest.fixture(autouse=True)
def _keyring_is_in_memory() -> Iterator[None]:
    """**어느 시험도 개발 PC의 OS 비밀 저장소를 읽거나 쓰지 않는다.** (위 데이터 폴더와 같은 까닭)

    시나리오 3 현장 리허설에서 사람이 Studio에 넣은 Center 키가 Windows 자격 증명 관리자에 남자,
    「설정이 없으면 …」을 보는 Studio 시험 둘이 그 키를 읽어 그 PC에서만 깨졌다(CI에는 키가 없어
    지나갔다). 그래서 시험 동안은 `keyring`의 저장소를 **메모리 하나로** 바꿔 끼운다 — Studio·PC 실행기·
    서버 실행기 모두 이것을 거친다. 「저장소가 없다」를 보는 시험은 `_keyring`을 따로 갈아 끼우므로
    그대로 돈다.
    """
    try:
        import keyring
        from keyring.backend import KeyringBackend
        from keyring.errors import PasswordDeleteError
    except ImportError:  # pragma: no cover - keyring이 없는 환경
        yield
        return

    class MemoryKeyring(KeyringBackend):
        priority = 1

        def __init__(self) -> None:
            super().__init__()  # type: ignore[no-untyped-call]
            self.values: dict[tuple[str, str], str] = {}

        def get_password(self, service: str, username: str) -> str | None:
            return self.values.get((service, username))

        def set_password(self, service: str, username: str, password: str) -> None:
            self.values[(service, username)] = password

        def delete_password(self, service: str, username: str) -> None:
            if self.values.pop((service, username), None) is None:
                raise PasswordDeleteError(f"{service}/{username}이 없다")

    before = keyring.get_keyring()
    keyring.set_keyring(MemoryKeyring())
    try:
        yield
    finally:
        keyring.set_keyring(before)


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
