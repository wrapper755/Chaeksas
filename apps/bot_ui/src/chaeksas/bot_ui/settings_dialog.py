"""BUI-03 설정·등록. **처음 실행하면 이 창이 먼저 뜬다** (등록이 안 되어 있으므로).

칸은 **탭으로 나눈다** — 「Center」·「실행」·「모델」·「파일」·「보내기」·「로컬 런타임」, 확장마다
하나, 「나중에」. 「저장」·「취소」는 탭 밖에 있어 모든 탭을 함께 저장한다.

「Center」 탭은 **주소 하나**다 — Center API 키 칸은 없다 (ADR-0092). 주소를 넣고 「연결 테스트」를
누르면 등록 요청을 보내고, 관리자가 요청 코드를 맞춰 승인하면 키를 받아 OS 비밀 저장소에 둔다.
사람은 키를 보지 않는다. 다른 키(모델·메일)는 칸에 가려 넣고 비밀 저장소로 간다 (CLAUDE.md §5).

확장별 설정 칸은 **확장이 기여한 것으로 그 자리에서 만든다** (C13 `configuration`). 아직 없는
섹션(툴팩 비밀)은 **끄고 이유를 가까이에 적는다** (U3).
"""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
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
from chaeksas.core.senders import KNOWN_SECURITY, SECURITY_NONE, SECURITY_STARTTLS

log = logging.getLogger(__name__)

