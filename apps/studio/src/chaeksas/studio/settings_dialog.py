"""STU-10 설정 — 왼쪽 분류 목록, 오른쪽 그 분류의 칸.

- **「저장」을 누를 때까지 아무것도 바뀌지 않는다** — 키도 그때 OS 비밀 저장소에 간다.
- 키는 칸에 **보이지 않는다** — 저장된 것이 있으면 자리 글로 알린다. 새로 넣을 때만 친다.
- 아직 받쳐 줄 기능이 없는 분류는 목록에 두되 **끄고 이유를 적는다** (U3).
- 「연결 테스트」는 사람이 누를 때만 한다 (창을 열 때 바깥에 묻지 않는다). 결과는 한 줄이다.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import replace
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
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

from chaeksas.qt.theme.tokens import SPACE_1
from chaeksas.studio.checks import center_status, key_status, llm_status, worker_place, worker_status
from chaeksas.studio.credentials import (
    ENV_CENTER_API_KEY,
    ENV_LLM_API_KEY,
    SecretsUnavailable,
    StudioCredentials,
    service_key_env,
)
from chaeksas.studio.extensions import Extensions
from chaeksas.studio.settings import ServiceKeyRef, Settings

log = logging.getLogger(__name__)

TITLE = "설정"
MIN_WIDTH = 720

#: 분류 이름 (STU-10 표 순서).
APPEARANCE, LLM, MAIL, CENTER, EXTENSIONS, WORKER, SERVICE_KEYS, SECRETS = (
    "외형", "LLM", "메일", "Center", "확장별 설정", "Worker", "서비스 앱 키", "비밀",
)
CATEGORIES = (APPEARANCE, LLM, MAIL, CENTER, EXTENSIONS, WORKER, SERVICE_KEYS, SECRETS)

#: 아직인 분류와 그 이유 (U3 — 끄고 가까이에 적는다).
LATER = {
    APPEARANCE: "테마·캔버스 팔레트는 지금 시스템 설정을 따릅니다 — 고르는 칸은 아직입니다.",
    MAIL: "시험 실행은 메일을 담아 두기만 합니다 (바깥으로 보내지 않는다) — 메일 서버 칸은 아직입니다.",
    EXTENSIONS: "Studio 범위(`studio`)의 설정 칸을 기여한 확장이 아직 없습니다.",
    SECRETS: "툴팩이 쓰는 비밀은 툴팩과 함께 옵니다 — 툴팩이 아직 없습니다.",
}

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
        #: 창을 열 때 있던 참조 — 지운 줄은 「저장」 때 비밀 저장소에서도 지운다.
        self._original_refs = [one.ref for one in settings.service_keys]
        self.setWindowTitle(TITLE)
        self.setMinimumWidth(MIN_WIDTH)

        self.categories = QListWidget()
        self.categories.setObjectName("categories")
        self.categories.setMaximumWidth(180)
        self.categories.setSpacing(SPACE_1)
        self.pages = QStackedWidget()
        for name in CATEGORIES:
            item = QListWidgetItem(name if name not in LATER else f"{name} (아직)")
            if name in LATER:
                item.setToolTip(LATER[name])
            self.categories.addItem(item)
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
        if name == LLM:
            return self._llm_page()
        if name == CENTER:
            return self._center_page()
        if name == WORKER:
            return self._worker_page()
        if name == SERVICE_KEYS:
            return self._keys_page()
        page = QWidget()
        layout = QVBoxLayout(page)
        reason = QLabel(LATER[name])
        reason.setWordWrap(True)
        reason.setEnabled(False)
        layout.addWidget(reason)
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
        page = QWidget()
        form = QFormLayout(page)
        intro = QLabel(
            "Center 콘솔(CON-11)에서 **Studio용**으로 발급받은 키를 넣습니다. "
            "Bot UI와는 다른 키입니다."
        )
        intro.setTextFormat(Qt.TextFormat.MarkdownText)
        intro.setWordWrap(True)
        self.center_url = QLineEdit(self.settings.center_url)
        self.center_url.setPlaceholderText("http://center.example.com:8800")
        self.center_key = QLineEdit()
        self.center_key.setEchoMode(QLineEdit.EchoMode.Password)
        if self.credentials.stored_center_api_key():
            self.center_key.setPlaceholderText(KEY_STORED)
        self.center_show = QCheckBox("표시")
        self.center_show.toggled.connect(
            lambda on: self.center_key.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
            )
        )
        key_row = QHBoxLayout()
        key_row.addWidget(self.center_key, 1)
        key_row.addWidget(self.center_show)
        self.center_test = QPushButton("연결 테스트")
        self.center_test.clicked.connect(self.test_center)
        self.center_result = QLabel("")
        self.center_result.setWordWrap(True)
        form.addRow(intro)
        form.addRow("Center 주소", self.center_url)
        form.addRow("Center API 키", key_row)
        if _env(ENV_CENTER_API_KEY):
            note = QLabel(f"환경변수 {ENV_CENTER_API_KEY}가 있어 그 값이 이깁니다.")
            note.setWordWrap(True)
            form.addRow("", note)
        test_row = QHBoxLayout()
        test_row.addWidget(self.center_test)
        test_row.addStretch(1)
        form.addRow("", test_row)
        form.addRow("", self.center_result)
        return page

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
        typed = self.center_key.text().strip()
        key = typed or self.credentials.center_api_key()
        self.center_result.setText(center_status(self.center_url.text().strip(), key, client=self.client))

    def test_worker(self) -> None:
        self.worker_state.setText(worker_status(self.worker, client=self.client))

    def test_keys(self) -> None:
        """줄마다 `/v1/keys/self` — 새로 친 값이 있으면 그것을, 없으면 지금 쓰일 값을 본다."""
        for at, (ref, app, typed) in enumerate(self.key_rows()):
            key = typed or (self.credentials.service_key(ref) if ref else None)
            found = key_status(self.extensions.service_url(app) if app else None, key, client=self.client)
            if not typed and ref and _env(service_key_env(ref)):
                found += " (환경변수)"
            item = self.keys.item(at, STATE)
            if item is not None:
                item.setText(found)
                item.setToolTip(found)

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
            typed_center = self.center_key.text().strip()
            if typed_center:
                self.credentials.set_center_api_key(typed_center)
            for ref, _, typed in rows:
                if typed:
                    self.credentials.set_service_key(ref, typed)
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
        )
        made.save()
        self.saved = made
        self.accept()


def _env(name: str) -> str | None:
    import os  # noqa: PLC0415

    return os.environ.get(name) or None


__all__ = ["CATEGORIES", "LATER", "StudioSettingsDialog"]
