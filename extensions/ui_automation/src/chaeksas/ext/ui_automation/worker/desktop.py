"""Windows 데스크톱 백엔드 — UIA로 **찾고 조작한다** (C10 `Backend`, C8 `Finder`, ADR-0020·0033).

브라우저 백엔드(`browser.py`)와 같은 모양이다. 사다리·치유·세션은 `ladder.py`·`app.py`가 들고
있고, 이 파일은 로케이터 하나를 UIA 조건으로 옮기고 동작을 한 번 하는 일만 한다.

- **붙은 창 안에서만** 찾는다. 창은 계획의 창 조건(C9 `window`)으로 고르고, 여럿이면 고르지
  않는다 — 엉뚱한 창에 입력하지 않게 (ADR-0033).
- **입력은 포커스 → 키 입력**이고, 읽을 수 있는 칸이면 **다시 읽어 확인**한다. 키 입력으로 안
  들어가는 글자(이모지 등)는 `ValuePattern.SetValue`로 넣고 또 확인한다 (ADR-0020·0033).
- **잠긴 화면에는 손대지 않는다.** UIA는 잠긴 동안에도 요소를 정상으로 돌려준다 — WTS로 본다
  (ADR-0023, C10 `session_locked`).
- **값을 로그에 남기지 않는다** (원칙 6). 치유 스냅샷은 입력한 값을 가린다.
- Windows가 아니거나 `uiautomation`이 없으면 `available()`이 거짓이고, 데스크톱 세션은 503이다.
"""

from __future__ import annotations

import ctypes
import json
import logging
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chaeksas.ext.ui_automation.contracts.plan import LocatorSpec, PlanStep, WindowSpec, masked
from chaeksas.ext.ui_automation.contracts.worker_local import SessionRequest
from chaeksas.ext.ui_automation.worker.ladder import Match

log = logging.getLogger(__name__)

#: 치유 요청에 싣는 스냅샷 크기 한도 (C8 — 브라우저와 같다).
SNAPSHOT_MAX = 32 * 1024
#: 창 안을 얼마나 깊이 훑나. 사내 앱은 깊다 — 그래도 끝없이 내려가지는 않는다.
SEARCH_DEPTH = 40
#: 찾기를 다시 해 보는 간격 (요소가 늦게 생길 수 있다).
POLL_S = 0.2
#: 앱을 띄운 뒤 창이 생기기를 기다리는 기본 시간 (C10).
START_TIMEOUT_S = 30.0
#: 그 PC의 앱 실행 명령 (C10 — Worker 데이터 폴더).
APPS_FILE = "desktop-apps.json"

#: 내용을 **이름**으로 내보내는 컨트롤 — 값이 비어 있으면 이름을 읽는다 (표 칸·목록 항목·글).
#: 입력칸은 여기 없다: 빈 입력칸에서 옆 라벨의 이름이 읽혀 나오면 안 된다.
CONTENT_IN_NAME = frozenset(
    {"DataItemControl", "ListItemControl", "TextControl", "HeaderItemControl", "TreeItemControl", "HyperlinkControl"}
)

APP_NOT_RUNNING = "app_not_running"
WINDOW_AMBIGUOUS = "window_ambiguous"


