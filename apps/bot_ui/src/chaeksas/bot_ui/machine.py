"""이 PC를 가리키는 값 — `machine_id`·OS 표시·PC 이름 (C4 `RegisterRequest`).

**원값은 보내지 않는다.** PC 고유값의 SHA-256만 보낸다 (C4) — Center 데이터가 새도 PC를
되짚을 수 없게.

| | 고유값 출처 |
| --- | --- |
| Windows | 레지스트리 `HKLM\\SOFTWARE\\Microsoft\\Cryptography` → `MachineGuid` |
| Linux | `/etc/machine-id` (없으면 `/var/lib/dbus/machine-id`) |
| macOS | `IOPlatformUUID` |

어느 것도 못 읽으면 **데이터 폴더에 한 번 만들어 둔 무작위 값**을 쓴다. 그래야 PC를 다시 켜도
같은 `bot_ui_id`로 남는다 (C4 키 묶기).
"""

from __future__ import annotations

import hashlib
import logging
import platform
import secrets
import socket
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)

#: 못 읽었을 때 쓰는 대체 값을 적어 두는 파일 이름 (`settings.data_dir()` 안).
FALLBACK_NAME = "machine-id"


def _windows_machine_guid() -> str | None:  # pragma: no cover - OS 분기
    # `sys.platform` 검사 안에서 import한다 — 그래야 다른 OS에서 타입 검사가 winreg를 찾지 않는다.
    if sys.platform != "win32":
        return None
    import winreg  # noqa: PLC0415

    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            # 32비트 프로세스에서도 64비트 뷰를 본다 (PyInstaller 빌드가 32비트일 수 있다).
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        ) as key:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
    except OSError as e:
        log.warning("MachineGuid를 읽지 못했다: %s", e)
        return None
    return str(value).strip() or None


def _linux_machine_id() -> str | None:
    for path in (Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id")):
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value
    return None


def _macos_platform_uuid() -> str | None:  # pragma: no cover - OS 분기
    try:
        out = subprocess.run(  # noqa: S603 — 인자 리스트, shell 없음
            ["/usr/sbin/ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.stdout.splitlines():
        if "IOPlatformUUID" in line:
            return line.split('"')[-2].strip() or None
    return None


def raw_machine_value(data_dir: Path) -> str:
    """이 PC의 고유값 (해시 전). **밖으로 내보내지 않는다.**"""
    found = None
    if sys.platform == "win32":  # pragma: no cover - OS 분기
        found = _windows_machine_guid()
    elif sys.platform == "darwin":  # pragma: no cover - OS 분기
        found = _macos_platform_uuid()
    else:
        found = _linux_machine_id()
    if found:
        return found

    # 대체 값: 한 번 만들어 적어 두고 계속 쓴다.
    path = data_dir / FALLBACK_NAME
    try:
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except OSError:
        pass
    made = secrets.token_hex(16)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(made + "\n", encoding="utf-8", newline="\n")
    log.warning("PC 고유값을 읽지 못해 %s에 새로 만들었다", path)
    return made


def machine_id(data_dir: Path) -> str:
    """C4 `machine_id` — 고유값의 SHA-256 (64자 16진수)."""
    return hashlib.sha256(raw_machine_value(data_dir).encode("utf-8")).hexdigest()


def os_label() -> str:
    """C4 `os` — 예: `windows-11-23H2`, `ubuntu-24.04`, `linux-6.18`."""
    if sys.platform == "win32":  # pragma: no cover - OS 분기
        release = platform.win32_ver()[0] or platform.release()
        build = platform.win32_edition() if hasattr(platform, "win32_edition") else ""
        parts = ["windows", release] + ([build] if build else [])
        return "-".join(p.lower().replace(" ", "") for p in parts if p)
    if sys.platform == "darwin":  # pragma: no cover - OS 분기
        return f"macos-{platform.mac_ver()[0]}"
    try:
        info = platform.freedesktop_os_release()
        name = info.get("ID", "linux")
        version = info.get("VERSION_ID", "")
        return f"{name}-{version}" if version else name
    except (OSError, AttributeError):  # pragma: no cover - 배포판 정보가 없는 경우
        return f"linux-{platform.release().split('-')[0]}"


def pc_name() -> str:
    """표시 이름의 기본값 (C4 `name`). 못 읽으면 `unknown-pc`."""
    try:
        found = socket.gethostname().strip()
    except OSError:  # pragma: no cover - 방어
        found = ""
    return found or "unknown-pc"


__all__ = ["FALLBACK_NAME", "machine_id", "os_label", "pc_name", "raw_machine_value"]
