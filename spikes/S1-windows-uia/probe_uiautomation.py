# /// script
# requires-python = ">=3.12"
# dependencies = ["uiautomation>=2.0.20"]
# ///
"""S1 시나리오를 `uiautomation`으로 돌린다.

    uv run spikes/S1-windows-uia/probe_uiautomation.py notepad|excel

메모장·엑셀이 이미 떠 있어야 한다 (dump_tree.py로 띄운다). 사용자 탭·문서 복구 창은 건드리지 않는다:
메모장은 새 탭 하나, 엑셀은 새 통합 문서 하나만 만들고 저장 없이 닫는다. 창 자체는 닫지 않는다.
"""

import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import uiautomation as auto

OUT = Path(__file__).parent / "outputs"
TEXT = "안녕하세요 Chaeksas 123\n둘째 줄 (S1)"
results: list[dict[str, Any]] = []


def step(name: str, fn: Callable[[], Any]) -> Any:
    t0 = time.perf_counter()
    try:
        value = fn()
        ok, err = True, None
    except Exception as e:  # 스파이크: 실패도 기록하고 다음 단계로
        value, ok, err = None, False, f"{type(e).__name__}: {e}"
    ms = round((time.perf_counter() - t0) * 1000)
    results.append({"step": name, "ok": ok, "ms": ms, "value": None if value is None else repr(value)[:80], "err": err})
    print(f"{'OK ' if ok else 'ERR'} {ms:6d}ms {name} {err or ''}")
    return value


def must(ctrl: auto.Control, seconds: float = 5) -> auto.Control:
    if not ctrl.Exists(maxSearchSeconds=seconds):
        raise LookupError(f"없음: {ctrl}")
    return ctrl


def dont_save(win: auto.WindowControl) -> str:
    # 저장 확인 대화상자의 「저장 안 함」 — 이름이 앱마다 다르다 (메모장 "저장 안 함", 엑셀 "저장 안 함(N)")
    btn = must(win.ButtonControl(searchDepth=8, RegexName=r"^저장 안 함"), 5)
    name = btn.Name
    btn.GetInvokePattern().Invoke()
    return name


def notepad() -> None:
    win = step("attach window class=Notepad", lambda: must(auto.WindowControl(searchDepth=1, ClassName="Notepad")))
    win.SetActive()
    tabs_before = step("count tabs", lambda: len(win.TabControl(AutomationId="Tabs").ListControl().GetChildren()))
    step("click aid=AddButton (새 탭)", lambda: must(win.ButtonControl(AutomationId="AddButton")).GetInvokePattern().Invoke())
    time.sleep(0.5)
    step("new tab added", lambda: len(win.TabControl(AutomationId="Tabs").ListControl().GetChildren()) - tabs_before)
    guard_selected_tab(win, "제목 없음")
    editor = step("find editor class=RichEditD2DPT", lambda: must(win.DocumentControl(ClassName="RichEditD2DPT")))
    step("editor by name '텍스트 편집기'", lambda: must(win.DocumentControl(Name="텍스트 편집기")).ClassName)
    step("editor patterns", lambda: [n for n, pid in (("Value", auto.PatternId.ValuePattern),
                                                     ("Text", auto.PatternId.TextPattern)) if editor.GetPattern(pid)])
    step("type text (SendKeys, 한글 포함)", lambda: editor.SendKeys(TEXT.replace("\n", "{Enter}"), interval=0.01))
    step("read back (TextPattern)", lambda: editor.GetTextPattern().DocumentRange.GetText(-1))
    step("readback == typed", lambda: _same(editor.GetTextPattern().DocumentRange.GetText(-1), TEXT))
    step("open menu aid=File", lambda: must(win.MenuItemControl(AutomationId="File")).GetExpandCollapsePattern().Expand())
    time.sleep(0.5)
    step("menu items visible", lambda: [c.Name for c in auto.GetFocusedControl().GetParentControl().GetChildren()][:8])
    step("close menu (Esc)", lambda: auto.SendKeys("{Esc}"))
    guard_selected_tab(win, "안녕하세요 Chaeksas")
    # 메뉴를 Esc로 닫으면 포커스가 메뉴 막대에 남아 Ctrl+W가 먹지 않는다 → 편집기에 포커스를 먼저 준다
    step("focus editor + Ctrl+W", lambda: (editor.SetFocus(), auto.SendKeys("{Ctrl}w")))
    # XAML ContentDialog: 저장=PrimaryButton, 저장하지 않음=SecondaryButton, 취소=CloseButton (언어 무관)
    step("dialog aid=SecondaryButton (저장하지 않음)",
         lambda: must(win.ButtonControl(AutomationId="SecondaryButton")).GetInvokePattern().Invoke())
    time.sleep(0.5)
    step("tabs back to before", lambda: len(win.TabControl(AutomationId="Tabs").ListControl().GetChildren()) == tabs_before)


