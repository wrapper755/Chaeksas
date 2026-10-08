"""설정·PC 고유값·비밀·자동 시작 — OS가 갈리는 자리 (CLAUDE.md §5, ADR-0011·0023).

Windows CI에서도 이 파일이 돈다. **OS 전용 길은 그 OS에서만** 실제로 실행되고, 나머지는
「무엇을 부르려 하는가」를 본다 (`schtasks` 인자·작업 XML 등).
"""

from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from chaeksas.bot_ui import autostart as autostart_module
from chaeksas.bot_ui import machine
from chaeksas.bot_ui.credentials import ENV_CENTER_API_KEY, Credentials, SecretsUnavailable
from chaeksas.bot_ui.settings import (
    DEFAULT_QUEUE_MAX,
    DEFAULT_WORKER_PORT,
    START_ALWAYS,
    RuntimeSettings,
    ServiceKeyRef,
    Settings,
)

# ─────────────────────────── 설정 ───────────────────────────


def test_defaults_come_from_the_setup_doc() -> None:
    """포트·대기열 기본값의 원본은 `docs/04-setup.md` §6이다 (코드에 숫자를 흘리지 않는다)."""
    found = Settings()
    assert found.queue_max == DEFAULT_QUEUE_MAX == 20
    assert found.runtime("worker") is not None
    assert found.runtime("worker").port == DEFAULT_WORKER_PORT == 8899  # type: ignore[union-attr]
    assert found.autostart is True and found.signed_only is True


