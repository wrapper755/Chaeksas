"""STU-01 메인 창 — 탐색기 · 캔버스 · 속성 패널 · 아래 탭 · 상태 줄.

조각 3e-1은 셸과 캔버스, **3e-2는 속성 패널(STU-04)과 실행 전 검사**다. 시험 실행(STU-07~09)은
3e-3이라 자리만 잡아 두고 「아직 없다」고 말한다 — 빈 상자를 말없이 두지 않는다.

제목·메뉴·단축키·닫기 보호는 `docs/06-screens/studio.md` STU-01 그대로다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from chaeksas.studio.canvas import Canvas, CanvasError
from chaeksas.studio.dialogs import NewProcessDialog, pick_example
from chaeksas.studio.explorer import Explorer
from chaeksas.studio.preflight import Preflight, inspect, summarize
from chaeksas.studio.properties import Properties
from chaeksas.studio.settings import Settings
from chaeksas.studio.workspace import BpmProcess, Workspace, WorkspaceError

log = logging.getLogger(__name__)

TITLE = "Chaeksas Studio"
NO_PROCESS = "(BPM 프로세스를 선택하거나 새로 만드세요)"
DEFAULT_SIZE = (1400, 860)

#: 아직 없는 것을 누르면 이렇게 말한다 — 조용히 아무 일도 없는 것보다 낫다.
LATER = {
    "run": "시험 실행은 다음 조각(3e-3)에서 붙입니다.",
    "package": "패키지로 내보내기는 다음 조각(3e-3)에서 붙입니다.",
    "center": "Center 올리기는 M5입니다.",
}


class MainWindow(QMainWindow):
    """STU-01. 열린 정의 하나를 캔버스가 들고 있고, 디스크가 원본이다."""

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.workspace = Workspace(settings.workspace_dir).ensure()
        self.process: BpmProcess | None = None
        self.definition: Path | None = None
        self.dirty = False

        self.resize(*DEFAULT_SIZE)
        self.canvas = Canvas(self)
        self.canvas.dirtied.connect(self._on_dirty)
        self.canvas.opened.connect(self._on_canvas_ready)

        self.explorer = Explorer(self.workspace, self)
        self.explorer.opening.connect(self.open_definition)

        self.log_view = QPlainTextEdit(self)
        self.log_view.setReadOnly(True)

        self.properties = Properties(self)
        self.properties.applying.connect(self._apply_properties)
        self.canvas.selected.connect(self._on_selected)

        self.preflight = Preflight(self)
        self.preflight.jumping.connect(lambda node_id: self.canvas.call("select", node_id))

        self._build_layout()
        self._build_menus()
        self.statusBar().showMessage("대기 중")
        self._retitle()
        self.canvas.boot()

    # ── 짜기 ──

    def _build_layout(self) -> None:
        dock = QDockWidget("BPM 프로세스", self)
        dock.setObjectName("explorerDock")
        tabs = QTabWidget(dock)
        tabs.addTab(self.explorer, "BPM 프로세스")
        later = QLabel("리소스 탐색기는 M4입니다.", tabs)
        later.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tabs.addTab(later, "리소스")
        dock.setWidget(tabs)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)

        middle = QSplitter(Qt.Orientation.Horizontal, self)
        middle.addWidget(self.canvas)
        middle.addWidget(self.properties)
        middle.setStretchFactor(0, 3)  # 캔버스와 속성 패널은 3:1 (STU-01)
        middle.setStretchFactor(1, 1)

        bottom = QTabWidget(self)
        self.bottom_tabs = bottom
        bottom.addTab(self.log_view, "로그")
        bottom.addTab(self.preflight, "검사")
        for name in ("화면", "변수"):
            placeholder = QLabel(f"「{name}」 탭은 실행이 붙는 조각(3e-3)에서 채웁니다.", bottom)
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            bottom.addTab(placeholder, name)

        split = QSplitter(Qt.Orientation.Vertical, self)
        split.addWidget(middle)
        split.addWidget(bottom)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 1)

        holder = QWidget(self)
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(split)
        self.setCentralWidget(holder)

    def _build_menus(self) -> None:
        bar = self.menuBar()
        files = bar.addMenu("파일")
        self._add(files, "새 BPM 프로세스...", self.new_process, QKeySequence.StandardKey.New)
        self._add(files, "예제 BPM 프로세스 가져오기...", self.import_example)
        files.addSeparator()
        self.save_action = self._add(files, "저장", self.save, QKeySequence.StandardKey.Save)
        self._add(files, "패키지로 내보내기...", lambda: self._later("package"))
        self._add(files, "Center로 올리기", lambda: self._later("center"))
        files.addSeparator()
        self._add(files, "종료", self.close)

        edit = bar.addMenu("편집")
        self._add(edit, "실행 취소", lambda: self.canvas.call("undo"), QKeySequence.StandardKey.Undo)
        self._add(edit, "다시 실행", lambda: self.canvas.call("redo"), QKeySequence.StandardKey.Redo)

        run = bar.addMenu("실행")
        self._add(run, "실행...", lambda: self._later("run"), QKeySequence("F5"))
        self._add(run, "실행 전 검사", self.run_preflight, QKeySequence("F6"))

        view = bar.addMenu("보기")
        self._add(view, "BPM 프로세스 탐색기", self.explorer.setFocus, QKeySequence("Ctrl+E"))

        tools = bar.addMenu("도구")
        self._add(tools, "로그 지우기", self.log_view.clear, QKeySequence("Ctrl+L"))

    def _add(
        self,
        menu: QMenu,
        text: str,
        slot: Callable[[], object],
        shortcut: QKeySequence | QKeySequence.StandardKey | None = None,
    ) -> QAction:
        action = QAction(text, self)
        if shortcut is not None:
            action.setShortcut(shortcut)
        action.triggered.connect(slot)
        menu.addAction(action)
        return action

    # ── 말하기 ──

    def say(self, message: str) -> None:
        """아래 「로그」 탭 한 줄 + 상태 줄."""
        self.log_view.appendPlainText(message)
        self.statusBar().showMessage(message)

    def _later(self, what: str) -> None:
        QMessageBox.information(self, TITLE, LATER[what])

    def _retitle(self) -> None:
        if self.process is None or self.definition is None:
            self.setWindowTitle(f"{TITLE} - {NO_PROCESS}")
            return
        mark = " *" if self.dirty else ""
        self.setWindowTitle(
            f"{TITLE} - {self.process.display} (v{self.process.version}) - {self.definition.stem}{mark}"
        )

    def _on_dirty(self, dirty: bool) -> None:
        self.dirty = dirty
        self._retitle()

    def _on_canvas_ready(self) -> None:
        self.say("캔버스를 띄웠습니다.")
        if self.settings.last_opened:
            path = Path(self.settings.last_opened)
            if path.is_file():
                self.open_definition(self.settings.last_opened)
                return
        self.say("열린 BPM 프로세스가 없습니다 — 탐색기에서 고르거나 새로 만드세요.")
        self.explorer.setFocus()

    # ── 속성 패널 (STU-04) ──

    def _on_selected(self, node_id: str) -> None:
        if not node_id:
            self.properties.show_nothing()
            return
        if node_id == self.properties.node_id:
            return
        if not self._may_drop_edits():
            # 머무르기 — 캔버스의 고른 것을 되돌린다.
            self.canvas.call("select", self.properties.node_id)
            return

        def done(found: dict[str, object]) -> None:
            if found.get("ok") and found.get("found"):
                self.properties.show_element(found)
            else:
                self.properties.show_nothing()

        self.canvas.call("properties", node_id, then=done)

    def _apply_properties(self, node_id: str, changes: dict[str, object]) -> None:
        def done(found: dict[str, object]) -> None:
            if not found.get("ok"):
                self.say(f"적용하지 못했습니다: {found.get('error')}")
                return
            self.say(f"적용했습니다: {node_id} ({', '.join(sorted(changes))})")
            self.canvas.call("properties", node_id, then=lambda again: self.properties.show_element(again))

        self.canvas.call("setProperties", node_id, changes, then=done)

    def _may_drop_edits(self) -> bool:
        """적용 안 한 편집이 있으면 묻는다 (STU-04). 지금 적용할 수 없으면 「적용」을 뺀다."""
        if not self.properties.unapplied:
            return True
        _, problem = self.properties.patch()
        buttons = QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel
        if problem is None:
            buttons |= QMessageBox.StandardButton.Apply
        box = QMessageBox(self)
        box.setWindowTitle("적용하지 않은 변경사항")
        box.setText(
            "속성 패널에 적용하지 않은 변경사항이 있습니다."
            + (f"\n\n지금 적용할 수 없습니다 — {problem}" if problem else "")
        )
        box.setStandardButtons(buttons)
        box.button(QMessageBox.StandardButton.Discard).setText("버리기")
        box.button(QMessageBox.StandardButton.Cancel).setText("머무르기")
        if problem is None:
            box.button(QMessageBox.StandardButton.Apply).setText("적용")
        answer = box.exec()
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Apply:
            return self.properties.apply()
        return True

    # ── 실행 전 검사 (B1~B14) ──

    def run_preflight(self) -> None:
        if self.process is None or self.definition is None:
            self.say("열린 정의가 없습니다.")
            return
        if not self._may_drop_edits():
            return
        try:
            xml = self.canvas.save_xml()
        except CanvasError as e:
            self.say(f"검사하지 못했습니다: {e}")
            return
        from chaeksas.contracts.bpmn_ext import BpmnReadError, read_process  # noqa: PLC0415

        try:
            found = read_process(xml)
        except BpmnReadError as e:
            self.say(f"검사하지 못했습니다: {e}")
            return
        violations = inspect(found, self.process)
        self.preflight.show_result(found, violations)
        self.bottom_tabs.setCurrentWidget(self.preflight)
        self.say(summarize(violations))

    # ── 열고 닫기 ──

    def open_definition(self, path_text: str) -> None:
        if not self._may_discard():
            return
        path = Path(path_text)
        process = next(
            (
                p
                for group in self.workspace.groups()
                for p in group.processes
                if any(d.path == path for d in p.definitions)
            ),
            None,
        )
        if process is None or not path.is_file():
            self.say(f"정의를 찾지 못했습니다: {path.name}")
            return

        def done(found: dict[str, object]) -> None:
            if not found.get("ok"):
                self.say(f"열지 못했습니다: {found.get('error')}")
                return
            warnings = found.get("warnings")
            count = len(warnings) if isinstance(warnings, list) else 0
            self.process, self.definition, self.dirty = process, path, False
            self.properties.show_nothing()
            self.preflight.setRowCount(0)
            self._retitle()
            self.explorer.refresh(opened=path.as_posix())
            note = f" (경고 {count}개)" if count else ""
            self.say(f"열었습니다: {process.display} / {path.name}{note}")

        self.canvas.load_xml(path.read_text(encoding="utf-8"), then=done)

    def save(self) -> bool:
        if self.process is None or self.definition is None:
            self.say("열린 정의가 없습니다.")
            return False
        if not self._may_drop_edits():
            return False
        try:
            xml = self.canvas.save_xml()
        except CanvasError as e:
            self.say(f"저장하지 못했습니다: {e}")
            return False
        self.workspace.save_definition(self.process, self.definition.name, xml)
        self.dirty = False
        self._retitle()
        self.say(f"저장했습니다: {self.definition.name}")
        return True

    def _may_discard(self) -> bool:
        """저장 안 한 변경이 있으면 묻는다 (STU-01 U11)."""
        if not self.dirty:
            return True
        answer = QMessageBox.question(
            self,
            "저장하지 않은 변경사항",
            "저장하지 않은 변경사항이 있습니다. 저장할까요?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save:
            return self.save()
        return True

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 — Qt 이름 그대로
        if not self._may_discard():
            event.ignore()
            return
        if self.definition is not None:
            from dataclasses import replace  # noqa: PLC0415

            replace(self.settings, last_opened=self.definition.as_posix()).save()
        event.accept()

    # ── 만들기·가져오기 ──

    def new_process(self) -> None:
        """STU-05. 만든 뒤 빈 정의를 캔버스에 띄우고 바로 저장한다."""
        if not self._may_discard():
            return
        made = NewProcessDialog.ask(self, self.workspace)
        if made is None:
            return
        try:
            self.canvas.create_empty(f"Proc_{made.id.replace('-', '_')}", made.display)
            xml = self.canvas.save_xml()
        except CanvasError as e:
            self.say(f"빈 정의를 만들지 못했습니다: {e}")
            return
        path = self.workspace.save_definition(made, made.entry, xml)
        self.explorer.refresh(opened=path.as_posix())
        self.open_definition(path.as_posix())

    def import_example(self) -> None:
        """예제 BPM 프로세스 가져오기 (STU-01 파일 메뉴). 예제 폴더는 **읽기만** 한다."""
        if not self._may_discard():
            return
        picked = pick_example(self)
        if picked is None:
            return
        source, example_id = picked
        try:
            made = self.workspace.import_example(source, example_id)
        except (WorkspaceError, OSError) as e:
            QMessageBox.warning(self, TITLE, f"가져오지 못했습니다: {e}")
            return
        entry = made.entry_definition
        self.explorer.refresh()
        self.say(f"가져왔습니다: {made.display}")
        if entry is not None:
            self.open_definition(entry.path.as_posix())


__all__ = ["DEFAULT_SIZE", "LATER", "NO_PROCESS", "TITLE", "MainWindow"]
