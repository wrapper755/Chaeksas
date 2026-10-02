# /// script
# requires-python = ">=3.12"
# dependencies = ["pyside6>=6.8"]
# ///
"""S3 Studio 셸: PySide6 + QtWebEngine + bpmn-js. 저장·불러오기 왕복을 확인한다.

    uv run spikes/S3-studio-shell/shell.py auto      # 업무 예제 BPMN 전부 불러오기→저장→원본과 비교, 끝나면 닫힘
    uv run spikes/S3-studio-shell/shell.py           # 직접 써 보기 (파일 메뉴: 예제 열기·저장)

먼저 `cd spikes/S3-studio-shell/web && npm install` (bpmn-js를 node_modules에 받는다).
"""

import json
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

T0 = time.perf_counter()

from PySide6.QtCore import QEventLoop, QObject, QTimer, QUrl, Signal, Slot  # noqa: E402
from PySide6.QtGui import QAction, QKeySequence  # noqa: E402
from PySide6.QtWebChannel import QWebChannel  # noqa: E402
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings  # noqa: E402
from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: E402
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow, QMessageBox  # noqa: E402

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
EXAMPLES = ROOT / "docs" / "08-business-examples" / "bpmn"
OUT = HERE / "outputs"
IMPORT_DONE = time.perf_counter()


class Bridge(QObject):
    """JS → Python. 이름이 index.html의 bridge.* 호출과 맞아야 한다."""

    readySig = Signal()
    resultSig = Signal(str, str)
    changedSig = Signal(bool)

    @Slot()
    def ready(self) -> None:
        self.readySig.emit()

    @Slot(str, str)
    def result(self, req_id: str, payload: str) -> None:
        self.resultSig.emit(req_id, payload)

    @Slot(bool)
    def changed(self, dirty: bool) -> None:
        self.changedSig.emit(dirty)


class Page(QWebEnginePage):
    """JS 콘솔을 모은다 (가상 함수는 하위 클래스로만 덮을 수 있다)."""

    console: list[str] = []

    def javaScriptConsoleMessage(self, level: Any, message: str, line: int, source: str) -> None:  # noqa: N802
        self.console.append(f"{level.name}: {message} ({Path(source).name}:{line})")


class Canvas(QWebEngineView):
    def __init__(self) -> None:
        super().__init__()
        self.setPage(Page(self))
        self.console = Page.console
        self.bridge = Bridge()
        self.channel = QWebChannel(self)
        self.channel.registerObject("bridge", self.bridge)
        self.page().setWebChannel(self.channel)
        s = self.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)  # 오프라인 보장
        self._results: dict[str, dict[str, Any]] = {}
        self._seq = 0
        self.bridge.resultSig.connect(lambda rid, p: self._results.__setitem__(rid, json.loads(p)))

    def open_page(self, moddle: bool, timeout: float = 30) -> float:
        t0 = time.perf_counter()
        loop = QEventLoop()
        self.bridge.readySig.connect(loop.quit)
        url = QUrl.fromLocalFile(str(HERE / "web" / "index.html"))
        url.setQuery("moddle=1" if moddle else "")
        self.load(url)
        QTimer.singleShot(int(timeout * 1000), loop.quit)
        loop.exec()
        self.bridge.readySig.disconnect(loop.quit)
        return time.perf_counter() - t0

    def call(self, name: str, *args: Any, timeout: float = 20) -> dict[str, Any]:
        self._seq += 1
        rid = str(self._seq)
        self.page().runJavaScript(f"window.chk({json.dumps(rid)}, {json.dumps(name)}, {json.dumps(json.dumps(args))})")
        deadline = time.perf_counter() + timeout
        while rid not in self._results:
            if time.perf_counter() > deadline:
                return {"ok": False, "error": f"timeout {name}"}
            QApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        return self._results.pop(rid)


# ---- XML 비교 ---------------------------------------------------------------

IGNORED_ATTRS = {"exporter", "exporterVersion"}  # bpmn-js가 자기 이름으로 바꾼다
# BPMN 스키마 기본값 — bpmn-js는 기본값과 같은 속성을 쓰지 않는다. 생략과 같은 뜻이다
SCHEMA_DEFAULTS = {"isSequential": "false", "cancelActivity": "true", "isInterrupting": "true",
                   "parallelMultiple": "false", "isForCompensation": "false", "startQuantity": "1",
                   "completionQuantity": "1", "isClosed": "false", "triggeredByEvent": "false",
                   "instantiate": "false"}


