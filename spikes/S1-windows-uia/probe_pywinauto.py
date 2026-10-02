# /// script
# requires-python = ">=3.12"
# dependencies = ["pywinauto>=0.6.9"]
# ///
"""S1 시나리오를 `pywinauto`(backend="uia")로 돌린다. probe_uiautomation.py와 같은 단계.

    uv run spikes/S1-windows-uia/probe_pywinauto.py notepad|excel

메모장·엑셀이 이미 떠 있어야 한다. 메모장은 새 탭 하나, 엑셀은 새 통합 문서 하나만 만들고 저장 없이 닫는다.
"""

import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pywinauto import Desktop, keyboard

OUT = Path(__file__).parent / "outputs"
TEXT = "안녕하세요 Chaeksas 123\n둘째 줄 (S1)"
results: list[dict[str, Any]] = []
desk = Desktop(backend="uia")


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


def tab_items(win: Any) -> list[Any]:
    return win.child_window(auto_id="TabListView", control_type="List").children(control_type="TabItem")


def guard_selected_tab(win: Any, prefix: str) -> None:
    """선택된 탭이 실험 탭이 아니면 멈춘다 — 사용자 탭에 입력하거나 저장 없이 닫지 않기 위해."""
    for item in tab_items(win):
        if item.is_selected():
            if item.window_text().lstrip("\xa0*").startswith(prefix):
                return
            sys.exit(f"중단: 선택된 탭이 실험 탭이 아님 (기대 접두사 {prefix!r})")
    sys.exit("중단: 선택된 탭을 찾지 못함")


def _same(got: str, want: str) -> bool:
    return got.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n") == want


def notepad() -> None:
    spec = desk.window(class_name="Notepad")
    win = step("attach window class=Notepad", lambda: spec.wait("exists", timeout=5))
    win.set_focus()
    tabs_before = step("count tabs", lambda: len(tab_items(spec)))
    step("click aid=AddButton (새 탭)", lambda: spec.child_window(auto_id="AddButton", control_type="Button").invoke())
    time.sleep(0.5)
    step("new tab added", lambda: len(tab_items(spec)) - tabs_before)
    guard_selected_tab(spec, "제목 없음")
    editor = step("find editor class=RichEditD2DPT",
                  lambda: spec.child_window(class_name="RichEditD2DPT").wait("exists", timeout=5))
    step("editor by name '텍스트 편집기'",
         lambda: spec.child_window(title="텍스트 편집기", control_type="Document").wrapper_object().class_name())
    step("type text (type_keys, 한글 포함)",
         lambda: editor.type_keys(TEXT.replace("\n", "{ENTER}"), with_spaces=True, pause=0.01))
    step("read back (TextPattern)", lambda: editor.iface_text.DocumentRange.GetText(-1))
    step("readback == typed", lambda: _same(editor.iface_text.DocumentRange.GetText(-1), TEXT))
    step("open menu aid=File", lambda: spec.child_window(auto_id="File", control_type="MenuItem").expand())
    time.sleep(0.5)
    step("menu items visible", lambda: [w.window_text() for w in desk.window(class_name="Notepad").descendants(
        control_type="MenuItem")][:8])
    step("close menu (Esc)", lambda: keyboard.send_keys("{ESC}"))
    guard_selected_tab(spec, "안녕하세요 Chaeksas")
    step("focus editor + Ctrl+W", lambda: (editor.set_focus(), keyboard.send_keys("^w")))
    step("dialog aid=SecondaryButton (저장하지 않음)",
         lambda: spec.child_window(auto_id="SecondaryButton", control_type="Button").wait("exists", timeout=5).invoke())
    time.sleep(0.5)
    step("tabs back to before", lambda: len(tab_items(spec)) == tabs_before)


