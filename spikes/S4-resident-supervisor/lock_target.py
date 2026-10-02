"""잠금 화면 시험 창: 빨간 칸(클릭 기록)과 입력칸(내용 기록). 표준 라이브러리만.

    python lock_target.py <events.jsonl>
"""

import ctypes
import json
import sys
import time
import tkinter as tk
from pathlib import Path


def main() -> None:
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    events = Path(sys.argv[1])
    events.write_text("", encoding="utf-8")

    def rec(**kw: object) -> None:
        with events.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": round(time.time(), 2), **kw}, ensure_ascii=False) + "\n")

    root = tk.Tk()
    root.title("S4 lock target")
    root.geometry("360x200+300+300")
    root.attributes("-topmost", True)
    cell = tk.Label(root, bg="#ff0000", bd=0)
    cell.place(x=20, y=20, width=120, height=80)
    cell.bind("<Button-1>", lambda e: rec(kind="click"))
    entry = tk.Entry(root)
    entry.place(x=20, y=130, width=300, height=30)
    entry.bind("<KeyRelease>", lambda e: rec(kind="key", text=entry.get()))
    root.update_idletasks()
    ctypes.windll.user32.SetWindowTextW(cell.winfo_id(), "S4-cell")
    ctypes.windll.user32.SetWindowTextW(entry.winfo_id(), "S4-entry")
    root.mainloop()


if __name__ == "__main__":
    main()
