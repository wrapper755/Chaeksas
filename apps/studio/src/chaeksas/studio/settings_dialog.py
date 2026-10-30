"""STU-10 설정 — 왼쪽 분류 목록, 오른쪽 그 분류의 칸.

- **「저장」을 누를 때까지 아무것도 바뀌지 않는다** — 키도 그때 OS 비밀 저장소에 간다. **예외는 「Center」가
  여는 STU-16 「Center에 연결」**이다 — 그 창은 누르는 그 자리에서 등록 요청을 보내거나 키를 받고 주소를
  적는다 (ADR-0093). 그래서 창을 「취소」로 닫아도 `center_changed`에 바뀐 설정이 남는다.
- 키는 칸에 **보이지 않는다** — 저장된 것이 있으면 자리 글로 알린다. 새로 넣을 때만 친다.
- **쓰는 곳이 있는 칸만 둔다** (ADR-0073) — 메일·비밀·모델 공급자·temperature는 읽는 곳이 없어 없다.
- 「확장별 설정」은 확장이 기여한 칸으로 **그 자리에서** 짓는다 (C13 `configuration`, scope `studio`).
  창은 어느 확장인지 모른다.
- 「연결 테스트」는 사람이 누를 때만 한다 (창을 열 때 바깥에 묻지 않는다). 결과는 한 줄이다.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from chaeksas.contracts import SCOPE_STUDIO, ConfigurationItem
from chaeksas.qt.theme import THEME_DARK, THEME_LIGHT, THEME_SYSTEM, set_role
from chaeksas.qt.theme.tokens import SPACE_1
from chaeksas.studio.center_enroll import StudioEnrollment, connected_text, expires_soon, waiting_text
from chaeksas.studio.checks import (
    center_status,
    llm_status,
    worker_place,
    worker_status,
)
from chaeksas.studio.connect_dialog import CenterConnectDialog
from chaeksas.studio.credentials import (
    CENTER_KEY_NAME,
    ENV_CENTER_API_KEY,
    ENV_LLM_API_KEY,
    SecretsUnavailable,
    StudioCredentials,
    extension_secret_env,
)
from chaeksas.studio.extensions import Extensions
from chaeksas.studio.settings import Settings

log = logging.getLogger(__name__)

TITLE = "설정"
MIN_WIDTH = 720

#: 분류 이름 (STU-10 표 순서).
APPEARANCE, LLM, CENTER, EXTENSIONS, WORKER = ("외형", "LLM", "Center", "확장별 설정", "Worker")
#: 「서비스 앱」 분류는 없다 — 서비스 앱 키가 없어졌다 (ADR-0102). 시험 실행은 Studio 키로 Center에 올린다.
CATEGORIES = (APPEARANCE, LLM, CENTER, EXTENSIONS, WORKER)

#: 「외형」 테마 — 저장하는 값과 보이는 글 (스타일 가이드 §4-2).
THEMES = ((THEME_SYSTEM, "시스템 따름"), (THEME_LIGHT, "밝게"), (THEME_DARK, "어둡게"))
NO_EXTENSION_FIELDS = "Studio 범위의 설정 칸을 기여한 확장이 없습니다."

KEY_STORED = "저장됨 (바꾸려면 새로 붙여 넣으세요)"
KEY_FROM_ENV = "환경변수가 이깁니다"
class StudioSettingsDialog(QDialog):
    """설정 창. 저장하면 `saved`에 새 설정이 담긴다."""

    def __init__(
        self,
        settings: Settings,
        extensions: Extensions,
        *,
        credentials: StudioCredentials | None = None,
        client: Any = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.extensions = extensions
        self.credentials = credentials or StudioCredentials()
        #: 시험이 끼우는 HTTP 클라이언트 (연결 테스트).
        self.client = client
        self.saved: Settings | None = None
        #: 「Center」가 그 자리에서 적은 설정 — 「취소」로 닫아도 부르는 쪽이 받는다 (ADR-0093).
        self.center_changed: Settings | None = None
        self.setWindowTitle(TITLE)
        self.setMinimumWidth(MIN_WIDTH)

        self.categories = QListWidget()
        self.categories.setObjectName("categories")
        self.categories.setMaximumWidth(180)
        self.categories.setSpacing(SPACE_1)
        self.pages = QStackedWidget()
        #: 「확장별 설정」의 칸 — `(확장, 칸)` → (기여, 입력 칸).
        self.extension_fields: dict[tuple[str, str], tuple[ConfigurationItem, QLineEdit]] = {}
        for name in CATEGORIES:
            self.categories.addItem(QListWidgetItem(name))
            self.pages.addWidget(self._page(name))
        self.categories.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.categories.setCurrentRow(CATEGORIES.index(LLM))

        self.error = QLabel("")
        set_role(self.error, "error")
        self.error.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("저장")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)

        body = QHBoxLayout()
        body.addWidget(self.categories)
        body.addWidget(self.pages, 1)
        layout = QVBoxLayout(self)
        layout.addLayout(body, 1)
        layout.addWidget(self.error)
        layout.addWidget(buttons)

    def show_category(self, name: str) -> None:
        self.categories.setCurrentRow(CATEGORIES.index(name))

    # ── 분류마다 ──

    def _page(self, name: str) -> QWidget:
        pages = {
            APPEARANCE: self._appearance_page,
            LLM: self._llm_page,
            CENTER: self._center_page,
            EXTENSIONS: self._extensions_page,
            WORKER: self._worker_page,
        }
        return pages[name]()

    def _appearance_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.theme = QComboBox()
        for value, label in THEMES:
            self.theme.addItem(label, value)
        at = self.theme.findData(self.settings.theme)
        self.theme.setCurrentIndex(at if at >= 0 else 0)
        form.addRow("테마", self.theme)
        return page

    def _extensions_page(self) -> QWidget:
        """켜진 확장이 기여한 `scope: studio` 칸 (C13). 비밀 칸은 값을 보이지 않는다 (ADR-0013)."""
        page = QWidget()
        layout = QVBoxLayout(page)
        for found in self.extensions.host.enabled():
            items = [one for one in found.manifest.contributes.configuration if one.scope == SCOPE_STUDIO]
            if not items:
                continue
            box = QGroupBox(found.manifest.name)
            form = QFormLayout(box)
            stored = self.settings.extension(found.id)
            for item in items:
                field = QLineEdit()
                field.setObjectName(f"ext:{found.id}:{item.key}")
                if item.secret:
                    field.setEchoMode(QLineEdit.EchoMode.Password)
                    if _env(extension_secret_env(found.id, item.key)):
                        field.setPlaceholderText(KEY_FROM_ENV)
                    elif self.credentials.stored_extension_secret(found.id, item.key):
                        field.setPlaceholderText(KEY_STORED)
                else:
                    value = stored.get(item.key)
                    field.setText("" if value is None else str(value))
                form.addRow(item.label, field)
                self.extension_fields[(found.id, item.key)] = (item, field)
            layout.addWidget(box)
        if not self.extension_fields:
            empty = QLabel(NO_EXTENSION_FIELDS)
            empty.setWordWrap(True)
            layout.addWidget(empty)
        layout.addStretch(1)
        return page

    def _llm_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.llm_url = QLineEdit(self.settings.llm_base_url)
        self.llm_model = QLineEdit(self.settings.llm_model)
        self.llm_key = QLineEdit()
        self.llm_key.setEchoMode(QLineEdit.EchoMode.Password)
        if self.credentials.stored("llm"):
            self.llm_key.setPlaceholderText(KEY_STORED)
        else:
            self.llm_key.setPlaceholderText("키가 필요 없으면 비워 두세요")
        self.llm_show = QCheckBox("표시")
        self.llm_show.toggled.connect(
            lambda on: self.llm_key.setEchoMode(QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password)
        )
        key_row = QHBoxLayout()
        key_row.addWidget(self.llm_key, 1)
        key_row.addWidget(self.llm_show)
        self.llm_test = QPushButton("연결 테스트")
        self.llm_test.clicked.connect(self.test_llm)
        self.llm_result = QLabel("")
        self.llm_result.setWordWrap(True)
        form.addRow("서버 주소", self.llm_url)
        form.addRow("모델", self.llm_model)
        form.addRow("API 키", key_row)
        if _env(ENV_LLM_API_KEY):
            note = QLabel(f"환경변수 {ENV_LLM_API_KEY}가 있어 그 값이 이깁니다.")
            note.setWordWrap(True)
            form.addRow("", note)
        test_row = QHBoxLayout()
        test_row.addWidget(self.llm_test)
        test_row.addStretch(1)
        form.addRow("", test_row)
        form.addRow("", self.llm_result)
        return page

    def _center_page(self) -> QWidget:
        """STU-10 「Center」 — 주소·상태 줄·「연결 테스트」, 필요할 때만 「다시 요청」 (ADR-0093).

        **들어오는 일 자체는 STU-16 「Center에 연결」**이 한다 — 키가 없으면 「연결 테스트」가 그 창을
        연다. 이 탭은 「지금 어떤가」를 보고 고치는 자리다. 아이디·비밀번호도, 키 칸도 없다.
        """
        page = QWidget()
        form = QFormLayout(page)
        self.center_url = QLineEdit(self.settings.center_url)
        self.center_url.setPlaceholderText("http://center.example.com:8800")
        self.center_result = QLabel("")
        self.center_result.setWordWrap(True)
        self.center_result.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.center_test = QPushButton("연결 테스트")
        self.center_test.clicked.connect(self.test_center)
        self.center_again = QPushButton("다시 요청")
        self.center_again.clicked.connect(self.request_again)

        form.addRow("Center 주소", self.center_url)
        form.addRow("", self.center_result)
        buttons = QHBoxLayout()
        buttons.addWidget(self.center_test)
        buttons.addWidget(self.center_again)
        buttons.addStretch(1)
        form.addRow("", buttons)
        self._show_center(self._center_text())
        return page

    def _enrollment(self) -> StudioEnrollment:
        return StudioEnrollment(
            base_url=self.center_url.text().strip(),
            data_dir=self.settings.data_dir,
            credentials=self.credentials,
            client=self.client,
        )

    def _center_text(self) -> str:
        """창을 열 때의 상태 줄 — 바깥에 묻지 않는다 (들고 있는 것만 본다)."""
        if _env(ENV_CENTER_API_KEY):
            return f"환경변수의 키를 씁니다 ({ENV_CENTER_API_KEY})."
        if self.credentials.stored_center_api_key():
            return connected_text(self.settings.center_key_name, self.settings.center_key_expires)
        found = self._enrollment().current()
        if found is None:
            return "아직 Center에 들어오지 않았습니다 — 「연결 테스트」를 누르세요."
        return waiting_text(found)

    def _show_center(self, text: str, *, refused: bool = False) -> None:
        """상태 줄과 「다시 요청」. **「다시 요청」은 거절·만료·키 거부·만료 14일 안일 때만** (STU-10).

        연결이 멀쩡할 때 보이면 쓰던 키를 버리고 처음부터 다시 승인받게 된다 — 보이지 않는다.
        """
        self.center_result.setText(text)
        if _env(ENV_CENTER_API_KEY):
            self.center_again.setVisible(False)
            return
        if self.credentials.stored_center_api_key():
            needed = refused or expires_soon(self.settings.center_key_expires)
        else:
            found = self._enrollment().current()
            needed = found is not None and found.state in ("rejected", "expired")
        self.center_again.setVisible(needed)

    def _connect(self, *, send_now: bool = False) -> None:
        """STU-16을 연다. 그 창은 「저장」이 없어 주소·키 이름을 그 자리에서 적는다 — 받아 온다."""
        dialog = CenterConnectDialog(
            replace(self.settings, center_url=self.center_url.text().strip() or self.settings.center_url),
            credentials=self.credentials,
            client=self.client,
            send_now=send_now,
            parent=self,
        )
        dialog.exec()
        self.settings = dialog.settings
        self.center_changed = dialog.settings
        self.center_url.setText(dialog.settings.center_url)
        self._show_center(dialog.status.text() if dialog.connected else self._center_text())

    def request_again(self) -> None:
        """「다시 요청」 — 들고 있던 키와 요청을 버리고 STU-16에서 새로 요청한다."""
        self.credentials.delete(CENTER_KEY_NAME)
        self._enrollment().forget()
        self._connect(send_now=True)

    def _worker_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        intro = QLabel("UI 태스크는 이 PC의 PC 실행기가 관리하는 Worker 프로세스가 처리합니다.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.worker = worker_place(self._runtime_values())
        form = QFormLayout()
        self.worker_port = QLabel(str(self.worker.port) if self.worker.port else "—")
        self.worker_tokens = QLabel(self.worker.token_dir or "—")
        self.worker_tokens.setWordWrap(True)
        self.worker_tokens.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.worker_state = QLabel("「연결 테스트」를 누르면 확인합니다.")
        self.worker_state.setWordWrap(True)
        form.addRow("포트", self.worker_port)
        form.addRow("토큰 폴더", self.worker_tokens)
        form.addRow("상태", self.worker_state)
        layout.addLayout(form)
        self.worker_test = QPushButton("연결 테스트")
        self.worker_test.clicked.connect(self.test_worker)
        layout.addWidget(self.worker_test, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        return page

    def _runtime_values(self) -> dict[str, Any]:
        """시험 실행이 쓰는 자리와 **같은 것** (`Extensions.runtime_settings`)."""
        out: dict[str, Any] = {}
        for found in self.extensions.host.local_runtimes():
            out.update(self.extensions.runtime_settings(found.extension_id))
        return out

    def test_llm(self) -> None:
        typed = self.llm_key.text().strip()
        key = typed or self.credentials.llm_api_key()
        self.llm_result.setText(llm_status(self.llm_url.text().strip(), key, client=self.client))

    def test_center(self) -> None:
        """키가 있으면 닿는지 본다. 없으면 **STU-16 「Center에 연결」을 연다** (ADR-0093)."""
        key = self.credentials.center_api_key()
        if key is None:
            self._connect()
            return
        said = center_status(self.center_url.text().strip(), key, client=self.client)
        refused = said.startswith("키가 거부되었습니다")
        if refused:
            said = "키가 거부되었습니다 — 「다시 요청」으로 새로 승인받으세요"
        self._show_center(said, refused=refused)

    def test_worker(self) -> None:
        self.worker_state.setText(worker_status(self.worker, client=self.client))

    def extension_values(self) -> dict[str, dict[str, Any]]:
        """「확장별 설정」에서 비밀이 **아닌** 칸만 — 비밀은 `save()`가 비밀 저장소로 보낸다.

        창에 보이지 않은 칸(꺼 둔 확장의 것)은 그대로 둔다 — 다시 켜면 넣었던 값이 돌아온다.
        """
        out: dict[str, dict[str, Any]] = {}
        for (extension_id, key), (item, field) in self.extension_fields.items():
            if item.secret:
                continue
            out.setdefault(extension_id, self.settings.extension(extension_id))
            text = field.text().strip()
            if text:
                out[extension_id][key] = text
            else:
                out[extension_id].pop(key, None)
        return out

    def problems(self) -> list[str]:
        out = []
        if not self.llm_model.text().strip():
            out.append("모델 이름이 비었습니다.")
        if not self.center_url.text().strip():
            out.append("Center 주소가 비었습니다.")
        return out

    def save(self) -> None:
        """설정 파일(이름만)과 OS 비밀 저장소(값)에 쓴다. 비밀을 못 쓰면 **창을 닫지 않는다**."""
        found = self.problems()
        if found:
            self.error.setText(found[0])
            return
        try:
            typed_llm = self.llm_key.text().strip()
            if typed_llm:
                self.credentials.set_llm_api_key(typed_llm)
            for (extension_id, key), (item, field) in self.extension_fields.items():
                if item.secret and field.text().strip():
                    self.credentials.set_extension_secret(extension_id, key, field.text().strip())
        except SecretsUnavailable as e:
            self.error.setText(f"키를 저장하지 못했습니다 — {e}")
            return
        made = replace(
            self.settings,
            center_url=self.center_url.text().strip(),
            llm_base_url=self.llm_url.text().strip(),
            llm_model=self.llm_model.text().strip(),
            theme=str(self.theme.currentData()),
            extensions={**self.settings.extensions, **self.extension_values()},
        )
        made.save()
        self.saved = made
        self.accept()


def _env(name: str) -> str | None:
    import os  # noqa: PLC0415

    return os.environ.get(name) or None


__all__ = ["CATEGORIES", "NO_EXTENSION_FIELDS", "THEMES", "StudioSettingsDialog"]
