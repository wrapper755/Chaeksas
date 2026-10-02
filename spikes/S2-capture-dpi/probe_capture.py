# /// script
# requires-python = ">=3.12"
# dependencies = ["uiautomation>=2.0.20", "mss>=9", "pillow>=10"]
# ///
"""S2: UIA 좌표 = 캡처 좌표 = 클릭 좌표인가. 배율·DPI 인식 모드 조합마다 판정한다.

    uv run spikes/S2-capture-dpi/probe_capture.py all          # Worker 모드 4가지를 각각 새 프로세스로
    uv run spikes/S2-capture-dpi/probe_capture.py <worker 모드>  # default|unaware|system|pmv2

Worker 모드 = 이 프로세스(Worker 역할)의 DPI 인식. `default`는 아무것도 정하지 않는다 (라이브러리가 몰래
바꾸는지 보려고). 시험 창(target_window.py)은 unaware·system·pmv2로 하나씩 띄운다.

칸마다:
- UIA BoundingRectangle (Worker가 받는 좌표)
- 캡처(mss, Pillow ImageGrab)에서 그 색의 실제 테두리 상자를 찾아 UIA 사각형과의 차이 (0이면 일치)
- UIA 사각형 가운데를 클릭 → 시험 창이 받은 칸 이름과 칸 안 위치(0.5, 0.5면 정확)

클릭 전에 그 점의 최상위 창이 시험 창 프로세스인지 확인하고, 아니면 클릭하지 않는다.
"""

import ctypes
import ctypes.wintypes
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "outputs"
CONTEXTS = {"unaware": -1, "system": -2, "pmv2": -4}
TARGET_MODES = ["unaware", "system", "pmv2"]
COLORS = {"red": (255, 0, 0), "green": (0, 255, 0), "blue": (0, 0, 255), "yellow": (255, 255, 0),
          "magenta": (255, 0, 255)}
user32 = ctypes.windll.user32
# 포인터·HWND를 int로 잘리지 않게 (64비트)
user32.GetThreadDpiAwarenessContext.restype = ctypes.c_void_p
user32.GetAwarenessFromDpiAwarenessContext.argtypes = [ctypes.c_void_p]
user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
user32.WindowFromPoint.argtypes = [ctypes.wintypes.POINT]
user32.WindowFromPoint.restype = ctypes.wintypes.HWND
user32.GetAncestor.argtypes = [ctypes.wintypes.HWND, ctypes.c_uint]
user32.GetAncestor.restype = ctypes.wintypes.HWND
user32.GetDpiForWindow.argtypes = [ctypes.wintypes.HWND]
user32.GetDC.restype = ctypes.wintypes.HDC
user32.ReleaseDC.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.HDC]
ctypes.windll.gdi32.GetDeviceCaps.argtypes = [ctypes.wintypes.HDC, ctypes.c_int]


def awareness() -> str:
    ctx = user32.GetThreadDpiAwarenessContext()
    return {0: "unaware", 1: "system", 2: "per-monitor"}.get(user32.GetAwarenessFromDpiAwarenessContext(ctx), "?")


def real_scale_pct() -> int:
    gdi32 = ctypes.windll.gdi32
    hdc = user32.GetDC(None)
    real_w = gdi32.GetDeviceCaps(hdc, 118)  # DESKTOPHORZRES: 가상화되지 않는 실제 가로 픽셀
    user32.ReleaseDC(None, hdc)
    return round(user32.GetDpiForSystem() / 96 * real_w / user32.GetSystemMetrics(0) * 100)


def main_all() -> None:
    for mode in ["default", "unaware", "system", "pmv2"]:
        subprocess.run([sys.executable, __file__, mode], check=False)
    summarize()


def run(worker_mode: str) -> None:
    # 반드시 다른 import보다 먼저 — 첫 설정만 먹고 나중 호출은 실패한다
    if worker_mode != "default":
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(CONTEXTS[worker_mode]))
    before = awareness()

    import mss  # noqa: PLC0415
    import uiautomation as auto  # noqa: PLC0415
    from PIL import Image, ImageChops, ImageGrab  # noqa: PLC0415

    after_import = awareness()
    sct = mss.MSS()
    after_mss = awareness()

    def grab_mss() -> tuple[Image.Image, int, int]:
        mon = sct.monitors[0]  # 가상 화면 전체
        shot = sct.grab(mon)
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX"), mon["left"], mon["top"]

    def grab_pil() -> tuple[Image.Image, int, int]:
        img = ImageGrab.grab(all_screens=True)
        # all_screens=True의 원점은 가상 화면 왼쪽 위 (이 프로세스 기준 좌표계)
        return img.convert("RGB"), user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)

    grabbers = {"mss": grab_mss, "pillow": grab_pil}

    def color_bbox(img: Image.Image, rgb: tuple[int, int, int]) -> tuple[int, int, int, int] | None:
        diff = ImageChops.difference(img, Image.new("RGB", img.size, rgb)).convert("L")
        return diff.point(lambda v: 255 if v == 0 else 0).getbbox()

    env = {
        "worker_mode": worker_mode,
        "awareness": {"before_import": before, "after_import": after_import, "after_mss": after_mss},
        "system_dpi": user32.GetDpiForSystem(),
        # DPI 비인식 프로세스에는 GetDpiForSystem이 96으로 속여 보인다 → 가상화되지 않는 실제 해상도와 비교
        "real_scale_pct": real_scale_pct(),
        "virtual_screen": [user32.GetSystemMetrics(i) for i in (76, 77, 78, 79)],
        "monitors_mss": sct.monitors[1:],
        "pillow_size": list(ImageGrab.grab(all_screens=True).size),
    }
    print(f"[worker={worker_mode}] awareness {env['awareness']} dpi={env['system_dpi']} vs={env['virtual_screen']}")

    timing = {}
    for lib, fn in grabbers.items():
        t0 = time.perf_counter()
        for _ in range(5):
            fn()
        timing[lib] = round((time.perf_counter() - t0) / 5 * 1000, 1)

    runs = []
    for tmode in TARGET_MODES:
        events = OUT / f"events-{worker_mode}-{tmode}.jsonl"
        proc = subprocess.Popen([sys.executable, str(HERE / "target_window.py"), tmode, str(events)])
        try:
            runs.append(check_target(auto, tmode, events, grabbers, color_bbox))
        finally:
            proc.terminate()
            proc.wait(5)

    OUT.mkdir(exist_ok=True)
    scale = env["real_scale_pct"]
    out = OUT / f"result-{scale}pct-w{worker_mode}.json"
    out.write_text(json.dumps({"env": env, "capture_ms": timing, "targets": runs}, indent=1), encoding="utf-8")


