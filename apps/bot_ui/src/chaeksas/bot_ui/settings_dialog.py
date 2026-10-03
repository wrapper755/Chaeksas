"""BUI-03 설정·등록. **처음 실행하면 이 창이 먼저 뜬다** (등록이 안 되어 있으므로).

키는 칸에 가려 넣고 **OS 비밀 저장소**로 간다 (설정 파일에 넣지 않는다, CLAUDE.md §5).
「연결 테스트」는 실제로 Center에 등록해 보고 결과를 한 줄로 보여 준다 (BUI-03).

아직 없는 섹션(툴팩 비밀, 확장별 설정)은 **끄고 이유를 가까이에 적는다** (U3) — 확장 호스트가
설정 칸을 기여하는 것은 M4다.
"""

from __future__ import annotations

import logging
from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from chaeksas.bot_ui import autostart as autostart_module
from chaeksas.bot_ui.agent import Agent
from chaeksas.bot_ui.center_client import CenterProblem, KeyRejected, MachineMismatch, Unreachable
from chaeksas.bot_ui.credentials import SecretsUnavailable
from chaeksas.bot_ui.settings import START_ALWAYS, START_WHEN_NEEDED, RuntimeSettings, Settings

log = logging.getLogger(__name__)

#: 키를 넣었는지 사람에게 알려 주는 자리 글. **값은 보이지 않는다.**
KEY_SET_PLACEHOLDER = "저장된 키가 있습니다 (바꾸려면 새로 붙여 넣으세요)"
KEY_EMPTY_PLACEHOLDER = "Center 콘솔 「Center API 키」에서 발급한 키"


class SettingsDialog(QDialog):
    """설정 창. 「저장」을 누를 때까지 `Agent`의 설정을 건드리지 않는다."""

    def __init__(self, agent: Agent, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._agent = agent
        self._autostart = autostart_module.autostart()
        self.setWindowTitle("Bot UI 설정")
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.addWidget(self._center_box())
        layout.addWidget(self._run_box())
        layout.addWidget(self._runtime_box())
        layout.addWidget(self._later_box())

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("저장")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

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

        note = QLabel("Worker 프로세스와 UI 자동화 설정은 UI 자동화 확장이 붙는 M4에 채워집니다.")
        note.setWordWrap(True)
        note.setEnabled(False)
        form.addRow(note)
        return box

    def _later_box(self) -> QGroupBox:
        """아직 없는 섹션 — 끄고 이유를 적는다 (U3)."""
        box = QGroupBox("나중에")
        box.setEnabled(False)
        layout = QVBoxLayout(box)
        for text in (
            "메시지 수신 포트 — ReceiveTask·메시지 시작 이벤트가 생기는 M3",
            "확장별 설정 (UI 자동화 등록 담당자 키) — M4",
            "툴팩 비밀 — M3",
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
            runtimes=(worker,),
        )

    def save(self) -> None:
        """설정 파일에 쓰고, 키를 비밀 저장소에, 자동 시작을 OS에 반영한다."""
        typed = self.api_key.text().strip()
        if typed:
            try:
                self._agent.credentials.set_center_api_key(typed)
            except SecretsUnavailable as e:
                QMessageBox.warning(self, "키를 저장하지 못했습니다", str(e))
                return

        wanted = self._pending_settings()
        self._agent.settings = wanted
        wanted.save()

        if self._autostart.available:
            try:
                self._autostart.enable() if wanted.autostart else self._autostart.disable()
            except RuntimeError as e:  # pragma: no cover - 권한 문제
                QMessageBox.warning(self, "자동 시작", str(e))
        self.accept()


__all__ = ["KEY_EMPTY_PLACEHOLDER", "KEY_SET_PLACEHOLDER", "SettingsDialog"]
