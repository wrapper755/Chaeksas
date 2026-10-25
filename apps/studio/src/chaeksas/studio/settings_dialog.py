"""STU-10 설정 — 왼쪽 분류 목록, 오른쪽 그 분류의 칸.

- **「저장」을 누를 때까지 아무것도 바뀌지 않는다** — 키도 그때 OS 비밀 저장소에 간다. **예외는 「Center」의
  「연결 테스트」·「다시 요청」**이다 — 누르는 그 자리에서 등록 요청을 보내거나 승인된 키를 받고 주소를
  적는다 (ADR-0093). 그래서 창을 「취소」로 닫아도 `center_changed`에 바뀐 설정이 남는다.
- 키는 칸에 **보이지 않는다** — 저장된 것이 있으면 자리 글로 알린다. 새로 넣을 때만 친다.
- **쓰는 곳이 있는 칸만 둔다** (ADR-0073) — 메일·비밀·모델 공급자·temperature는 읽는 곳이 없어 없다.
- 「확장별 설정」은 확장이 기여한 칸으로 **그 자리에서** 짓는다 (C13 `configuration`, scope `studio`).
  창은 어느 확장인지 모른다.
- 「연결 테스트」는 사람이 누를 때만 한다 (창을 열 때 바깥에 묻지 않는다). 결과는 한 줄이다.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import replace
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from chaeksas.contracts import SCOPE_STUDIO, ConfigurationItem
from chaeksas.qt.theme import THEME_DARK, THEME_LIGHT, THEME_SYSTEM
from chaeksas.qt.theme.tokens import SPACE_1
from chaeksas.studio.center_enroll import Outcome, StudioEnrollment, connected_text, waiting_text
from chaeksas.studio.checks import (
    EXTERNAL_NOT_CHECKED,
    AppPlaces,
    app_places,
    center_status,
    key_status,
    llm_status,
    worker_place,
    worker_status,
)
from chaeksas.studio.credentials import (
    ENV_CENTER_API_KEY,
    ENV_LLM_API_KEY,
    SecretsUnavailable,
    StudioCredentials,
    extension_secret_env,
    service_key_env,
)
from chaeksas.studio.extensions import Extensions
from chaeksas.studio.settings import ServiceKeyRef, Settings

log = logging.getLogger(__name__)

TITLE = "설정"
MIN_WIDTH = 720

#: 분류 이름 (STU-10 표 순서).
APPEARANCE, LLM, CENTER, EXTENSIONS, WORKER, SERVICE_KEYS = (
    "외형", "LLM", "Center", "확장별 설정", "Worker", "서비스 앱 키",
)
CATEGORIES = (APPEARANCE, LLM, CENTER, EXTENSIONS, WORKER, SERVICE_KEYS)

#: 「외형」 테마 — 저장하는 값과 보이는 글 (스타일 가이드 §4-2).
THEMES = ((THEME_SYSTEM, "시스템 따름"), (THEME_LIGHT, "밝게"), (THEME_DARK, "어둡게"))
NO_EXTENSION_FIELDS = "Studio 범위의 설정 칸을 기여한 확장이 없습니다."

KEY_STORED = "저장됨 (바꾸려면 새로 붙여 넣으세요)"
KEY_FROM_ENV = "환경변수가 이깁니다"
KEY_COLUMNS = ("키 참조 이름", "서비스 앱", "키 값", "상태")
REF, APP, VALUE, STATE = range(4)


class StudioSettingsDialog(QDialog):
    """설정 창. 저장하면 `saved`에 새 설정이 담긴다."""

    def __init__(
        self,
        settings: Settings,
        extensions: Extensions,
        *,
        refs: Iterable[tuple[str, str]] = (),
        credentials: StudioCredentials | None = None,
        client: Any = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.extensions = extensions
        self.credentials = credentials or StudioCredentials()
        #: 열린 BPM 프로세스가 쓰는 키 참조 `(참조, 서비스 앱)` — 「참조 채우기」가 쓴다.
        self.refs = list(refs)
        #: 시험이 끼우는 HTTP 클라이언트 (연결 테스트).
        self.client = client
        self.saved: Settings | None = None
        #: 「Center」가 그 자리에서 적은 설정 — 「취소」로 닫아도 부르는 쪽이 받는다 (ADR-0093).
        self.center_changed: Settings | None = None
        #: 창을 열 때 있던 참조 — 지운 줄은 「저장」 때 비밀 저장소에서도 지운다.
        self._original_refs = [one.ref for one in settings.service_keys]
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
        self.error.setProperty("role", "error")
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
            SERVICE_KEYS: self._keys_page,
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
        note = QLabel("캔버스의 그림은 테마와 상관없이 밝게 둡니다 — 그림의 선과 글자가 검정입니다.")
        note.setWordWrap(True)
        note.setProperty("role", "muted")
        form.addRow("", note)
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
        """STU-10 「Center」 — 주소 하나와 상태 줄 (ADR-0093). 아이디·비밀번호도, 키 칸도 없다.

        「연결 테스트」가 등록 요청을 보내거나 승인됐나 묻고, 승인되면 키를 받아 비밀 저장소에 둔다.
        기다리는 동안은 **창이 열려 있을 때만** 10초마다 묻는다 (Studio에는 상시 주기가 없다).
        """
        page = QWidget()
        form = QFormLayout(page)
        self.center_url = QLineEdit(self.settings.center_url)
        self.center_url.setPlaceholderText("http://center.example.com:8800")
        self.center_result = QLabel("")
        self.center_result.setWordWrap(True)
        self.center_result.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.center_code = QLabel("")
        self.center_code.setProperty("role", "h2")
        self.center_code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.center_copy = QPushButton("복사")
        self.center_copy.clicked.connect(self._copy_code)
        self.center_test = QPushButton("연결 테스트")
        self.center_test.clicked.connect(self.test_center)
        self.center_again = QPushButton("다시 요청")
        self.center_again.clicked.connect(self.request_again)

        form.addRow("Center 주소", self.center_url)
        code_row = QHBoxLayout()
        code_row.addWidget(self.center_code)
        code_row.addWidget(self.center_copy)
        code_row.addStretch(1)
        form.addRow("", self.center_result)
        form.addRow("", code_row)
        buttons = QHBoxLayout()
        buttons.addWidget(self.center_test)
        buttons.addWidget(self.center_again)
        buttons.addStretch(1)
        form.addRow("", buttons)

        # 기다리는 동안만 돈다 — 창을 닫으면 함께 사라진다.
        self.center_timer = QTimer(self)
        self.center_timer.setInterval(10_000)
        self.center_timer.timeout.connect(self._poll_center)
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
            return "아직 등록 요청을 보내지 않았습니다 — 주소를 넣고 「연결 테스트」를 누르세요."
        return waiting_text(found)

    def _show_center(self, text: str) -> None:
        """상태 줄·요청 코드·「다시 요청」을 지금 상태에 맞춘다. 기다리면 10초 주기를 켠다."""
        from_env = bool(_env(ENV_CENTER_API_KEY))
        has_key = bool(self.credentials.stored_center_api_key())
        found = None if (from_env or has_key) else self._enrollment().current()
        waiting = found is not None and found.state == "pending"
        self.center_result.setText(text)
        self.center_code.setText(found.code if waiting and found is not None else "")
        self.center_code.setVisible(waiting)
        self.center_copy.setVisible(waiting)
        self.center_again.setVisible(not from_env and (has_key or (found is not None and found.state != "pending")))
        self.center_test.setEnabled(True)
        if waiting:
            self.center_timer.start()
        else:
            self.center_timer.stop()

    def _remember_center(self, *, key_name: str | None = None, expires: str | None = None) -> None:
        """그 자리에서 주소·키 이름·만료를 적는다 — 「저장」을 기다리지 않는다 (ADR-0093)."""
        made = replace(
            self.settings,
            center_url=self.center_url.text().strip() or self.settings.center_url,
            center_key_name=self.settings.center_key_name if key_name is None else key_name,
            center_key_expires=self.settings.center_key_expires if expires is None else expires,
        )
        made.save()
        self.settings = made
        self.center_changed = made

    def _take(self, outcome: Outcome) -> None:
        if outcome.got_key:
            self._remember_center(key_name=outcome.key_name, expires=outcome.expires_at)
        else:
            self._remember_center()
        self._show_center(outcome.text)

    def _poll_center(self) -> None:
        self._take(self._enrollment().step())

    def _copy_code(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self.center_code.text())

    def request_again(self) -> None:
        """「다시 요청」 — 거절·만료된 뒤, 또는 키가 거부·만료되었을 때 새로 승인받는다."""
        self._remember_center(key_name="", expires="")
        self._take(self._enrollment().again())

    def _worker_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        intro = QLabel("UI 태스크는 이 PC의 Bot UI가 관리하는 Worker 프로세스가 처리합니다.")
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

    def _keys_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        intro = QLabel(
            "서비스 앱 관리 콘솔에서 **개발용**(자율·결정 허용)으로 발급받은 키를 넣습니다. "
            "Bot UI와 같은 참조 이름을 쓰되 값은 다릅니다."
        )
        intro.setTextFormat(Qt.TextFormat.MarkdownText)
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.keys = QTableWidget(0, len(KEY_COLUMNS))
        self.keys.setHorizontalHeaderLabels(list(KEY_COLUMNS))
        self.keys.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        header = self.keys.horizontalHeader()
        for column in (REF, APP):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(VALUE, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(STATE, QHeaderView.ResizeMode.Stretch)
        self.keys.verticalHeader().setVisible(False)
        for line in self.settings.service_keys:
            self._add_key_row(line.ref, line.app_id)
        layout.addWidget(self.keys, 1)
        row = QHBoxLayout()
        self.add_key = QPushButton("추가")
        self.drop_key = QPushButton("삭제")
        self.test_keys_button = QPushButton("연결 테스트")
        self.fill_refs = QPushButton("열린 BPM 프로세스가 쓰는 참조 채우기")
        self.fill_refs.setEnabled(bool(self.refs))
        if not self.refs:
            self.fill_refs.setToolTip("열린 BPM 프로세스가 없거나 키 참조를 쓰지 않습니다.")
        self.add_key.clicked.connect(lambda: self._add_key_row("", ""))
        self.drop_key.clicked.connect(self.drop_selected_key)
        self.test_keys_button.clicked.connect(self.test_keys)
        self.fill_refs.clicked.connect(self.fill_from_process)
        for one in (self.add_key, self.drop_key, self.test_keys_button):
            row.addWidget(one)
        row.addStretch(1)
        row.addWidget(self.fill_refs)
        layout.addLayout(row)
        return page

    def _add_key_row(self, ref: str, app_id: str) -> int:
        at = self.keys.rowCount()
        self.keys.insertRow(at)
        self.keys.setItem(at, REF, QTableWidgetItem(ref))
        self.keys.setItem(at, APP, QTableWidgetItem(app_id))
        value = QLineEdit()
        value.setEchoMode(QLineEdit.EchoMode.Password)
        if ref and _env(service_key_env(ref)):
            value.setPlaceholderText(KEY_FROM_ENV)
        elif ref and self.credentials.stored_service_key(ref):
            value.setPlaceholderText(KEY_STORED)
        self.keys.setCellWidget(at, VALUE, value)
        state = QTableWidgetItem("")
        state.setFlags(state.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.keys.setItem(at, STATE, state)
        return at

    # ── 동작 ──

    def key_rows(self) -> list[tuple[str, str, str]]:
        """표의 줄 `(참조, 서비스 앱, 새로 친 값)`."""
        out = []
        for at in range(self.keys.rowCount()):
            ref, app = self._cell(at, REF), self._cell(at, APP)
            field = self.keys.cellWidget(at, VALUE)
            typed = field.text().strip() if isinstance(field, QLineEdit) else ""
            out.append((ref, app, typed))
        return out

    def _cell(self, at: int, column: int) -> str:
        item = self.keys.item(at, column)
        return item.text().strip() if item is not None else ""

    def drop_selected_key(self) -> None:
        rows = sorted({index.row() for index in self.keys.selectedIndexes()}, reverse=True)
        for at in rows:
            self.keys.removeRow(at)

    def fill_from_process(self) -> None:
        """그림이 쓰는 참조 중 표에 없는 것을 빈 줄로 더한다."""
        have = {ref for ref, _, _ in self.key_rows()}
        for ref, app in self.refs:
            if ref not in have:
                self._add_key_row(ref, app)

    def test_llm(self) -> None:
        typed = self.llm_key.text().strip()
        key = typed or self.credentials.llm_api_key()
        self.llm_result.setText(llm_status(self.llm_url.text().strip(), key, client=self.client))

    def test_center(self) -> None:
        """키가 있으면 닿는지 본다. 없으면 **등록 요청을 보내거나 승인됐나 묻는다** (ADR-0093)."""
        key = self.credentials.center_api_key()
        if key is None:
            self._take(self._enrollment().step())
            return
        said = center_status(self.center_url.text().strip(), key, client=self.client)
        if said.startswith("키가 거부되었습니다"):
            said = "키가 거부되었습니다 — 「다시 요청」으로 새로 승인받으세요"
        self._show_center(said)

    def test_worker(self) -> None:
        self.worker_state.setText(worker_status(self.worker, client=self.client))

    def test_keys(self) -> None:
        """줄마다 `/v1/keys/self` — 새로 친 값이 있으면 그것을, 없으면 지금 쓰일 값을 본다.

        주소는 설치된 확장 정의가 먼저, 없으면 **Center 리소스 목록**이다(시험 실행과 같은 곳).
        Center는 **주소를 모르는 줄이 있을 때만 한 번** 묻는다. 외부 확장은 묻지 않는다.
        """
        places: AppPlaces | None = None
        for at, (ref, app, typed) in enumerate(self.key_rows()):
            key = typed or (self.credentials.service_key(ref) if ref else None)
            url = self.extensions.service_url(app) if app else None
            if app and url is None:
                places = places or app_places(self._center_reader())
                url = places.addresses.get(app)
            if places is not None and app in places.externals:
                found = EXTERNAL_NOT_CHECKED
            else:
                found = key_status(url, key, client=self.client)
                if url is None and places is not None and places.problem:
                    found += f" ({places.problem})"
            if not typed and ref and _env(service_key_env(ref)):
                found += " (환경변수)"
            item = self.keys.item(at, STATE)
            if item is not None:
                item.setText(found)
                item.setToolTip(found)

    def _center_reader(self) -> Any:
        """지금 창에 적힌 Center 주소·키로 읽는 쪽 — 둘 중 하나라도 없으면 `None`(두드리지 않는다)."""
        from chaeksas.studio.services import CenterReader  # noqa: PLC0415

        url = self.center_url.text().strip()
        key = self.credentials.center_api_key()
        if not url or not key:
            return None
        return CenterReader(base_url=url, api_key=key, client=self.client)

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
        rows = self.key_rows()
        out = []
        if any(not ref for ref, _, _ in rows):
            out.append("키 참조 이름이 빈 줄이 있습니다.")
        refs = [ref for ref, _, _ in rows if ref]
        doubled = sorted({ref for ref in refs if refs.count(ref) > 1})
        if doubled:
            out.append(f"같은 키 참조 이름이 두 줄입니다: {', '.join(doubled)}")
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
        rows = self.key_rows()
        try:
            typed_llm = self.llm_key.text().strip()
            if typed_llm:
                self.credentials.set_llm_api_key(typed_llm)
            for ref, _, typed in rows:
                if typed:
                    self.credentials.set_service_key(ref, typed)
            for (extension_id, key), (item, field) in self.extension_fields.items():
                if item.secret and field.text().strip():
                    self.credentials.set_extension_secret(extension_id, key, field.text().strip())
        except SecretsUnavailable as e:
            self.error.setText(f"키를 저장하지 못했습니다 — {e}")
            return
        kept = {ref for ref, _, _ in rows}
        for ref in self._original_refs:
            if ref not in kept:
                # 지운 줄 — 비밀 저장소에 남겨 두면 보이지 않는 키가 계속 쓰인다.
                self.credentials.delete_service_key(ref)
        made = replace(
            self.settings,
            center_url=self.center_url.text().strip(),
            llm_base_url=self.llm_url.text().strip(),
            llm_model=self.llm_model.text().strip(),
            service_keys=tuple(ServiceKeyRef(ref=ref, app_id=app) for ref, app, _ in rows),
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