def normalize(e: ET.Element) -> ET.Element:
    """의미가 같으면 같은 나무가 되게 한다: id 있는 자식은 id 순(bpmn-js가 DI 순서를 바꾼다),
    id 없는 자식(경로점·본문 요소)은 원래 순서 유지, 무시할 속성·기본값과 같은 속성은 뺀다."""
    n = ET.Element(e.tag, {k: v for k, v in e.attrib.items()
                           if k not in IGNORED_ATTRS and SCHEMA_DEFAULTS.get(k) != v})
    n.text = (e.text or "").strip()
    kids = [normalize(c) for c in e]
    n.extend([c for c in kids if not c.get("id")] + sorted((c for c in kids if c.get("id")), key=lambda c: c.get("id")))
    return n


def diff(a: ET.Element, b: ET.Element, path: str = "", out: list[str] | None = None) -> list[str]:
    """normalize()한 두 나무의 차이를 사람이 읽게."""
    out = [] if out is None else out
    here = f"{path}/{a.tag.split('}')[-1]}" + (f"[{a.get('id')}]" if a.get("id") else "")
    if a.tag != b.tag or a.get("id") != b.get("id"):
        out.append(f"{here}: 요소 다름 {b.tag.split('}')[-1]}[{b.get('id')}]")
        return out
    if a.attrib != b.attrib:
        out.append(f"{here}: 속성 {sorted(set(a.attrib.items()) ^ set(b.attrib.items()))[:4]}")
    if a.text != b.text:
        out.append(f"{here}: 본문 다름")
    ca, cb = list(a), list(b)
    if len(ca) != len(cb):
        ta, tb = {c.tag.split('}')[-1] for c in ca}, {c.tag.split('}')[-1] for c in cb}
        out.append(f"{here}: 자식 {len(ca)} ≠ {len(cb)} (없어짐 {sorted(ta - tb)}, 생김 {sorted(tb - ta)})")
    for x, y in zip(ca, cb, strict=False):
        diff(x, y, here, out)
    return out


def compare(original: str, saved: str) -> list[str]:
    return diff(normalize(ET.fromstring(original.encode("utf-8"))), normalize(ET.fromstring(saved.encode("utf-8"))))


def roundtrip(canvas: Canvas, src: Path) -> dict[str, Any]:
    xml = src.read_text(encoding="utf-8")
    imp = canvas.call("importXML", xml)
    if not imp["ok"]:
        return {"file": src.name, "import": imp}
    saved = canvas.call("saveXML")
    if not saved["ok"]:
        return {"file": src.name, "save": saved}
    d = compare(xml, saved["xml"])
    return {"file": src.name, "import_ms": imp["ms"], "warnings": imp["warnings"][:3], "n_warnings": len(imp["warnings"]),
            "identical": not d, "diffs": d[:6], "n_diffs": len(d), "saved_xml": saved["xml"]}


def memory_mb() -> dict[str, int]:
    """이 프로세스와 QtWebEngineProcess(크로미움 자식 프로세스들)의 작업 집합 합 (tasklist)."""
    import csv  # noqa: PLC0415
    import os  # noqa: PLC0415
    import subprocess  # noqa: PLC0415

    def rows(flt: str) -> list[list[str]]:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH", "/FI", flt], capture_output=True, text=True,
                             encoding="mbcs", check=False).stdout
        return [r for r in csv.reader(out.splitlines()) if len(r) >= 5]

    def mb(r: list[str]) -> int:
        return int("".join(ch for ch in r[4] if ch.isdigit())) // 1024

    web = rows("IMAGENAME eq QtWebEngineProcess.exe")
    me = rows(f"PID eq {os.getpid()}")
    return {"python": sum(map(mb, me)), "webengine": sum(map(mb, web)), "webengine_procs": len(web)}


