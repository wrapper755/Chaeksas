"""서버 실행기의 비밀 폴더 (ADR-0100) — OS 비밀 저장소가 없는 컨테이너에서 받은 키를 둘 자리."""

from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

import pytest

from chaeksas.server_runner import secret_file
from chaeksas.server_runner.credentials import Credentials


def test_set_get_delete_round_trip(tmp_path: Path) -> None:
    store = secret_file.SecretFile(tmp_path / "secrets")
    assert store.get_password("svc", "a") is None
    store.set_password("svc", "a", "one")
    store.set_password("other", "a", "two")
    assert store.get_password("svc", "a") == "one"
    assert store.get_password("other", "a") == "two"  # 서비스 이름마다 나뉜다
    store.delete_password("svc", "a")
    store.delete_password("svc", "a")  # 없는 것을 지워도 오류가 아니다
    assert store.get_password("svc", "a") is None
    assert json.loads(store.path.read_text(encoding="utf-8")) == {"other": {"a": "two"}}


@pytest.mark.skipif(sys.platform == "win32", reason="Windows에는 권한 비트가 없다")
def test_only_the_owner_can_read(tmp_path: Path) -> None:
    store = secret_file.SecretFile(tmp_path / "secrets")
    store.set_password("svc", "a", "one")
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(store.folder.stat().st_mode) == 0o700


def test_a_broken_file_is_not_overwritten(tmp_path: Path) -> None:
    """받은 키를 조용히 잃으면 다시 승인해야 한다 — 깨진 파일은 덮지 않고 멈춘다."""
    store = secret_file.SecretFile(tmp_path)
    store.path.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError):
        store.set_password("svc", "a", "one")
    assert store.path.read_text(encoding="utf-8") == "[1, 2]"


def test_off_unless_the_operator_names_a_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(secret_file.ENV_SECRETS_DIR, raising=False)
    assert secret_file.from_env() is None


def test_credentials_use_the_folder_when_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """적어 두면 등록·회전·서비스 앱 키가 모두 그 자리를 쓴다 — 부르는 쪽은 그대로다."""
    monkeypatch.setenv(secret_file.ENV_SECRETS_DIR, str(tmp_path / "secrets"))
    monkeypatch.delenv("CHK_SERVER_RUNNER__CENTER_API_KEY", raising=False)
    found = Credentials()
    assert found.available
    found.set_enroll_secret("private")
    found.set_center_api_key("chk_key")
    again = Credentials()  # 다시 떠도 남는다 (볼륨)
    assert again.enroll_secret() == "private"
    assert again.center_api_key() == "chk_key"
    assert not again.center_key_from_env()  # 환경변수 키가 아니므로 회전을 받는다
