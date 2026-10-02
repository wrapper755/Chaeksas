# /// script
# requires-python = ">=3.12"
# dependencies = ["uiautomation>=2.0.20", "mss>=9", "pillow>=10"]
# ///
"""잠금 화면(Win+L) 동안 Worker가 할 수 있는 일을 3초마다 기록한다.

    uv run spikes/S4-resident-supervisor/lock_probe.py [초=120]

틱마다: 입력 데스크톱 이름(잠기면 Default가 아니다), UIA로 칸 찾기·사각형, 클릭(SendInput) → 시험 창이 받았나,
키 입력 → 입력칸에 들어갔나, 캡처(mss) → 빨간 칸이 보이나, Worker REST(가짜 Worker) 응답.
클릭은 그 점의 창이 시험 창일 때만 한다. 결과: outputs/lock.jsonl
"""

import ctypes
import ctypes.wintypes as wt
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

user32 = ctypes.windll.user32
user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # S2: Worker는 PMv2 (다른 import보다 먼저)

import mss  # noqa: E402
import uiautomation as auto  # noqa: E402

HERE = Path(__file__).parent
OUT = HERE / "outputs"
user32.OpenInputDesktop.restype = wt.HANDLE
user32.GetUserObjectInformationW.argtypes = [wt.HANDLE, ctypes.c_int, wt.LPVOID, wt.DWORD, ctypes.POINTER(wt.DWORD)]
user32.CloseDesktop.argtypes = [wt.HANDLE]
user32.WindowFromPoint.argtypes = [wt.POINT]
user32.WindowFromPoint.restype = wt.HWND
user32.GetAncestor.argtypes = [wt.HWND, ctypes.c_uint]
user32.GetAncestor.restype = wt.HWND


def input_desktop() -> str:
    h = user32.OpenInputDesktop(0, False, 0x0001)  # DESKTOP_READOBJECTS
    if not h:
        return f"(열 수 없음 err={ctypes.GetLastError()})"
    buf = ctypes.create_unicode_buffer(64)
    user32.GetUserObjectInformationW(h, 2, buf, ctypes.sizeof(buf), None)  # UOI_NAME
    user32.CloseDesktop(h)
    return buf.value


def session_locked() -> object:
    """WTS 세션 잠금 플래그 (입력 데스크톱 이름과 별개의 두 번째 신호)."""
    wtsapi = ctypes.windll.wtsapi32
    buf, n = ctypes.c_void_p(), wt.DWORD()
    sid = ctypes.windll.kernel32.WTSGetActiveConsoleSessionId()
    if not wtsapi.WTSQuerySessionInformationW(None, sid, 25, ctypes.byref(buf), ctypes.byref(n)):  # WTSSessionInfoEx
        return f"err {ctypes.GetLastError()}"
    try:
        # WTSINFOEXW: Level(DWORD) + 공용체(8바이트 정렬 — LARGE_INTEGER 필드) → Data는 오프셋 8.
        # WTSINFOEX_LEVEL1_W: SessionId, SessionState, SessionFlags → DWORD 2, 3, 4번째
        flags = ctypes.cast(buf, ctypes.POINTER(wt.DWORD))[4]
        return {0: True, 1: False}.get(flags, f"? {flags}")  # WTS_SESSIONSTATE_LOCK=0, UNLOCK=1
    finally:
        wtsapi.WTSFreeMemory(buf)


def point_owner(x: int, y: int) -> tuple[int, str]:
    """그 화면 점의 최상위 창 주인 (pid, 실행 파일 이름)."""
    top = user32.GetAncestor(user32.WindowFromPoint(wt.POINT(x, y)), 2)
    owner = wt.DWORD()
    user32.GetWindowThreadProcessId(top, ctypes.byref(owner))
    k32 = ctypes.windll.kernel32
    k32.OpenProcess.restype = wt.HANDLE
    h = k32.OpenProcess(0x1000, False, owner.value)
    name = "?"
    if h:
        buf, size = ctypes.create_unicode_buffer(260), wt.DWORD(260)
        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            name = Path(buf.value).name
        k32.CloseHandle(h)
    return owner.value, name


