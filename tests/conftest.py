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


@pytest.fixture(autouse=True)
def _studio_data_dir_is_temporary(tmp_path_factory: pytest.TempPathFactory, monkeypatch: Any) -> Iterator[Path]:
    """**어느 시험도 개발 PC의 Studio 데이터 폴더를 쓰지 않는다.** (위 Bot UI와 같은 까닭)

    STU-15가 끈 확장 목록을 `settings.json`에 **그 자리에서** 저장하면서 시험이 설정 파일을 쓰게
    됐다 (ADR-0043). 막지 않으면 그 PC에서 진짜 Studio를 띄웠을 때 시험이 꺼 둔 확장이 빠진 채로
    뜬다 — Bot UI에서 이미 겪은 이슈 #3과 같은 꼴이다.
    """
    path = tmp_path_factory.mktemp("studio-data")
    monkeypatch.setenv("CHK_STUDIO__DATA_DIR", str(path))
    yield path


@pytest.fixture(autouse=True)
def _no_real_outbound_catalog_call(monkeypatch: Any) -> None:
    """**시험은 안 듣는 포트로 전화하지 않는다** (`docs/04-setup.md` §7).

    STU-13 편집기는 열릴 때 공개 카탈로그를 읽는다 (C9). 주소는 **확장 정의**가 주므로
    (`service.base_url`) Qt 단위 시험에서도 값이 차 있고, 그 포트에는 아무도 없다 — 그래서
    창을 띄우는 시험마다 **진짜 TCP 연결을 시도**했다. Windows CI에서 그 자리가
    `Fatal Python error: Aborted`로 죽었다 (Qt·소켓·스레드가 한 프로세스에 쌓인 채였다).

    **클라이언트를 끼운 시험은 그대로 간다** — 가짜를 준 시험(`client=`)은 진짜 코드를 돌고,
    끼우지 않은 자리만 「오프라인」으로 떨어진다(주소를 모를 때와 같은 상태다). 그 상태는
    편집기가 다루도록 만들어져 있다.
    """
    from chaeksas.ext.ui_automation.client.catalog import Catalog

    real = Catalog.reload

    def guarded(self: Catalog) -> bool:
        # **주소가 있고 클라이언트가 없을 때만** 막는다 — 그 조합이 진짜로 거는 자리다.
        # 주소가 없는 길은 진짜 코드가 그대로 돌아야 한다 (「주소를 모릅니다」를 시험이 본다).
        if self.client is None and self.base_url:
            self.offline = True
            self.last_error = "시험에서는 바깥으로 전화하지 않습니다"
            return False
        return bool(real(self))

    monkeypatch.setattr(Catalog, "reload", guarded)


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
