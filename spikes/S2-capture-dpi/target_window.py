"""S2 시험 창: 색 칸 다섯 개를 띄우고, 칸이 받은 클릭을 기록한다 (표준 라이브러리만).

    uv run spikes/S2-capture-dpi/target_window.py <unaware|system|pmv2> <events.jsonl>

- DPI 인식 모드를 Tk를 만들기 전에 정한다 → 배율 125%·150%에서 DPI 비인식 앱(비트맵 확대)과
  인식 앱을 둘 다 시험할 수 있다.
- 칸마다 HWND 창 텍스트를 `S2-<색>`으로 넣어 UIA Name으로 찾게 한다.
- 클릭은 `{"name", "x", "y", "w", "h"}`(칸 안 좌표, 이 프로세스 기준 픽셀)로 한 줄씩 쓴다.
"""

import ctypes
import json
import sys
import tkinter as tk
from pathlib import Path

CONTEXTS = {"unaware": -1, "system": -2, "pmv2": -4}  # DPI_AWARENESS_CONTEXT_*
CELLS = [  # (이름, 색, x, y) — 창 안 논리 좌표, 칸 크기 80x60
    ("red", "#ff0000", 10, 10),
    ("green", "#00ff00", 310, 10),
    ("blue", "#0000ff", 160, 110),
    ("yellow", "#ffff00", 10, 210),
    ("magenta", "#ff00ff", 310, 210),
]


def main() -> None:
    mode, events = sys.argv[1], Path(sys.argv[2])
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(CONTEXTS[mode]))
    events.write_text("", encoding="utf-8")

    root = tk.Tk()
    root.title(f"S2 target ({mode})")
    root.geometry("400x280+200+200")
    root.attributes("-topmost", True)
    root.configure(bg="#808080")

    def on_click(name: str, label: tk.Label, e: tk.Event) -> None:
        rec = {"name": name, "x": e.x, "y": e.y, "w": label.winfo_width(), "h": label.winfo_height()}
        with events.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")

    for name, color, x, y in CELLS:
        label = tk.Label(root, bg=color, bd=0, highlightthickness=0)
        label.place(x=x, y=y, width=80, height=60)
        label.bind("<Button-1>", lambda e, n=name, lb=label: on_click(n, lb, e))
        root.update_idletasks()
        ctypes.windll.user32.SetWindowTextW(label.winfo_id(), f"S2-{name}")

    root.mainloop()


if __name__ == "__main__":
    main()