def check_target(auto, tmode, events, grabbers, color_bbox):  # type: ignore[no-untyped-def]
    win = auto.WindowControl(searchDepth=1, SubName=f"S2 target ({tmode})")
    if not win.Exists(maxSearchSeconds=10):
        return {"target": tmode, "error": "창 없음"}
    time.sleep(0.8)
    hwnd = win.NativeWindowHandle
    # Popen pid는 uv 가상환경 런처라 창 주인이 아니다 → 제목으로 찾은 시험 창의 pid와 비교
    pid = win.ProcessId
    res = {"target": tmode, "window_dpi": user32.GetDpiForWindow(hwnd),
           "target_awareness": None, "cells": []}
    shots = {lib: fn() for lib, fn in grabbers.items()}
    pos = auto.GetCursorPos()
    for name, rgb in COLORS.items():
        cell = win.Control(searchDepth=3, Name=f"S2-{name}")
        r = cell.BoundingRectangle
        uia = [r.left, r.top, r.right, r.bottom]
        row = {"name": name, "uia": uia, "capture": {}}
        for lib, (img, ox, oy) in shots.items():
            bb = color_bbox(img, rgb)
            if bb is None:
                row["capture"][lib] = None
                continue
            found = [bb[0] + ox, bb[1] + oy, bb[2] + ox, bb[3] + oy]
            row["capture"][lib] = {"found": found, "delta": [f - u for f, u in zip(found, uia, strict=True)]}
        cx, cy = (r.left + r.right) // 2, (r.top + r.bottom) // 2
        top = user32.GetAncestor(user32.WindowFromPoint(ctypes.wintypes.POINT(cx, cy)), 2)
        owner = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(top, ctypes.byref(owner))
        if owner.value != pid:
            row["click"] = {"skipped": f"그 점의 창이 시험 창이 아님 (pid {owner.value})"}
        else:
            n_before = len(events.read_text(encoding="utf-8").splitlines())
            auto.Click(cx, cy, waitTime=0.3)
            lines = events.read_text(encoding="utf-8").splitlines()
            if len(lines) > n_before:
                ev = json.loads(lines[-1])
                row["click"] = {"hit": ev["name"], "ok": ev["name"] == name,
                                "frac": [round(ev["x"] / ev["w"], 2), round(ev["y"] / ev["h"], 2)],
                                "cell_px": [ev["w"], ev["h"]]}
            else:
                row["click"] = {"hit": None, "ok": False}
        res["cells"].append(row)
    auto.SetCursorPos(*pos)
    return res


def verdict(row: dict, lib: str) -> str:
    cap = row["capture"].get(lib)
    if cap is None:
        return "색 없음"
    return "일치" if not any(cap["delta"]) else f"차이 {cap['delta']}"


def summarize() -> None:
    lines = []
    for f in sorted(OUT.glob("result-*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        aw = d["env"]["awareness"]
        lines.append(f"## {f.stem}  (awareness {aw['before_import']}→{aw['after_import']}→{aw['after_mss']}, "
                     f"dpi {d['env']['system_dpi']}, real {d['env'].get('real_scale_pct')}%, capture ms {d['capture_ms']})")
        for t in d["targets"]:
            if "error" in t:
                lines.append(f"  target={t['target']}: {t['error']}")
                continue
            cells = t["cells"]
            def agg(lib: str, cells: list = cells) -> str:
                vs = {verdict(c, lib) for c in cells}
                return "일치" if vs == {"일치"} else "; ".join(sorted(vs))
            clicks = [c["click"] for c in cells]
            ok = sum(1 for c in clicks if c.get("ok"))
            fr = {tuple(c["frac"]) for c in clicks if c.get("frac")}
            lines.append(f"  target={t['target']:8} winDPI={t['window_dpi']:3}  mss={agg('mss')}  "
                         f"pillow={agg('pillow')}  click {ok}/{len(clicks)} frac={sorted(fr)}")
    text = "\n".join(lines)
    (OUT / "summary.txt").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    if sys.argv[1] == "all":
        main_all()
    elif sys.argv[1] == "summary":
        summarize()
    else:
        run(sys.argv[1])
