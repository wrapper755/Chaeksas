"""BUI-03 설정·등록. **처음 실행하면 이 창이 먼저 뜬다** (등록이 안 되어 있으므로).

키는 칸에 가려 넣고 **OS 비밀 저장소**로 간다 (설정 파일에 넣지 않는다, CLAUDE.md §5).
「연결 테스트」는 실제로 Center에 등록해 보고 결과를 한 줄로 보여 준다 (BUI-03).

아직 없는 섹션(툴팩 비밀, 확장별 설정)은 **끄고 이유를 가까이에 적는다** (U3) — 확장 호스트가
설정 칸을 기여하는 것은 M4다.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from chaeksas.bot_ui import autostart as autostart_module
from chaeksas.bot_ui.agent import Agent
from chaeksas.bot_ui.center_client import CenterProblem, KeyRejected, MachineMismatch, Unreachable
from chaeksas.bot_ui.credentials import SecretsUnavailable
from chaeksas.bot_ui.settings import (
    START_ALWAYS,
    START_WHEN_NEEDED,
    RuntimeSettings,
    Settings,
    data_dir,
)
from chaeksas.contracts import SCOPE_BOT_UI, ConfigurationItem
from chaeksas.contracts.center_keys import KEY_PREFIX, looks_like_key

log = logging.getLogger(__name__)

#: 모양이 아닌 값을 붙여 넣었을 때 (이슈 #3 — 명령 한 줄이 그대로 키로 저장돼 401만 났다).
KEY_SHAPE_MESSAGE = (
    f"Center API 키는 「{KEY_PREFIX}」로 시작하는 48자입니다 — "
    "Center 콘솔 「Center API 키」에서 발급한 값만 붙여 넣으세요."
)

#: 키를 넣었는지 사람에게 알려 주는 자리 글. **값은 보이지 않는다.**
KEY_SET_PLACEHOLDER = "저장된 키가 있습니다 (바꾸려면 새로 붙여 넣으세요)"
KEY_EMPTY_PLACEHOLDER = "Center 콘솔 「Center API 키」에서 발급한 키"
LLM_KEY_PLACEHOLDER = "키가 필요 없으면 비워 두세요"


class SettingsDialog(QDialog):
    """설정 창. 「저장」을 누를 때까지 `Agent`의 설정을 건드리지 않는다."""

    def __init__(self, agent: Agent, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._agent = agent
        #: 확장 설정 칸 — `(확장 id, 칸 이름)` → `(선언, 입력칸)`.
        self._extension_fields: dict[tuple[str, str], tuple[ConfigurationItem, QLineEdit]] = {}
        self._autostart = autostart_module.autostart()
        self.setWindowTitle("Bot UI 설정")
        self.setMinimumWidth(560)

        # 내용은 스크롤 영역에, 단추는 그 밖에 둔다 — 1920×1080을 150%로 쓰면 화면 높이가 672라
        # 창 전체가 들어가지 않고 「저장」이 화면 밖으로 나갔다 (BUI-03, 이슈 #3 2-12).
        content = QWidget()
        sections = QVBoxLayout(content)
        sections.setContentsMargins(0, 0, 0, 0)
        sections.addWidget(self._center_box())
        sections.addWidget(self._run_box())
        sections.addWidget(self._model_box())
        sections.addWidget(self._files_box())
        sections.addWidget(self._runtime_box())
        for box in self._extension_boxes():
            sections.addWidget(box)
        sections.addWidget(self._later_box())
        sections.addStretch(1)

        self.sections_area = QScrollArea()
        self.sections_area.setWidget(content)
        self.sections_area.setWidgetResizable(True)
        self.sections_area.setFrameShape(QFrame.Shape.NoFrame)
        self.sections_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("저장")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.sections_area, 1)
        layout.addWidget(buttons)
        self._fit_to_screen(content)

    def _fit_to_screen(self, content: QWidget) -> None:
        """내용이 다 보이는 높이로 열되, 화면(작업 표시줄 뺀 영역)을 넘지 않게."""
        screen = self.screen() or QGuiApplication.primaryScreen()
        available = screen.availableGeometry().height() if screen else 0
        # 스크롤 영역 밖(단추·여백·제목 표시줄)이 차지하는 몫을 남긴다.
        outside = self.sizeHint().height() - self.sections_area.sizeHint().height()
        wanted = content.sizeHint().height() + outside
        height = min(wanted, int(available * 0.9)) if available else wanted
        self.resize(max(self.minimumWidth(), self.sizeHint().width()), height)

    # ── 섹션 ──

    def _center_box(self) -> QGroupBox:
        box = QGroupBox("Center")
        form = QFormLayout(box)

        self.center_url = QLineEdit(self._agent.settings.center_url)
        self.center_url.setPlaceholderText("http://center.example.com:8800")
        form.addRow("주소", self.center_url)

        self.name = QLineEdit(self._agent.settings.name or "")
        self.name.setPlaceholderText(f"비우면 PC 이름 ({self._agent.display_name()})")
        form.addRow("이 PC의 표시 이름", self.name)

        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        has_key = bool(self._agent.credentials.center_api_key())
        self.api_key.setPlaceholderText(KEY_SET_PLACEHOLDER if has_key else KEY_EMPTY_PLACEHOLDER)
        form.addRow("Center API 키", self.api_key)

        test = QPushButton("연결 테스트")
        test.clicked.connect(self.test_connection)
        form.addRow("", test)

        self.result_label = QLabel(self._initial_result())
        self.result_label.setWordWrap(True)
        self.result_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow("", self.result_label)
        return box

    def _run_box(self) -> QGroupBox:
        box = QGroupBox("실행")
        form = QFormLayout(box)

        self.autostart = QCheckBox("로그인할 때 자동 시작")
        self.autostart.setChecked(self._agent.settings.autostart)
        if not self._autostart.available:
            # 못 하는 OS면 끄고 이유를 보인다 (U3).
            self.autostart.setChecked(False)
            self.autostart.setEnabled(False)
            self.autostart.setToolTip(getattr(self._autostart, "reason", ""))
        form.addRow(self.autostart)

        self.remote_approval = QCheckBox("결재를 Center로 올리기")
        self.remote_approval.setChecked(self._agent.settings.remote_approval)
        self.remote_approval.setToolTip(
            "BPM 프로세스의 결재 위치가 「Bot UI 설정을 따름」인 결재에만 적용됩니다 (Studio가 정한 것이 우선)."
        )
        form.addRow(self.remote_approval)

        self.signed_only = QCheckBox("서명된 패키지만 설치")
        self.signed_only.setChecked(self._agent.settings.signed_only)
        form.addRow(self.signed_only)

        self.queue_max = QSpinBox()
        self.queue_max.setRange(1, 200)
        self.queue_max.setValue(self._agent.settings.queue_max)
        self.queue_max.setToolTip("실행 자리는 하나로 고정입니다 (PC 한 대에 실행 중 Bot은 하나).")
        form.addRow("대기열 크기", self.queue_max)
        return box

    def _model_box(self) -> QGroupBox:
        """BUI-03 「모델」 (ADR-0027). **주소·키는 여기만 안다** — BPM 프로세스에 들어가지 않는다."""
        box = QGroupBox("모델")
        form = QFormLayout(box)

        self.llm_url = QLineEdit(self._agent.settings.llm_base_url)
        self.llm_url.setPlaceholderText("http://localhost:11434 (OpenAI 호환 주소. 비우면 AI 태스크가 돌지 않습니다)")
        form.addRow("주소", self.llm_url)

        self.llm_model = QLineEdit(self._agent.settings.llm_model)
        form.addRow("모델 이름", self.llm_model)

        self.llm_key = QLineEdit()
        self.llm_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.llm_key.setPlaceholderText(
            KEY_SET_PLACEHOLDER if self._agent.credentials.llm_api_key() else LLM_KEY_PLACEHOLDER
        )
        form.addRow("API 키", self.llm_key)

        note = QLabel("키가 필요 없는 로컬 모델(Ollama·vLLM)이면 비워 두세요 — 비우면 보내지 않습니다.")
        note.setWordWrap(True)
        note.setEnabled(False)
        form.addRow("", note)
        return box

    def _files_box(self) -> QGroupBox:
        """BUI-03 「파일」 (ADR-0026). **여기 적은 폴더만** Bot이 읽을 수 있다."""
        box = QGroupBox("파일")
        layout = QVBoxLayout(box)

        self.readable = QListWidget()
        for one in self._agent.settings.readable_dirs:
            self.readable.addItem(str(one))
        layout.addWidget(self.readable)

        buttons = QHBoxLayout()
        add = QPushButton("추가...")
        add.clicked.connect(self.add_readable)
        drop = QPushButton("삭제")
        drop.clicked.connect(self.drop_readable)
        buttons.addWidget(add)
        buttons.addWidget(drop)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        where = QLabel(f"출력 폴더: {data_dir() / 'outputs'}/<Bot> (고정)")
        where.setWordWrap(True)
        where.setEnabled(False)
        layout.addWidget(where)

        note = QLabel("읽기 허용 폴더가 비어 있으면 파일을 읽는 태스크는 실패합니다 (조용히 넘어가지 않습니다).")
        note.setWordWrap(True)
        note.setEnabled(False)
        layout.addWidget(note)
        return box

    def add_readable(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "읽기 허용 폴더 추가")
        if not chosen:
            return
        if not self.readable.findItems(chosen, Qt.MatchFlag.MatchExactly):
            self.readable.addItem(chosen)

    def drop_readable(self) -> None:
        for item in self.readable.selectedItems():
            self.readable.takeItem(self.readable.row(item))

    def readable_dirs(self) -> tuple[Path, ...]:
        return tuple(Path(self.readable.item(i).text()) for i in range(self.readable.count()))

    def _runtime_box(self) -> QGroupBox:
        box = QGroupBox("로컬 런타임")
        form = QFormLayout(box)
        worker = self._agent.settings.runtime("worker")

        self.worker_port = QSpinBox()
        self.worker_port.setRange(1024, 65535)
        self.worker_port.setValue(worker.port if worker else 0)
        form.addRow("Worker 포트", self.worker_port)

        self.worker_always = QCheckBox("항상 띄워 두기 (끄면 필요할 때 시작)")
        self.worker_always.setChecked(bool(worker and worker.start == START_ALWAYS))
        form.addRow(self.worker_always)

        return box

    def _extension_boxes(self) -> list[QGroupBox]:
        """BUI-03 「확장별 설정」 — 확장의 `configuration` 기여로 **그 자리에서** 만든다 (C13).

        Bot UI는 어느 확장인지 모른다. 비밀 칸은 값을 보이지 않고 OS 비밀 저장소로 간다
        (ADR-0013) — **설정 파일에는 들어가지 않는다.**
        """
        self._extension_fields = {}
        host = self._agent.host
        if host is None:
            return []
        out = []
        for found in host.all():
            items = [one for one in found.manifest.contributes.configuration if one.scope == SCOPE_BOT_UI]
            if not items:
                continue
            box = QGroupBox(found.manifest.name)
            form = QFormLayout(box)
            stored = self._agent.settings.extension(found.id)
            for item in items:
                field = QLineEdit()
                if item.secret:
                    field.setEchoMode(QLineEdit.EchoMode.Password)
                    has = bool(self._agent.credentials.extension_secret(found.id, item.key))
                    field.setPlaceholderText(KEY_SET_PLACEHOLDER if has else KEY_EMPTY_PLACEHOLDER)
                else:
                    field.setText(str(stored.get(item.key, "")))
                form.addRow(item.label, field)
                self._extension_fields[(found.id, item.key)] = (item, field)
            out.append(box)
        return out

    def _extension_values(self) -> dict[str, dict[str, object]]:
        """비밀이 **아닌** 칸만 (비밀은 `save()`가 비밀 저장소로 보낸다)."""
        out: dict[str, dict[str, object]] = {}
        for (extension_id, key), (item, field) in self._extension_fields.items():
            if item.secret:
                continue
            out.setdefault(extension_id, dict(self._agent.settings.extension(extension_id)))
            out[extension_id][key] = field.text().strip()
        return out

    def _later_box(self) -> QGroupBox:
        """아직 없는 섹션 — 끄고 이유를 적는다 (U3)."""
        box = QGroupBox("나중에")
        box.setEnabled(False)
        layout = QVBoxLayout(box)
        for text in (
            "메시지 수신 포트 — 메시지 시작 이벤트를 바깥에서 받는 M5",
            "툴팩 비밀 — M5",
        ):
            layout.addWidget(QLabel(text))
        return box

    # ── 동작 ──

    def _initial_result(self) -> str:
        if not self._agent.credentials.center_api_key():
            return "아직 등록되지 않았습니다 — 콘솔에서 발급한 Center API 키를 넣고 「연결 테스트」를 누르세요."
        if self._agent.registered:
            return f"등록됨 — 이 PC는 「{self._agent.display_name()}」입니다."
        return "키는 있지만 아직 등록되지 않았습니다."

    def test_connection(self) -> None:
        """실제로 등록해 본다 (C4 등록은 멱등이라 여러 번 눌러도 된다).

        **동기 호출이지만** 창이 떠 있는 동안의 한 번이고 사람이 결과를 기다리는 중이다
        (타임아웃 10초, `center_client.DEFAULT_TIMEOUT_S`).
        """
        wanted = self._pending_settings()
        typed = self.api_key.text().strip()
        if typed:
            if not looks_like_key(typed):
                # 모양부터 틀린 값을 저장하면 등록이 401로만 실패해 이유를 알 수 없다 (이슈 #3).
                self.result_label.setText(KEY_SHAPE_MESSAGE)
                return
            try:
                self._agent.credentials.set_center_api_key(typed)
            except SecretsUnavailable as e:
                self.result_label.setText(f"키를 저장하지 못했습니다 — {e}")
                return
            self.api_key.clear()
            self.api_key.setPlaceholderText(KEY_SET_PLACEHOLDER)

        before = self._agent.settings
        self._agent.settings = wanted
        try:
            found = self._agent.register()
        except Unreachable as e:
            self.result_label.setText(f"닿지 못함 — {e}")
        except KeyRejected as e:
            self.result_label.setText(f"키가 거부되었습니다 — {e} (콘솔에서 키 상태를 확인하세요)")
        except MachineMismatch as e:
            self.result_label.setText(f"{e}")
        except CenterProblem as e:
            self.result_label.setText(f"등록하지 못했습니다 — {e}")
        else:
            self.result_label.setText(
                f"연결됨 — 이 PC는 「{wanted.name or self._agent.display_name()}」으로 등록됨 ({found.bot_ui_id})"
            )
            return
        # 실패했으면 설정을 되돌린다 (저장을 누르지 않았으므로).
        self._agent.settings = before

    def _pending_settings(self) -> Settings:
        worker = RuntimeSettings(
            runtime_id="worker",
            port=self.worker_port.value(),
            start=START_ALWAYS if self.worker_always.isChecked() else START_WHEN_NEEDED,
        )
        return replace(
            self._agent.settings,
            center_url=self.center_url.text().strip() or self._agent.settings.center_url,
            name=self.name.text().strip() or None,
            autostart=self.autostart.isChecked(),
            remote_approval=self.remote_approval.isChecked(),
            signed_only=self.signed_only.isChecked(),
            queue_max=self.queue_max.value(),
            llm_base_url=self.llm_url.text().strip(),
            llm_model=self.llm_model.text().strip() or self._agent.settings.llm_model,
            readable_dirs=self.readable_dirs(),
            runtimes=(worker,),
            extensions={**self._agent.settings.extensions, **self._extension_values()},
        )

    def save(self) -> None:
        """설정 파일에 쓰고, 키를 비밀 저장소에, 자동 시작을 OS에 반영한다."""
        typed = self.api_key.text().strip()
        if typed:
            if not looks_like_key(typed):
                QMessageBox.warning(self, "키 모양이 다릅니다", KEY_SHAPE_MESSAGE)
                self.api_key.selectAll()
                self.api_key.setFocus()
                return
            try:
                self._agent.credentials.set_center_api_key(typed)
            except SecretsUnavailable as e:
                QMessageBox.warning(self, "키를 저장하지 못했습니다", str(e))
                return

        model_key = self.llm_key.text().strip()
        if model_key:
            try:
                self._agent.credentials.set_llm_api_key(model_key)
            except SecretsUnavailable as e:
                QMessageBox.warning(self, "모델 키를 저장하지 못했습니다", str(e))
                return

        for (extension_id, key), (item, field) in self._extension_fields.items():
            typed_secret = field.text().strip()
            if not item.secret or not typed_secret:
                continue
            try:
                self._agent.credentials.set_extension_secret(extension_id, key, typed_secret)
            except SecretsUnavailable as e:
                QMessageBox.warning(self, f"{item.label}을 저장하지 못했습니다", str(e))
                return

        wanted = self._pending_settings()
        failure = None
        if self._autostart.available:
            try:
                self._autostart.enable() if wanted.autostart else self._autostart.disable()
            except RuntimeError as e:
                # 켰다고 저장해 두면 다음에 열 때 칸이 거짓말을 한다 — OS의 실제 상태를 남긴다 (BUI-03).
                failure = str(e)
                wanted = replace(wanted, autostart=self._autostart.enabled())
                self.autostart.setChecked(wanted.autostart)

        self._agent.settings = wanted
        wanted.save()
        if failure:
            QMessageBox.warning(self, "자동 시작", failure)
        self.accept()


__all__ = [
    "KEY_EMPTY_PLACEHOLDER",
    "KEY_SET_PLACEHOLDER",
    "KEY_SHAPE_MESSAGE",
    "LLM_KEY_PLACEHOLDER",
    "SettingsDialog",
]
