"""내부 렌더 위젯이 뷰를 꽉 채우나 — 채우면 위젯 좌표 = 페이지 CSS 픽셀."""
from __future__ import annotations
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
from PySide6.QtCore import QCoreApplication, QPoint, Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView

QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
app = QApplication.instance() or QApplication([])
view = QWebEngineView()
view.resize(640, 480)
view.setHtml("<body style='margin:0'><div id=canvas style='width:100%;height:100%'></div></body>")
view.show()
for _ in range(80):
    app.processEvents()
proxy = view.focusProxy()
print("뷰:", view.size().toTuple(), "| 내부 위젯:", proxy.size().toTuple(),
      "| 왼쪽 위:", proxy.mapTo(view, QPoint(0, 0)).toTuple(),
      "| DPR:", view.devicePixelRatio())
