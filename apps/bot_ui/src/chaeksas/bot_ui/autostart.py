"""로그인할 때 자동 시작 (BUI-03 「실행」, ADR-0023).

OS마다 자리가 다르니 **인터페이스 뒤에 두고 구현을 나눈다** (CLAUDE.md §5).

| OS | 방법 | 왜 |
| --- | --- | --- |
| Windows | **작업 스케줄러** (`schtasks`, `ONLOGON`) | 시작 폴더·Run 키는 UAC 문제가 있다 (ADR-0023) |
| Linux | `~/.config/autostart/*.desktop` (XDG) | 데스크톱 세션이 읽는 표준 자리 |
| macOS | 아직 없다 | 지원 OS가 아니다 (launchd는 나중) |

**자동 시작은 로그인 세션에서 돈다** — Windows 서비스 모드는 나중에 검토다 (BUI 설계서).
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)

#: 작업 스케줄러·`.desktop`에서 쓰는 이름. 바꾸면 **옛 등록이 남는다.**
TASK_NAME = "Chaeksas Bot UI"
DESKTOP_FILE = "chaeksas-bot-ui.desktop"


def launch_command() -> list[str]:
    """Bot UI를 띄우는 명령. 설치 파일(PyInstaller)로 묶였으면 그 실행 파일 하나다 (ADR-0024)."""
    if getattr(sys, "frozen", False):  # pragma: no cover - 묶인 뒤에만
        return [sys.executable]
    return [sys.executable, "-m", "chaeksas.bot_ui"]


class Autostart(Protocol):
    """자동 시작 등록. 상태를 묻고, 켜고, 끈다."""

    @property
    def available(self) -> bool:
        """이 OS에서 할 수 있나."""
        ...

    def enabled(self) -> bool: ...

    def enable(self) -> None: ...

    def disable(self) -> None: ...


class NoAutostart:
    """할 수 없는 OS용. 화면은 칸을 끄고 이유를 보인다 (U3)."""

    reason = "이 OS에서는 자동 시작을 설정할 수 없습니다"

    @property
    def available(self) -> bool:
        return False

    def enabled(self) -> bool:
        return False

    def enable(self) -> None:
        log.info("자동 시작: %s", self.reason)

    def disable(self) -> None:
        pass


class WindowsTaskScheduler:
    """Windows 작업 스케줄러 (ADR-0023). `schtasks`를 **인자 리스트로** 부른다."""

    reason = ""

    def __init__(self, task_name: str = TASK_NAME, command: list[str] | None = None) -> None:
        self.task_name = task_name
        self.command = command or launch_command()

    @property
    def available(self) -> bool:
        return sys.platform == "win32"

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 — 인자 리스트, shell 없음
            ["schtasks", *args],
            capture_output=True,
            text=True,
            # Windows 콘솔 기본 코드페이지에서 한글 출력이 깨질 수 있다 — 쓰지 않고 코드만 본다.
            errors="replace",
            check=False,
        )

    def create_args(self) -> list[str]:
        """만들 때 쓰는 인자. 시험이 이것만 본다 (실제로 등록하지 않고).

        `/RL LIMITED`: 권한을 올리지 않는다 (UAC 창이 뜨지 않게).
        `/F`: 이미 있으면 덮어쓴다 — 명령이 바뀌었을 수 있다 (새 버전을 깔았을 때).
        """
        # 인자가 있는 명령은 한 문자열로 묶어 넘긴다 (`/TR`는 문자열 하나를 받는다).
        target = self.command[0] if len(self.command) == 1 else subprocess.list2cmdline(self.command)
        return ["/Create", "/TN", self.task_name, "/TR", target, "/SC", "ONLOGON", "/RL", "LIMITED", "/F"]

    def enabled(self) -> bool:
        if not self.available:
            return False
        return self._run(["/Query", "/TN", self.task_name]).returncode == 0

    def enable(self) -> None:
        if not self.available:  # pragma: no cover - OS 분기
            return
        done = self._run(self.create_args())
        if done.returncode != 0:  # pragma: no cover - 권한 문제
            raise RuntimeError(f"자동 시작을 등록하지 못했습니다: {done.stderr.strip() or done.stdout.strip()}")

    def disable(self) -> None:
        if not self.available:  # pragma: no cover - OS 분기
            return
        self._run(["/Delete", "/TN", self.task_name, "/F"])


class FreedesktopAutostart:
    """Linux 데스크톱 세션 — `~/.config/autostart`에 `.desktop` 파일 하나."""

    reason = ""

    def __init__(self, directory: Path | None = None, command: list[str] | None = None) -> None:
        import platformdirs  # noqa: PLC0415

        self.directory = directory or Path(platformdirs.user_config_dir()) / "autostart"
        self.command = command or launch_command()

    @property
    def available(self) -> bool:
        return sys.platform.startswith("linux")

    @property
    def path(self) -> Path:
        return self.directory / DESKTOP_FILE

    def contents(self) -> str:
        exec_line = " ".join(self.command)
        return (
            "[Desktop Entry]\n"
            "Type=Application\n"
            f"Name={TASK_NAME}\n"
            f"Exec={exec_line}\n"
            "Terminal=false\n"
            "X-GNOME-Autostart-enabled=true\n"
        )

    def enabled(self) -> bool:
        return self.path.exists()

    def enable(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path.write_text(self.contents(), encoding="utf-8", newline="\n")

    def disable(self) -> None:
        self.path.unlink(missing_ok=True)


def autostart() -> Autostart:
    """이 OS에 맞는 구현. 모르는 OS면 「할 수 없다」고 말하는 것을 준다."""
    if sys.platform == "win32":  # pragma: no cover - OS 분기
        return WindowsTaskScheduler()
    if sys.platform.startswith("linux"):
        return FreedesktopAutostart()
    return NoAutostart()  # pragma: no cover - OS 분기


__all__ = [
    "DESKTOP_FILE",
    "TASK_NAME",
    "Autostart",
    "FreedesktopAutostart",
    "NoAutostart",
    "WindowsTaskScheduler",
    "autostart",
    "launch_command",
]