def excel() -> None:
    spec = desk.window(class_name="XLMAIN")
    win = step("attach window class=XLMAIN", lambda: spec.wait("exists", timeout=5))
    win.set_focus()
    step("new workbook Ctrl+N", lambda: keyboard.send_keys("^n"))
    time.sleep(2)
    step("title", lambda: spec.window_text())
    if not spec.window_text().startswith("통합 문서"):
        sys.exit("중단: 새 통합 문서가 앞에 있지 않음")
    namebox = step("name box aid=1001", lambda: spec.child_window(auto_id="1001", control_type="Edit").wrapper_object())
    step("name box by name '이름 상자'",
         lambda: spec.child_window(title="이름 상자", control_type="Edit").wrapper_object().automation_id())

    def goto(ref: str) -> None:
        namebox.click_input()
        keyboard.send_keys("^a" + ref + "{ENTER}")

    step("goto B2 + type 123", lambda: (goto("B2"), keyboard.send_keys("123{ENTER}456{ENTER}=B2{+}B3{ENTER}한글값{ENTER}")))
    grid = step("find grid aid=Grid (DataGrid)",
                lambda: spec.child_window(auto_id="Grid", control_type="DataGrid").wrapper_object())
    step("grid info", lambda: (grid.window_text(), grid.automation_id(), grid.class_name()))

    # wrapper에는 child_window가 없다 → 창 스펙에서 grid 경로를 다시 잡는다
    gspec = spec.child_window(auto_id="Grid", control_type="DataGrid")
    step("cell B4 by name -> value", lambda: gspec.child_window(title="B4", control_type="DataItem").iface_value.CurrentValue)
    step("cell B5 by name -> value", lambda: gspec.child_window(title="B5", control_type="DataItem").iface_value.CurrentValue)
    # title은 UIA Name이 아니라 rich_text(셀 값)와 비교된다 → 이름은 직접 비교하는 우회책
    def by_name(ref: str) -> Any:
        found = [c for c in grid.children(control_type="DataItem") if c.element_info.name == ref]
        if not found:
            raise LookupError(ref)
        return found[0]

    step("cell B4 by title='579' (값으로 찾힘)",
         lambda: gspec.child_window(title="579", control_type="DataItem").wrapper_object().element_info.name)
    step("cell B4 by name (우회: children 필터)", lambda: by_name("B4").iface_value.CurrentValue)
    step("cell via GridPattern(3,1)", lambda: grid.iface_grid.GetItem(3, 1).CurrentName)
    step("grid size (rows, cols)", lambda: (grid.iface_grid.CurrentRowCount, grid.iface_grid.CurrentColumnCount))
    step("cell B2 set_value('999')", lambda: by_name("B2").iface_value.SetValue("999"))
    time.sleep(0.3)
    step("B2 after set_value", lambda: by_name("B2").iface_value.CurrentValue)
    step("B4 after set_value", lambda: by_name("B4").iface_value.CurrentValue)
    if not spec.window_text().startswith("통합 문서"):
        sys.exit("중단: 닫을 창이 새 통합 문서가 아님")
    step("close workbook Ctrl+W", lambda: (win.set_focus(), keyboard.send_keys("^w")))
    time.sleep(1)
    step("dialog 저장 안 함", lambda: _dont_save(spec))


def _dont_save(spec: Any) -> str:
    btn = spec.child_window(title_re=r"^저장 안 함", control_type="Button").wait("exists", timeout=5)
    name = btn.window_text()
    btn.invoke()
    return name


def main() -> None:
    target = sys.argv[1]
    t0 = time.perf_counter()
    {"notepad": notepad, "excel": excel}[target]()
    total = round(time.perf_counter() - t0, 2)
    OUT.mkdir(exist_ok=True)
    out = OUT / f"result-pywinauto-{target}.json"
    out.write_text(json.dumps({"lib": "pywinauto", "target": target, "total_s": total, "steps": results},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"total {total}s, {sum(r['ok'] for r in results)}/{len(results)} ok -> {out.name}")


if __name__ == "__main__":
    main()