#: 키를 넣었는지 사람에게 알려 주는 자리 글. **값은 보이지 않는다.**
KEY_SET_PLACEHOLDER = "저장된 키가 있습니다 (바꾸려면 새로 붙여 넣으세요)"
KEY_EMPTY_PLACEHOLDER = "넣으면 OS 비밀 저장소에 둡니다"
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

        # 탭마다 내용은 스크롤 영역에, 단추는 탭 밖에 둔다 — 1920×1080을 150%로 쓰면 화면 높이가
        # 672라 창 전체가 들어가지 않고 「저장」이 화면 밖으로 나갔다 (BUI-03, 이슈 #3 2-12).
        self.tabs = QTabWidget()
        #: 탭마다 `(스크롤 영역, 그 안의 내용)` — 탭 순서 그대로.
        self._pages: list[tuple[QScrollArea, QWidget]] = []
        self._add_tab("Center", self._center_box())
        self._add_tab("실행", self._run_box())
        self._add_tab("모델", self._model_box())
        self._add_tab("파일", self._files_box())
        self._add_tab("보내기", self._sending_box())
        self._add_tab("로컬 런타임", self._runtime_box())
        for name, box in self._extension_boxes():
            self._add_tab(name, box)
        self._add_tab("나중에", self._later_box())

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("저장")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(buttons)
        self._fit_to_screen()

    def _add_tab(self, name: str, content: QWidget) -> None:
        """탭 하나 — 내용이 창보다 길면 **그 탭의 내용만** 스크롤된다."""
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.addWidget(content)
        column.addStretch(1)
        area = QScrollArea()
        area.setWidget(page)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tabs.addTab(area, name)
        self._pages.append((area, page))

    def tab_pages(self) -> list[QWidget]:
        """탭마다 스크롤되는 내용 (탭 순서 그대로)."""
        return [page for _area, page in self._pages]

    def _fit_to_screen(self) -> None:
        """가장 긴 탭이 다 보이는 높이로 열되, 화면(작업 표시줄 뺀 영역)을 넘지 않게."""
        screen = self.screen() or QGuiApplication.primaryScreen()
        available = screen.availableGeometry().height() if screen else 0
        # 스크롤 영역 밖(탭 머리·단추·여백)이 차지하는 몫을 남긴다.
        outside = self.sizeHint().height() - max(area.sizeHint().height() for area, _page in self._pages)
        tallest = max(page.sizeHint().height() for _area, page in self._pages)
        wanted = tallest + outside
        height = min(wanted, int(available * 0.9)) if available else wanted
        self.resize(max(self.minimumWidth(), self.sizeHint().width()), height)

    # ── 섹션 ──

    def _center_box(self) -> QWidget:
        box = QWidget()
        form = QFormLayout(box)

        self.center_url = QLineEdit(self._agent.settings.center_url)
        self.center_url.setPlaceholderText("http://center.example.com:8800")
        form.addRow("주소", self.center_url)

        self.name = QLineEdit(self._agent.settings.name or "")
        self.name.setPlaceholderText(f"비우면 PC 이름 ({self._agent.display_name()})")
        form.addRow("이 PC의 표시 이름", self.name)

        test = QPushButton("연결 테스트")
        test.clicked.connect(self.test_connection)
        form.addRow("", test)

        # 상태 줄 하나 (BUI-03) — 승인을 기다리면 요청 코드를 크게, 「복사」와 함께.
        self.result_label = QLabel(self._initial_result())
        self.result_label.setWordWrap(True)
        self.result_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow("", self.result_label)

        code_row = QHBoxLayout()
        self.code_label = QLabel()
        self.code_label.setProperty("role", "h2")
        self.code_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.copy_code = QPushButton("복사")
        self.copy_code.clicked.connect(self._copy_code)
        self.again = QPushButton("다시 요청")
        self.again.clicked.connect(self.request_again)
        code_row.addWidget(self.code_label)
        code_row.addWidget(self.copy_code)
        code_row.addWidget(self.again)
        code_row.addStretch(1)
        form.addRow("", code_row)
        self._show_code()
        return box

    def _show_code(self) -> None:
        """요청 코드와 「다시 요청」을 지금 상태에 맞춘다."""
        pending = self._agent.enrollment
        waiting = (
            not self._agent.credentials.center_api_key() and pending is not None and pending.state == "pending"
        )
        self.code_label.setText(pending.code if waiting and pending is not None else "")
        self.code_label.setVisible(waiting)
        self.copy_code.setVisible(waiting)
        closed = not self._agent.credentials.center_api_key() and pending is not None and pending.state in (
            "rejected",
            "expired",
        )
        self.again.setVisible(closed or bool(self._agent.last_problem and not self._agent.registered))

    def _copy_code(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self.code_label.text())

    def _run_box(self) -> QWidget:
        box = QWidget()
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

    def _model_box(self) -> QWidget:
        """BUI-03 「모델」 (ADR-0027). **주소·키는 여기만 안다** — BPM 프로세스에 들어가지 않는다."""
        box = QWidget()
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

    def _files_box(self) -> QWidget:
        """BUI-03 「파일」 (ADR-0026). **여기 적은 폴더만** Bot이 읽을 수 있다."""
        box = QWidget()
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

        layout.addWidget(QLabel("쓰기 허용 폴더"))
        self.writable = QListWidget()
        for one in self._agent.settings.writable_dirs:
            self.writable.addItem(str(one))
        layout.addWidget(self.writable)

        write_buttons = QHBoxLayout()
        add_write = QPushButton("추가...")
        add_write.clicked.connect(self.add_writable)
        drop_write = QPushButton("삭제")
        drop_write.clicked.connect(self.drop_writable)
        write_buttons.addWidget(add_write)
        write_buttons.addWidget(drop_write)
        write_buttons.addStretch(1)
        layout.addLayout(write_buttons)

        # **적은 폴더 안의 파일을 Bot이 고칠 수 있다** — 넓히는 일이라 분명히 말한다 (ADR-0032).
        warn = QLabel(
            "비워 두면 Bot은 출력 폴더 안에만 씁니다. 폴더를 적으면 **그 안의 파일을 Bot이 "
            "고칠 수 있습니다** (공유 장부에 덧붙이는 업무에 필요합니다)."
        )
        warn.setWordWrap(True)
        warn.setEnabled(False)
        layout.addWidget(warn)
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

    def add_writable(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "쓰기 허용 폴더 추가")
        if not chosen:
            return
        if not self.writable.findItems(chosen, Qt.MatchFlag.MatchExactly):
            self.writable.addItem(chosen)

    def drop_writable(self) -> None:
        for item in self.writable.selectedItems():
            self.writable.takeItem(self.writable.row(item))

    def writable_dirs(self) -> tuple[Path, ...]:
        return tuple(Path(self.writable.item(i).text()) for i in range(self.writable.count()))

    def _sending_box(self) -> QWidget:
        """BUI-03 「보내기」 ([ADR-0059](../../../../../docs/decisions/0059-sending-mail-and-webhooks.md)).

        **비어 있으면 `chk:email`이 보내지 않고 실패한다** — 조용히 넘어가지 않는다. 비밀번호는
        설정 파일이 아니라 OS 비밀 저장소로 간다 (CLAUDE.md §5).
        """
        box = QWidget()
        form = QFormLayout(box)
        settings = self._agent.settings

        self.smtp_host = QLineEdit(settings.smtp_host)
        self.smtp_host.setPlaceholderText("smtp.example.com (비우면 메일 태스크가 실패합니다)")
        form.addRow("SMTP 주소", self.smtp_host)

        self.smtp_security = QComboBox()
        for one in KNOWN_SECURITY:
            self.smtp_security.addItem(one)
        self.smtp_security.setCurrentText(
            settings.smtp_security if settings.smtp_security in KNOWN_SECURITY else SECURITY_STARTTLS
        )
        self.smtp_security.currentTextChanged.connect(self._say_security)
        form.addRow("보안", self.smtp_security)

        self.smtp_port = QSpinBox()
        self.smtp_port.setRange(0, 65535)
        self.smtp_port.setSpecialValueText("기본")
        self.smtp_port.setValue(settings.smtp_port)
        self.smtp_port.setToolTip("비우면(0) 보안에 맞는 기본 포트를 씁니다 — starttls 587 · ssl 465 · none 25.")
        form.addRow("포트", self.smtp_port)

        self.smtp_user = QLineEdit(settings.smtp_username)
        form.addRow("사용자", self.smtp_user)

        self.smtp_password = QLineEdit()
        self.smtp_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.smtp_password.setPlaceholderText(
            KEY_SET_PLACEHOLDER if self._agent.credentials.smtp_password() else "비워 두면 로그인하지 않습니다"
        )
        form.addRow("비밀번호", self.smtp_password)

        self.smtp_from = QLineEdit(settings.smtp_sender)
        self.smtp_from.setPlaceholderText("bot@example.com (받는 쪽이 보는 보내는 주소)")
        form.addRow("보내는 주소", self.smtp_from)

        self.smtp_attachment = QDoubleSpinBox()
        self.smtp_attachment.setRange(0.1, 100.0)
        self.smtp_attachment.setSingleStep(1.0)
        self.smtp_attachment.setSuffix(" MB")
        self.smtp_attachment.setValue(settings.smtp_attachment_mb)
        form.addRow("첨부 합계 상한", self.smtp_attachment)

        self.security_note = QLabel("")
        self.security_note.setWordWrap(True)
        self.security_note.setEnabled(False)
        form.addRow("", self.security_note)
        self._say_security(self.smtp_security.currentText())

        form.addRow(QLabel("웹훅 허용 호스트"))
        self.webhook_hosts = QListWidget()
        for one in settings.webhook_allowed_hosts:
            self.webhook_hosts.addItem(str(one))
        form.addRow(self.webhook_hosts)

        buttons = QHBoxLayout()
        add = QPushButton("추가...")
        add.clicked.connect(self.add_webhook_host)
        drop = QPushButton("삭제")
        drop.clicked.connect(self.drop_webhook_host)
        buttons.addWidget(add)
        buttons.addWidget(drop)
        buttons.addStretch(1)
        form.addRow(buttons)

        note = QLabel(
            "비워 두면 웹훅을 **아무 데도 보내지 않습니다**. 적은 호스트만 열리고, "
            "사설·루프백 주소는 적어도 열리지 않습니다."
        )
        note.setWordWrap(True)
        note.setEnabled(False)
        form.addRow("", note)
        return box

    def _say_security(self, value: str) -> None:
        """`none`을 고르면 **위험을 분명히 말한다** (쓰기 허용 폴더와 같은 결)."""
        if value == SECURITY_NONE:
            self.security_note.setText("암호화하지 않고 보냅니다 — 사내 중계기에만 쓰세요.")
        else:
            self.security_note.setText("")

    def add_webhook_host(self) -> None:
        typed, ok = QInputDialog.getText(self, "웹훅 허용 호스트", "호스트 이름 (예: hooks.example.com)")
        host = typed.strip() if ok else ""
        if not host:
            return
        if host in self.webhook_host_list():
            return  # 같은 호스트를 두 번 적지 않는다
        self.webhook_hosts.addItem(host)

    def drop_webhook_host(self) -> None:
        for item in self.webhook_hosts.selectedItems():
            self.webhook_hosts.takeItem(self.webhook_hosts.row(item))

    def webhook_host_list(self) -> tuple[str, ...]:
        return tuple(
            self.webhook_hosts.item(i).text() for i in range(self.webhook_hosts.count())
        )

    def _runtime_box(self) -> QWidget:
        box = QWidget()
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

    def _extension_boxes(self) -> list[tuple[str, QWidget]]:
        """BUI-03 「확장별 설정」 — **확장마다 탭 하나**(이름은 확장 이름).

        확장의 `configuration` 기여로 **그 자리에서** 만든다 (C13).

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
            box = QWidget()
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
            out.append((found.manifest.name, box))
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

    def _later_box(self) -> QWidget:
        """아직 없는 섹션 — 끄고 이유를 적는다 (U3)."""
        box = QWidget()
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
        if self._agent.credentials.center_key_from_env():
            return "환경변수의 키를 씁니다 (CHK_BOT_UI__CENTER_API_KEY)."
        if not self._agent.credentials.center_api_key():
            return enrollment_text(self._agent)
        if self._agent.registered:
            return f"연결됨 — 이 PC는 「{self._agent.display_name()}」으로 등록됨"
        return "키를 받았습니다 — 「연결 테스트」를 누르면 등록합니다."

    def test_connection(self) -> None:
        """실제로 등록해 본다 (C4 등록은 멱등이라 여러 번 눌러도 된다).

        **동기 호출이지만** 창이 떠 있는 동안의 한 번이고 사람이 결과를 기다리는 중이다
        (타임아웃 10초, `center_client.DEFAULT_TIMEOUT_S`).
        """
        wanted = self._pending_settings()
        before = self._agent.settings
        self._agent.settings = wanted
        if not self._agent.credentials.center_api_key():
            # **키가 없다 — 등록 요청을 보내거나 승인됐나 묻는다** (C4 §등록 요청과 승인).
            try:
                got = self._agent.enroll_step()
            except Unreachable as e:
                self.result_label.setText(f"닿지 못함 — {e}")
                self._agent.settings = before
                self._show_code()
                return
            except CenterProblem as e:
                self.result_label.setText(enrollment_problem_text(e))
                self._agent.settings = before
                self._show_code()
                return
            if not got:
                self.result_label.setText(enrollment_text(self._agent))
                self._show_code()
                return
            self._agent.store.state.bot_ui_id = None
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
            self._show_code()
            return
        # 실패했으면 설정을 되돌린다 (저장을 누르지 않았으므로).
        self._agent.settings = before
        self._show_code()

    def request_again(self) -> None:
        """「다시 요청」 — 거절·만료된 뒤, 또는 키가 거부된 뒤 새로 승인받는다."""
        wanted = self._pending_settings()
        before = self._agent.settings
        self._agent.settings = wanted
        if self._agent.credentials.center_api_key() and not self._agent.credentials.center_key_from_env():
            # 거부된 키를 들고 있으면 새 요청이 묻히지 않는다 — 지우고 새로 받는다.
            self._agent.credentials.delete("center_api_key")
        try:
            self._agent.request_enrollment()
        except CenterProblem as e:
            self.result_label.setText(enrollment_problem_text(e))
            self._agent.settings = before
        else:
            self.result_label.setText(enrollment_text(self._agent))
        self._show_code()

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
            writable_dirs=self.writable_dirs(),
            smtp_host=self.smtp_host.text().strip(),
            smtp_port=self.smtp_port.value(),
            smtp_security=self.smtp_security.currentText(),
            smtp_username=self.smtp_user.text().strip(),
            smtp_sender=self.smtp_from.text().strip(),
            smtp_attachment_mb=float(self.smtp_attachment.value()),
            webhook_allowed_hosts=self.webhook_host_list(),
            runtimes=(worker,),
            extensions={**self._agent.settings.extensions, **self._extension_values()},
        )

    def save(self) -> None:
        """설정 파일에 쓰고, 키를 비밀 저장소에, 자동 시작을 OS에 반영한다."""
        model_key = self.llm_key.text().strip()
        if model_key:
            try:
                self._agent.credentials.set_llm_api_key(model_key)
            except SecretsUnavailable as e:
                QMessageBox.warning(self, "모델 키를 저장하지 못했습니다", str(e))
                return

        typed_password = self.smtp_password.text().strip()
        if typed_password:
            try:
                self._agent.credentials.set_smtp_password(typed_password)
            except SecretsUnavailable as e:
                QMessageBox.warning(self, "메일 비밀번호를 저장하지 못했습니다", str(e))
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
        # 설정이 바뀌면 사전 점검도 다시 잰다 — 안 비우면 SMTP를 넣어도 「준비 안 됨」이 계속
        # 올라간다(현장 리허설에서 드러났다. 키·배포·확장 자리는 이미 비우고 있었다).
        self._agent.invalidate_preflight()
        if failure:
            QMessageBox.warning(self, "자동 시작", failure)
        self.accept()


__all__ = [
    "KEY_EMPTY_PLACEHOLDER",
    "KEY_SET_PLACEHOLDER",
    "LLM_KEY_PLACEHOLDER",
    "SettingsDialog",
    "enrollment_problem_text",
    "enrollment_text",
]


def enrollment_text(agent: Agent) -> str:
    """키가 없을 때의 상태 줄 (BUI-03 「Center」 탭)."""
    pending = agent.enrollment
    if pending is None:
        return "아직 등록 요청을 보내지 않았습니다 — 주소를 넣고 「연결 테스트」를 누르세요."
    if pending.state == "pending":
        return (
            f"승인을 기다립니다 — 관리자에게 요청 코드 {pending.code}를 알려 주세요 "
            f"({pending.expires_at[:16].replace('T', ' ')}까지)"
        )
    if pending.state == "rejected":
        reason = f": {pending.reason}" if pending.reason else ""
        return f"거절되었습니다{reason}"
    if pending.state == "expired":
        return "요청이 만료되었습니다"
    return "승인되었습니다 — 키를 받는 중입니다."


def enrollment_problem_text(problem: CenterProblem) -> str:
    """등록 요청이 막혔을 때 (C4 오류 표)."""
    if problem.code in ("enroll_rate_limited", "enroll_queue_full"):
        return "Center가 지금 등록 요청을 받지 않습니다 — 잠시 뒤 다시 요청합니다"
    return f"등록 요청을 보내지 못했습니다 — {problem}"
