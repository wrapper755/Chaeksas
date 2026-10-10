"""STU-01 메인 창 — 탐색기 · 캔버스 · 속성 패널 · 아래 탭 · 상태 줄.

조각 3e-1은 셸과 캔버스, 3e-2는 속성 패널(STU-04)과 실행 전 검사, 3e-3은 시험 실행
(STU-08·STU-09), **3e-4는 케이스 편집기(STU-07)와 패키지 내보내기**다. 아직 없는 것은
「아직 없다」고 말한다 — 빈 상자를 말없이 두지 않는다.

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
    QFileDialog,
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

from chaeksas.contracts import Violation
from chaeksas.studio import service_catalog, services
from chaeksas.studio.canvas import Canvas, CanvasError
from chaeksas.studio.case_dialog import CaseDialog
from chaeksas.studio.checks import refs_in
from chaeksas.studio.dialogs import NewProcessDialog, ShareDefinitionsDialog, pick_example
from chaeksas.studio.explorer import Explorer
from chaeksas.studio.extension_dialog import StudioExtensionsDialog
from chaeksas.studio.extensions import Extensions
from chaeksas.studio.packaging import (
    PackageError,
    default_lib_name,
    default_name,
    export,
    export_lib,
)
from chaeksas.studio.preflight import Preflight, inspect, readiness, summarize
from chaeksas.studio.properties import Properties
from chaeksas.studio.receiver import Receiver
from chaeksas.studio.run_dialog import RunDialog
from chaeksas.studio.runner import CaseRun, Outcome, Plan
from chaeksas.studio.runner import summarize as summarize_runs
from chaeksas.studio.settings import Settings
from chaeksas.studio.settings_dialog import StudioSettingsDialog
from chaeksas.studio.workspace import BpmProcess, Definition, Workspace, WorkspaceError

log = logging.getLogger(__name__)


def _inherited_keys(process: BpmProcess) -> dict[str, str]:
    """그 BPM 프로세스가 적어 둔 키 참조 `{app_id: 참조}` (`chk:process.service_keys`).

    STU-14가 「프로세스 설정을 따름 (<참조>)」에 보인다. **값은 담지 않는다** (ADR-0013).
    """
    found: dict[str, str] = {}
    for definition in process.definitions:
        if definition.process is not None:
            found.update(definition.process.info.service_keys)
    return found

TITLE = "Chaeksas Studio"
NO_PROCESS = "(BPM 프로세스를 선택하거나 새로 만드세요)"
DEFAULT_SIZE = (1400, 860)

#: 아직 없는 것을 누르면 이렇게 말한다 — 조용히 아무 일도 없는 것보다 낫다.
LATER = {
    "center": "Center 올리기는 아직 없습니다 (docs/09-gaps.md §4-5).",
}

PACKAGE_FILTER = "패키지 (*.zip)"


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

        self.extensions = Extensions.load()
        self.properties = Properties(self, extensions=self.extensions)
        self.properties.applying.connect(self._apply_properties)
        self.canvas.selected.connect(self._on_selected)

        self.preflight = Preflight(self)
        self.preflight.jumping.connect(lambda node_id: self.canvas.call("select", node_id))

        self.variables_view = QPlainTextEdit(self)
        self.variables_view.setReadOnly(True)
        #: 돌릴 것이 남아 있는 계획과 지금까지의 결과 (「모든 케이스 차례로」).
        self.queue: list[Plan] = []
        self.outcomes: list[Outcome] = []
        self.running: CaseRun | None = None
        self.receiver = Receiver(port=settings.receiver_port)

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
        later = QLabel("리소스 탐색기(STU-03)는 아직 없습니다 (docs/09-gaps.md §4-4).", tabs)
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
        screen = QLabel("「화면」 탭은 아직 비어 있습니다 (docs/09-gaps.md §4-6).", bottom)
        screen.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bottom.addTab(screen, "화면")
        bottom.addTab(self.variables_view, "변수")

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
        self._add(files, "시험 케이스...", self.edit_cases)
        files.addSeparator()
        self.save_action = self._add(files, "저장", self.save, QKeySequence.StandardKey.Save)
        self._add(files, "패키지로 내보내기...", self.export_package)
        self._add(files, "공유 BPM 프로세스로 내보내기...", self.export_shared)
        self._add(files, "Center로 올리기", lambda: self._later("center"))
        self._add(files, "공유 BPM 프로세스 Center로 올리기", lambda: self._later("center"))
        files.addSeparator()
        self._add(files, "종료", self.close)

        edit = bar.addMenu("편집")
        self._add(edit, "실행 취소", lambda: self.canvas.call("undo"), QKeySequence.StandardKey.Undo)
        self._add(edit, "다시 실행", lambda: self.canvas.call("redo"), QKeySequence.StandardKey.Redo)

        run = bar.addMenu("실행")
        self.run_action = self._add(run, "실행...", self.run_test, QKeySequence("F5"))
        self.stop_action = self._add(run, "실행 중지", self.stop_test)
        self.stop_action.setEnabled(False)
        self._add(run, "실행 전 검사", self.run_preflight, QKeySequence("F6"))

        settings = bar.addMenu("설정")
        self._add(settings, "설정...", self.open_settings, QKeySequence("Ctrl+,"))

        view = bar.addMenu("보기")
        self._add(view, "BPM 프로세스 탐색기", self.explorer.setFocus, QKeySequence("Ctrl+E"))

        tools = bar.addMenu("도구")
        self._add(tools, "확장...", self.open_extensions)
        self._add(tools, "로그 지우기", self.log_view.clear, QKeySequence("Ctrl+L"))

    def refresh_catalog(self) -> None:
        """STU-14가 고를 거리를 Center에서 받아 속성 패널에 준다 (C7 리소스 목록).

        **열 때마다 Center를 두드리지 않는다** — 정의를 열 때와 설정을 저장한 뒤에만 받는다.
        받지 못하면 로그에 적고 편집기가 「등록된 서비스 앱이 없습니다」라고 말한다.
        """
        found = services.from_settings(self.settings)
        self.properties.catalog = service_catalog.from_center(found.reader)
        for why in self.properties.catalog.problems:
            self.say(f"서비스 앱 목록: {why}")

    def open_settings(self) -> None:
        """STU-10. 저장하면 이 창의 설정도 바뀐다 (다음 시험 실행부터 쓴다)."""
        refs = refs_in(self.process.definitions) if self.process is not None else []
        dialog = StudioSettingsDialog(self.settings, self.extensions, refs=refs, parent=self)
        if dialog.exec() and dialog.saved is not None:
            self.settings = dialog.saved
            self.say("설정을 저장했습니다.")
            self.refresh_catalog()  # Center 주소·키가 바뀌었을 수 있다

    def open_extensions(self) -> None:
        """STU-15. **읽기만 한다** — 이 창이 설정·확장 호스트를 바꾸지 않는다."""
        StudioExtensionsDialog(self.settings, self.extensions, parent=self).exec()

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

    # ── 실행 전 검사 (B1~B15 + 사전 점검) ──

    def _readiness(self) -> list[Violation]:
        """사전 점검 — **이 PC에서 돌 수 있나** (`core.preflight`, ADR-0013).

        키 값은 Studio 비밀 저장소에서, 확장은 호스트에서 온다. 시험 실행과 **같은 것을 본다**
        (`Extensions.context`) — 점검이 다른 설정을 보면 「점검은 통과했는데 실행이 안 된다」가 된다.
        """
        from chaeksas.studio.credentials import StudioCredentials  # noqa: PLC0415 - 누를 때만 든다

        if self.process is None:
            return []
        return readiness(
            self.process,
            key_value=StudioCredentials().service_key,
            host=self.extensions.host,
            context=self.extensions.context,
            dirty=self.dirty,
        )

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
        violations = inspect(found, self.process) + self._readiness()
        self.preflight.show_result(found, violations)
        self.bottom_tabs.setCurrentWidget(self.preflight)
        self.say(summarize(violations))

    # ── 시험 실행 (STU-08·STU-09) ──

    # ── 시험 케이스 · 패키지 (3e-4) ──

    def opened_definition(self) -> Definition | None:
        """지금 열린 정의 (디스크에서 읽은 것). 없으면 `None`."""
        if self.process is None or self.definition is None:
            return None
        return next((d for d in self.process.definitions if d.path == self.definition), None)

    def edit_cases(self) -> None:
        """STU-07. 케이스는 **열린 정의 옆**에 있다 — 무엇의 케이스인지 모호하지 않게."""
        found = self.opened_definition()
        if self.process is None or found is None:
            self.say("열린 정의가 없습니다.")
            return
        CaseDialog(self, self.process, found).exec()
        self.say(f"시험 케이스: {self.process.case_file(found).name}")

    def export_package(self) -> None:
        """C1 패키지 zip. **저장하지 않은 편집은 들어가지 않는다** — 먼저 저장한다."""
        if self.process is None:
            self.say("열린 BPM 프로세스가 없습니다.")
            return
        if not self._may_drop_edits():
            return
        if self.dirty and not self.save():
            return
        target, _ = QFileDialog.getSaveFileName(
            self,
            "패키지로 내보내기",
            str(self.settings.outputs_dir / default_name(self.process)),
            PACKAGE_FILTER,
        )
        if not target:
            return
        try:
            written = export(self.process, Path(target))
        except PackageError as error:
            QMessageBox.warning(self, TITLE, str(error))
            self.say(f"패키지를 만들지 못했습니다: {error}")
            return
        self.say(f"패키지를 만들었습니다: {written}")

    def export_shared(self) -> None:
        """STU-12. 고른 정의를 공유 BPM 프로세스 패키지(`process_lib`)로 내보낸다.

        **저장하지 않은 편집은 들어가지 않는다** — 담는 것은 디스크의 파일이다 (`export_package`와
        같은 관문을 쓴다).
        """
        if self.process is None:
            self.say("열린 BPM 프로세스가 없습니다.")
            return
        if not self._may_drop_edits():
            return
        if self.dirty and not self.save():
            return
        picked = ShareDefinitionsDialog.ask(self, self.process)
        if not picked:
            return
        target, _ = QFileDialog.getSaveFileName(
            self,
            "공유 BPM 프로세스로 내보내기",
            str(self.settings.outputs_dir / default_lib_name(self.process)),
            PACKAGE_FILTER,
        )
        if not target:
            return
        try:
            written = export_lib(self.process, picked, Path(target))
        except PackageError as error:
            QMessageBox.warning(self, TITLE, str(error))
            self.say(f"공유 BPM 프로세스 패키지를 만들지 못했습니다: {error}")
            return
        self.say(f"공유 BPM 프로세스 패키지를 만들었습니다: {written}")

    def run_test(self) -> None:
        if self.process is None or self.definition is None:
            self.say("열린 정의가 없습니다.")
            return
        if self.running is not None:
            self.say("이미 실행 중입니다.")
            return
        # STU-08 실행 순서: 적용 안 한 편집 확인 → 저장 → 사전 점검 → 시작.
        if not self._may_drop_edits():
            return
        if self.dirty and not self.save():
            return
        found = next((d for d in self.process.definitions if d.path == self.definition), None)
        if found is None or found.process is None:
            self.say("정의를 읽지 못했습니다.")
            return
        # 그림 검사(B1~B15)와 **사전 점검**(이 PC에서 돌 수 있나)이 같은 관문이다.
        violations = inspect(found.process, self.process) + self._readiness()
        blocking = [v for v in violations if v.blocks]
        if blocking:
            self.preflight.show_result(found.process, violations)
            self.bottom_tabs.setCurrentWidget(self.preflight)
            QMessageBox.warning(self, TITLE, f"실행 전 검사가 막습니다 ({len(blocking)}개).")
            return

        plans = RunDialog.ask(self, self.process, found, self.settings)
        if not plans:
            return
        # 확장 태스크·데스크톱 AI 태스크가 이 PC Bot UI의 Worker를 쓴다 (STU-10 「Worker」).
        tasks = self.extensions.tasks()
        # 바깥 앱 한 벌 — **실행마다 한 번** 받는다 (케이스마다 Center를 두드리지 않게).
        # 받지 못한 것은 로그에 적고 그 앱을 부르는 순간 분명히 실패한다 (C7·C13 「전송」).
        found_apps = services.from_settings(self.settings)
        directory = found_apps.directory()
        for why in found_apps.problems:
            self.log_view.appendPlainText(f"바깥 앱: {why}")
        for plan in plans:
            plan.extensions = tasks
            plan.apps = directory
        self.receiver.start()
        self.queue = plans
        self.outcomes = []
        self.log_view.clear()
        self.canvas.mark({})
        self._next_run()

    def _next_run(self) -> None:
        if not self.queue:
            self._all_done()
            return
        plan = self.queue.pop(0)
        self.running = CaseRun(plan, self.receiver, self)
        self.running.said.connect(self.say)
        self.running.marked.connect(self.canvas.mark)
        self.running.varied.connect(self._show_variables)
        self.running.ended.connect(self._one_done)
        self.run_action.setEnabled(False)
        self.stop_action.setEnabled(True)
        self.statusBar().showMessage(f"실행 중: {plan.case.name if plan.case else '(케이스 없음)'}")
        self.running.start()

    def _one_done(self, outcome: Outcome) -> None:
        self.running = None
        self.outcomes.append(outcome)
        name = f"[{outcome.case}] " if outcome.case else ""
        self.say(f"{name}{outcome.detail}")
        if self.queue:
            self._next_run()
            return
        self._all_done()

    def _all_done(self) -> None:
        self.run_action.setEnabled(True)
        self.stop_action.setEnabled(False)
        if len(self.outcomes) > 1:
            self.say(summarize_runs(self.outcomes))
        last = self.outcomes[-1] if self.outcomes else None
        self.statusBar().showMessage(last.detail if last else "대기 중")
        if last is not None and last.run is not None and last.verdict in ("통과", "비교 안 함"):
            self.bottom_tabs.setCurrentWidget(self.variables_view)

    def stop_test(self) -> None:
        self.queue = []
        if self.running is not None:
            self.running.stop()

    def _show_variables(self, variables: dict[str, object]) -> None:
        import json  # noqa: PLC0415

        lines = [f"변수 {len(variables)}개", ""]
        for name in sorted(variables):
            value = variables[name]
            shown = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
            lines.append(f"{name} ({type(value).__name__}) = {shown[:200]}")
        self.variables_view.setPlainText("\n".join(lines))

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
            # STU-14가 고를 거리는 **정의를 열 때** 받는다 (노드를 고를 때마다 두드리지 않게).
            self.refresh_catalog()
            self.properties.service_keys = _inherited_keys(process)

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
        self.stop_test()
        self.receiver.stop()
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
