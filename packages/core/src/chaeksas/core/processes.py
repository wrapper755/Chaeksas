"""자식 프로세스 관리 — **공통 헬퍼 한 곳** (CLAUDE.md §5, ADR-0023).

Bot UI가 Worker 프로세스와 실행기를 띄우고 감시·재시작·강제 종료한다. 그 OS 차이를 여기서만 다룬다.

| | Windows (주 환경) | Linux·macOS |
| --- | --- | --- |
| 묶기 | **Job Object** + `CREATE_NEW_PROCESS_GROUP` | 새 세션 (`setsid`) |
| 곱게 멈추기 | `CTRL_BREAK_EVENT` → 안 되면 `TerminateProcess` | 프로세스 그룹에 `SIGTERM` |
| 끝까지 멈추기 | Job 핸들을 닫으면 **트리 전체**가 죽는다 | 그룹에 `SIGKILL` |

`os.killpg`·그룹 신호는 Windows에 없다. 그래서 「프로세스 하나를 죽였는데 그 자식이 남는」 일을
Windows에서는 Job Object가, 그 밖에서는 프로세스 그룹이 막는다.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

#: 곱게 멈추기를 기다리는 기본 시간. 넘으면 강제 종료한다.
DEFAULT_STOP_TIMEOUT_S = 10.0
#: 다시 띄우기 사이의 기다림 (초). 연속 실패가 늘면 뒤로 간다 (지수 백오프).
RESTART_BACKOFF_S = (1.0, 2.0, 5.0, 15.0, 30.0)
#: 이만큼 연속으로 실패하면 **그만 띄운다** (상태 `stopped`). 사람이 설정을 봐야 한다.
MAX_RESTARTS = 5
#: 이 시간 넘게 살아 있었으면 「잘 돌았다」로 보고 연속 실패 수를 되돌린다.
HEALTHY_AFTER_S = 60.0

#: 자식에게 물려주는 UTF-8 입출력 설정.
#:
#: Windows에서 자식의 출력을 파일로 돌리면 그 파일의 인코딩이 **시스템 코드페이지**(cp949·cp1252)가
#: 되어, 한글을 찍는 자식이 `UnicodeEncodeError`로 죽는다 (CI의 Windows가 잡아 줬다). 우리 자식
#: (Worker·실행기)은 한글로 말하므로 UTF-8을 물려준다. 파이썬이 아닌 자식은 이 값을 무시한다.
UTF8_ENV = {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}


class ProcessError(RuntimeError):
    """자식 프로세스를 띄우지 못했다."""


def _windows_job() -> int | None:
    """자식을 담을 Job Object를 만든다. **닫으면 그 안의 프로세스가 모두 죽는다.**

    Windows 밖에서는 `None`. 만들지 못해도 (권한·중첩 Job) `None`을 돌려주고 계속 간다 —
    묶기가 없으면 손자 프로세스가 남을 수 있지만, 그것 때문에 Bot UI가 안 뜨면 더 나쁘다.
    """
    if sys.platform != "win32":  # pragma: no cover - OS 분기
        return None
    import ctypes  # noqa: PLC0415 — Windows에서만 필요하다
    from ctypes import wintypes  # noqa: PLC0415

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):  # noqa: N801 — Win32 이름 그대로
        _fields_ = [
            ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
            ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IO_COUNTERS(ctypes.Structure):  # noqa: N801
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):  # noqa: N801
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    job_object_limit_kill_on_job_close = 0x2000
    extended_limit_information = 9

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.CreateJobObjectW(None, None)
    if not handle:
        log.warning("Job Object를 만들지 못했다 (오류 %s) — 트리 종료 없이 간다", ctypes.get_last_error())
        return None

    limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    limits.BasicLimitInformation.LimitFlags = job_object_limit_kill_on_job_close
    ok = kernel32.SetInformationJobObject(
        handle, extended_limit_information, ctypes.byref(limits), ctypes.sizeof(limits)
    )
    if not ok:
        log.warning("Job Object에 한도를 걸지 못했다 (오류 %s)", ctypes.get_last_error())
        kernel32.CloseHandle(handle)
        return None
    return int(handle)


def _assign_to_job(job: int, process: subprocess.Popen[bytes]) -> None:
    """자식을 Job에 넣는다. 실패해도 멈추지 않는다 (묶기만 없어진다)."""
    if sys.platform != "win32":  # pragma: no cover - OS 분기
        return
    import ctypes  # noqa: PLC0415

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    # Popen._handle은 Windows에서 프로세스 핸들이다 (공개 API가 없어 이것을 쓴다).
    handle = getattr(process, "_handle", None)
    if handle is None:  # pragma: no cover - 방어
        return
    if not kernel32.AssignProcessToJobObject(job, int(handle)):
        log.warning("자식을 Job Object에 넣지 못했다 (오류 %s)", ctypes.get_last_error())


def _close_job(job: int | None) -> None:
    """Job 핸들을 닫는다 — **그 안의 프로세스 트리가 모두 죽는다.**"""
    if job is None or sys.platform != "win32":
        return
    import ctypes  # noqa: PLC0415

    ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(job)


@dataclass
class ChildProcess:
    """자식 프로세스 하나. **인자는 리스트로** 넘긴다 (`shell=True` 금지, CLAUDE.md §5).

    `start()` → `poll()`/`alive` → `stop()`. 다시 띄우는 판단은 `Supervisor`가 한다.
    """

    args: Sequence[str]
    cwd: Path | None = None
    env: Mapping[str, str] | None = None
    #: 자식의 출력을 적을 파일. `None`이면 부모와 같은 곳으로 간다.
    log_path: Path | None = None
    name: str = "child"
    #: 자식의 입출력을 UTF-8로 맞춘다 (`UTF8_ENV`). 끄면 OS 기본 코드페이지를 쓴다.
    utf8_io: bool = True

    _process: subprocess.Popen[bytes] | None = field(default=None, init=False, repr=False)
    _job: int | None = field(default=None, init=False, repr=False)
    _log_file: IO[bytes] | None = field(default=None, init=False, repr=False)
    _started_at: float | None = field(default=None, init=False, repr=False)

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process else None

    @property
    def alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def uptime_s(self) -> float:
        return 0.0 if self._started_at is None else time.monotonic() - self._started_at

    def poll(self) -> int | None:
        """끝났으면 종료 코드, 아직 돌면 `None`."""
        return None if self._process is None else self._process.poll()

    def start(self) -> None:
        """띄운다. 이미 돌고 있으면 아무것도 하지 않는다."""
        if self.alive:
            return
        if not self.args:
            raise ProcessError("실행할 명령이 비어 있다")

        stdout: IO[bytes] | None = None
        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            # 자식의 출력은 한글일 수 있다 — 바이트로 그냥 붙인다 (인코딩은 자식이 정한다).
            self._log_file = self.log_path.open("ab")
            stdout = self._log_file

        kwargs: dict[str, Any] = {}
        if IS_WINDOWS:  # pragma: no cover - OS 분기
            # 새 프로세스 그룹: CTRL_BREAK_EVENT를 자식에게만 보낼 수 있다.
            # 콘솔 창은 띄우지 않는다 (Bot UI는 트레이 앱이다).
            kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
            )
            self._job = _windows_job()
        else:
            # 새 세션 — 부모가 받은 Ctrl+C가 자식에게 번지지 않고, 그룹째 신호를 보낼 수 있다.
            kwargs["start_new_session"] = True

        try:
            process: subprocess.Popen[bytes] = subprocess.Popen(  # noqa: S603 — 인자 리스트, shell 없음
                list(self.args),
                cwd=str(self.cwd) if self.cwd else None,
                env=self._env(),
                stdout=stdout,
                stderr=subprocess.STDOUT if stdout is not None else None,
                stdin=subprocess.DEVNULL,
                **kwargs,
            )
        except OSError as e:
            self._cleanup_log()
            _close_job(self._job)
            self._job = None
            raise ProcessError(f"{self.name}을 띄우지 못했다: {e}") from e

        self._process = process
        if self._job is not None:
            _assign_to_job(self._job, process)
        self._started_at = time.monotonic()
        log.info("%s 띄움 (pid %s)", self.name, process.pid)

    def stop(self, *, timeout_s: float = DEFAULT_STOP_TIMEOUT_S) -> int | None:
        """곱게 멈추고, 시간이 지나면 강제로. 종료 코드를 돌려준다.

        **자식의 자식까지** 정리한다 (Windows는 Job 핸들을 닫고, 그 밖에서는 그룹에 신호).
        """
        process = self._process
        if process is None:
            return None
        if process.poll() is None:
            self._signal_graceful(process)
            try:
                process.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                log.warning("%s이 %.0f초 안에 안 멈춰 강제 종료한다", self.name, timeout_s)
                self._kill(process)
                try:
                    process.wait(timeout=timeout_s)
                except subprocess.TimeoutExpired:  # pragma: no cover - 거의 없다
                    log.error("%s을 강제 종료하지 못했다 (pid %s)", self.name, process.pid)

        code = process.poll()
        _close_job(self._job)  # 트리 정리 (Windows)
        self._job = None
        self._cleanup_log()
        self._started_at = None
        return code

    def _env(self) -> dict[str, str] | None:
        """자식에게 줄 환경. UTF-8 입출력을 물려준다 (`UTF8_ENV`를 보라)."""
        if self.env is None and not self.utf8_io:
            return None
        base = dict(self.env) if self.env is not None else dict(os.environ)
        if self.utf8_io:
            base.update(UTF8_ENV)
        return base

    def _signal_graceful(self, process: subprocess.Popen[bytes]) -> None:
        if IS_WINDOWS:  # pragma: no cover - OS 분기
            try:
                # 콘솔 없는 자식에게는 닿지 않는다 — 그럼 바로 강제 종료로 간다.
                process.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
                return
            except (OSError, ValueError):
                process.terminate()
                return
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            process.terminate()

    def _kill(self, process: subprocess.Popen[bytes]) -> None:
        if IS_WINDOWS:  # pragma: no cover - OS 분기
            process.kill()
            return
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            process.kill()

    def _cleanup_log(self) -> None:
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None


@dataclass
class Supervisor:
    """자식 하나를 감시하고 **죽으면 다시 띄운다** (ADR-0023).

    상태는 C4 `WorkerState.state`와 같은 낱말을 쓴다 — 하트비트에 그대로 실린다.

    - `off` — 필요할 때 시작하기로 해 두고 아직 안 띄웠다
    - `running` / `restarting` / `stopped`(연속 실패가 한도를 넘어 그만둠)

    시간은 주입할 수 있게 두어(`monotonic`) 테스트가 기다리지 않는다.
    """

    child: ChildProcess
    max_restarts: int = MAX_RESTARTS
    backoff_s: Sequence[float] = RESTART_BACKOFF_S
    healthy_after_s: float = HEALTHY_AFTER_S

    state: str = "off"
    #: **연속** 실패 횟수 (C4 `restarts`). 오래 잘 돌면 0으로 되돌린다.
    restarts: int = 0
    last_error: str | None = None

    _retry_at: float | None = field(default=None, init=False, repr=False)
    _monotonic: object = field(default=time.monotonic, repr=False)

    def _now(self) -> float:
        return float(self._monotonic())  # type: ignore[operator]

    def start(self) -> None:
        """사람이·필요가 시작시킨다. 연속 실패 수를 되돌린다."""
        self.restarts = 0
        self.last_error = None
        self._retry_at = None
        self._start_now()

    def _start_now(self) -> None:
        try:
            self.child.start()
        except ProcessError as e:
            self.last_error = str(e)
            self.state = "stopped"
            log.error("%s", e)
            return
        self.state = "running"

    def stop(self, *, timeout_s: float = DEFAULT_STOP_TIMEOUT_S) -> None:
        """끈다. 다시 띄우지 않는다 (`off`)."""
        self.child.stop(timeout_s=timeout_s)
        self.state = "off"
        self._retry_at = None

    def tick(self) -> None:
        """주기마다 부른다 (하트비트와 같은 주기면 충분하다).

        죽었으면 백오프만큼 기다린 뒤 다시 띄우고, 한도를 넘으면 `stopped`로 둔다.
        """
        if self.state in ("off", "stopped"):
            return
        if self.child.alive:
            # 오래 잘 돌았으면 연속 실패를 잊는다 (몇 달 뒤의 한 번이 한도를 채우지 않게).
            if self.restarts and self.child.uptime_s >= self.healthy_after_s:
                self.restarts = 0
            self.state = "running"
            return

        code = self.child.poll()
        now = self._now()
        if self._retry_at is None:
            self.restarts += 1
            self.last_error = f"{self.child.name}이 멈췄다 (종료 코드 {code})"
            if self.restarts > self.max_restarts:
                self.state = "stopped"
                log.error("%s을 %d번 다시 띄웠지만 계속 멈춘다 — 그만둔다", self.child.name, self.max_restarts)
                return
            wait = self.backoff_s[min(self.restarts - 1, len(self.backoff_s) - 1)]
            self._retry_at = now + wait
            self.state = "restarting"
            log.warning("%s이 멈췄다 (코드 %s) — %.0f초 뒤 다시 띄운다", self.child.name, code, wait)
            return

        if now >= self._retry_at:
            self._retry_at = None
            self._start_now()


__all__ = [
    "DEFAULT_STOP_TIMEOUT_S",
    "UTF8_ENV",
    "HEALTHY_AFTER_S",
    "IS_WINDOWS",
    "MAX_RESTARTS",
    "RESTART_BACKOFF_S",
    "ChildProcess",
    "ProcessError",
    "Supervisor",
]
