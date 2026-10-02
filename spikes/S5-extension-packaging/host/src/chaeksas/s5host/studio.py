"""Studio 흉내 부분: QtWebEngine. Bot UI 묶음에는 들어가지 않게 app.py는 이 모듈을 문자열로만 부른다."""

import time

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWebEngineWidgets import QWebEngineView


def check(app: object) -> str:
    v = QWebEngineView()
    loop = QEventLoop()
    result: dict[str, object] = {}
    v.loadFinished.connect(lambda ok: (result.setdefault("ok", ok), loop.quit()))
    t = time.perf_counter()
    v.setHtml("<html><body><h1 id=h>웹엔진 한글</h1></body></html>")
    v.show()
    QTimer.singleShot(30000, loop.quit)
    loop.exec()
    ms = round((time.perf_counter() - t) * 1000)
    v.close()
    if not result.get("ok"):
        raise RuntimeError("loadFinished 실패 또는 30초 초과")
    return f"loaded in {ms}ms"
