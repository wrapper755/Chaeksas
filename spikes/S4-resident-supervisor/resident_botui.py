"""상주 가짜 Bot UI: 숨은 창 + Worker·실행기 자식. 로그오프·잠금 알림을 받으면 기록한다.

    pythonw resident_botui.py   → outputs/logoff.jsonl

- WM_QUERYENDSESSION / WM_ENDSESSION: 로그오프·종료 알림. ENDSESSION에서 자식을 정리하고 기록한다.
- WM_WTSSESSION_CHANGE: 잠금·해제·로그오프 세션 알림 (WTSRegisterSessionNotification).
- 기록은 줄마다 flush + fsync (로그오프 중에 끊길 수 있다).
"""

import ctypes
import ctypes.wintypes as wt
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from supervisor import Supervisor  # noqa: E402
from winjob import JobProcess  # noqa: E402

OUT = HERE / "outputs"
OUT.mkdir(exist_ok=True)
LOG = (OUT / "logoff.jsonl").open("a", encoding="utf-8")
T0 = time.perf_counter()


def log(event: str, **kw: object) -> None:
    LOG.write(json.dumps({"at": time.strftime("%H:%M:%S"), "t": round(time.perf_counter() - T0, 2),
                          "event": event, **kw}, ensure_ascii=False) + "\n")
    LOG.flush()
    os.fsync(LOG.fileno())


WM_QUERYENDSESSION, WM_ENDSESSION, WM_WTSSESSION_CHANGE, WM_DESTROY = 0x11, 0x16, 0x2B1, 0x2
WTS_CODES = {5: "logon", 6: "logoff", 7: "lock", 8: "unlock"}
WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
user32 = ctypes.windll.user32
user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.CreateWindowExW.restype = wt.HWND
user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
                ("lpszClassName", wt.LPCWSTR)]


def main() -> None:
    sv = Supervisor(18898, OUT / "tok-resident")
    ok = sv.start_worker()
    runner_holder: dict[str, JobProcess] = {}
    # 실행기는 drain() 대신 직접 띄워 pid만 기록하고 쥐고 있는다
    import subprocess  # noqa: PLC0415

    env = {**os.environ, "CHK_WORKER__URL": sv.url, "CHK_WORKER__TOKEN_FILE": str(sv.token_dir / "worker.token")}
    runner = JobProcess([sys.executable, str(HERE / "fake_runner.py"), "spawn"], stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
    first = json.loads(runner.proc.stdout.readline())  # type: ignore[union-attr]
    runner_holder["r"] = runner
    log("started", botui=os.getpid(), worker_ok=ok, worker_launcher=sv.worker.pid,  # type: ignore[union-attr]
        runner_launcher=runner.pid, runner=first["pid"], runner_grandchild=first["grandchild"])

    def wndproc(hwnd: int, msg: int, wp: int, lp: int) -> int:
        if msg == WM_QUERYENDSESSION:
            log("WM_QUERYENDSESSION", logoff=bool(lp & 0x80000000), lparam=hex(lp & 0xFFFFFFFF))
            return 1  # 막지 않는다 (막으면 사용자에게 「앱이 종료를 막고 있음」 화면)
        if msg == WM_ENDSESSION:
            log("WM_ENDSESSION", ending=bool(wp), logoff=bool(lp & 0x80000000))
            if wp:
                t = time.perf_counter()
                runner_holder["r"].terminate_tree()
                sv.shutdown()
                log("children-terminated", ms=round((time.perf_counter() - t) * 1000),
                    runner_left=runner_holder["r"].active_processes())
            return 0
        if msg == WM_WTSSESSION_CHANGE:
            log("WTS", change=WTS_CODES.get(wp, wp))
            return 0
        return user32.DefWindowProcW(hwnd, msg, wp, lp)

    proc = WNDPROC(wndproc)
    hinst = ctypes.windll.kernel32.GetModuleHandleW(None)
    wc = WNDCLASSW(lpfnWndProc=proc, hInstance=hinst, lpszClassName="ChaeksasS4Resident")
    user32.RegisterClassW(ctypes.byref(wc))
    # 최상위 숨은 창 (메시지 전용 창 HWND_MESSAGE는 WM_QUERYENDSESSION을 못 받는다)
    hwnd = user32.CreateWindowExW(0, "ChaeksasS4Resident", "S4 resident", 0, 0, 0, 0, 0, None, None, hinst, None)
    ctypes.windll.wtsapi32.WTSRegisterSessionNotification(hwnd, 0)  # NOTIFY_FOR_THIS_SESSION
    log("window", hwnd=hwnd)
    msg = wt.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log("crash", error=repr(e))
        raise
