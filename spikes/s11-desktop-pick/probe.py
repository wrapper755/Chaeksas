"""s11 데스크톱 「직접 고르기」·「표시」 — 전역 훅 없이 되는가 (09-gaps §7-3).

    uv run --no-sync python spikes/s11-desktop-pick/probe.py

A. 고르기: 커서를 요소 위에 두고 Ctrl을 누른 채 → `ControlFromCursor`가 그 요소를 주는가,
   표 안의 칸이면 위로 올라가 등록할 만한 것(표)에 닿는가, 붙은 창 밖이면 가를 수 있는가.
   **입력을 가로채지 않는다** — 커서 위치와 키 상태를 *읽기만* 한다 (GetCursorPos·GetAsyncKeyState).
B. 표시: UIA 사각형(물리 픽셀)에 Qt 테두리 창(논리 픽셀 = 물리 / devicePixelRatio)을 띄우고
   화면을 캡처해 테두리가 정말 그 자리에 그려졌는지 픽셀로 본다.

결과는 `outputs/result.json`. 시험 창은 tests/fake_desktop_apps.py의 회계 프로그램이다(읽기만 한다).
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import uiautomation as auto

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
OUT = HERE / "outputs"
TAG = " (s11)"
REGISTRABLE = {
    "EditControl", "ButtonControl", "ComboBoxControl", "CheckBoxControl", "RadioButtonControl",
    "ListControl", "HyperlinkControl", "MenuItemControl", "TableControl", "DataGridControl", "TextControl",
}


def launch() -> subprocess.Popen[bytes]:
    env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}
    return subprocess.Popen([sys.executable, str(REPO / "tests" / "fake_desktop_apps.py"), "taxbook", TAG], env=env)


def window() -> auto.Control:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        for one in auto.GetRootControl().GetChildren():
            if (one.Name or "").endswith(TAG):
                return one
        time.sleep(0.2)
    raise SystemExit("시험 창이 뜨지 않았다")


def center(control: auto.Control) -> tuple[int, int]:
    r = control.BoundingRectangle
    return (r.left + r.right) // 2, (r.top + r.bottom) // 2


def registrable(control: auto.Control | None, top: auto.Control) -> auto.Control | None:
    """커서 아래가 칸·틀이면 위로 올라가 등록할 만한 것을 찾는다. 창을 넘으면 없다."""
    while control is not None:
        if control.ProcessId != top.ProcessId:
            return None
        if control.ControlTypeName in REGISTRABLE:
            return control
        if auto.ControlsAreSame(control, top):
            return None
        control = control.GetParentControl()
    return None


def pick_probe(top: auto.Control) -> dict[str, object]:
    out: dict[str, object] = {}
    targets = {
        "nextRow": top.EditControl(AutomationId="QApplication.taxbook.nextRow"),
        "saveMenu": top.ButtonControl(AutomationId="QApplication.taxbook.saveMenu"),
        "sheet": top.TableControl(AutomationId="QApplication.taxbook.sheet"),
    }
    before = auto.GetCursorPos()
    try:
        for name, control in targets.items():
            x, y = center(control)
            auto.SetCursorPos(x, y)
            time.sleep(0.2)
            raw = auto.ControlFromCursor()
            found = registrable(raw, top)
            out[name] = {
                "raw": f"{raw.ControlTypeName} {raw.AutomationId!r}" if raw else None,
                "registrable": f"{found.ControlTypeName} {found.AutomationId!r}" if found else None,
                "same": bool(found and auto.ControlsAreSame(found, control)),
            }
        # Ctrl 상태 읽기 — 누른 척(keybd_event)하고 읽는다. **가로채지 않는다.**
        auto.PressKey(auto.Keys.VK_CONTROL, waitTime=0.05)
        held = auto.IsKeyPressed(auto.Keys.VK_CONTROL)
        auto.ReleaseKey(auto.Keys.VK_CONTROL, waitTime=0.05)
        out["ctrl_read_while_held"] = held
        out["ctrl_read_after_release"] = auto.IsKeyPressed(auto.Keys.VK_CONTROL)
        # 창 밖 (바탕화면 쪽 한 점)
        r = top.BoundingRectangle
        auto.SetCursorPos(max(0, r.left - 40), max(0, r.top - 40))
        time.sleep(0.2)
        outside = auto.ControlFromCursor()
        out["outside_rejected"] = registrable(outside, top) is None
    finally:
        auto.SetCursorPos(*before)
    return out


def highlight_probe(top: auto.Control) -> dict[str, object]:
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication, QWidget

    app = QApplication.instance() or QApplication([])
    target = top.EditControl(AutomationId="QApplication.taxbook.nextRow")
    r = target.BoundingRectangle
    screen = QGuiApplication.screenAt(QGuiApplication.primaryScreen().geometry().center())
    ratio = screen.devicePixelRatio()

    frame = QWidget()
    frame.setWindowFlags(
        Qt.WindowType.FramelessWindowHint
        | Qt.WindowType.WindowStaysOnTopHint
        | Qt.WindowType.Tool
        | Qt.WindowType.WindowTransparentForInput
    )
    frame.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    frame.setStyleSheet("border: 3px solid #ff0000;")
    inner = QWidget(frame)
    inner.setStyleSheet("border: 3px solid #ff0000; background: transparent;")
    pad = 4
    logical = QRect(
        round(r.left / ratio) - pad, round(r.top / ratio) - pad,
        round((r.right - r.left) / ratio) + 2 * pad, round((r.bottom - r.top) / ratio) + 2 * pad,
    )
    frame.setGeometry(logical)
    inner.setGeometry(0, 0, logical.width(), logical.height())
    frame.show()
    for _ in range(20):
        app.processEvents()
        time.sleep(0.05)
    shot = screen.grabWindow(0).toImage()
    # 캡처는 물리 픽셀이다 (devicePixelRatio 배). 테두리 위 한 점과 안쪽 한 점을 본다.
    def px(x: int, y: int) -> str:
        return shot.pixelColor(round(x), round(y)).name()

    border_y = (logical.top() + 1) * ratio
    mid_x = (logical.left() + logical.width() / 2) * ratio
    inside = ((r.left + r.right) / 2, (r.top + r.bottom) / 2)
    result = {
        "ratio": ratio,
        "uia_rect": [r.left, r.top, r.right, r.bottom],
        "qt_logical": [logical.left(), logical.top(), logical.width(), logical.height()],
        "border_pixel": px(mid_x, border_y),
        "inside_pixel": px(*inside),
        "click_through": bool(frame.windowFlags() & Qt.WindowType.WindowTransparentForInput),
    }
    frame.close()
    return result


def main() -> None:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-Monitor (ADR-0021 Worker와 같다)
    OUT.mkdir(exist_ok=True)
    proc = launch()
    try:
        top = window()
        top.SetActive()
        time.sleep(0.5)
        result = {"pick": pick_probe(top), "highlight": highlight_probe(top)}
    finally:
        proc.kill()
    (OUT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
