"""STU-01 메인 창 — 탐색기 · 캔버스 · 속성 패널 · 아래 탭 · 상태 줄.

**창이 쥐는 것**은 열린 BPM 프로세스·정의 하나, 캔버스, 돌고 있는 시험 실행이다. 제목·메뉴·
단축키·닫기 보호는 `docs/06-screens/studio.md` STU-01 그대로다. 아직 없는 것은 「아직 없다」고
말한다 — 빈 상자를 말없이 두지 않는다.

**메뉴 동작 중 큰 두 묶음은 떼어 냈다** (이 파일이 500줄 선을 넘어서다, CLAUDE.md §4):
`export_actions`(내보내기·올리기 넷)와 `run_actions`(시험 실행 몰이). 둘은 창을 받아 쓰고,
창은 그들이 쓰는 **작은 길**만 공개한다 — `saved_to_disk()`·`readiness()`·`say()`·
`show_preflight()`·`show_variables()`·`reset_ui_sessions()`·`show_ui_session()`. 창이 그 일의
속을 알지는 않는다 — 아래 탭의 글·줄은 떼어 낸 모듈과 `ui_sessions.py`가 짓는다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
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
from chaeksas.contracts.bpmn_ext import BpmnProcess
from chaeksas.studio import (
    center_actions,
    export_actions,
    file_actions,
    layout,
    resources,
    run_actions,
    run_dialog,
    services,
)
from chaeksas.studio.canvas import Canvas, CanvasError
from chaeksas.studio.case_dialog import CaseDialog
from chaeksas.studio.checks import refs_in
from chaeksas.studio.explorer import Explorer
from chaeksas.studio.extension_dialog import StudioExtensionsDialog, pin_patch
from chaeksas.studio.extensions import Extensions
from chaeksas.studio.preflight import Preflight, inspect, readiness, summarize
from chaeksas.studio.process_dialog import ProcessInfoDialog
from chaeksas.studio.properties import Properties
from chaeksas.studio.receiver import Receiver
from chaeksas.studio.runner import CaseRun, Outcome, Plan
from chaeksas.studio.settings import Settings
from chaeksas.studio.settings_dialog import StudioSettingsDialog
from chaeksas.studio.ui_sessions import Row as UiSessionRow
from chaeksas.studio.ui_sessions import UiSessions
from chaeksas.studio.workspace import BpmProcess, Definition, Workspace

log = logging.getLogger(__name__)


TITLE = "Chaeksas Studio"
NO_PROCESS = "(BPM 프로세스를 선택하거나 새로 만드세요)"
DEFAULT_SIZE = (1400, 860)

PACKAGE_FILTER = "패키지 (*.zip)"

#: Center가 필요한 동작을 설정 없이 눌렀을 때 (STU-10 맨 아래).
NO_CENTER_SETTINGS = (
    "Center 주소와 Center API 키가 아직 없습니다.\n\n지금 설정 → Center를 열까요?"
)


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
        # STU-03 끌어다 놓기 (ADR-0044) — **캔버스는 무엇이 떨어졌는지 모른다.** 받을 형식을
        # 알려 주고, 뜻은 이 창이 푼다 (「캔버스에 추가」와 같은 길로 보낸다).
        self.canvas.accept_drops_of(resources.MIME_TYPE)
        self.canvas.dropped.connect(
            lambda payload, x, y: center_actions.drop_on_canvas(self, payload, x, y)
        )

        self.explorer = Explorer(self.workspace, self)
        self.explorer.opening.connect(self.open_definition)

        # STU-03. **받는 일은 이 창이 한다** — 탐색기는 돌아온 것을 그리기만 한다.
        self.resource_tree = resources.ResourceExplorer(self)
        self.resource_tree.reloading.connect(self.refresh_catalog)
        self.resource_tree.adding.connect(lambda create: center_actions.add_to_canvas(self, create))
        self.resource_tree.opening_center.connect(
            lambda: center_actions.open_center_resources(self)
        )
        # 공유 BPM 프로세스 정의 보기·복사 (ADR-0051) — **창을 쥐는 쪽이 하나**라 여기서 받는다.
        self.resource_tree.viewing.connect(
            lambda shared: center_actions.view_shared(self, shared)
        )
        self.resource_tree.copying.connect(
            lambda shared: center_actions.copy_shared(self, shared)
        )
        self.resource_tree.said.connect(self.say)

        self.log_view = QPlainTextEdit(self)
        self.log_view.setReadOnly(True)

        self.extensions = Extensions.load(off=settings.disabled_extensions, configured=settings.extensions)
        self.extensions.process_key_refs = self.process_key_refs
        self.properties = Properties(self, extensions=self.extensions)
        self.properties.applying.connect(self._apply_properties)
        self.canvas.selected.connect(self._on_selected)

        self.preflight = Preflight(self)
        self.preflight.jumping.connect(lambda node_id: self.canvas.call("select", node_id))

        # STU-09 「UI 태스크」. 재료는 C3 `ui_session`이라 **플랫폼이 그린다** (ADR-0042 — 확장이
        # 기여한 칸이 아니다. BUI-09는 재료가 C10이라 그쪽이 그린다).
        self.ui_sessions = UiSessions(self)

        self.variables_view = QPlainTextEdit(self)
        self.variables_view.setReadOnly(True)
        #: 돌릴 것이 남아 있는 계획과 지금까지의 결과 (「모든 케이스 차례로」).
        self.queue: list[Plan] = []
        self.outcomes: list[Outcome] = []
        self.running: CaseRun | None = None
        self.receiver = Receiver(port=settings.receiver_port)

        self._build_layout()
        self._build_menus()
        self._restore_layout()
        # 뿌리는 선언에서 오므로 **Center 없이도** 바로 그린다 (빈 상자를 말없이 두지 않는다).
        # 목록은 정의를 열 때·「새로 고침」에 채운다 — 뜨면서 Center를 두드리지 않는다.
        self.refresh_resources(reader=None)
        self.statusBar().showMessage("대기 중")
        self.retitle()
        self.canvas.boot()

    # ── 짜기 ──

    def _build_layout(self) -> None:
        dock = QDockWidget("BPM 프로세스", self)
        dock.setObjectName("explorerDock")
        tabs = QTabWidget(dock)
        self.explorer_tabs = tabs
        tabs.addTab(self.explorer, "BPM 프로세스")
        tabs.addTab(self.resource_tree, "리소스")
        dock.setWidget(tabs)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)

        self.explorer_dock = dock
        middle = QSplitter(Qt.Orientation.Horizontal, self)
        self.middle = middle
        middle.addWidget(self.canvas)
        middle.addWidget(self.properties)
        middle.setObjectName("middleSplit")
        middle.setStretchFactor(0, 3)  # 캔버스와 속성 패널은 3:1 (STU-01)
        middle.setStretchFactor(1, 1)

        bottom = QTabWidget(self)
        self.bottom_tabs = bottom
        bottom.addTab(self.log_view, "로그")
        bottom.addTab(self.preflight, "검사")
        bottom.addTab(self.ui_sessions, "UI 태스크")
        bottom.addTab(self.variables_view, "변수")

        split = QSplitter(Qt.Orientation.Vertical, self)
        self.split = split
        split.addWidget(middle)
        split.addWidget(bottom)
        split.setObjectName("bottomSplit")
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 1)

        holder = QWidget(self)
        box = QVBoxLayout(holder)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(split)
        self.setCentralWidget(holder)

    # ── 배치 기억 (STU-01 — 「크기·위치를 기억한다」) ──

    def layout_path(self) -> Path:
        return layout.layout_path(self.settings.data_dir)

    def _restore_layout(self) -> None:
        """담아 둔 배치로 되돌린다. **없으면 기본 배치 그대로** 둔다."""
        found = layout.read(self.layout_path())
        if found is None:
            return
        layout.apply(found, self, self.middle, self.split)
        self.collapse_action.setChecked(found.properties_collapsed)
        self.properties.setVisible(not found.properties_collapsed)

    def toggle_properties(self) -> None:
        """도구 → 「속성 패널 접기」 (Ctrl+Shift+P). 체크가 곧 접힌 상태다."""
        collapsed = self.collapse_action.isChecked()
        self.properties.setVisible(not collapsed)
        self.say("속성 패널을 접었습니다." if collapsed else "속성 패널을 펼쳤습니다.")

    def reset_layout(self) -> None:
        """도구 → 「레이아웃 초기화」 — 담아 둔 것을 **지우고** 기본 배치로 돌린다.

        지우기만 하면 다음에 뜰 때나 돌아오므로, 지금 창도 함께 되돌린다.
        """
        layout.clear(self.layout_path())
        self.resize(*DEFAULT_SIZE)
        self.explorer_dock.setFloating(False)
        self.explorer_dock.show()
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.explorer_dock)
        self.collapse_action.setChecked(False)
        self.properties.setVisible(True)
        # 3:1·4:1은 짤 때의 비율 그대로다 (STU-01).
        width, height = self.middle.width(), self.split.height()
        self.middle.setSizes([width * 3 // 4, width // 4])
        self.split.setSizes([height * 4 // 5, height // 5])
        self.say("레이아웃을 기본으로 돌렸습니다.")

    def _build_menus(self) -> None:
        bar = self.menuBar()
        files = bar.addMenu("파일")
        self._add(files, "새 BPM 프로세스...", self.new_process, QKeySequence.StandardKey.New)
        self._add(files, "예제 BPM 프로세스 가져오기...", self.import_example)
        self._add(
            files, "파일에서 BPM 프로세스 가져오기...", lambda: file_actions.import_file(self)
        )
        self.close_action = self._add(
            files,
            "BPM 프로세스 닫기",
            lambda: file_actions.close_process(self),
            QKeySequence.StandardKey.Close,
        )
        self._add(files, "BPM 프로세스 정보...", self.edit_info)
        self.add_definition_action = self._add(
            files, "정의 추가...", lambda: file_actions.add_definition(self)
        )
        self.entry_action = self._add(
            files, "이 정의를 진입으로 지정", lambda: file_actions.make_entry(self)
        )
        self._add(files, "시험 케이스...", self.edit_cases)
        files.addSeparator()
        self.save_action = self._add(files, "저장", self.save, QKeySequence.StandardKey.Save)
        self.save_as_action = self._add(
            files,
            "다른 이름으로 저장...",
            lambda: file_actions.save_process_as(self),
            QKeySequence("Ctrl+Shift+S"),
        )
        self._add(files, "패키지로 내보내기...", lambda: export_actions.export_package(self))
        self._add(files, "공유 BPM 프로세스로 내보내기...", lambda: export_actions.export_shared(self))
        self._add(files, "Center로 올리기", lambda: export_actions.upload_package(self))
        self._add(
            files, "공유 BPM 프로세스 Center로 올리기", lambda: export_actions.upload_shared(self)
        )
        self._add(files, "Center 공유 자원...", lambda: center_actions.open_center_resources(self))
        files.addSeparator()
        self._add(files, "종료", self.close)

        edit = bar.addMenu("편집")
        self._add(edit, "실행 취소", lambda: self.canvas.call("undo"), QKeySequence.StandardKey.Undo)
        self._add(edit, "다시 실행", lambda: self.canvas.call("redo"), QKeySequence.StandardKey.Redo)

        run = bar.addMenu("실행")
        self.run_action = self._add(run, "실행...", lambda: run_actions.run_test(self), QKeySequence("F5"))
        # **끄지 않는다** (STU-01 「항상 켜짐») — 학습 안 된 AI 태스크가 있으면 **창이** 그
        # 수행 모드를 끄고 이유를 보인다 (U3). 여기서 끄면 왜 못 하는지 말할 자리가 없다.
        self.replay_action = self._add(
            run,
            "결정 수행 (재생)...",
            lambda: run_actions.run_test(self, mode=run_dialog.DETERMINISTIC),
            QKeySequence("Ctrl+F5"),
        )
        self.stop_action = self._add(run, "실행 중지", lambda: run_actions.stop_test(self))
        self.stop_action.setEnabled(False)
        self._add(run, "실행 전 검사", self.run_preflight, QKeySequence("F6"))

        settings = bar.addMenu("설정")
        self._add(settings, "설정...", self.open_settings, QKeySequence("Ctrl+,"))

        view = bar.addMenu("보기")
        self._add(view, "BPM 프로세스 탐색기", self.show_explorer, QKeySequence("Ctrl+E"))
        self._add(view, "리소스", self.show_resources, QKeySequence("Ctrl+Shift+E"))

        tools = bar.addMenu("도구")
        self._add(tools, "확장...", self.open_extensions)
        self.collapse_action = self._add(
            tools, "속성 패널 접기", self.toggle_properties, QKeySequence("Ctrl+Shift+P")
        )
        self.collapse_action.setCheckable(True)
        self._add(tools, "레이아웃 초기화", self.reset_layout)
        self._add(tools, "로그 지우기", self.log_view.clear, QKeySequence("Ctrl+L"))

    def refresh_catalog(self) -> None:
        """Center 리소스 목록을 받아 꽂는다 — 하는 일은 `center_actions`에 있다."""
        center_actions.refresh_catalog(self)

    def refresh_resources(self, *, reader: services.CenterReader | None) -> None:
        """받아 둔 것으로 STU-03을 그린다 (`reader`가 `None`이면 두드리지 않는다)."""
        center_actions.refresh_resources(self, reader=reader)

    def show_explorer(self) -> None:
        """보기 → 「BPM 프로세스 탐색기」 (Ctrl+E). 독의 탭을 앞으로 내고 포커스를 준다."""
        self.explorer_tabs.setCurrentWidget(self.explorer)
        self.explorer.setFocus()

    def show_resources(self) -> None:
        """보기 → 「리소스」 (Ctrl+Shift+E)."""
        self.explorer_tabs.setCurrentWidget(self.resource_tree)
        self.resource_tree.setFocus()

    def process_key_refs(self) -> dict[str, str]:
        """열린 BPM 프로세스의 `chk:process.service_keys` — 편집기의 `service.key_ref` (ADR-0074).

        저장된 파일 기준이다(키 참조는 STU-06에서 고쳐 저장한다). 정의가 여럿이면 먼저 적힌 것.
        """
        found: dict[str, str] = {}
        for definition in self.process.definitions if self.process is not None else ():
            drawn = getattr(definition, "process", None)
            if drawn is None:
                continue
            for owner, ref in drawn.info.service_keys.items():
                if ref:
                    found.setdefault(str(owner), str(ref))
        return found

    def _apply_theme(self, choice: str) -> None:
        """STU-10 「외형」 — **저장하는 그 자리에서** 창 전체에 입힌다 (ADR-0073)."""
        from PySide6.QtWidgets import QApplication  # noqa: PLC0415

        from chaeksas.qt.theme import apply_theme  # noqa: PLC0415

        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_theme(app, choice=choice)

    def open_settings(self) -> None:
        """STU-10. 저장하면 이 창의 설정도 바뀐다 (다음 시험 실행부터 쓴다)."""
        refs = refs_in(self.process.definitions) if self.process is not None else []
        dialog = StudioSettingsDialog(self.settings, self.extensions, refs=refs, parent=self)
        if dialog.exec() and dialog.saved is not None:
            if dialog.saved.theme != self.settings.theme:
                self._apply_theme(dialog.saved.theme)
            self.settings = dialog.saved
            # 확장별 설정 — 다음 시험 실행·사전 점검부터 쓴다.
            self.extensions.configured = dict(dialog.saved.extensions)
            self.say("설정을 저장했습니다.")
            self.refresh_catalog()  # Center 주소·키가 바뀌었을 수 있다

    def open_extensions(self) -> None:
        """STU-15. 끄고 켠 것이 있으면 **속성 패널을 다시 그린다** (ADR-0043).

        꺼진 확장의 편집기가 패널에 남아 있으면 안 된다 — 창이 호스트를 다시 읽어 두었으니
        지금 고른 요소를 다시 보이면 패널이 새 호스트에게 묻는다.
        """
        # 고정은 **그림을 고치는 일**이라 진입 정의가 열려 있을 때만 된다 (STU-06과 같은 규칙,
        # ADR-0022·ADR-0060). 창은 그림을 만지지 않고 `pins`에 적어 두고, 넘기는 것은 여기다.
        entry = self.process.entry_definition if self.process is not None else None
        editable = entry is not None and entry.process is not None and self.definition == entry.path
        dialog = StudioExtensionsDialog(
            self.settings,
            self.extensions,
            process_info=entry.process.info if editable and entry is not None and entry.process is not None else None,
            parent=self,
        )
        dialog.exec()
        if dialog.pins and entry is not None and entry.process is not None:
            self._apply_properties(
                entry.process.id,
                {"chk": {"process": pin_patch(entry.process.info, dialog.pins)}},
            )
            self.say("정의 고정을 그림에 적용했습니다 — 「저장」(Ctrl+S)으로 파일에 씁니다.")
        if not dialog.changed:
            return
        self.settings = dialog.settings
        node_id = self.properties.node_id
        self.properties.show_nothing()
        if node_id:
            self.canvas.call("properties", node_id, then=lambda found: self.properties.show_element(found))
        # 리소스 탐색기의 뿌리도 기여다 — 끈 확장의 뿌리가 남아 있으면 안 된다 (ADR-0043).
        self.refresh_resources(reader=services.from_settings(self.settings).reader)
        self.say("확장을 바꿨습니다 — 「실행 전 검사」로 확인하세요.")

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

    def retitle(self) -> None:
        if self.process is None or self.definition is None:
            self.setWindowTitle(f"{TITLE} - {NO_PROCESS}")
            self.refresh_menus()
            return
        mark = " *" if self.dirty else ""
        self.setWindowTitle(
            f"{TITLE} - {self.process.display} (v{self.process.version}) - {self.definition.stem}{mark}"
        )
        # 제목과 메뉴는 **같은 상태**에서 온다 — 열고·지정하고·복사할 때마다 함께 바뀐다.
        self.refresh_menus()

    def refresh_menus(self) -> None:
        """STU-01 「켜지는 조건」 — 지금 할 수 없는 메뉴를 끈다.

        **까닭을 말할 자리가 없는 것만 끈다** (U3): 「이 정의를 진입으로 지정」은 이미 진입이면
        할 일이 없고, 나머지 둘은 BPM 프로세스가 열려 있어야 한다. 실행 쪽은 끄지 않는다 —
        「결정 수행 (재생)」은 **항상 켜져 있고** 못 하는 까닭을 STU-08이 말한다.
        """
        open_process = self.process is not None
        self.add_definition_action.setEnabled(open_process)
        self.close_action.setEnabled(open_process)
        self.save_as_action.setEnabled(open_process)
        found = self.opened_definition()
        entry = self.process.entry_definition if self.process is not None else None
        self.entry_action.setEnabled(
            found is not None and (entry is None or entry.path != found.path)
        )

    def _on_dirty(self, dirty: bool) -> None:
        self.dirty = dirty
        self.retitle()

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
        if not self.may_drop_edits():
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

    def saved_to_disk(self) -> bool:
        """「내보내기」·「올리기」·「실행」의 공통 관문 — 적용 안 한 편집을 확인하고 저장한다.

        **담는 것은 디스크의 파일이다** — 저장하지 않은 편집은 패키지에도 시험 실행에도
        들어가지 않는다. 떼어 낸 모듈(`export_actions`·`run_actions`)이 이것을 쓴다.
        """
        if not self.may_drop_edits():
            return False
        return not self.dirty or self.save()

    def may_drop_edits(self) -> bool:
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

    def task_type_locations(self) -> dict[str, list[str]]:
        """확장 태스크 종류 → 실행 위치 (C13). **F6·STU-06·매니페스트가 같은 표를 쓴다.**

        베껴 두면 셋이 서로 다른 말을 한다 — 창이 「서버로 바꿔도 된다」고 하고 F6이 막거나,
        올리기가 거짓으로 422를 받는다. **꺼 둔 확장은 표에 없다** (ADR-0043) — 받는 쪽은
        모르는 종류를 막지 않는다.
        """
        return self.extensions.host.task_type_locations()

    def readiness(self) -> list[Violation]:
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
            # **어느 확장이 외부인가는 받아 둔 리소스 목록이 안다** (C7) — 외부 확장은 이 PC에
            # 깔리지 않아 호스트가 모른다. 점검은 서버를 부르지 않으므로 여기서 넘긴다 (ADR-0060).
            external_ids=self.properties.catalog.external_ids(),
        )

    def delegated_outputs(self) -> dict[str, tuple[str, ...]]:
        """PC 위임으로 부르는 Bot들이 **선언한 `outputs`** (C1 → C14 B14, ADR-0062).

        **창은 Center를 부르지 않는다** — 받아 둔 카탈로그에서 꺼낸다 (「새로 고침」·정의를 열
        때·설정을 저장한 뒤에 받는다). 못 받았으면 **비어 있고** 그러면 B14가 그 대조를
        건너뛴다 — 모르는 것으로 막지 않는다.
        """
        return dict(self.properties.catalog.bot_outputs)

    def run_preflight(self) -> None:
        if self.process is None or self.definition is None:
            self.say("열린 정의가 없습니다.")
            return
        if not self.may_drop_edits():
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
        violations = inspect(
            found,
            self.process,
            task_type_locations=self.task_type_locations(),
            delegated_outputs=self.delegated_outputs(),
        ) + self.readiness()
        self.preflight.show_result(found, violations)
        self.bottom_tabs.setCurrentWidget(self.preflight)
        self.say(summarize(violations))

    # ── 시험 실행 (STU-08·STU-09) ──

    # ── 떼어 낸 모듈이 쓰는 길 (`export_actions`·`run_actions`) ──

    def show_preflight(self, process: BpmnProcess, violations: list[Violation]) -> None:
        """검사 결과를 「검사」 탭에 보이고 그 탭을 앞으로 낸다 (STU-09)."""
        self.preflight.show_result(process, violations)
        self.bottom_tabs.setCurrentWidget(self.preflight)

    def show_variables(self, text: str) -> None:
        """「변수」 탭의 글. **글은 `run_actions.format_variables`가 짓는다** (Qt를 모르는 자리)."""
        self.variables_view.setPlainText(text)

    def reset_ui_sessions(self) -> None:
        """「UI 태스크」 탭을 비운다 — 실행 하나가 시작할 때 (STU-09)."""
        self.ui_sessions.reset_rows()

    def show_ui_session(self, row: UiSessionRow) -> None:
        """UI 세션 한 줄을 더한다. **줄은 `ui_sessions.row_of`가 짓는다** (Qt를 모르는 자리)."""
        self.ui_sessions.add(row)

    def show_variables_tab(self) -> None:
        self.bottom_tabs.setCurrentWidget(self.variables_view)

    # ── 시험 케이스 · BPM 프로세스 정보 ──

    def opened_definition(self) -> Definition | None:
        """지금 열린 정의 (디스크에서 읽은 것). 없으면 `None`."""
        if self.process is None or self.definition is None:
            return None
        return next((d for d in self.process.definitions if d.path == self.definition), None)

    def edit_info(self) -> None:
        """STU-06. 기록은 창이 쓰고, **그림은 캔버스가** 쓴다 (XML을 파이썬이 만지지 않는다).

        그래서 실행 위치·키 참조는 **진입 정의가 열려 있을 때만** 켜진다 — 창이 그 까닭을
        적는다 (U3). 열려 있으면 「저장」이 `chk:process`를 한 걸음으로 적용해 **실행 취소도
        한 걸음**이다.
        """
        if self.process is None:
            self.say("열린 BPM 프로세스가 없습니다.")
            return
        entry = self.process.entry_definition
        editable = entry is not None and self.definition == entry.path
        if editable and not self.may_drop_edits():
            return
        from chaeksas.studio.credentials import StudioCredentials  # noqa: PLC0415 — 순환 피함

        store = StudioCredentials()
        dialog = ProcessInfoDialog(
            self.process,
            self.workspace,
            has_value=lambda ref: bool(ref) and store.service_key(ref) is not None,
            editable=editable,
            # 창은 호스트를 들고 있지 않다 — **F6과 같은 표**를 여기서 넘긴다 (C13).
            task_type_locations=self.task_type_locations(),
            parent=self,
        )
        if not dialog.exec() or dialog.saved is None:
            if dialog.split_requested:
                self.split_to_pc()
            return
        self.process = dialog.saved
        self.retitle()
        self.explorer.refresh(opened=self.definition.name if self.definition else "")
        self.say(f"BPM 프로세스 정보를 저장했습니다: {dialog.saved.display} (v{dialog.saved.version})")
        if dialog.process_patch is None or entry is None or entry.process is None:
            return
        # 그림은 **캔버스에만** 반영된다 — 파일로 가는 것은 「저장」(Ctrl+S)이다 (STU-04의 「적용」과
        # 같은 결). 그렇게 말해 둬야 「저장했다는데 패키지에 안 들어갔다」가 생기지 않는다.
        self._apply_properties(entry.process.id, {"chk": {"process": dialog.process_patch}})
        self.say("실행 위치·키 참조는 그림에 적용했습니다 — 「저장」(Ctrl+S)으로 파일에 씁니다.")

    def split_to_pc(self) -> None:
        """STU-06a — 서버에서 못 하는 노드 하나를 새 PC Bot으로 옮긴다 (ADR-0071).

        진입 정의가 열려 있고 실행 위치가 「서버」일 때만 한다(그 밖은 까닭을 말한다). 창은 고르기만
        하고 그림은 `split_actions.split()`이 **캔버스로** 바꾼다.
        """
        from chaeksas.studio import split_actions  # noqa: PLC0415 — 쓸 때만 든다
        from chaeksas.studio.split_dialog import SplitDialog  # noqa: PLC0415

        if self.process is None:
            self.say("열린 BPM 프로세스가 없습니다.")
            return
        entry = self.process.entry_definition
        if entry is None or entry.process is None or self.definition != entry.path:
            self.say("나누기는 진입 정의를 연 채로 합니다 — 진입 정의를 여세요.")
            return
        if (entry.process.info.run_location or "server") != "server":
            self.say("실행 위치가 「서버」인 BPM 프로세스만 나눕니다.")
            return
        found = split_actions.blockers(entry.process, self.task_type_locations())
        if not found:
            self.say("서버에서 못 하는 노드가 없습니다 — 나눌 것이 없습니다.")
            return
        dialog = SplitDialog(
            entry.process,
            found,
            server_id=self.process.id,
            server_name=self.process.display,
            taken=lambda one: self.workspace.find(one) is not None,
            parent=self,
        )
        if not dialog.exec() or dialog.plan is None:
            return
        split_actions.split(self, dialog.plan)

    def edit_cases(self) -> None:
        """STU-07. 케이스는 **열린 정의 옆**에 있다 — 무엇의 케이스인지 모호하지 않게."""
        found = self.opened_definition()
        if self.process is None or found is None:
            self.say("열린 정의가 없습니다.")
            return
        CaseDialog(self, self.process, found).exec()
        self.say(f"시험 케이스: {self.process.case_file(found).name}")

    # ── 열고 닫기 (하는 일은 `file_actions`에 있다) ──

    def open_definition(self, path_text: str) -> None:
        file_actions.open_definition(self, path_text)

    def save(self) -> bool:
        return file_actions.save(self)

    def new_process(self) -> None:
        file_actions.new_process(self)

    def import_example(self) -> None:
        file_actions.import_example(self)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 — Qt 이름 그대로
        """닫기 보호 (U11) → **돌던 것 멈추기** → 마지막 정의 기억하기."""
        if not file_actions.may_discard(self):
            event.ignore()
            return
        # 창이 없어진 뒤 타이머가 깨어나면 안 된다.
        run_actions.stop_test(self)
        self.receiver.stop()
        file_actions.remember_last_opened(self)
        layout.write(
            self.layout_path(),
            layout.capture(
                self, self.middle, self.split, collapsed=self.collapse_action.isChecked()
            ),
        )
        event.accept()


__all__ = ["DEFAULT_SIZE", "NO_CENTER_SETTINGS", "NO_PROCESS", "TITLE", "MainWindow"]
