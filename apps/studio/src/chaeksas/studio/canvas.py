"""캔버스 — QtWebEngine 안의 bpmn-js ([ADR-0022](../../../../../docs/decisions/0022-studio-canvas.md)).

**Python ↔ JS는 QWebChannel 하나**다. `runJavaScript`가 Promise 결과를 받지 못해서, Python이
`window.chk(요청 id, 함수 이름, 인자 JSON)`을 부르고 JS가 `bridge.result(요청 id, 결과 JSON)`으로
돌려준다. 요청 id로 짝을 맞춘다.

**오프라인이다** — 자원은 모두 앱과 함께 있는 로컬 파일이고 `LocalContentCanAccessRemoteUrls`를
끈다 (업무 PC는 인터넷이 막혀 있을 수 있다, ADR-0029).

**끌어다 놓기는 내부 렌더 위젯에서 가로챈다** ([ADR-0044](../../../../../docs/decisions/0044-canvas-drag-and-drop.md)) —
`QWebEngineView`는 드래그 이벤트를 자식 위젯에 넘기므로 뷰에 `dropEvent`를 달면 **영원히
불리지 않는다**. 그 자식은 `__init__`에 없어 `ChildAdded`를 보고 생길 때 단다. 캔버스는
**무엇이 떨어졌는지 모른다** — 받을 형식은 부르는 쪽이 알려 주고(`accept_drops_of`), 글과
자리만 `dropped`로 올려 보낸다.

**그림도 창의 테마를 따른다** ([ADR-0101](../../../../../docs/decisions/0101-canvas-follows-theme.md)) —
bpmn-js가 선·채움·글자를 CSS 변수로 그리고, 캔버스가 토큰 색을 그 변수에 넣는다(`CANVAS_TOKENS`).
페이지가 뜰 때와 앱의 팔레트가 바뀔 때(`apply_theme`) 넣으므로 테마를 바꿔도 그림을 다시
읽지 않는다 — 실행 취소·「저장 안 한 변경」이 그대로다.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QChildEvent, QEvent, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QDropEvent
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QWidget

from chaeksas.qt.theme import THEME_DARK, current
from chaeksas.qt.theme.tokens import colors as token_colors

log = logging.getLogger(__name__)

#: 캔버스가 사는 곳 (`index.html`·`view.html`·`bpm-moddle.js`는 우리 것, `vendor/`는 생성물이다).
WEB_DIR = Path(__file__).resolve().parent / "web"

#: 편집하는 페이지 (bpmn-js **모델러**).
EDIT_PAGE = "index.html"
#: 읽기 전용으로 보는 페이지 (bpmn-js **뷰어** — 편집 기능이 아예 없다, ADR-0051).
VIEW_PAGE = "view.html"

#: 한 번의 부름을 기다리는 기본 시간 (ms). bpmn-js가 큰 그림을 읽을 때를 넉넉히 잡는다.
DEFAULT_TIMEOUT_MS = 15_000

#: 페이지의 CSS 변수 ↔ 토큰 (ADR-0101). 페이지는 이 변수만 쓰고 색 값을 적지 않는다.
CANVAS_TOKENS = {
    "--bpm-surface": "bg.surface",
    "--bpm-subtle": "bg.subtle",
    "--bpm-line": "text.primary",
    "--bpm-text": "text.primary",
    "--bpm-text-muted": "text.muted",
    "--bpm-border": "border.default",
    "--bpm-border-strong": "border.strong",
    "--bpm-accent": "primary",
    "--bpm-accent-subtle": "primary.subtle",
}


def canvas_colors(theme: str) -> dict[str, str]:
    """그 테마에서 페이지에 넣을 `{CSS 변수: 색}`."""
    found = token_colors(dark=theme == THEME_DARK)
    return {name: found[token] for name, token in CANVAS_TOKENS.items()}


class CanvasError(RuntimeError):
    """캔버스가 돌려준 실패 (JS 쪽 예외·시간 초과)."""


class Bridge(QObject):
    """JS가 부르는 쪽. 슬롯 이름이 그대로 JS의 `bridge.<이름>`이 된다."""

    #: 캔버스가 뜨고 채널이 이어졌다.
    opened = Signal()
    #: 「저장 안 한 변경」이 생겼다 (STU-01 제목의 `*`).
    dirtied = Signal(bool)
    #: 하나만 골랐을 때 그 노드 id, 아니면 빈 글 (STU-04 속성 패널이 받는다).
    selected = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._waiting: dict[str, Callable[[dict[str, Any]], None]] = {}

    def expect(self, request_id: str, then: Callable[[dict[str, Any]], None]) -> None:
        self._waiting[request_id] = then

    def drop(self, request_id: str) -> None:
        self._waiting.pop(request_id, None)

    @Slot()
    def ready(self) -> None:
        self.opened.emit()

    @Slot(bool)
    def changed(self, dirty: bool) -> None:
        self.dirtied.emit(dirty)

    @Slot(str)
    def picked(self, node_id: str) -> None:
        self.selected.emit(node_id)

    @Slot(str, str)
    def result(self, request_id: str, payload: str) -> None:
        then = self._waiting.pop(request_id, None)
        if then is None:
            return  # 시간이 지나 버린 요청 — 조용히 버린다
        try:
            then(json.loads(payload))
        except ValueError:
            then({"ok": False, "error": "캔버스 응답이 JSON이 아니다"})


class Canvas(QWebEngineView):
    """BPMN 편집기 하나. 부르는 쪽은 `call()`(비동기)이나 `call_sync()`를 쓴다."""

    opened = Signal()
    dirtied = Signal(bool)
    selected = Signal(str)
    #: 무언가 떨어졌다 — `(실린 글, x, y)`. **캔버스는 뜻을 모른다** (ADR-0044).
    dropped = Signal(str, int, int)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self._bridge = Bridge()
        self._bridge.opened.connect(self.opened)
        self._bridge.dirtied.connect(self.dirtied)
        self._bridge.selected.connect(self.selected)
        self._next = 0
        self._live = False
        self._drop_format = ""
        self.opened.connect(self._mark_live)
        # 내부 렌더 위젯은 **뒤에 생긴다** — 생길 때 거기에 필터를 단다 (ADR-0044).
        self.installEventFilter(self)

        channel = QWebChannel(self)
        channel.registerObject("bridge", self._bridge)
        self.page().setWebChannel(channel)
        # 오프라인 (ADR-0022·0029) — 로컬 페이지가 바깥을 부르지 못하게 한다.
        self.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        self.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        self.loadFinished.connect(lambda _ok: self.paint_theme())
        self.paint_theme()

    def theme(self) -> str:
        """지금 앱의 테마 (`light`/`dark`). 앱이 없으면 밝게."""
        app = QApplication.instance()
        return current(app) if isinstance(app, QApplication) else "light"

    def paint_theme(self) -> None:
        """앱의 테마 색을 페이지에 넣는다 — 뜰 때·팔레트가 바뀔 때 (ADR-0101)."""
        colors = canvas_colors(self.theme())
        # 페이지가 뜨기 전 바탕도 같은 색이다 — 어두운 창에서 흰 판이 번쩍이지 않게.
        self.page().setBackgroundColor(QColor(colors["--bpm-surface"]))
        self.page().runJavaScript(f"window.chkTheme && window.chkTheme({json.dumps(colors)})")

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 — Qt 이름 그대로
        # `apply_theme`이 앱 팔레트를 바꾸면 모든 위젯이 이것을 받는다 — 「시스템 따름」도 같은 길이다.
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange):
            self.paint_theme()
        super().changeEvent(event)

    def _mark_live(self) -> None:
        self._live = True

    @property
    def live(self) -> bool:
        """캔버스가 뜨고 채널이 이어졌나."""
        return self._live

    # ── 끌어다 놓기 (ADR-0044) ──

    def accept_drops_of(self, mime_format: str) -> None:
        """이 형식의 드롭만 받는다. **캔버스는 그것이 무엇인지 모른다** — 부르는 쪽이 안다."""
        self._drop_format = mime_format
        self.setAcceptDrops(bool(mime_format))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 — Qt 이름 그대로
        """내부 렌더 위젯의 드래그를 가로챈다 — **뷰의 `dropEvent`는 불리지 않는다.**

        우리 형식이 아니면 `False`를 돌려 **가던 길로 보낸다** — 페이지 안의 bpmn-js 팔레트
        드래그와 바깥에서 끌어 온 파일이 그대로 Chromium으로 간다.
        """
        if isinstance(event, QChildEvent) and event.added() and watched is self:
            child = event.child()
            if isinstance(child, QWidget):
                child.setAcceptDrops(True)
                child.installEventFilter(self)
        elif (
            # `QDragEnterEvent`·`QDragMoveEvent`가 모두 `QDropEvent`의 자손이다 — 셋을 한 번에 본다.
            isinstance(event, QDropEvent)
            and watched is not self
            and self._drop_format
            and event.mimeData().hasFormat(self._drop_format)
        ):
            event.acceptProposedAction()
            if event.type() == QEvent.Type.Drop:
                raw = event.mimeData().data(self._drop_format).data()
                payload = bytes(raw).decode("utf-8", "replace")
                at = event.position().toPoint()
                self.dropped.emit(payload, at.x(), at.y())
            return True
        return super().eventFilter(watched, event)

    def boot(self, web_dir: Path | None = None, *, page: str = EDIT_PAGE) -> None:
        """페이지를 띄운다. 끝나면 `opened`가 울린다.

        `page`를 `VIEW_PAGE`로 주면 **읽기 전용 뷰어**다 (ADR-0051) — 다리 규약은 같고,
        모델러에게만 있는 것을 물으면 그 페이지가 「모르는 함수다」로 답한다.
        """
        page_path = (web_dir or WEB_DIR) / page
        if not page_path.is_file():
            raise CanvasError(
                f"캔버스 파일이 없다: {page_path} — "
                "`pnpm --filter @chaeksas/bpmn-canvas build` (ADR-0029)"
            )
        self.load(QUrl.fromLocalFile(str(page_path)))

    # ── 부르기 ──

    def call(
        self,
        name: str,
        *args: Any,
        then: Callable[[dict[str, Any]], None] | None = None,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ) -> str:
        """캔버스의 함수 하나를 부른다. 결과는 `then`으로 온다 (요청 id를 돌려준다)."""
        self._next += 1
        request_id = f"r{self._next}"

        done = False

        def finish(found: dict[str, Any]) -> None:
            nonlocal done
            if done:
                return
            done = True
            if then is not None:
                then(found)

        def gave_up() -> None:
            self._bridge.drop(request_id)
            finish({"ok": False, "error": f"캔버스가 {timeout_ms}ms 안에 답하지 않았다: {name}"})

        self._bridge.expect(request_id, finish)
        QTimer.singleShot(timeout_ms, gave_up)
        arguments = json.dumps(list(args), ensure_ascii=False)
        call = f"window.chk({json.dumps(request_id)}, {json.dumps(name)}, {json.dumps(arguments)})"
        self.page().runJavaScript(call)
        return request_id

    def call_sync(self, name: str, *args: Any, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> dict[str, Any]:
        """답이 올 때까지 기다린다 — **저장처럼 결과가 바로 필요한 자리**와 시험에서만 쓴다.

        안쪽에서 이벤트 루프를 돌리므로 화면이 반응은 하지만, 부르는 중에 또 부르지 않게 한다.
        """
        from PySide6.QtCore import QEventLoop  # noqa: PLC0415

        loop = QEventLoop()
        box: dict[str, Any] = {}

        def done(found: dict[str, Any]) -> None:
            box.update(found)
            loop.quit()

        self.call(name, *args, then=done, timeout_ms=timeout_ms)
        loop.exec()
        if not box.get("ok"):
            raise CanvasError(str(box.get("error") or f"캔버스 호출이 실패했다: {name}"))
        return box

    # ── 자주 쓰는 것 ──

    def load_xml(self, xml: str, *, then: Callable[[dict[str, Any]], None] | None = None) -> None:
        self.call("importXML", xml, then=then)

    def save_xml(self) -> str:
        return str(self.call_sync("saveXML")["xml"])

    def create_empty(self, process_id: str, name: str) -> None:
        self.call_sync("createEmpty", process_id, name)

    def clear(self) -> None:
        """그림을 내린다 (STU-01 「BPM 프로세스 닫기」)."""
        self.call_sync("clear")

    def create_task(
        self,
        bpmn: str,
        name: str,
        chk: dict[str, str],
        *,
        attrs: dict[str, str] | None = None,
        at: tuple[int, int] | None = None,
        then: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        """STU-03 「캔버스에 추가」 — 노드 하나를 만든다. **실행 취소는 한 걸음**이다.

        `chk`는 `properties`·`setProperties`와 같은 **`{요소 이름: JSON 글}`**이다.

        `attrs`는 **그냥 BPMN 속성**이다 (`calledElement` 같은 것, ADR-0051) — `bpm:*`가 아니라
        요소 자신의 칸이라 만들 때 함께 넣는다.

        `at`은 **화면 자리**(캔버스 위젯의 CSS 픽셀)다 — 끌어다 놓은 자리다 (ADR-0044).
        다이어그램 좌표로 바꾸는 일은 **JS가** 한다(축척·스크롤을 아는 쪽이 하나다). 주지
        않으면 지금처럼 보이는 자리의 빈 곳을 찾는다 — **만드는 길은 하나**여서 실행 취소가
        양쪽에서 한 걸음이다.
        """
        spec: dict[str, Any] = {"bpmn": bpmn, "name": name, "chk": chk}
        if attrs:
            spec["attrs"] = attrs
        if at is not None:
            spec["at"] = {"x": at[0], "y": at[1]}
        self.call("createTask", spec, then=then)

    def append_chain(self, specs: list[dict[str, Any]]) -> list[str]:
        """빈 그림의 시작 이벤트 뒤에 노드들을 **이어 붙인다** (STU-06a, ADR-0071).

        `specs` 한 줄은 `create_task`와 같은 `{bpmn, name, chk, attrs?}`다. 만든 id들을 돌려준다.
        """
        return [str(one) for one in self.call_sync("appendChain", specs)["ids"]]

    def delegate_node(self, node_id: str, *, name: str, called: str, call: str) -> str:
        """노드 하나를 **위임 호출로 바꾼다** (STU-06a) — 흐름·경계는 그대로, 실행 취소 한 걸음.

        `call`은 `bpm:call` 본문(JSON 글)이다. 바뀐 노드의 id를 돌려준다.
        """
        found = self.call_sync("delegateNode", node_id, {"name": name, "calledElement": called, "chk": {"call": call}})
        if not found.get("found"):
            raise CanvasError(f"그 노드가 그림에 없다: {node_id}")
        return str(found["id"])

    def mark(self, states: dict[str, str]) -> None:
        """실행 중 노드 색 (STU-09). `states`는 `{노드 id: running|done|failed|waiting}`."""
        self.call("mark", states)


__all__ = [
    "DEFAULT_TIMEOUT_MS",
    "EDIT_PAGE",
    "VIEW_PAGE",
    "WEB_DIR",
    "Bridge",
    "Canvas",
    "CanvasError",
]