def count(events: Path, kind: str) -> tuple[int, str]:
    rows = [json.loads(x) for x in events.read_text(encoding="utf-8").splitlines() if x]
    rows = [r for r in rows if r["kind"] == kind]
    return len(rows), (rows[-1].get("text", "") if rows else "")


def main() -> None:
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 120
    OUT.mkdir(exist_ok=True)
    events = OUT / "lock-events.jsonl"
    sys.path.insert(0, str(HERE))
    from supervisor import Supervisor  # noqa: PLC0415

    sv = Supervisor(18897, OUT / "tok-lock")
    sv.start_worker()
    target = subprocess.Popen([sys.executable, str(HERE / "lock_target.py"), str(events)])
    win = auto.WindowControl(searchDepth=1, Name="S4 lock target")
    win.Exists(10)
    pid = win.ProcessId
    sct = mss.MSS()
    log = (OUT / "lock.jsonl").open("w", encoding="utf-8")
    end = time.time() + seconds
    print("시작 — 이제 Win+L로 잠그고, 30초쯤 뒤 풀어 주세요", flush=True)
    try:
        loop(win, pid, events, sct, log, end, sv)
    finally:  # 예외로 끝나도 시험 창·Worker를 남기지 않는다
        target.terminate()
        sv.shutdown()


def loop(win, pid, events, sct, log, end, sv) -> None:  # type: ignore[no-untyped-def]
    n = 0
    while time.time() < end:
        n += 1
        row: dict = {"t": time.strftime("%H:%M:%S"), "desktop": input_desktop(), "wts_locked": session_locked()}
        try:
            cell = win.Control(searchDepth=3, Name="S4-cell")
            r = cell.BoundingRectangle
            row["uia"] = [r.left, r.top, r.width(), r.height()]
            cx, cy = (r.left + r.right) // 2, (r.top + r.bottom) // 2
        except Exception as e:
            row["uia"] = f"ERR {type(e).__name__}"
            cx = cy = None
        if cx is not None:
            owner, name = point_owner(cx, cy)
            if owner == pid:
                before = count(events, "click")[0]
                auto.Click(cx, cy, waitTime=0.3)
                row["click_received"] = count(events, "click")[0] > before
            else:
                row["click_received"] = f"skip (그 점은 {name})"
            try:
                px = sct.grab({"left": cx - 5, "top": cy - 5, "width": 10, "height": 10}).pixel(5, 5)
                row["capture_center_rgb"] = px
                row["capture_sees_red"] = px == (255, 0, 0)
            except Exception as e:  # 잠금 중 BitBlt가 실패한다
                row["capture_sees_red"] = f"ERR {type(e).__name__}"
            try:
                er = win.Control(searchDepth=3, Name="S4-entry").BoundingRectangle
                ex, ey = (er.left + er.right) // 2, (er.top + er.bottom) // 2
                fg = wt.DWORD()
                user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(fg))
                if point_owner(ex, ey)[0] != pid:  # 다른 창(잠금 화면 등)을 누르지 않게
                    row["key_received"] = "skip (입력칸이 가려짐)"
                else:
                    auto.Click(ex, ey, waitTime=0.1)
                    user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(fg))
                    if fg.value != pid:  # 키가 다른 창으로 새지 않게
                        row["key_received"] = f"skip (앞 창 pid {fg.value})"
                    else:
                        before_len = len(count(events, "key")[1])
                        auto.SendKeys(str(n % 10), waitTime=0.3)
                        # 커서가 클릭한 자리에 있어 끝에 붙지 않을 수 있다 → 글자 수로 판정
                        row["key_received"] = len(count(events, "key")[1]) > before_len
            except Exception as e:
                row["key_received"] = f"ERR {type(e).__name__}"
        row["worker_rest"] = sv.health()
        log.write(json.dumps(row, ensure_ascii=False) + "\n")
        log.flush()
        print(json.dumps(row, ensure_ascii=False), flush=True)
        time.sleep(3)


if __name__ == "__main__":
    main()