def guard_selected_tab(win: auto.WindowControl, prefix: str) -> None:
    """선택된 탭이 실험 탭이 아니면 멈춘다 — 사용자 탭에 입력하거나 저장 없이 닫지 않기 위해."""
    for item in win.TabControl(AutomationId="Tabs").ListControl().GetChildren():
        if item.GetSelectionItemPattern().IsSelected:
            if item.Name.lstrip("\xa0*").startswith(prefix):
                return
            sys.exit(f"중단: 선택된 탭이 실험 탭이 아님 (기대 접두사 {prefix!r})")
    sys.exit("중단: 선택된 탭을 찾지 못함")


def _same(got: str, want: str) -> bool:
    # RichEdit는 줄바꿈을 \r로 돌려준다
    return got.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n") == want


def excel() -> None:
    win = step("attach window class=XLMAIN", lambda: must(auto.WindowControl(searchDepth=1, ClassName="XLMAIN")))
    win.SetActive()
    step("new workbook Ctrl+N", lambda: win.SendKeys("{Ctrl}n"))
    time.sleep(2)
    win = must(auto.WindowControl(searchDepth=1, ClassName="XLMAIN"))
    step("title", lambda: win.Name)
    if not win.Name.startswith("통합 문서"):
        sys.exit("중단: 새 통합 문서가 앞에 있지 않음")
    namebox = step("name box aid=1001", lambda: must(win.EditControl(AutomationId="1001")))
    step("name box by name '이름 상자'", lambda: must(win.EditControl(Name="이름 상자")).AutomationId)

    def goto(ref: str) -> None:
        namebox.Click(simulateMove=False)
        namebox.SendKeys("{Ctrl}a" + ref + "{Enter}")

    step("goto B2 + type 123", lambda: (goto("B2"), win.SendKeys("123{Enter}456{Enter}=B2+B3{Enter}한글값{Enter}")))
    grid = step("find grid (DataGrid)", lambda: must(win.DataGridControl(searchDepth=12)))
    step("grid info", lambda: (grid.Name, grid.AutomationId, grid.ClassName))
    step("cell B4 by name -> value", lambda: must(grid.DataItemControl(Name="B4")).GetValuePattern().Value)
    step("cell B5 by name -> value", lambda: must(grid.DataItemControl(Name="B5")).GetValuePattern().Value)
    step("cell via GridPattern(3,1)", lambda: grid.GetGridPattern().GetItem(3, 1).Name)
    step("grid size (rows, cols)", lambda: (grid.GetGridPattern().RowCount, grid.GetGridPattern().ColumnCount))
    step("cell B2 SetValue('999')", lambda: must(grid.DataItemControl(Name="B2")).GetValuePattern().SetValue("999"))
    time.sleep(0.3)
    step("B2 after SetValue", lambda: grid.DataItemControl(Name="B2").GetValuePattern().Value)
    step("B4 after SetValue", lambda: grid.DataItemControl(Name="B4").GetValuePattern().Value)
    if not auto.WindowControl(searchDepth=1, ClassName="XLMAIN").Name.startswith("통합 문서"):
        sys.exit("중단: 닫을 창이 새 통합 문서가 아님")
    step("close workbook Ctrl+W", lambda: win.SendKeys("{Ctrl}w"))
    time.sleep(1)
    step("dialog 저장 안 함", lambda: dont_save(auto.WindowControl(searchDepth=1, ClassName="XLMAIN")))


def main() -> None:
    target = sys.argv[1]
    t0 = time.perf_counter()
    {"notepad": notepad, "excel": excel}[target]()
    total = round(time.perf_counter() - t0, 2)
    OUT.mkdir(exist_ok=True)
    out = OUT / f"result-uiautomation-{target}.json"
    out.write_text(json.dumps({"lib": "uiautomation", "target": target, "total_s": total, "steps": results},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"total {total}s, {sum(r['ok'] for r in results)}/{len(results)} ok -> {out.name}")


if __name__ == "__main__":
    main()