class DesktopProblem(Exception):
    """C10 오류 하나로 나갈 데스크톱 쪽 실패 — Worker가 `status`·`code`로 옮긴다."""

    def __init__(self, status: int, code: str, message: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.detail = detail or {}


class ScreenLocked(RuntimeError):
    """화면이 잠겨 있다 — 조작하지 않는다 (C10 `session_locked`)."""


def available() -> bool:
    """이 PC에서 데스크톱 세션을 열 수 있나 (Windows + `uiautomation`)."""
    if sys.platform != "win32":
        return False
    try:
        import uiautomation  # noqa: F401, PLC0415
    except ImportError:
        return False
    return True


# ─────────────────────────── Windows 바닥 ───────────────────────────


def ensure_per_monitor_dpi() -> bool:
    """프로세스가 Per-Monitor v2인지 보고 아니면 선언한다 (ADR-0021).

    좌표로 누르는 일이 있으니 DPI 비인식이면 배율만큼 빗나간다. **처음 정한 것만 먹으므로**
    이미 다른 것으로 정해져 있으면 바꾸지 못하고 거짓을 돌려준다.
    """
    if sys.platform != "win32":
        return False
    user32 = ctypes.windll.user32
    user32.GetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    user32.GetAwarenessFromDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    per_monitor = 2
    if user32.GetAwarenessFromDpiAwarenessContext(user32.GetThreadDpiAwarenessContext()) == per_monitor:
        return True
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
    ok = bool(user32.GetAwarenessFromDpiAwarenessContext(user32.GetThreadDpiAwarenessContext()) == per_monitor)
    if not ok:
        log.warning("Worker가 Per-Monitor DPI 인식이 아니다 — 배율이 다른 화면에서 좌표가 빗나갈 수 있다")
    return ok


def screen_locked() -> bool:
    """WTS 세션 잠금 (ADR-0023). 입력 데스크톱 이름이나 UIA로는 알 수 없다 (S4)."""
    if sys.platform != "win32":
        return False
    from ctypes import wintypes  # noqa: PLC0415

    wtsapi = ctypes.windll.wtsapi32
    buffer, size = ctypes.c_void_p(), wintypes.DWORD()
    session = ctypes.windll.kernel32.WTSGetActiveConsoleSessionId()
    if not wtsapi.WTSQuerySessionInformationW(None, session, 25, ctypes.byref(buffer), ctypes.byref(size)):
        return False  # 물어볼 수 없으면 잠기지 않았다고 본다 — 원격 세션 등
    try:
        # WTSINFOEXW: Level(DWORD) 뒤 공용체가 8바이트 정렬이라 Data는 오프셋 8이고, 그 안에서
        # SessionId·SessionState 다음의 SessionFlags는 오프셋 16이다 (S4에서 4로 읽어 거꾸로 읽었다).
        raw = ctypes.string_at(buffer, 20)
        flags = int.from_bytes(raw[16:20], "little", signed=True)
        return flags == 0  # WTS_SESSIONSTATE_LOCK
    finally:
        wtsapi.WTSFreeMemory(buffer)


def type_text(text: str) -> None:
    """글자를 **그대로** 친다 (`SendInput` 유니코드). 한글·`{ } ( ) + ^ %`가 문법으로 먹히지 않는다."""
    if sys.platform != "win32":
        raise RuntimeError("Windows에서만 칠 수 있다")
    from ctypes import wintypes  # noqa: PLC0415

    class KeyboardInput(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_size_t),
        ]

    class InputUnion(ctypes.Union):
        _fields_ = [("ki", KeyboardInput), ("pad", ctypes.c_byte * 32)]

    class Input(ctypes.Structure):
        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", InputUnion)]

    unicode, key_up = 0x0004, 0x0002
    events = []
    units = text.encode("utf-16-le")
    for i in range(0, len(units), 2):
        code = int.from_bytes(units[i : i + 2], "little")
        for flags in (unicode, unicode | key_up):
            one = Input(type=1)
            one.ki = KeyboardInput(0, code, flags, 0, 0)
            events.append(one)
    if not events:
        return
    array = (Input * len(events))(*events)
    sent = ctypes.windll.user32.SendInput(len(events), array, ctypes.sizeof(Input))
    if sent != len(events):
        raise RuntimeError(f"키 입력이 막혔다 ({sent}/{len(events)})")


#: `press` 값 → 키 (Playwright와 같은 이름을 쓴다 — C10 `press`는 웹·데스크톱이 같다).
KEY_NAMES = {
    "enter": "{Enter}",
    "tab": "{Tab}",
    "escape": "{Esc}",
    "esc": "{Esc}",
    "backspace": "{Back}",
    "delete": "{Del}",
    "home": "{Home}",
    "end": "{End}",
    "pageup": "{PageUp}",
    "pagedown": "{PageDown}",
    "arrowup": "{Up}",
    "arrowdown": "{Down}",
    "arrowleft": "{Left}",
    "arrowright": "{Right}",
    "space": "{Space}",
    **{f"f{n}": f"{{F{n}}}" for n in range(1, 13)},
}
MODIFIERS = {"control": "{Ctrl}", "ctrl": "{Ctrl}", "shift": "{Shift}", "alt": "{Alt}"}


