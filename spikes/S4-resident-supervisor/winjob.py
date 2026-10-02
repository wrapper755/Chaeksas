"""Windows Job Object로 자식 프로세스 나무를 묶는다 (표준 라이브러리 + ctypes만).

- 자식마다 Job 하나. `KILL_ON_JOB_CLOSE`라서 Job 핸들을 쥔 프로세스(Bot UI)가 어떻게 죽든 — 강제 종료여도 —
  OS가 핸들을 닫으면서 그 Job의 프로세스 나무가 전부 죽는다.
- 자식은 **일시 정지 상태로 만들고 Job에 넣은 뒤 깨운다.** 그냥 띄운 다음 넣으면, 넣기 전에 자식이 손자를 띄워
  손자가 Job 밖에 남을 수 있다. (uv 가상환경의 python.exe도 진짜 인터프리터를 손자로 띄우는 런처다.)
- `terminate()`는 나무 전체를 죽인다 (`TerminateJobObject`).
"""

import ctypes
import subprocess
from ctypes import wintypes

k32 = ctypes.WinDLL("kernel32", use_last_error=True)

CREATE_SUSPENDED = 0x00000004
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JobObjectExtendedLimitInformation = 9
JobObjectBasicAccountingInformation = 1
TH32CS_SNAPTHREAD = 0x4
THREAD_SUSPEND_RESUME = 0x2


class IO_COUNTERS(ctypes.Structure):  # noqa: N801
    _fields_ = [(n, ctypes.c_ulonglong) for n in ("r_ops", "w_ops", "o_ops", "r_bytes", "w_bytes", "o_bytes")]


class BASIC_LIMIT(ctypes.Structure):  # noqa: N801
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]


class EXTENDED_LIMIT(ctypes.Structure):  # noqa: N801
    _fields_ = [("Basic", BASIC_LIMIT), ("Io", IO_COUNTERS), ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t)]


class BASIC_ACCOUNTING(ctypes.Structure):  # noqa: N801
    _fields_ = [("TotalUserTime", ctypes.c_longlong), ("TotalKernelTime", ctypes.c_longlong),
                ("ThisPeriodTotalUserTime", ctypes.c_longlong), ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
                ("TotalPageFaultCount", wintypes.DWORD), ("TotalProcesses", wintypes.DWORD),
                ("ActiveProcesses", wintypes.DWORD), ("TotalTerminatedProcesses", wintypes.DWORD)]


class THREADENTRY32(ctypes.Structure):  # noqa: N801
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ThreadID", wintypes.DWORD),
                ("th32OwnerProcessID", wintypes.DWORD), ("tpBasePri", wintypes.LONG),
                ("tpDeltaPri", wintypes.LONG), ("dwFlags", wintypes.DWORD)]


k32.CreateJobObjectW.restype = wintypes.HANDLE
k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
k32.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
                                          wintypes.LPVOID]
k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
k32.CloseHandle.argtypes = [wintypes.HANDLE]
k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
k32.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(THREADENTRY32)]
k32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(THREADENTRY32)]
k32.OpenThread.restype = wintypes.HANDLE
k32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
k32.ResumeThread.argtypes = [wintypes.HANDLE]


def _check(ok: object, what: str) -> None:
    if not ok:
        raise OSError(ctypes.get_last_error(), f"{what} 실패")


def _resume_all_threads(pid: int) -> int:
    """Popen은 주 스레드 핸들을 버리므로, 스냅숏에서 그 프로세스의 스레드를 찾아 깨운다."""
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    entry = THREADENTRY32(dwSize=ctypes.sizeof(THREADENTRY32))
    resumed = 0
    try:
        ok = k32.Thread32First(snap, ctypes.byref(entry))
        while ok:
            if entry.th32OwnerProcessID == pid:
                h = k32.OpenThread(THREAD_SUSPEND_RESUME, False, entry.th32ThreadID)
                if h:
                    k32.ResumeThread(h)
                    k32.CloseHandle(h)
                    resumed += 1
            ok = k32.Thread32Next(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return resumed


class JobProcess:
    """Job 하나에 묶인 자식 프로세스 (나무)."""

    def __init__(self, args: list[str], *, use_job: bool = True, **popen_kw: object) -> None:
        self.job = None
        flags = CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW | (CREATE_SUSPENDED if use_job else 0)
        self.proc = subprocess.Popen(args, creationflags=flags, **popen_kw)  # type: ignore[call-overload]
        if not use_job:
            return
        self.job = k32.CreateJobObjectW(None, None)
        _check(self.job, "CreateJobObject")
        info = EXTENDED_LIMIT()
        info.Basic.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        _check(k32.SetInformationJobObject(self.job, JobObjectExtendedLimitInformation, ctypes.byref(info),
                                           ctypes.sizeof(info)), "SetInformationJobObject")
        _check(k32.AssignProcessToJobObject(self.job, int(self.proc._handle)), "AssignProcessToJobObject")
        if _resume_all_threads(self.proc.pid) == 0:
            raise OSError("자식 스레드를 깨우지 못함")

    @property
    def pid(self) -> int:
        return self.proc.pid

    def active_processes(self) -> int:
        """Job 안에 살아 있는 프로세스 수 (손자 포함)."""
        if not self.job:
            return 1 if self.proc.poll() is None else 0
        acc = BASIC_ACCOUNTING()
        k32.QueryInformationJobObject(self.job, JobObjectBasicAccountingInformation, ctypes.byref(acc),
                                      ctypes.sizeof(acc), None)
        return acc.ActiveProcesses

    def terminate_tree(self, code: int = 1) -> None:
        if self.job:
            k32.TerminateJobObject(self.job, code)
        else:
            self.proc.kill()

    def close(self) -> None:
        if self.job:
            k32.CloseHandle(self.job)  # KILL_ON_JOB_CLOSE → 남은 나무도 죽는다
            self.job = None


def pid_alive(pid: int) -> bool:
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000  # noqa: N806
    STILL_ACTIVE = 259  # noqa: N806
    k32.OpenProcess.restype = wintypes.HANDLE
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return False
    code = wintypes.DWORD()
    k32.GetExitCodeProcess(h, ctypes.byref(code))
    k32.CloseHandle(h)
    return code.value == STILL_ACTIVE
