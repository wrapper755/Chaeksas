"""Qt 트리 → QtWebEngine 캔버스 드래그가 **가로채지는가**.

확인할 것 셋.
1. `QWebEngineView`에 놓은 드롭이 **우리 쪽에 오는가**. 뷰는 이벤트를 내부 자식 위젯
   (`focusProxy()`)에 넘기므로 뷰에 `dropEvent`를 달면 불리지 않는다는 말이 있다.
2. 자식이 **언제 생기는가** — `__init__`에 없으면 `ChildAdded`를 기다려야 한다.
3. 드롭 자리(위젯 좌표)가 페이지의 CSS 픽셀과 맞는가 (devicePixelRatio).
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

from PySide6.QtCore import QCoreApplication, QEvent, QMimeData, QPoint, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView

MIME = "application/x-chaeksas-resource"
seen: list[str] = []


class Probe(QWebEngineView):
    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.installEventFilter(self)
        self.children_at_init = [type(c).__name__ for c in self.children()]
        self.armed: list[str] = []

    def eventFilter(self, obj, event):  # noqa: N802
        kind = event.type()
        if kind == QEvent.Type.ChildAdded and obj is self:
            child = event.child()
            if child is not None and child.isWidgetType():
                child.setAcceptDrops(True)
                child.installEventFilter(self)
                self.armed.append(type(child).__name__)
        elif obj is not self and kind in (
            QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop
        ):
            seen.append(f"{kind.name} on {type(obj).__name__}")
            if event.mimeData().hasFormat(MIME):
                event.acceptProposedAction()
                return True
        return super().eventFilter(obj, event)

    # 뷰 자신에게도 달아 둬서 **어느 쪽으로 오는지** 본다.
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        seen.append("dragEnterEvent on view")
        event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        seen.append("dropEvent on view")
        event.acceptProposedAction()


def main() -> int:
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication.instance() or QApplication([])
    view = Probe()
    view.resize(800, 600)
    view.setHtml("<body style='margin:0'><div id=canvas style='width:100%;height:100%'></div></body>")
    view.show()
    for _ in range(50):
        app.processEvents()

    print("① __init__ 때의 자식:", view.children_at_init)
    print("② 뒤에 생겨 이벤트 필터를 단 자식:", view.armed)
    print("   focusProxy():", type(view.focusProxy()).__name__ if view.focusProxy() else None)

    data = QMimeData()
    data.setData(MIME, b'{"bpmn":"bpmn:ServiceTask"}')
    at = QPoint(321, 234)
    target = view.focusProxy() or view
    for kind, cls in (("enter", QDragEnterEvent), ("drop", QDropEvent)):
        event = cls(at, Qt.DropAction.CopyAction, data, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(target, event)
        print(f"③ {kind}: isAccepted={event.isAccepted()}")
    print("④ 본 것:", seen)
    print("⑤ devicePixelRatio:", view.devicePixelRatio())
    return 0


if __name__ == "__main__":
    sys.exit(main())
