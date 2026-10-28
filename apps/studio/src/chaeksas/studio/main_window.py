"""STU-01 메인 창 — 탐색기 · 캔버스 · 속성 패널 · 아래 탭 · 상태 줄.

**창이 쥐는 것**은 열린 BPM 프로세스·정의 하나, 캔버스, 돌고 있는 시험 실행이다. 제목·메뉴·
단축키·닫기 보호는 `docs/06-screens/studio.md` STU-01 그대로다. 아직 없는 것은 「아직 없다」고
말한다 — 빈 상자를 말없이 두지 않는다.

**메뉴 동작 중 큰 두 묶음은 떼어 냈다** (이 파일이 500줄 선을 넘어서다, CLAUDE.md §4):
`export_actions`(내보내기·올리기 넷)와 `run_actions`(시험 실행 몰이). 둘은 창을 받아 쓰고,
창은 그들이 쓰는 **작은 길**만 공개한다 — `saved_to_disk()`·`readiness()`·`say()`·
`show_preflight()`·`show_variables()`·`variables_running()`·`reset_ui_sessions()`·`show_ui_session()`. 창이 그 일의
속을 알지는 않는다 — 아래 탭의 글·줄은 떼어 낸 모듈과 `ui_sessions.py`가 짓는다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence, QPalette
from PySide6.QtWidgets import (
    QDockWidget,
    QFrame,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from chaeksas.contracts import Violation
from chaeksas.contracts.bpmn_ext import BpmnProcess, BpmnReadError, read_process
from chaeksas.core.preflight import key_apps_of
from chaeksas.qt.theme.tokens import SPACE_2
from chaeksas.studio import (
    center_actions,
    dev_keys,
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
from chaeksas.studio.connect_dialog import CenterConnectDialog
from chaeksas.studio.dev_keys import DevKeys
from chaeksas.studio.explorer import Explorer
from chaeksas.studio.extension_dialog import StudioExtensionsDialog, pin_patch
from chaeksas.studio.extensions import Extensions
from chaeksas.studio.packaging import build_manifest
from chaeksas.studio.preflight import Preflight, inspect, readiness, summarize
from chaeksas.studio.process_dialog import ProcessInfoDialog
from chaeksas.studio.properties import Properties
from chaeksas.studio.receiver import Receiver
from chaeksas.studio.runner import CaseRun, Outcome, Plan
from chaeksas.studio.settings import Settings
from chaeksas.studio.settings_dialog import StudioSettingsDialog
from chaeksas.studio.ui_sessions import Row as UiSessionRow
from chaeksas.studio.ui_sessions import UiSessions
from chaeksas.studio.variables import known_names, made_by
from chaeksas.studio.variables_tab import RUNNING, VariablesTab
from chaeksas.studio.workspace import BpmProcess, Definition, Workspace

log = logging.getLogger(__name__)


TITLE = "Chaeksas Studio"
NO_PROCESS = "(BPM 프로세스를 선택하거나 새로 만드세요)"
DEFAULT_SIZE = (1400, 860)
#: 도구 모음의 실행 단추 (STU-01 [B]) — 실행 중에는 수행 모드에 맞는 중지 글이 된다 (U5).
RUN_TEXT = "실행..."
STOP_TEXTS = {
    run_dialog.AUTONOMOUS: "자율 수행 중지",
    run_dialog.DETERMINISTIC: "결정 수행 중지",
}

PACKAGE_FILTER = "패키지 (*.zip)"
#: 캔버스가 바뀐 뒤 「변수」 탭이 그림을 다시 읽기까지 (ms) — 끌기 한 번에 여러 번 바뀐다.
VARIABLES_DELAY_MS = 300

def ask_unapplied(parent: QWidget, text: str, problem: str | None) -> QMessageBox.StandardButton:
    """「적용하지 않은 변경사항」 — 「적용」/「버리기」/「머무르기」 (STU-04). 지금 적용할 수 없으면 「적용」을 뺀다."""
    buttons = QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel
    if problem is None:
        buttons |= QMessageBox.StandardButton.Apply
    box = QMessageBox(parent)
    box.setWindowTitle("적용하지 않은 변경사항")
    box.setText(text + (f"\n\n지금 적용할 수 없습니다 — {problem}" if problem else ""))
    box.setStandardButtons(buttons)
    box.button(QMessageBox.StandardButton.Discard).setText("버리기")
    box.button(QMessageBox.StandardButton.Cancel).setText("머무르기")
    if problem is None:
        box.button(QMessageBox.StandardButton.Apply).setText("적용")
    return QMessageBox.StandardButton(box.exec())


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

        self.explorer = Explorer(self.workspace, self, listed=settings.open_processes)
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
        self.extensions.dev_keys = self.dev_keys
        self.properties = Properties(self, extensions=self.extensions)
        self.properties.applying.connect(self._apply_properties)
        self.canvas.selected.connect(self._on_selected)

        self.preflight = Preflight(self)
        self.preflight.jumping.connect(lambda node_id: self.canvas.call("select", node_id))

        # STU-09 「UI 태스크」. 재료는 C3 `ui_session`이라 **플랫폼이 그린다** (ADR-0042 — 확장이
        # 기여한 칸이 아니다. BUI-09는 재료가 C10이라 그쪽이 그린다).
        self.ui_sessions = UiSessions(self)

        # 「변수」 — 입력·출력 **정의**와 시험 실행의 지금 값 (STU-01). 그림은 캔버스에서 읽고
        # 「적용」은 캔버스로 넘긴다 (ADR-0022). 캔버스가 바뀔 때마다 읽으면 한 번에 몇 번씩이라 모아 읽는다.
        self.variables = VariablesTab(self)
        self.variables.applying.connect(self._apply_variables)
        self._variables_timer = QTimer(self)
        self._variables_timer.setSingleShot(True)
        self._variables_timer.setInterval(VARIABLES_DELAY_MS)
        self._variables_timer.timeout.connect(self.refresh_variables)
        #: 돌릴 것이 남아 있는 계획과 지금까지의 결과 (「모든 케이스 차례로」).
        self.queue: list[Plan] = []
        self.outcomes: list[Outcome] = []
        self.running: CaseRun | None = None
        self.receiver = Receiver(port=settings.receiver_port)

        self._build_layout()
        self._build_menus()
        self._build_toolbar()
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
        tabs.setObjectName("PaneTabs")
        self.explorer_tabs = tabs
        tabs.addTab(self.explorer, "BPM 프로세스")
        tabs.addTab(self.resource_tree, "리소스")
        # 바깥 틈 — 창 가장자리와 캔버스 쪽 틈은 분할자·가운데 영역이 낸다.
        dock.setWidget(_margined(tabs, SPACE_2, SPACE_2, 0, SPACE_2))
        # STU-01 [E] — 왼쪽 고정, 제목 줄 없음 (띄우기·닫기·옮기기가 없다 — 닫아 잃어버릴 일이 없다).
        dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        dock.setTitleBarWidget(QWidget(dock))
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)

        self.explorer_dock = dock
        middle = QSplitter(Qt.Orientation.Horizontal, self)
        self.middle = middle
        middle.addWidget(_pane(self.canvas))
        self.properties_pane = _pane(self.properties)
        middle.addWidget(self.properties_pane)
        middle.setObjectName("middleSplit")
        middle.setStretchFactor(0, 3)  # 캔버스와 속성 패널은 3:1 (STU-01)
        middle.setStretchFactor(1, 1)
        # 처음 비율도 3:1이다 — 비율만 주면 첫 크기는 위젯의 sizeHint가 정해 캔버스가 좁게 뜬다.
        # 분할자는 준 크기를 지금 너비에 비례해 맞추므로 큰 수로 비율만 준다.
        middle.setSizes([3000, 1000])

        bottom = QTabWidget(self)
        bottom.setObjectName("PaneTabs")
        self.bottom_tabs = bottom
        bottom.addTab(self.log_view, "로그")
        bottom.addTab(self.preflight, "검사")
        bottom.addTab(self.ui_sessions, "UI 태스크")
        bottom.addTab(self.variables, "변수")

        split = QSplitter(Qt.Orientation.Vertical, self)
        self.split = split
        split.addWidget(middle)
        split.addWidget(bottom)
        split.setObjectName("bottomSplit")
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 1)
        split.setSizes([4000, 1000])

        holder = QWidget(self)
        box = QVBoxLayout(holder)
        box.setContentsMargins(0, SPACE_2, SPACE_2, SPACE_2)
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
        self.properties_pane.setVisible(not found.properties_collapsed)

    def toggle_properties(self) -> None:
        """보기 → 「속성 패널 접기」 (Ctrl+Shift+P). 체크가 곧 접힌 상태다."""
        collapsed = self.collapse_action.isChecked()
        self.properties_pane.setVisible(not collapsed)
        self.say("속성 패널을 접었습니다." if collapsed else "속성 패널을 펼쳤습니다.")

    def reset_layout(self) -> None:
        """보기 → 「레이아웃 초기화」 — 담아 둔 것을 **지우고** 기본 배치로 돌린다.

        지우기만 하면 다음에 뜰 때나 돌아오므로, 지금 창도 함께 되돌린다.
        """
        layout.clear(self.layout_path())
        self.resize(*DEFAULT_SIZE)
        self.explorer_dock.setFloating(False)
        self.explorer_dock.show()
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.explorer_dock)
        self.collapse_action.setChecked(False)
        self.properties_pane.setVisible(True)
        # 3:1·4:1은 짤 때의 비율 그대로다 (STU-01).
        width, height = self.middle.width(), self.split.height()
        self.middle.setSizes([width * 3 // 4, width // 4])
        self.split.setSizes([height * 4 // 5, height // 5])
        self.say("레이아웃을 기본으로 돌렸습니다.")

    def _build_menus(self) -> None:
        bar = self.menuBar()
        files = bar.addMenu("파일")
        self._add(files, "새 BPM 프로세스...", self.new_process, QKeySequence.StandardKey.New)
        self._add(
            files,
            "BPM 프로세스 열기...",
            lambda: file_actions.open_process(self),
            QKeySequence.StandardKey.Open,
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
        self.undo_action = self._add(
            edit, "실행 취소", lambda: self.canvas.call("undo"), QKeySequence.StandardKey.Undo
        )
        self.redo_action = self._add(
            edit, "다시 실행", lambda: self.canvas.call("redo"), QKeySequence.StandardKey.Redo
        )

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
        self.preflight_action = self._add(run, "실행 전 검사", self.run_preflight, QKeySequence("F6"))

        settings = bar.addMenu("설정")
        self._add(settings, "설정...", self.open_settings, QKeySequence("Ctrl+,"))

        view = bar.addMenu("보기")
        self.collapse_action = self._add(
            view, "속성 패널 접기", self.toggle_properties, QKeySequence("Ctrl+Shift+P")
        )
        self.collapse_action.setCheckable(True)
        self._add(view, "레이아웃 초기화", self.reset_layout)
        self._add(view, "로그 지우기", self.log_view.clear, QKeySequence("Ctrl+L"))

        tools = bar.addMenu("도구")
        self._add(tools, "확장...", self.open_extensions)

    def refresh_catalog(self) -> None:
        """Center 리소스 목록을 받아 꽂는다 — 하는 일은 `center_actions`에 있다."""
        center_actions.refresh_catalog(self)

    def refresh_resources(self, *, reader: services.CenterReader | None) -> None:
        """받아 둔 것으로 STU-03을 그린다 (`reader`가 `None`이면 두드리지 않는다)."""
        center_actions.refresh_resources(self, reader=reader)

    def dev_keys(self) -> DevKeys:
        """개발 키 한 벌 — 승인된 Studio 키로 Center에 청한다 (ADR-0094 §5). 누를 때마다 새로 짓는다."""
        return dev_keys.from_settings(self.settings)

    def key_apps(self) -> dict[str, str]:
        """열린 BPM 프로세스의 `{키 참조: 앱}` — 빌드가 짓는 매니페스트와 **같은 것**이다 (C1)."""
        if self.process is None:
            return {}
        try:
            made = build_manifest(
                self.process,
                task_type_locations=self.task_type_locations(),
                keyless_apps=self.keyless_apps(),
                key_extensions=self.key_extensions(),
            )
        except Exception as e:  # noqa: BLE001 — 진입 정의가 없는 등 — 그때는 키를 풀 앱을 모른다
            log.debug("매니페스트를 짓지 못했다: %s", e)
            return {}
        return key_apps_of(made)

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

    def ensure_center(self, *, refused: bool = False, send_now: bool = False) -> bool:
        """STU-16 「Center에 연결」을 띄운다. 키를 받았으면 참 — 부르는 쪽이 원래 동작을 이어 간다.

        「나중에」로 닫아도 주소는 적혀 있을 수 있어 설정은 늘 받아 온다 (그 창은 「저장」이 없다).
        """
        dialog = CenterConnectDialog(self.settings, refused=refused, send_now=send_now, parent=self)
        dialog.exec()
        self.settings = dialog.settings
        if dialog.connected:
            self.say(dialog.status.text())
            self.refresh_catalog()
        return dialog.connected

    def check_center_at_start(self) -> None:
        """Studio를 켤 때 한 번 (STU-16 「언제 뜨나」). **메인 창이 먼저 뜬 뒤** 부른다.

        키가 없거나 거부됐을 때만 창을 띄운다. 닿지 못한 것·만료 14일 안은 상태 표시줄 한 줄이다.
        """
        import os  # noqa: PLC0415

        from chaeksas.studio import center_enroll  # noqa: PLC0415
        from chaeksas.studio.credentials import ENV_CENTER_API_KEY, StudioCredentials  # noqa: PLC0415

        need = center_enroll.need_at_start(
            base_url=self.settings.center_url,
            key=StudioCredentials().center_api_key(),
            from_env=bool(os.environ.get(ENV_CENTER_API_KEY)),
            key_expires=self.settings.center_key_expires,
        )
        if need.kind in (center_enroll.NEED_CONNECT, center_enroll.NEED_REFUSED):
            self.ensure_center(refused=need.kind == center_enroll.NEED_REFUSED)
        elif need.text:
            self.say(need.text)

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
        elif dialog.center_changed is not None:
            # 「Center」의 등록 요청·키 받기는 「저장」을 기다리지 않는다 (ADR-0093) — 「취소」로 닫아도 받는다.
            self.settings = dialog.center_changed
            self.refresh_catalog()

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

    def _build_toolbar(self) -> None:
        """STU-01 [B] — 메뉴와 **같은 동작**(같은 켜짐·체크)을 아이콘 + 글자 단추로. 고정이라 옮기거나 감출 수 없다.

        「실행...」만 따로다 — 실행 중에는 그 자리가 중지 단추가 된다 (U5, `show_running`).
        """
        bar = QToolBar("도구 모음", self)
        bar.setObjectName("mainToolbar")
        bar.setMovable(False)
        bar.setFloatable(False)
        bar.toggleViewAction().setVisible(False)
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.run_tool_action = QAction(RUN_TEXT, self)
        self.run_tool_action.triggered.connect(self._run_or_stop)
        bar.addAction(self.save_action)
        bar.addSeparator()
        bar.addActions([self.undo_action, self.redo_action])
        bar.addSeparator()
        bar.addActions([self.preflight_action, self.run_tool_action])
        bar.addSeparator()
        bar.addAction(self.collapse_action)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, bar)
        self.toolbar = bar
        self._paint_icons()

    def _paint_icons(self) -> None:
        """도구 모음 아이콘을 **지금 팔레트의 글자색**으로 칠한다 (팔레트는 토큰에서 온다).

        테마가 바뀌면 다시 부른다 (`changeEvent`) — 칠한 색이 아이콘에 박혀 있어서다. 실행 중 단추는
        강조색 바탕이라 그 위의 글자색(`primary.fg` = 팔레트 `HighlightedText`)으로 칠한다.
        """
        from chaeksas.qt.theme import icon  # noqa: PLC0415

        colors = self.palette()
        plain = colors.color(QPalette.ColorRole.ButtonText).name()
        on_accent = colors.color(QPalette.ColorRole.HighlightedText).name()
        for action, name in (
            (self.save_action, "save"),
            (self.undo_action, "undo-2"),
            (self.redo_action, "redo-2"),
            (self.preflight_action, "list-checks"),
            (self.collapse_action, "panel-right-close"),
        ):
            action.setIcon(icon(name, plain))
            # 메뉴와 같은 동작이지만 아이콘은 도구 모음에만 — 메뉴에서는 체크 표시(「속성 패널 접기」)를 가린다.
            action.setIconVisibleInMenu(False)
        running = self.run_tool_action.text() != RUN_TEXT
        self.run_tool_action.setIcon(
            icon("square", on_accent) if running else icon("play", plain)
        )

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 — Qt 이름 그대로
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange):
            if hasattr(self, "toolbar"):
                self._paint_icons()
        super().changeEvent(event)

    def _run_or_stop(self) -> None:
        if self.running is not None:
            run_actions.stop_test(self)
        else:
            run_actions.run_test(self)

    def show_running(self, mode: str | None) -> None:
        """U5 — 실행 중이면 도구 모음의 「실행...」이 강조색 중지 단추가 된다. `None`이면 되돌린다."""
        action = self.run_tool_action
        action.setText(STOP_TEXTS.get(mode, "실행 중지") if mode is not None else RUN_TEXT)
        self._paint_icons()
        button = self.toolbar.widgetForAction(action)
        if button is not None:
            # 스타일시트는 처음 보일 때 한 번 입힌다 — 속성을 바꾼 뒤 다시 칠한다 (`set_role`과 같은 까닭).
            button.setProperty("running", mode is not None)
            button.style().unpolish(button)
            button.style().polish(button)

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
            self._variables_timer.start()
            return
        self._variables_timer.start()  # 열고·닫고·고칠 때마다 — 「변수」 탭도 같은 상태에서 온다
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
        self.say("열린 BPM 프로세스가 없습니다 — 파일 → BPM 프로세스 열기...로 열거나 새로 만드세요.")
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
        """적용 안 한 편집이 있으면 묻는다 (STU-04 → 「변수」 탭). 지금 적용할 수 없으면 「적용」을 뺀다."""
        if not self._may_drop_properties():
            return False
        return self._may_drop_variables()

    def _may_drop_variables(self) -> bool:
        """「변수」 탭의 적용 안 한 편집 — 속성 패널과 **같은 확인**이다 (STU-01 「닫기·전환 보호」)."""
        if not self.variables.unapplied:
            return True
        _, problem = self.variables.patch()
        answer = ask_unapplied(self, "「변수」 탭에 적용하지 않은 변경사항이 있습니다.", problem)
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Apply:
            return self.variables.apply()
        self.variables.discard()
        return True

    def _may_drop_properties(self) -> bool:
        if not self.properties.unapplied:
            return True
        _, problem = self.properties.patch()
        answer = ask_unapplied(self, "속성 패널에 적용하지 않은 변경사항이 있습니다.", problem)
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

    def key_extensions(self) -> list[str]:
        """키를 받는 켜진 확장 (C13 `requires_keys` `run`) — 빌드가 그 확장의 앱 줄을 적는다 (ADR-0094)."""
        return self.extensions.host.key_extensions()

    def readiness(self) -> list[Violation]:
        """사전 점검 — **이 PC에서 돌 수 있나** (`core.preflight`, ADR-0013).

        키 값은 Studio 비밀 저장소에서, 확장은 호스트에서 온다. 시험 실행과 **같은 것을 본다**
        (`Extensions.context`) — 점검이 다른 설정을 보면 「점검은 통과했는데 실행이 안 된다」가 된다.
        """
        if self.process is None:
            return []
        return readiness(
            self.process,
            # 참조를 **그 앱의 개발 키로** 푼다 — 없으면 Center에 청한다 (ADR-0094 §5).
            key_value=self.dev_keys().resolver(self.key_apps()),
            host=self.extensions.host,
            context=self.extensions.context,
            dirty=self.dirty,
            # **어느 확장이 외부인가는 받아 둔 리소스 목록이 안다** (C7) — 외부 확장은 이 PC에
            # 깔리지 않아 호스트가 모른다. 점검은 서버를 부르지 않으므로 여기서 넘긴다 (ADR-0060).
            external_ids=self.properties.catalog.external_ids(),
            keyless_apps=self.keyless_apps(),
        )

    def keyless_apps(self) -> tuple[str, ...]:
        """**키를 받지 않는 앱** (C13 `auth`가 없는 외부 앱, ADR-0091) — B7·매니페스트·사전 점검·
        STU-06이 **같은 목록**을 본다. 받아 둔 고를 거리(STU-14)에서 꺼내고, 못 받았으면 비어 있어
        모든 앱에 키를 묻는다.
        """
        return self.properties.catalog.keyless_ids()

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
            keyless_apps=self.keyless_apps(),
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

    def show_variables(self, variables: dict[str, object]) -> None:
        """시험 실행의 지금 값 — 「변수」 탭의 정의 표에 「지금 값」 열로 붙는다 (STU-09)."""
        self.variables.show_values(variables)

    def variables_running(self, running: bool) -> None:
        """시험 실행이 시작·끝날 때 — 시작하면 지난 값을 비우고 고치기를 잠근다 (STU-01 「변수」 탭)."""
        if running:
            self.variables.clear_values()
            self.variables.set_locked(True, RUNNING)
        else:
            self.refresh_variables()

    def reset_ui_sessions(self) -> None:
        """「UI 태스크」 탭을 비운다 — 실행 하나가 시작할 때 (STU-09)."""
        self.ui_sessions.reset_rows()

    def show_ui_session(self, row: UiSessionRow) -> None:
        """UI 세션 한 줄을 더한다. **줄은 `ui_sessions.row_of`가 짓는다** (Qt를 모르는 자리)."""
        self.ui_sessions.add(row)

    def show_variables_tab(self) -> None:
        self.bottom_tabs.setCurrentWidget(self.variables)

    # ── 「변수」 탭 (STU-01) ──

    def refresh_variables(self) -> None:
        """그림을 **캔버스에서** 읽어 「변수」 탭을 채운다 — 파일에서 읽으면 「적용」한 것이 안 보인다.

        고칠 수 있는 것은 **열린 정의**다 — 하위 정의도 제 입력·출력을 가진다(호출이 그것과 맞춰
        본다, B14). 시험 실행 중이면 표는 보이고 고치기만 잠근다 (U3).
        """
        key = self.definition.as_posix() if self.definition is not None else ""
        if self.process is None or self.definition is None or not self.canvas.live:
            self.variables.show_definition(None, {}, key=key)
            self.properties.known_names.setStringList([])
            return

        def done(found: dict[str, object]) -> None:
            if not found.get("ok") or key != (self.definition.as_posix() if self.definition else ""):
                return  # 읽는 사이에 다른 정의를 열었다 — 그쪽의 읽기가 채운다
            try:
                drawn = read_process(str(found.get("xml") or ""))
            except BpmnReadError:
                return  # 그리는 중의 반쪽 그림 — 들고 있던 것을 둔다
            made = made_by(drawn)
            reason = RUNNING if self.running is not None else ""
            self.variables.show_definition(drawn.info, made, key=key, reason=reason)
            self.properties.known_names.setStringList(known_names(drawn.info, made))

        self.canvas.call("saveXML", then=done)

    def _apply_variables(self, body: str) -> None:
        """「변수」 탭의 「적용」 — 열린 정의의 `chk:process`를 **한 걸음으로** 바꾼다 (ADR-0022)."""
        try:
            drawn = read_process(self.canvas.save_xml())
        except (CanvasError, BpmnReadError) as e:
            self.say(f"적용하지 못했습니다: {e}")
            return

        def done(found: dict[str, object]) -> None:
            if not found.get("ok"):
                self.say(f"적용하지 못했습니다: {found.get('error')}")
                return
            self.say("입력·출력을 그림에 적용했습니다 — 「저장」(Ctrl+S)으로 파일에 씁니다.")
            self.refresh_variables()

        self.canvas.call("setProperties", drawn.id, {"chk": {"process": body}}, then=done)

    # ── 시험 케이스 · BPM 프로세스 정보 ──

    def opened_definition(self) -> Definition | None:
        """지금 열린 정의 (디스크에서 읽은 것). 없으면 `None`."""
        if self.process is None or self.definition is None:
            return None
        return next((d for d in self.process.definitions if d.path == self.definition), None)

    def edit_info(self) -> None:
        """STU-06. 기록은 창이 쓰고, **그림은 캔버스가** 쓴다 (XML을 파이썬이 만지지 않는다).

        그래서 실행 위치·키 참조는 **진입 정의가 열려 있을 때만** 켜진다 — 창이 그 까닭을
        적는다 (U3). 열려 있으면 「적용」이 `chk:process`를 한 걸음으로 적용해 **실행 취소도
        한 걸음**이다.
        """
        if self.process is None:
            self.say("열린 BPM 프로세스가 없습니다.")
            return
        entry = self.process.entry_definition
        editable = entry is not None and self.definition == entry.path
        if editable and not self.may_drop_edits():
            return
        from chaeksas.contracts.bpmn_ext import BpmnReadError, read_process  # noqa: PLC0415

        drawn = None
        if editable:
            # **그림은 캔버스의 지금 것을 읽는다** — 파일에서 읽으면 「적용」한 것이 Ctrl+S 전에는
            # 다시 열었을 때 안 보인다 (STU-06).
            try:
                drawn = read_process(self.canvas.save_xml())
            except (CanvasError, BpmnReadError) as e:
                self.say(f"그림을 읽지 못해 BPM 프로세스 정보를 열지 않았습니다: {e}")
                return
        dialog = ProcessInfoDialog(
            self.process,
            self.workspace,
            editable=editable,
            # 창은 호스트를 들고 있지 않다 — **F6과 같은 표**를 여기서 넘긴다 (C13).
            task_type_locations=self.task_type_locations(),
            drawn=drawn,
            parent=self,
        )
        if not dialog.exec() or dialog.saved is None:
            if dialog.split_requested:
                self.split_to_pc()
            return
        self.process = dialog.saved
        self.retitle()
        self.explorer.refresh(opened=self.definition.as_posix() if self.definition else "")
        self.say(f"BPM 프로세스 정보를 저장했습니다: {dialog.saved.display} (v{dialog.saved.version})")
        if dialog.process_patch is None or entry is None or drawn is None:
            return
        # 그림은 **캔버스에만** 반영된다 — 파일로 가는 것은 「저장」(Ctrl+S)이다 (STU-04의 「적용」과
        # 같은 결). 그렇게 말해 둬야 「저장했다는데 패키지에 안 들어갔다」가 생기지 않는다.
        self._apply_properties(drawn.id, {"chk": {"process": dialog.process_patch}})
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


__all__ = ["DEFAULT_SIZE", "NO_PROCESS", "RUN_TEXT", "STOP_TEXTS", "TITLE", "MainWindow"]


def _pane(widget: QWidget) -> QFrame:
    """STU-01 — 작업 영역 하나를 카드(흰 바탕 + 테두리)로 감싼다. 영역 사이는 바탕색 틈이 가른다."""
    frame = QFrame(widget.parentWidget())
    frame.setObjectName("Pane")
    box = QVBoxLayout(frame)
    box.setContentsMargins(1, 1, 1, 1)  # 테두리 1px 안쪽 — 캔버스(WebEngine)가 테두리를 덮지 않게
    box.addWidget(widget)
    return frame


def _margined(widget: QWidget, left: int, top: int, right: int, bottom: int) -> QWidget:
    holder = QWidget(widget.parentWidget())
    box = QVBoxLayout(holder)
    box.setContentsMargins(left, top, right, bottom)
    box.addWidget(widget)
    return holder