def key_sequence(value: str) -> str:
    """`Control+A`·`Enter` → `uiautomation.SendKeys` 문법. 모르는 키는 거절한다 (아무 글이나 치지 않게)."""
    parts = [one.strip() for one in value.split("+") if one.strip()]
    if not parts:
        raise ValueError("누를 키가 없다")
    *mods, last = parts
    out = []
    for mod in mods:
        if mod.lower() not in MODIFIERS:
            raise ValueError(f"모르는 보조 키다: {mod}")
        out.append(MODIFIERS[mod.lower()])
    name = last.lower()
    if name in KEY_NAMES:
        out.append(KEY_NAMES[name])
    elif len(last) == 1 and last.isascii() and last.isalnum():
        out.append(last.lower())
    else:
        raise ValueError(f"모르는 키다: {last}")
    return "".join(out)


def process_name(pid: int) -> str:
    """그 프로세스의 실행 파일 이름 (`erp.exe`). 모르면 빈 글."""
    if sys.platform != "win32":
        return ""
    from ctypes import wintypes  # noqa: PLC0415

    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        buffer, size = ctypes.create_unicode_buffer(1024), wintypes.DWORD(1024)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return ""
        return Path(buffer.value).name
    finally:
        kernel32.CloseHandle(handle)


def foreground_is(window_handle: int) -> bool:
    """앞에 있는 최상위 창이 그 창인가 — 키 입력이 다른 창으로 새지 않게 (S4)."""
    if sys.platform != "win32":
        return False
    from ctypes import wintypes  # noqa: PLC0415

    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]
    user32.GetAncestor.restype = wintypes.HWND
    front = user32.GetForegroundWindow()
    root = user32.GetAncestor(front, 2) if front else None  # GA_ROOT
    return bool(root) and int(root or 0) == int(window_handle)


def point_process(x: int, y: int) -> int:
    """그 화면 점의 최상위 창을 가진 프로세스 — 좌표로 누르기 전에 본다 (S4: 잠금 화면·다른 앱을 누르지 않게).

    창이 아니라 **프로세스**로 보는 것은 펼친 목록·대화상자가 같은 앱의 다른 최상위 창이기 때문이다.
    """
    if sys.platform != "win32":
        return 0
    from ctypes import wintypes  # noqa: PLC0415

    user32 = ctypes.windll.user32
    user32.WindowFromPoint.argtypes = [wintypes.POINT]
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]
    user32.GetAncestor.restype = wintypes.HWND
    hit = user32.WindowFromPoint(wintypes.POINT(x, y))
    root = user32.GetAncestor(hit, 2) if hit else None
    if not root:
        return 0
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(root, ctypes.byref(pid))
    return int(pid.value)


# ─────────────────────────── 창 고르기 ───────────────────────────


def window_matches(spec: WindowSpec, *, title: str, class_name: str, process: str) -> bool:
    """창 조건 (C9 `window`) — 주어진 것을 **모두** 만족해야 한다."""
    if spec.empty:
        return False
    if spec.title and not re.search(spec.title, title):
        return False
    if spec.class_name and spec.class_name != class_name:
        return False
    return not (spec.process and spec.process.lower() != process.lower())


def find_windows(spec: WindowSpec) -> list[Any]:
    """조건에 맞는 **최상위** 창들 (UIA 컨트롤)."""
    import uiautomation as auto  # noqa: PLC0415

    found = []
    for one in auto.GetRootControl().GetChildren():
        try:
            title, class_name = one.Name or "", one.ClassName or ""
            process = process_name(one.ProcessId) if spec.process else ""
        except Exception:  # noqa: BLE001 — 사라지는 중인 창
            continue
        if window_matches(spec, title=title, class_name=class_name, process=process):
            found.append(one)
    return found


