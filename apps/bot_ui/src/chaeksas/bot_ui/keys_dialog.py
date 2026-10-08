"""BUI-10 서비스 앱 키 — 이 PC의 **키 참조 이름 ↔ 키 값** (ADR-0013 §3).

값은 각 서비스 앱의 관리 콘솔(SVC-02)에서 발급받아 여기 넣는다. BPM 프로세스·패키지에는 **참조
이름만** 있으므로, 이 창이 비어 있으면 그 Bot은 사전 점검에서 막힌다 (`core.preflight`).

지키는 것 다섯.

- **값을 보여 주지 않는다** — 앞자리 16자까지만 (SVC-02 목록과 같은 만큼).
- **「저장」이 없다.** 키 관리창이라 추가·변경·삭제가 **그 자리에서** 일어난다. 그래서 바꾼 뒤에는
  사전 점검 캐시를 비운다 — 빠진 키를 넣으면 **다음 하트비트에 「준비됨」이 올라가야 한다**.
- **환경변수로 오는 키는 여기서 바꾸지 못한다** (개발·CI). 그렇게 말해 준다 — 저장소에 덮어써도
  환경변수가 이기므로, 「바꿨는데 그대로」가 된다.
- **삭제는 되돌릴 수 없다.** 쓰는 Bot이 있으면 몇 개가 실행 불가가 되는지 말하고, 확인 창의
  기본은 「취소」다.
- **「확인」만 앱을 부른다.** 표를 그릴 때는 네트워크를 타지 않는다 (`core.key_check`).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from chaeksas.bot_ui.agent import Agent
from chaeksas.bot_ui.bots import InstalledBot, installed
from chaeksas.bot_ui.credentials import Credentials, SecretsUnavailable, service_key_env
from chaeksas.bot_ui.settings import ServiceKeyRef, data_dir
from chaeksas.contracts.manifest import KEY_REF_PATTERN, Manifest
from chaeksas.core.key_check import key_status
from chaeksas.qt import theme

log = logging.getLogger(__name__)

TITLE = "서비스 앱 키"

#: BUI-10 표의 열.
COLUMNS = ("참조 이름", "서비스 앱", "키", "상태", "쓰는 Bot")
REF, APP, VALUE, STATE, USED_BY = range(len(COLUMNS))

#: 값 앞자리를 이만큼만 보인다 (SVC-02 목록의 `prefix`와 같은 길이).
PREFIX_CHARS = 16

#: 「상태」의 처음 값 — **아직 앱에 묻지 않았다**는 뜻이다 (「정상」이라고 단정하지 않는다).
NOT_CHECKED = "확인 전"
#: 설치된 Bot이 요구하는데 값이 없다 (표 맨 위, 빨간 줄).
NEEDS_KEY = "등록 필요"
#: 값이 있지만 어느 설치된 Bot도 쓰지 않는다 (미리 넣어 둔 것일 수 있다 — 지우라고 하지 않는다).
UNUSED = "쓰는 Bot 없음"

ENV_NOTE = "환경변수"
STORED_NOTE = "저장됨"


@dataclass(frozen=True)
class KeyRow:
    """표의 한 줄. **값은 들고 있지 않다** — 앞자리와 「어디서 오나」만."""

    ref: str
    app_id: str
    #: 이 참조를 쓰는 설치된 Bot의 이름들.
    used_by: tuple[str, ...] = ()
    #: 비밀 저장소에 값이 있다.
    stored: bool = False
    #: 환경변수로 온다 (`CHK_BOT_UI__SVC__<참조>`) — 여기서 바꿀 수 없다.
    from_env: bool = False
    prefix: str = ""

    @property
    def registered(self) -> bool:
        return self.stored or self.from_env

    @property
    def missing(self) -> bool:
        """설치된 Bot이 요구하는데 값이 없다 — 그 Bot은 실행 불가다."""
        return bool(self.used_by) and not self.registered

    def where(self) -> str:
        """「키」 열에 쓸 글. 값은 앞자리까지만."""
        if not self.registered:
            return NEEDS_KEY if self.used_by else "없음"
        note = ENV_NOTE if self.from_env else STORED_NOTE
        return f"{self.prefix}… ({note})" if self.prefix else note


def refs_of(manifest: Manifest) -> dict[str, str]:
    """그 Bot이 쓰는 `참조 → 서비스 앱 id` (C1 `requires.service_apps`).

    BPM 프로세스가 상속하는 `key_ref`와 태스크가 따로 적은 `task_key_refs`를 함께 센다 — 둘 다
    실행 중에 풀어야 한다 (`core.preflight.key_refs_of`가 같은 것을 센다).
    """
    out: dict[str, str] = {}
    for need in manifest.requires.service_apps:
        for ref in (need.key_ref, *need.task_key_refs):
            if ref:
                out.setdefault(ref, need.app_id)
    return out


def collect(
    bots: Sequence[InstalledBot],
    registered: Iterable[ServiceKeyRef],
    credentials: Credentials,
) -> list[KeyRow]:
    """표의 줄들 — 설치된 Bot이 요구하는 참조 ∪ 사람이 등록해 둔 참조.

    **빠진 것이 맨 위다** (BUI-10 — 빨간 줄로 「등록 필요」). 나머지는 이름 순이다.
    """
    apps: dict[str, str] = {}
    users: dict[str, list[str]] = {}
    for bot in bots:
        for ref, app_id in refs_of(bot.manifest).items():
            if app_id and not apps.get(ref):
                apps[ref] = app_id
            users.setdefault(ref, []).append(bot.name)
    for one in registered:
        if one.app_id and not apps.get(one.ref):
            apps[one.ref] = one.app_id
        apps.setdefault(one.ref, "")

    rows = []
    for ref in {*apps, *users}:
        stored = credentials.stored_service_app_key(ref)
        from_env = bool(credentials.service_app_key(ref)) and not stored
        value = stored or credentials.service_app_key(ref) or ""
        rows.append(
            KeyRow(
                ref=ref,
                app_id=apps.get(ref, ""),
                used_by=tuple(sorted(set(users.get(ref, [])))),
                stored=bool(stored),
                from_env=from_env,
                prefix=value[:PREFIX_CHARS],
            )
        )
    return sorted(rows, key=lambda row: (not row.missing, row.ref))


class KeyValueDialog(QDialog):
    """키 하나를 넣는 작은 창. 「값 바꾸기」면 참조·앱은 읽기 전용이다."""

    def __init__(
        self, parent: QWidget | None = None, *, ref: str = "", app_id: str = "", fixed: bool = False
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("키 값 바꾸기" if fixed else "서비스 앱 키 추가")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.ref = QLineEdit(ref)
        self.ref.setReadOnly(fixed)
        self.ref.setPlaceholderText("BPM 프로세스에 적힌 참조 이름 (예: finance-invoice)")
        self.app = QLineEdit(app_id)
        self.app.setReadOnly(fixed)
        self.app.setPlaceholderText("서비스 앱 id (모르면 비워 두세요)")
        self.value = QLineEdit()
        self.value.setEchoMode(QLineEdit.EchoMode.Password)
        self.value.setPlaceholderText("관리 콘솔(SVC-02)에서 발급한 값")
        form.addRow("참조 이름", self.ref)
        form.addRow("서비스 앱", self.app)
        form.addRow("키 값", self.value)
        layout.addLayout(form)
        self.error = QLabel()
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.submit)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def typed(self) -> tuple[str, str, str]:
        return self.ref.text().strip(), self.app.text().strip(), self.value.text().strip()

    def problem(self) -> str | None:
        ref, _, value = self.typed()
        if not ref:
            return "참조 이름이 비었습니다."
        if not re.fullmatch(KEY_REF_PATTERN, ref):
            # C1 R4와 같은 규칙이다 — 매니페스트가 받지 않는 이름을 여기서 받으면 영원히 안 맞는다.
            return f"참조 이름은 {KEY_REF_PATTERN} 모양이어야 합니다 (예: finance-invoice)."
        if not value:
            return "키 값이 비었습니다."
        return None

    def submit(self) -> None:
        """틀리면 **창을 닫지 않는다** — 닫고 나서 「왜 안 들어갔지」가 되면 안 된다."""
        found = self.problem()
        if found:
            self.error.setText(found)
            return
        self.accept()


class KeysDialog(QDialog):
    """BUI-10. 「도구」 → 「서비스 앱 키...」."""

    def __init__(self, agent: Agent, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._agent = agent
        self._rows: list[KeyRow] = []
        self.setWindowTitle(TITLE)
        self.setMinimumSize(820, 440)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "BPM 프로세스(Bot)가 서비스 앱을 부를 때 쓰는 키입니다. 값은 각 앱의 관리 콘솔"
            "(「API 키」)에서 발급받아 넣으세요 — BPM 파일에는 **참조 이름만** 들어 있습니다."
        )
        intro.setTextFormat(Qt.TextFormat.MarkdownText)
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(list(COLUMNS))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        for column in (REF, APP, VALUE):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        for column in (STATE, USED_BY):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        layout.addWidget(self.table, 1)

        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)

        buttons = QHBoxLayout()
        self.add_button = QPushButton("추가...")
        self.change_button = QPushButton("값 바꾸기...")
        self.drop_button = QPushButton("삭제...")
        self.check_button = QPushButton("확인")
        self.add_button.clicked.connect(self.add_key)
        self.change_button.clicked.connect(self.change_key)
        self.drop_button.clicked.connect(self.drop_key)
        self.check_button.clicked.connect(self.check_keys)
        for one in (self.add_button, self.change_button, self.drop_button, self.check_button):
            buttons.addWidget(one)
        buttons.addStretch(1)
        close = QPushButton("닫기")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)

        self.refresh()

    # ── 표 ──

    def refresh(self) -> None:
        """표를 다시 그린다. **앱을 부르지 않는다** — 「상태」는 「확인」을 누를 때 채운다."""
        self._rows = collect(
            installed(data_dir()), self._agent.settings.service_keys, self._agent.credentials
        )
        self.table.setRowCount(len(self._rows))
        # 빠진 줄의 색은 **토큰에서** 온다 (CLAUDE.md §5 — 값을 코드에 쓰지 않는다).
        failed = theme.status_color("Bot 준비", "서비스 앱 키 없음", part="fg")
        for at, row in enumerate(self._rows):
            used = ", ".join(row.used_by) if row.used_by else UNUSED
            state = NOT_CHECKED if row.registered else "—"
            for column, text in (
                (REF, row.ref),
                (APP, row.app_id or "—"),
                (VALUE, row.where()),
                (STATE, state),
                (USED_BY, used),
            ):
                item = QTableWidgetItem(text)
                if row.missing and failed is not None:
                    item.setForeground(QColor(failed))
                self.table.setItem(at, column, item)
        missing = [row.ref for row in self._rows if row.missing]
        if missing:
            self.note.setText(
                f"설치된 Bot이 요구하는데 값이 없는 참조 {len(missing)}개: {', '.join(missing)} — "
                "그 Bot은 실행되지 않습니다."
            )
        elif not self._rows:
            self.note.setText("등록한 키가 없습니다. 설치된 Bot이 서비스 앱을 부르면 여기 나타납니다.")
        else:
            self.note.setText("")
        self._selection_changed()

    def selected(self) -> KeyRow | None:
        rows = {index.row() for index in self.table.selectedIndexes()}
        if len(rows) != 1:
            return None
        at = rows.pop()
        return self._rows[at] if 0 <= at < len(self._rows) else None

    def _selection_changed(self) -> None:
        chosen = self.selected()
        self.change_button.setEnabled(chosen is not None)
        self.drop_button.setEnabled(chosen is not None and chosen.stored)
        if chosen is None:
            self.drop_button.setToolTip("지울 줄을 고르세요.")
        elif chosen.from_env and not chosen.stored:
            self.drop_button.setToolTip(
                f"환경변수 {service_key_env(chosen.ref)}로 오는 키입니다 — 여기서 지울 수 없습니다."
            )
        elif not chosen.stored:
            self.drop_button.setToolTip("이 PC에 저장된 값이 없습니다.")
        else:
            self.drop_button.setToolTip("")

    # ── 동작 ──

    def add_key(self) -> None:
        self._put(KeyValueDialog(self))

    def change_key(self) -> None:
        chosen = self.selected()
        if chosen is None:
            return
        if chosen.from_env:
            # 저장소에 덮어써도 읽기는 환경변수가 이긴다 — 바꿨는데 그대로가 된다.
            QMessageBox.information(
                self,
                TITLE,
                f"이 키는 환경변수 {service_key_env(chosen.ref)}로 들어옵니다 — "
                "값을 바꾸려면 그 환경변수를 고치세요.",
            )
            return
        self._put(KeyValueDialog(self, ref=chosen.ref, app_id=chosen.app_id, fixed=True))

    def _put(self, dialog: KeyValueDialog) -> None:
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        ref, app_id, value = dialog.typed()
        try:
            self._agent.credentials.set_service_app_key(ref, value)
        except SecretsUnavailable as e:
            QMessageBox.warning(self, "키를 저장하지 못했습니다", str(e))
            return
        self._remember(ref, app_id)
        self.refresh()

    def drop_key(self) -> None:
        """되돌릴 수 없다 — 쓰는 Bot이 있으면 그 수를 말하고 기본은 「취소」다."""
        chosen = self.selected()
        if chosen is None or not chosen.stored:
            return
        warning = f"키 참조 「{chosen.ref}」의 값을 이 PC에서 지웁니다. 되돌릴 수 없습니다."
        if chosen.used_by:
            warning += f"\n\n이 참조를 쓰는 Bot {len(chosen.used_by)}개가 실행 불가가 됩니다: " + ", ".join(
                chosen.used_by
            )
        answer = QMessageBox.question(
            self,
            "키를 지울까요?",
            warning,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._agent.credentials.delete_service_app_key(chosen.ref)
        self._forget(chosen.ref)
        self.refresh()

    def check_keys(self) -> None:
        """줄마다 `GET <앱 주소>/v1/keys/self` (C11). 주소는 **들고 있는 것**을 쓴다 (C7 캐시)."""
        from chaeksas.bot_ui.services import Services  # noqa: PLC0415 - 누를 때만 든다

        held = Services(data_dir=data_dir())
        for at, row in enumerate(self._rows):
            if not row.registered:
                continue
            base_url = held.base_url_of(app_id=row.app_id) if row.app_id else None
            found = key_status(base_url, self._agent.credentials.service_app_key(row.ref))
            item = self.table.item(at, STATE)
            if item is not None:
                item.setText(found)
                item.setToolTip(found)

    # ── 설정 파일 (이름만) ──

    def _remember(self, ref: str, app_id: str) -> None:
        """참조 이름을 설정에 남긴다 — 비밀 저장소는 목록을 뽑을 수 없다."""
        kept = [one for one in self._agent.settings.service_keys if one.ref != ref]
        kept.append(ServiceKeyRef(ref=ref, app_id=app_id))
        self._save(tuple(sorted(kept, key=lambda one: one.ref)))

    def _forget(self, ref: str) -> None:
        self._save(tuple(one for one in self._agent.settings.service_keys if one.ref != ref))

    def _save(self, refs: tuple[ServiceKeyRef, ...]) -> None:
        made = replace(self._agent.settings, service_keys=refs)
        made.save()
        self._agent.settings = made
        # 키가 바뀌었다 — 다음 하트비트가 준비 상태를 다시 재야 한다 (C4 `readiness`).
        self._agent.invalidate_preflight()


__all__ = ["COLUMNS", "NEEDS_KEY", "NOT_CHECKED", "KeyRow", "KeysDialog", "KeyValueDialog", "collect", "refs_of"]