def auto(app: QApplication) -> None:
    OUT.mkdir(exist_ok=True)
    win = QMainWindow()
    canvas = Canvas()
    win.setCentralWidget(canvas)
    win.resize(1400, 860)
    win.show()
    report: dict[str, Any] = {"qt_import_s": round(IMPORT_DONE - T0, 2)}
    files = sorted(EXAMPLES.glob("*.bpmn"))
    for moddle in (False, True):
        key = "moddle" if moddle else "plain"
        report[f"{key}_page_ready_s"] = round(canvas.open_page(moddle), 2)
        report[f"{key}_stats"] = canvas.call("stats")  # 페이지가 정말 그 모드로 떴는지
        if key == "plain":
            report["first_window_s"] = round(time.perf_counter() - T0, 2)
        rows = [roundtrip(canvas, f) for f in files]
        if moddle:
            # 한글 라벨 편집 → 저장에 들어가는가
            canvas.call("importXML", files[0].read_text(encoding="utf-8"))
            first_task = next(e.get("id") for e in ET.parse(files[0]).iter() if e.tag.endswith("serviceTask"))
            canvas.call("setLabel", first_task, "한글 라벨 ✓ 편집")
            saved = canvas.call("saveXML")["xml"]
            report["korean_label_saved"] = 'name="한글 라벨 ✓ 편집"' in saved
            app.processEvents()
            canvas.grab().save(str(OUT / "canvas.png"))
        for r in rows:
            if "saved_xml" in r:
                (OUT / f"saved-{key}-{r['file']}").write_text(r.pop("saved_xml"), encoding="utf-8")
        report[key] = {
            "files": len(rows),
            "import_ok": sum(1 for r in rows if "import_ms" in r),
            "identical": sum(1 for r in rows if r.get("identical")),
            "with_warnings": sum(1 for r in rows if r.get("n_warnings")),
            "import_ms_max": max((r.get("import_ms", 0) for r in rows), default=0),
            "rows": rows,
        }
        print(f"[{key}] 불러오기 {report[key]['import_ok']}/{len(rows)}, 원본과 같음 {report[key]['identical']}/{len(rows)}, "
              f"경고 있는 파일 {report[key]['with_warnings']}")
    report["console"] = canvas.console[:20]
    report["memory_mb"] = memory_mb()
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("plain", "moddle", "console")}, ensure_ascii=False))
    app.quit()


class StudioWindow(QMainWindow):
    """직접 써 보기용 최소 창. 한글 IME로 라벨을 고쳐 보고 저장한다."""

    def __init__(self) -> None:
        super().__init__()
        self.canvas = Canvas()
        self.setCentralWidget(self.canvas)
        self.resize(1400, 860)
        self.path: Path | None = None
        self.dirty = False
        self.canvas.bridge.changedSig.connect(self._set_dirty)
        m = self.menuBar().addMenu("파일")
        for text, key, fn in (("예제 열기...", QKeySequence.StandardKey.Open, self.open_example),
                              ("저장", QKeySequence.StandardKey.Save, self.save)):
            act = QAction(text, self)
            act.setShortcut(key)
            act.triggered.connect(lambda _=False, fn=fn: fn())
            m.addAction(act)
        self._title()

    def _set_dirty(self, d: bool) -> None:
        self.dirty = d
        self._title()

    def _title(self) -> None:
        name = self.path.name if self.path else "(예제를 여세요)"
        self.setWindowTitle(f"S3 Studio 셸 - {name}{' *' if self.dirty else ''}")

    def open_example(self, f: str | None = None) -> None:
        if not f:
            f, _ = QFileDialog.getOpenFileName(self, "예제 열기", str(EXAMPLES), "BPMN (*.bpmn)")
        if f:
            r = self.canvas.call("importXML", Path(f).read_text(encoding="utf-8"))
            if not r["ok"]:
                QMessageBox.warning(self, "불러오기 실패", r["error"])
                return
            self.path = Path(f)
            self._set_dirty(False)

    def save(self) -> None:
        if not self.path:
            return
        OUT.mkdir(exist_ok=True)
        dst = OUT / f"edited-{self.path.name}"  # 원본(생성물)은 덮어쓰지 않는다
        dst.write_text(self.canvas.call("saveXML")["xml"], encoding="utf-8")
        self._set_dirty(False)
        self.statusBar().showMessage(f"저장: {dst}", 5000)
        print(f"saved {dst.name}", flush=True)


def main() -> None:
    app = QApplication(sys.argv)
    if sys.argv[1:] == ["auto"]:
        QTimer.singleShot(0, lambda: auto(app))
    else:
        w = StudioWindow()
        w.show()
        w.canvas.open_page(moddle=True)
        if sys.argv[1:]:  # 파일을 바로 연다 (재현용)
            w.open_example(sys.argv[1])
    app.exec()


if __name__ == "__main__":
    main()