def test_settings_round_trip_through_a_file(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    before = Settings(
        center_url="http://center:8800",
        name="재무팀 PC-03",
        queue_max=5,
        runtimes=(RuntimeSettings(runtime_id="worker", port=9000, start=START_ALWAYS),),
    )
    before.save(path)
    after = Settings.load(path)
    assert (after.center_url, after.name, after.queue_max) == ("http://center:8800", "재무팀 PC-03", 5)
    assert after.runtime("worker").start == START_ALWAYS  # type: ignore[union-attr]
    # UTF-8로 쓴다 (Windows 기본 인코딩은 cp949다 — CLAUDE.md §5).
    assert "재무팀 PC-03" in path.read_text(encoding="utf-8")


def test_a_broken_settings_file_falls_back_to_defaults(tmp_path: Path) -> None:
    """설정이 깨졌다고 앱이 안 뜨면 고칠 길이 없다 — 기본값으로 뜨고 BUI-03을 보인다."""
    path = tmp_path / "settings.json"
    path.write_text("{고장", encoding="utf-8")
    assert Settings.load(path).queue_max == DEFAULT_QUEUE_MAX


def test_environment_variables_win(monkeypatch: Any, tmp_path: Path) -> None:
    """`CHK_BOT_UI__*`가 파일을 덮는다 (ADR-0011 — 중첩은 `__`)."""
    path = tmp_path / "settings.json"
    Settings(center_url="http://file:8800", queue_max=5).save(path)
    monkeypatch.setenv("CHK_BOT_UI__CENTER__URL", "http://env:8800")
    monkeypatch.setenv("CHK_BOT_UI__QUEUE__MAX", "7")
    monkeypatch.setenv("CHK_BOT_UI__WORKER__PORT", "9100")
    monkeypatch.setenv("CHK_BOT_UI__AUTOSTART", "false")

    found = Settings.load(path)
    assert (found.center_url, found.queue_max) == ("http://env:8800", 7)
    assert found.runtime("worker").port == 9100  # type: ignore[union-attr]
    assert found.autostart is False


def test_saving_never_writes_a_secret(tmp_path: Path) -> None:
    """설정 파일에는 **값이 없다**. 키 참조 이름(BUI-10)은 비밀이 아니다 (ADR-0013 §3).

    이름은 들어가야 한다 — 그것으로 OS 비밀 저장소를 찾는다. 들어가면 안 되는 것은 값이다.
    """
    made = replace(Settings(), service_keys=(ServiceKeyRef(ref="finance-invoice", app_id="erp-finance"),))
    path = made.save(tmp_path / "settings.json")
    text = path.read_text(encoding="utf-8")
    assert "finance-invoice" in text
    assert "chk_" not in text
    for word in ("api_key", "secret", "token", "password"):
        assert word not in text.lower()


# ─────────────────────────── PC 고유값 ───────────────────────────


def test_machine_id_is_a_hash_not_the_raw_value(tmp_path: Path) -> None:
    """C4 — **원값은 보내지 않는다.** SHA-256만 보낸다."""
    found = machine.machine_id(tmp_path)
    assert len(found) == 64 and found == found.lower()
    raw = machine.raw_machine_value(tmp_path)
    assert raw not in found


def test_machine_id_is_stable(tmp_path: Path) -> None:
    """같은 PC면 같은 값이다 — 아니면 키 묶기가 매번 깨진다 (C4)."""
    assert machine.machine_id(tmp_path) == machine.machine_id(tmp_path)


def test_a_missing_os_value_falls_back_to_a_stored_random(tmp_path: Path, monkeypatch: Any) -> None:
    """OS 고유값을 못 읽어도 **다시 켜면 같은 값**이어야 한다 (파일에 적어 둔다)."""
    monkeypatch.setattr(machine, "_linux_machine_id", lambda: None)
    monkeypatch.setattr(machine, "_windows_machine_guid", lambda: None)
    monkeypatch.setattr(machine, "_macos_platform_uuid", lambda: None)

    first = machine.raw_machine_value(tmp_path)
    assert (tmp_path / machine.FALLBACK_NAME).exists()
    assert machine.raw_machine_value(tmp_path) == first


def test_os_label_and_pc_name_are_filled() -> None:
    label = machine.os_label()
    assert label and " " not in label
    if sys.platform == "win32":  # pragma: no cover - OS 분기
        assert label.startswith("windows")
    assert machine.pc_name()


# ─────────────────────────── 비밀 ───────────────────────────


def test_environment_variable_can_stand_in_for_the_keyring(monkeypatch: Any) -> None:
    """헤드리스 CI·개발에서는 환경변수로 준다 (평소에는 OS 비밀 저장소)."""
    monkeypatch.setenv(ENV_CENTER_API_KEY, "chk_ctr_fromenv")
    assert Credentials().center_api_key() == "chk_ctr_fromenv"


def test_saving_without_a_store_fails_loudly(monkeypatch: Any) -> None:
    """저장소가 없으면 **분명히 실패한다** — 평문으로 흘리지 않는다."""
    found = Credentials()
    monkeypatch.setattr(found, "_keyring", lambda: None)
    with pytest.raises(SecretsUnavailable, match="비밀 저장소"):
        found.set_center_api_key("chk_ctr_x")


def test_service_app_keys_are_kept_by_reference_name(monkeypatch: Any) -> None:
    """ADR-0013 §3 — BPM 프로세스 속성에는 **참조 이름**만 있고 값은 여기 있다."""
    from conftest import FakeCredentials  # noqa: PLC0415

    found = FakeCredentials()
    found.set_service_app_key("finance-invoice", "chk_svc_abc")
    assert found.service_app_key("finance-invoice") == "chk_svc_abc"
    assert found.service_app_key("없는-참조") is None


# ─────────────────────────── 자동 시작 ───────────────────────────


def test_the_launch_command_can_start_the_app() -> None:
    """등록할 명령은 `python -m chaeksas.bot_ui`다 (묶으면 실행 파일 하나)."""
    command = autostart_module.launch_command()
    assert command[1:] == ["-m", "chaeksas.bot_ui"]
    if sys.platform == "win32":
        # 콘솔 창 없이 뜨게 `pythonw.exe` (이슈 #3) — 같은 가상환경의 것이다.
        assert command[0] == str(Path(sys.executable).with_name("pythonw.exe"))
    else:
        assert command[0] == sys.executable


TASK_NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


def task_xml(command: list[str], user: str = "PC-03\\홍길동") -> Any:
    found = autostart_module.WindowsTaskScheduler(command=command, user=user)
    return ET.fromstring(found.task_xml().split("?>", 1)[1])  # 선언의 encoding="UTF-16"은 문자열에 안 맞는다


def test_windows_task_scheduler_arguments() -> None:
    """실제 등록은 Windows에서만 — 여기서는 **무엇을 부르려 하는가**를 본다 (ADR-0023)."""
    found = autostart_module.WindowsTaskScheduler(command=["C:\\Program Files\\Chaeksas\\bot-ui.exe"])
    args = found.create_args(Path("task.xml"))
    assert args == ["/Create", "/TN", autostart_module.TASK_NAME, "/XML", "task.xml", "/F"]
    # `/SC ONLOGON`은 「모든 사용자의 로그온」이라 관리자가 아니면 거부된다 (이슈 #3).
    assert "/SC" not in args and "/RL" not in args


def test_the_task_starts_at_this_users_logon_without_elevation() -> None:
    """일반 권한으로 등록되려면 트리거와 실행 사용자가 **이 사용자**여야 한다 (이슈 #3)."""
    root = task_xml(["C:\\Program Files\\Chaeksas\\bot-ui.exe"])
    assert root.findtext("t:Triggers/t:LogonTrigger/t:UserId", namespaces=TASK_NS) == "PC-03\\홍길동"
    principal = root.find("t:Principals/t:Principal", TASK_NS)
    assert principal is not None
    assert principal.findtext("t:UserId", namespaces=TASK_NS) == "PC-03\\홍길동"
    assert principal.findtext("t:LogonType", namespaces=TASK_NS) == "InteractiveToken"
    # 권한을 올리지 않는다 (UAC 창이 뜨지 않게).
    assert principal.findtext("t:RunLevel", namespaces=TASK_NS) == "LeastPrivilege"


def test_the_task_is_not_stopped_by_time_or_battery() -> None:
    """상주 앱이다 — 72시간 기본 제한, 배터리 조건을 끈다 (ADR-0023)."""
    settings = task_xml(["C:\\bot-ui.exe"]).find("t:Settings", TASK_NS)
    assert settings is not None
    assert settings.findtext("t:ExecutionTimeLimit", namespaces=TASK_NS) == "PT0S"
    assert settings.findtext("t:DisallowStartIfOnBatteries", namespaces=TASK_NS) == "false"
    assert settings.findtext("t:StopIfGoingOnBatteries", namespaces=TASK_NS) == "false"
    assert settings.findtext("t:MultipleInstancesPolicy", namespaces=TASK_NS) == "IgnoreNew"


def test_windows_arguments_quote_a_command_with_spaces() -> None:
    root = task_xml(["C:\\Program Files\\Py & Co\\python.exe", "-m", "chaeksas.bot_ui"])
    assert root.findtext("t:Actions/t:Exec/t:Command", namespaces=TASK_NS) == "C:\\Program Files\\Py & Co\\python.exe"
    assert root.findtext("t:Actions/t:Exec/t:Arguments", namespaces=TASK_NS) == "-m chaeksas.bot_ui"


def test_an_installed_exe_has_no_arguments_element() -> None:
    root = task_xml(["C:\\Program Files\\Chaeksas\\bot-ui.exe"])
    assert root.find("t:Actions/t:Exec/t:Arguments", TASK_NS) is None


@pytest.mark.skipif(
    sys.platform != "win32" or not os.environ.get("CHK_TEST_AUTOSTART"),
    reason="Windows 실기 확인 — `CHK_TEST_AUTOSTART=1`로 켠다 (작업 스케줄러를 실제로 건드린다)",
)
def test_windows_autostart_really_registers() -> None:  # pragma: no cover - 실기에서만
    """**실제로** 작업을 등록하고 지운다.

    기본으로 돌리지 않는다 — CI 러너는 작업 등록이 막혀 있을 수 있고(실제로 막혔다), 시험이
    그 PC의 설정을 바꾸게 두어서도 안 된다. Windows PC에서 확인할 때 `CHK_TEST_AUTOSTART=1`로 켠다.
    """
    found = autostart_module.WindowsTaskScheduler(task_name="Chaeksas Bot UI 시험")
    try:
        found.enable()
        assert found.enabled()
    finally:
        found.disable()
    assert not found.enabled()


def test_linux_autostart_writes_a_desktop_file(tmp_path: Path) -> None:
    found = autostart_module.FreedesktopAutostart(directory=tmp_path, command=["/usr/bin/chk-bot-ui"])
    assert not found.enabled()
    found.enable()
    assert found.enabled()
    text = found.path.read_text(encoding="utf-8")
    assert "Exec=/usr/bin/chk-bot-ui" in text
    assert "Type=Application" in text
    found.disable()
    assert not found.enabled()


def test_the_os_picker_gives_something_that_answers(monkeypatch: Any) -> None:
    found = autostart_module.autostart()
    # 어느 OS에서든 물어볼 수 있다 (모르는 OS면 「할 수 없다」고 답한다).
    assert isinstance(found.enabled(), bool)
    assert found.available == (sys.platform == "win32" or sys.platform.startswith("linux"))


# ─────────────────────── 모델·파일 (BUI-03, 조각 4c) ───────────────────────


def test_the_model_address_is_saved_but_the_key_is_not(tmp_path: Path) -> None:
    """**키는 설정 파일에 들어가지 않는다** (CLAUDE.md §5) — OS 비밀 저장소로 간다."""
    settings = replace(Settings(), llm_base_url="http://localhost:11434", llm_model="qwen2.5:7b")
    path = settings.save(tmp_path / "settings.json")
    raw = path.read_text(encoding="utf-8")

    assert "localhost:11434" in raw and "qwen2.5:7b" in raw
    assert "api_key" not in raw and "llm_api_key" not in raw


def test_readable_dirs_survive_a_restart(tmp_path: Path) -> None:
    """Bot이 읽을 수 있는 곳은 **여기 적은 폴더뿐**이다 (ADR-0026)."""
    folders = (tmp_path / "공유", tmp_path / "청구서")
    path = replace(Settings(), readable_dirs=folders).save(tmp_path / "settings.json")

    again = Settings.load(path)
    assert again.readable_dirs == folders


def test_without_a_model_address_the_default_is_empty() -> None:
    """**비우면 AI 태스크가 돌지 않는다** — 주소를 지어내지 않는다 (ADR-0027)."""
    assert Settings().llm_base_url == ""


def test_the_model_key_goes_to_the_secret_store_and_an_env_var_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """읽기는 환경변수가 먼저다 (개발·CI). 실행기에는 환경변수로 건넨다."""
    from chaeksas.bot_ui.credentials import ENV_LLM_API_KEY, Credentials

    monkeypatch.setenv(ENV_LLM_API_KEY, "sk-from-env")
    assert Credentials().llm_api_key() == "sk-from-env"