@dataclass
class AppLauncher:
    """앱 이름 → 그 PC의 실행 명령 (`desktop-apps.json`, C10). 경로는 PC마다 다르다 (ADR-0033)."""

    apps_file: Path | None = None

    def command(self, app: str) -> tuple[list[str], float] | None:
        if self.apps_file is None or not self.apps_file.is_file():
            return None
        try:
            table = json.loads(self.apps_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            log.warning("%s를 읽지 못했다: %s", self.apps_file.name, type(e).__name__)
            return None
        entry = table.get(app) if isinstance(table, dict) else None
        if not isinstance(entry, dict) or not isinstance(entry.get("command"), list) or not entry["command"]:
            return None
        return [str(one) for one in entry["command"]], float(entry.get("start_timeout_s") or START_TIMEOUT_S)

    def launch(self, command: list[str]) -> None:
        # 인자 리스트로 넘긴다 (CLAUDE.md §5). 업무 앱이라 콘솔을 띄우지 않는다.
        subprocess.Popen(command, close_fds=True)  # noqa: S603


# ─────────────────────────── 찾기·조작 ───────────────────────────


def _control_type(locator: LocatorSpec) -> str | None:
    """C8 `control_type`(UIA 이름, 예: `Edit`) → `uiautomation`의 `ControlTypeName`(`EditControl`)."""
    if not locator.control_type:
        return None
    name = locator.control_type
    return name if name.endswith("Control") else f"{name}Control"


def matches(locator: LocatorSpec, *, automation_id: str, class_name: str, name: str, control_type: str) -> bool:
    """로케이터 하나가 컨트롤 하나에 맞나 (C8 데스크톱 전략). **여기가 셀렉터가 사는 자리**다."""
    wanted_type = _control_type(locator)
    if wanted_type and wanted_type != control_type:
        return False
    if locator.type == "automation_id":
        return automation_id == locator.value
    if locator.type == "class_name":
        return class_name == locator.value
    if locator.type == "control_name":
        return name == locator.value if locator.exact else locator.value in name
    raise ValueError(f"데스크톱에서 쓸 수 없는 전략이다: {locator.type}")


@dataclass
class DesktopFinder:
    """붙은 창 하나에서 찾고 조작한다 (C8 `Finder`)."""

    window: Any
    app: str
    #: 가릴 업무 값 (입력한 값들). **스냅샷을 보내기 전에** 쓴다 (원칙 6).
    secrets: list[str] = field(default_factory=list)
    clock: Any = time.monotonic

    # ── 찾기 ──

    def find(self, locator: LocatorSpec, *, timeout_ms: int) -> Match:
        """창 안에서 맞는 것을 센다. **하나여야** 쓴다 — 둘째를 찾으면 거기서 멈춘다."""
        deadline = self.clock() + timeout_ms / 1000
        while True:
            try:
                hits = self._scan(locator)
            except ValueError as e:
                return Match(error=str(e))
            except Exception as e:  # noqa: BLE001 — 창이 닫혔을 수 있다
                return Match(error=type(e).__name__)
            if hits or self.clock() >= deadline:
                break
            time.sleep(POLL_S)
        if len(hits) != 1:
            return Match(count=len(hits))
        return Match(count=1, handle=hits[0])

    def _scan(self, locator: LocatorSpec) -> list[Any]:
        import uiautomation as auto  # noqa: PLC0415

        hits: list[Any] = []
        for control, _depth in auto.WalkControl(self.window, maxDepth=SEARCH_DEPTH):
            if matches(
                locator,
                automation_id=control.AutomationId or "",
                class_name=control.ClassName or "",
                name=control.Name or "",
                control_type=control.ControlTypeName or "",
            ):
                hits.append(control)
                if len(hits) > 1:
                    break
        return hits

    def locked(self) -> bool:
        return screen_locked()

    # ── 조작 ──

    def act(self, handle: Any, step: PlanStep, *, timeout_ms: int) -> str | None:
        """조작하거나 읽는다. **읽기 결과만** 글로 돌려준다 (C10 `text`)."""
        if screen_locked():
            raise ScreenLocked("화면이 잠겨 있습니다")
        action = step.action
        if action == "fill":
            self._fill(handle, str(step.value if step.value is not None else ""))
            return None
        if action == "click":
            self._click(handle)
            return None
        if action == "press":
            self._front(handle)
            import uiautomation as auto  # noqa: PLC0415

            auto.SendKeys(key_sequence(str(step.value)), waitTime=0.05)
            return None
        if action == "select":
            self._select(handle, str(step.value))
            return None
        if action == "read":
            return self.read_value(handle)
        if action == "read_table":
            return self._table(handle)
        if action == "read_options":
            return "\n".join(self._options(handle))
        if action == "read_selection":
            return self._selection(handle)
        raise ValueError(f"모르는 동작이다: {action}")

    def _front(self, handle: Any) -> None:
        """그 컨트롤에 포커스를 주고, **그 창이 앞에 왔는지** 확인한다 — 안 왔으면 치지 않는다."""
        handle.SetFocus()
        if not foreground_is(self.window.NativeWindowHandle):
            try:
                self.window.SetActive()
                handle.SetFocus()
            except Exception:  # noqa: BLE001
                pass
        if not foreground_is(self.window.NativeWindowHandle):
            raise RuntimeError("창을 앞으로 가져오지 못했습니다 — 다른 창에 입력하지 않으려고 멈춥니다")

    def _fill(self, handle: Any, value: str) -> None:
        """포커스 → 전부 고르기 → 키 입력 → **다시 읽어 확인** → 다르면 `SetValue` → 또 확인."""
        import uiautomation as auto  # noqa: PLC0415

        self.secrets.append(value)
        self._front(handle)
        auto.SendKeys("{Ctrl}a", waitTime=0.05)
        if value:
            type_text(value)
        else:
            auto.SendKeys("{Del}", waitTime=0.05)
        time.sleep(0.05)
        readable, got = self._value(handle)
        if not readable or _same(got, value):
            return
        # 키 입력으로 안 들어가는 글자(이모지 등)가 있다 — 값 패턴으로 넣고 다시 본다.
        pattern = handle.GetPattern(auto.PatternId.ValuePattern)
        if pattern is not None and not pattern.IsReadOnly:
            pattern.SetValue(value)
            time.sleep(0.05)
            readable, got = self._value(handle)
            if _same(got, value):
                return
        raise RuntimeError("입력값이 칸에 들어가지 않았습니다")

    def _click(self, handle: Any) -> None:
        """`Invoke`가 있으면 그것으로, 없으면 화면 좌표로 — **그 점이 이 창일 때만** 누른다."""
        import uiautomation as auto  # noqa: PLC0415

        invoke = handle.GetPattern(auto.PatternId.InvokePattern)
        if invoke is not None:
            invoke.Invoke()
            return
        toggle = handle.GetPattern(auto.PatternId.TogglePattern)
        if toggle is not None:
            toggle.Toggle()
            return
        self._click_point(handle)

    def _click_point(self, handle: Any) -> None:
        """화면 좌표로 누른다 — **그 점이 이 앱의 창일 때만** (잠금 화면·다른 앱을 누르지 않게)."""
        rect = handle.BoundingRectangle
        x, y = (rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2
        if point_process(x, y) != self.window.ProcessId:
            raise RuntimeError("누를 자리가 다른 창에 가려져 있습니다")
        handle.Click(x=x - rect.left, y=y - rect.top, simulateMove=False)

    def _select(self, handle: Any, value: str) -> None:
        """목록에서 그 이름의 항목을 고른다 — `Invoke`가 있으면 그것으로(콤보 상자는 이래야 값이 바뀐다),
        없으면 `Select`. 고른 뒤 **값이 그 항목이 됐는지 확인**한다. 항목이 없으면 값 패턴으로."""
        import uiautomation as auto  # noqa: PLC0415

        self.secrets.append(value)
        expand = handle.GetPattern(auto.PatternId.ExpandCollapsePattern)
        if expand is not None:
            expand.Expand()
            time.sleep(0.1)
        try:
            for control, _depth in auto.WalkControl(handle, maxDepth=4):
                if control.ControlTypeName != "ListItemControl" or control.Name != value:
                    continue
                # 패턴으로 고르고, 값이 안 바뀌면(Qt 콤보 상자) 그 항목을 눌러 본다.
                for choose in (self._invoke, self._select_item, self._click_point):
                    try:
                        choose(control)
                    except Exception:  # noqa: BLE001 — 다음 길로
                        continue
                    time.sleep(0.15)
                    readable, got = self._value(handle)
                    if not readable or got == value:
                        return
                    if expand is not None and expand.ExpandCollapseState != auto.ExpandCollapseState.Expanded:
                        expand.Expand()
                        time.sleep(0.1)
                raise RuntimeError("고른 항목이 칸에 들어가지 않았습니다")
        finally:
            if expand is not None and expand.ExpandCollapseState == auto.ExpandCollapseState.Expanded:
                expand.Collapse()
        pattern = handle.GetPattern(auto.PatternId.ValuePattern)
        if pattern is not None and not pattern.IsReadOnly:
            pattern.SetValue(value)
            return
        raise RuntimeError("고를 항목이 없습니다")

    def _invoke(self, control: Any) -> None:
        import uiautomation as auto  # noqa: PLC0415

        invoke = control.GetPattern(auto.PatternId.InvokePattern)
        if invoke is None:
            raise RuntimeError("Invoke 없음")
        invoke.Invoke()

    def _select_item(self, control: Any) -> None:
        import uiautomation as auto  # noqa: PLC0415

        item = control.GetPattern(auto.PatternId.SelectionItemPattern)
        if item is None:
            raise RuntimeError("SelectionItem 없음")
        item.Select()

    # ── 읽기 ──

    def _value(self, handle: Any) -> tuple[bool, str]:
        """`(읽을 수 있나, 값)` — 값 패턴 → 범위 값 → 없음."""
        import uiautomation as auto  # noqa: PLC0415

        pattern = handle.GetPattern(auto.PatternId.ValuePattern)
        if pattern is not None:
            return True, str(pattern.Value or "")
        ranged = handle.GetPattern(auto.PatternId.RangeValuePattern)
        if ranged is not None:
            number = ranged.Value
            return True, str(int(number)) if float(number).is_integer() else str(number)
        return False, ""

    def read_value(self, handle: Any) -> str:
        """읽기 (C10 `read`) — 값 → 글 → 이름 순. 보이는 글을 그대로 돌려준다."""
        import uiautomation as auto  # noqa: PLC0415

        readable, value = self._value(handle)
        if readable and (value or handle.ControlTypeName not in CONTENT_IN_NAME):
            return value
        text = handle.GetPattern(auto.PatternId.TextPattern)
        if text is not None:
            return str(text.DocumentRange.GetText(-1))
        return str(handle.Name or "")

    def _table(self, handle: Any) -> str:
        """표는 **TSV**로 (C10). 격자 패턴이 있으면 칸으로, 없으면 줄(자식)로."""
        import uiautomation as auto  # noqa: PLC0415

        grid = handle.GetPattern(auto.PatternId.GridPattern)
        rows: list[str] = []
        if grid is not None:
            for r in range(grid.RowCount):
                cells = [grid.GetItem(r, c) for c in range(grid.ColumnCount)]
                rows.append("\t".join(self.read_value(cell).strip() for cell in cells if cell is not None))
            return "\n".join(rows)
        for row in handle.GetChildren():
            cells = row.GetChildren()
            rows.append("\t".join(self.read_value(c).strip() for c in cells) if cells else self.read_value(row))
        return "\n".join(rows)

    def _options(self, handle: Any) -> list[str]:
        import uiautomation as auto  # noqa: PLC0415

        expand = handle.GetPattern(auto.PatternId.ExpandCollapsePattern)
        if expand is not None:
            expand.Expand()
            time.sleep(0.1)
        try:
            return [
                str(control.Name)
                for control, _depth in auto.WalkControl(handle, maxDepth=4)
                if control.ControlTypeName == "ListItemControl"
            ]
        finally:
            if expand is not None:
                expand.Collapse()

    def _selection(self, handle: Any) -> str:
        import uiautomation as auto  # noqa: PLC0415

        selection = handle.GetPattern(auto.PatternId.SelectionPattern)
        if selection is not None:
            return "\n".join(str(one.Name) for one in selection.GetSelection())
        return self.read_value(handle)

    # ── 치유·표시 ──

    def snapshot(self) -> tuple[str, str]:
        """치유에 보낼 `(트리, "")` — 창의 UIA 트리를 줄글로, **입력한 값은 가려서** (C8·원칙 6)."""
        import uiautomation as auto  # noqa: PLC0415

        lines = []
        try:
            for control, depth in auto.WalkControl(self.window, includeTop=True, maxDepth=12):
                lines.append(
                    f'{"  " * depth}{control.ControlTypeName} "{control.Name}"'
                    f" aid={control.AutomationId} class={control.ClassName}"
                )
                if sum(len(one) for one in lines) > SNAPSHOT_MAX:
                    break
        except Exception:  # noqa: BLE001 — 스냅샷을 못 떠도 치유는 시도할 수 있다
            pass
        return masked("\n".join(lines), self.secrets)[:SNAPSHOT_MAX], ""

    def url(self) -> str:
        """`desktop:<앱>` — 창 제목에는 문서 이름 같은 업무 값이 있을 수 있어 싣지 않는다 (C10)."""
        return f"desktop:{self.app}"


def _same(got: str, wanted: str) -> bool:
    """입력 확인 — 칸이 줄바꿈을 `\\r`로 돌려주는 일이 있다."""
    return got.replace("\r\n", "\n").replace("\r", "\n") == wanted.replace("\r\n", "\n")


# ─────────────────────────── 백엔드 ───────────────────────────


@dataclass
class DesktopBackend:
    """C10 `Backend` — 세션마다 붙은 창 하나 (ADR-0033).

    **창을 닫지 않는다.** 사용자의 업무 앱이다 — 세션이 끝나면 놓기만 한다.
    """

    launcher: AppLauncher = field(default_factory=AppLauncher)
    clock: Any = time.monotonic
    _finders: dict[str, DesktopFinder] = field(default_factory=dict)

    def __post_init__(self) -> None:
        ensure_per_monitor_dpi()

    def open(self, request: SessionRequest, plan: Any = None) -> str:
        window_spec: WindowSpec | None = getattr(plan, "window", None)
        if plan is None or window_spec is None or window_spec.empty:
            # 계획이 없으면(앱 주소·키가 없음) 어느 창인지 모른다 — 스텝이 받는 것과 같은 코드다.
            raise DesktopProblem(422, "unknown_semantic_key", "이 세션에 계획이 없어 어느 창인지 모릅니다")
        app = request.app or getattr(plan, "app", None) or ""
        window = self._attach(window_spec)
        if window is None:
            window = self._launch(app, window_spec)
        self._finders[request.business_key] = DesktopFinder(window=window, app=app or "?", clock=self.clock)
        return f"desktop:{app or '?'}"

    def _attach(self, spec: WindowSpec) -> Any:
        found = find_windows(spec)
        if len(found) > 1:
            raise DesktopProblem(
                409, WINDOW_AMBIGUOUS, "창 조건에 맞는 창이 여럿입니다", {"count": len(found)}
            )
        return found[0] if found else None

    def _launch(self, app: str, spec: WindowSpec) -> Any:
        """창이 없다 — 그 PC의 실행 명령으로 띄우고 창이 생기기를 기다린다 (C10)."""
        planned = self.launcher.command(app) if app else None
        if planned is None:
            raise DesktopProblem(
                409, APP_NOT_RUNNING, f"「{app or '?'}」 창이 없고 띄우는 방법이 설정되어 있지 않습니다", {"app": app}
            )
        command, timeout_s = planned
        self.launcher.launch(command)
        deadline = self.clock() + timeout_s
        while self.clock() < deadline:
            found = self._attach(spec)
            if found is not None:
                return found
            time.sleep(0.25)
        raise DesktopProblem(409, APP_NOT_RUNNING, f"「{app}」을 띄웠지만 창이 생기지 않았습니다", {"app": app})

    def finder(self, business_key: str) -> DesktopFinder | None:
        return self._finders.get(business_key)

    def goto(self, session_id: str, url: str) -> str:
        raise DesktopProblem(422, "value_not_allowed", "데스크톱 화면에는 주소가 없습니다")

    def close(self, session_id: str) -> None:
        # 사용자의 앱이다 — 닫지 않고 놓기만 한다.
        self._finders.clear()


__all__ = [
    "APPS_FILE",
    "APP_NOT_RUNNING",
    "WINDOW_AMBIGUOUS",
    "AppLauncher",
    "DesktopBackend",
    "DesktopFinder",
    "DesktopProblem",
    "ScreenLocked",
    "available",
    "ensure_per_monitor_dpi",
    "find_windows",
    "key_sequence",
    "matches",
    "screen_locked",
    "type_text",
    "window_matches",
]
