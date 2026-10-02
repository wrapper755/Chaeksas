# /// script
# requires-python = ">=3.12"
# dependencies = ["uiautomation>=2.0.20"]
# ///
"""메모장·엑셀 창을 띄우고 UIA 트리를 깊이 제한으로 덤프한다 (식별자 탐색용).

    uv run spikes/S1-windows-uia/dump_tree.py notepad|excel
"""

import subprocess
import sys
import time
from pathlib import Path

import uiautomation as auto

OUT = Path(__file__).parent / "outputs"


def walk(ctrl: auto.Control, depth: int, max_depth: int, lines: list[str]) -> None:
    lines.append(
        f"{'  ' * depth}{ctrl.ControlTypeName} | name={ctrl.Name[:40]!r} | aid={ctrl.AutomationId!r} "
        f"| class={ctrl.ClassName!r} | fw={ctrl.FrameworkId!r}"
    )
    if depth >= max_depth:
        return
    for child in ctrl.GetChildren():
        walk(child, depth + 1, max_depth, lines)


def main() -> None:
    target = sys.argv[1]
    if target == "notepad":
        subprocess.Popen(["notepad.exe"])
        win = auto.WindowControl(searchDepth=1, ClassName="Notepad")
        depth = 12
    else:
        subprocess.Popen([r"C:\Program Files\Microsoft Office\Root\Office16\EXCEL.EXE", "/e"])
        win = auto.WindowControl(searchDepth=1, ClassName="XLMAIN")
        depth = 9
    if not win.Exists(maxSearchSeconds=20):
        sys.exit(f"{target} 창을 찾지 못함")
    time.sleep(2)
    lines: list[str] = []
    t0 = time.perf_counter()
    walk(win, 0, depth, lines)
    lines.append(f"# walk {time.perf_counter() - t0:.2f}s, {len(lines)} nodes, pid={win.ProcessId}")
    OUT.mkdir(exist_ok=True)
    (OUT / f"tree-{target}.txt").write_text("\n".join(lines), encoding="utf-8")
    print(lines[-1])


if __name__ == "__main__":
    main()
