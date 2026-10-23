"""Admin UI 창 — 키(ADM-01)·외부 확장(ADM-04) (ADR-0089).

- 서명은 **누를 때마다 암호를 묻고** `ops.sign_with` 한 번 안에서 키를 열고 놓는다. 창은 암호도
  열린 키도 쥐지 않는다.
- 확인 문구·봉투·키 고르기는 **CLI와 같은 `ops`**다.
- Center는 **사람이 누를 때만** 부른다 (창을 열 때 한 번, 「새로 고침」, 각 동작). 닿지 못하면
  표의 등록 상태는 「알 수 없음」이다.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from chaeksas.admin import keys as keystore
from chaeksas.admin import ops
from chaeksas.admin.client import Center, CenterProblem
from chaeksas.admin.dialogs import Prompter, describe
from chaeksas.contracts.resources import ExtensionResource
from chaeksas.qt import theme

WINDOW_TITLE = "Chaeksas Admin"
KEY_STATUS_GROUP = "Admin 키"
EXTENSION_STATUS_GROUP = "서비스 앱"
#: C7 `status` → `status_map` 「서비스 앱」의 표기. 서버 부분이 없으면(`n/a`) 「—」.
EXTENSION_STATUS = {"ok": "정상", "degraded": "저하", "unreachable": "응답 없음", "unknown": "확인 전"}
REVOKE_REASON = "관리자 철회"


def _table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    table.horizontalHeader().setStretchLastSection(True)
    return table


def _rejected(line: str) -> bool:
    """`describe()`의 줄이 「토큰이 거부되었다」인가 — 쓰는 도중이면 연결을 다시 받는다."""
    return line.startswith("토큰이 거부")


def _status_item(group: str, label: str) -> QTableWidgetItem:
    item = QTableWidgetItem(label)
    color = theme.status_color(group, label, part="fg")
    if color is not None:
        item.setForeground(QColor(color))
    return item


class AdminWindow(QMainWindow):
    """창 하나. `center`는 부를 때마다 새로 짓는다 — 연결을 저장하면 다음 누름부터 그것을 쓴다."""

    def __init__(
        self,
        *,
        center: Callable[[], Center] = Center.from_env,
        prompter: Prompter | None = None,
        run: Any = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.make_center = center
        self.ask = prompter or Prompter(self)
        #: 부트스트랩이 docker를 부르는 자리 (시험이 끼운다).
        self.run = run
        self.states = ops.KeyStates(rows=[], center_keys=None)
        self.extensions: list[ExtensionResource] = []
        self.center_line = ""
        self._reconnecting = False

        root = QWidget()
        layout = QVBoxLayout(root)

        # Center 연결은 시작할 때·토큰이 거부될 때 저절로 뜬다 (ADM-05). 바꾸려면 「연결 변경」.
        # 탭 줄 모서리에 끼우면 표 테두리에 붙는다 — **탭 위 줄**에 오른쪽으로 따로 둔다.
        # 지금 Center 주소·상태를 왼쪽에, 그것을 바꾸는 단추를 바로 오른쪽 끝에 둔다.
        top = QHBoxLayout()
        self.center_label = QLabel("")
        top.addWidget(self.center_label, 1)
        leave = QPushButton("연결 변경")
        leave.setToolTip("다른 Center 주소·토큰으로 연결합니다")
        leave.clicked.connect(self.disconnect_center)
        top.addWidget(leave)
        layout.addLayout(top)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._keys_tab(), "키")
        self.tabs.addTab(self._extensions_tab(), "확장")
        layout.addWidget(self.tabs, 1)

        # 탭마다 다른 단추 줄은 **탭 상자 밖, 아래**에 둔다 — 지금 탭의 줄만 보인다.
        self.action_rows = QStackedWidget()
        self.action_rows.addWidget(self._keys_actions())
        self.action_rows.addWidget(self._extensions_actions())
        self.tabs.currentChanged.connect(self.action_rows.setCurrentIndex)
        layout.addWidget(self.action_rows)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.setCentralWidget(root)
        # 키는 보통 한두 개다 — 표가 화면을 차지하지 않게 작게 연다.
        self.resize(720, 500)

    # ── 짓기 ──

    def _refresh_row(self) -> QHBoxLayout:
        """「새로 고침」 — 표를 다시 읽는다. 그래서 **탭 안, 표 오른쪽 아래**에 둔다."""
        row = QHBoxLayout()
        row.addStretch(1)
        button = QPushButton("새로 고침")
        button.clicked.connect(self.refresh)
        row.addWidget(button)
        return row

    def _keys_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.keys_table = _table(["키 id", "이름", "만든 날", "Center 상태"])
        self.keys_table.itemSelectionChanged.connect(self._refresh_key_buttons)
        layout.addWidget(self.keys_table, 1)
        layout.addLayout(self._refresh_row())
        return page

    def _keys_actions(self) -> QWidget:
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        self.new_key_button = QPushButton("새 키")
        self.register_button = QPushButton("등록")
        self.register_button.setToolTip("고른 키를 Center에 등록합니다")
        self.revoke_key_button = QPushButton("철회")
        self.delete_key_button = QPushButton("지우기")
        self.new_key_button.clicked.connect(self.new_key)
        self.register_button.clicked.connect(self.register_key)
        self.revoke_key_button.clicked.connect(self.revoke_key)
        self.delete_key_button.clicked.connect(self.delete_key)
        for one in (self.new_key_button, self.register_button, self.revoke_key_button, self.delete_key_button):
            row.addWidget(one)
        row.addStretch(1)
        return holder

    def _extensions_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.ext_table = _table(["id", "판", "이름", "게시자", "상태"])
        self.ext_table.itemSelectionChanged.connect(self._refresh_ext_buttons)
        layout.addWidget(self.ext_table, 1)
        layout.addLayout(self._refresh_row())
        return page

    def _extensions_actions(self) -> QWidget:
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        self.sign_ext_button = QPushButton("서명하고 등록...")
        self.revoke_ext_button = QPushButton("철회...")
        self.sign_ext_button.clicked.connect(self.sign_extension)
        self.revoke_ext_button.clicked.connect(self.revoke_extension)
        row.addWidget(self.sign_ext_button)
        row.addWidget(self.revoke_ext_button)
        row.addStretch(1)
        return holder

    # ── 읽기 ──

    def refresh(self) -> None:
        center = self.make_center()
        line = describe(center)
        if _rejected(line) and self.reconnect(line):
            center = self.make_center()
            line = describe(center)
        self.center_line = f"{center.base_url} · {line}"
        self.states = ops.key_states(center)
        self.center_label.setText(f"Center  {self.center_line}")
        self._fill_keys()
        try:
            self.extensions = [one for one in center.extensions() if one.tier == "external"]
        except CenterProblem:
            self.extensions = []
        self._fill_extensions()

    def _fill_keys(self) -> None:
        self.keys_table.setRowCount(len(self.states.rows))
        for at, row in enumerate(self.states.rows):
            self.keys_table.setItem(at, 0, QTableWidgetItem(row.key.key_id))
            self.keys_table.setItem(at, 1, QTableWidgetItem(row.key.label or ""))
            self.keys_table.setItem(at, 2, QTableWidgetItem(row.key.created_at[:10]))
            self.keys_table.setItem(at, 3, _status_item(KEY_STATUS_GROUP, row.state))
        self._refresh_key_buttons()

    def _fill_extensions(self) -> None:
        self.ext_table.setRowCount(len(self.extensions))
        for at, one in enumerate(self.extensions):
            label = EXTENSION_STATUS.get(one.status, "—")
            for column, text in enumerate([one.id, one.version, one.name or "", one.publisher or ""]):
                self.ext_table.setItem(at, column, QTableWidgetItem(text))
            self.ext_table.setItem(at, 4, _status_item(EXTENSION_STATUS_GROUP, label))
        self._refresh_ext_buttons()

    def selected_key(self) -> ops.KeyRow | None:
        rows = self.keys_table.selectionModel().selectedRows()
        return self.states.rows[rows[0].row()] if rows else None

    def selected_extension(self) -> ExtensionResource | None:
        rows = self.ext_table.selectionModel().selectedRows()
        return self.extensions[rows[0].row()] if rows else None

    def _refresh_key_buttons(self) -> None:
        row = self.selected_key()
        self.register_button.setEnabled(row is not None and row.state not in ("등록됨", "철회됨"))
        self.revoke_key_button.setEnabled(row is not None and row.registered)
        self.delete_key_button.setEnabled(row is not None)

    def _refresh_ext_buttons(self) -> None:
        self.revoke_ext_button.setEnabled(self.selected_extension() is not None)

    def say(self, message: str) -> None:
        self.status.setText(message)

    def _failed(self, e: Exception) -> None:
        if isinstance(e, CenterProblem) and e.status in (401, 403) and self.reconnect(str(e)):
            # 쓰는 도중 토큰이 거부됐다 — 연결을 다시 받았으니 표를 다시 읽는다 (사람이 다시 누른다).
            self.say("Center 연결을 다시 저장했습니다 — 방금 하던 일을 다시 눌러 주세요")
            self.refresh()
            return
        self.say(f"오류: {e}")
        self.ask.fail(str(e))

    def reconnect(self, reason: str) -> bool:
        """토큰이 거부되면 그 자리에서 ADM-05를 띄운다. 다시 들어오는 것은 막는다 (창이 겹쳐 뜨지 않게)."""
        if self._reconnecting:
            return False
        self._reconnecting = True
        try:
            return self.ask.connection(reason)
        finally:
            self._reconnecting = False

    # ── 키 (ADM-01) ──

    def new_key(self) -> None:
        found = self.ask.new_key()
        if found is None:
            return
        label, secret = found
        try:
            made = keystore.create(label=label, passphrase=secret)
        except keystore.KeyError_ as e:
            self._failed(e)
            return
        self.say(f"키를 만들었습니다 — {made.key_id}")
        self.refresh()
        if self.states.needs_bootstrap and self.ask.confirm(
            "첫 Admin 키", "Center에 Admin 키가 없습니다. 이 키를 첫 키로 넣을까요?"
        ):
            self._bootstrap(made)

    def _key_to_register(self) -> ops.KeyRow | None:
        """표에서 고른 것, 없으면 등록 안 된 이 PC의 키 — 하나면 그것, 여럿이면 고르게 한다."""
        row = self.selected_key()
        if row is not None:
            return row
        loose = [one for one in self.states.rows if one.state in ("등록 안 됨", "알 수 없음")]
        if len(loose) == 1:
            return loose[0]
        if not loose:
            self._failed(RuntimeError("등록할 키가 없습니다 — 「새 키...」로 먼저 만드세요"))
            return None
        names = [f"{one.key.key_id}  {one.key.label or ''}".strip() for one in loose]
        picked = self.ask.choose("Center에 등록", "등록할 키", names)
        return loose[names.index(picked)] if picked is not None else None

    def register_key(self) -> None:
        row = self._key_to_register()
        if row is None:
            return
        self.refresh()
        if self.states.center_keys is None:
            if self.ask.confirm(
                "Center에 닿지 못했습니다",
                f"{self.states.problem}\n\nCenter 연결(주소·관리자 토큰)을 확인할까요?",
            ):
                self.open_settings()
            return
        if self.states.needs_bootstrap:
            self._bootstrap(row.key)
            return
        signer = self._pick_signer(exclude=row.key.key_id, purpose=f"{row.key.key_id}를 추가할 서명 키")
        if signer is None:
            return
        secret = self.ask.passphrase(signer.key_id)
        if secret is None:
            return
        try:
            envelope = ops.sign_with(signer, ops.admin_key_payload(row.key), passphrase=secret)
            found = self.make_center().add_admin_key(envelope)
        except (keystore.KeyError_, CenterProblem) as e:
            self._failed(e)
            return
        self.say(f"Center에 등록했습니다 — {found.key_id} ({signer.key_id}의 서명)")
        self.refresh()

    def _bootstrap(self, key: keystore.StoredKey) -> None:
        """첫 키 — ADM-06에서 고른 **서버 셸**(이 PC·SSH)에서 넣고 **API로 확인한다** (ADR-0089 §6).

        네트워크(API)로 넣는 길은 없다 (C2).
        """
        center = self.make_center()
        kwargs = {"run": self.run} if self.run is not None else {}
        shell = self.ask.first_key(key, center.base_url, **kwargs)
        if shell is None:
            self.say("첫 키를 넣지 않았습니다")
            return
        found = ops.find_center(shell, center.base_url, **kwargs)
        if not found.ok:
            self._failed(RuntimeError(found.problem))
            return
        result = ops.bootstrap(found, key, **kwargs)
        if not result.ok:
            self._failed(RuntimeError(result.message))
            return
        self.refresh()
        # **주소의 Center가 그 키를 알아야** 성공이다 — 셸과 주소가 다른 서버를 가리킬 수 있다.
        known = {one.key_id for one in self.states.active_in_center}
        if key.key_id not in known:
            self._failed(
                RuntimeError(
                    f"{found.describe()}에서는 넣었지만 {center.base_url}의 Center는 이 키를 모릅니다 — "
                    "서버 셸과 Center 주소가 같은 서버를 가리키는지 확인하세요"
                )
            )
            return
        self.say(result.message)

    def _pick_signer(self, *, exclude: str | None, purpose: str) -> keystore.StoredKey | None:
        """서명할 키 — Center에 등록되고 철회되지 않은 **이 PC의** 키. 하나면 그것, 여럿이면 고른다."""
        usable = [row.key for row in self.states.rows if row.registered and row.key.key_id != exclude]
        if not usable:
            self._failed(RuntimeError("Center에 등록된 키가 이 PC에 없습니다 — 그 키가 있는 PC에서 하세요"))
            return None
        if len(usable) == 1:
            return usable[0]
        names = [f"{one.key_id}  {one.label or ''}".strip() for one in usable]
        picked = self.ask.choose("서명 키", purpose, names)
        if picked is None:
            return None
        return usable[names.index(picked)]

    def revoke_key(self) -> None:
        row = self.selected_key()
        if row is None or not row.registered:
            return
        if not self.ask.confirm("키 철회", ops.REVOKE_KEY_WARNING.format(key_id=row.key.key_id)):
            return
        signer = self._pick_signer(exclude=None, purpose=f"{row.key.key_id}의 철회에 서명할 키")
        if signer is None:
            return
        secret = self.ask.passphrase(signer.key_id)
        if secret is None:
            return
        try:
            payload = ops.admin_key_revoke_payload(row.key.key_id, REVOKE_REASON)
            found = self.make_center().revoke_admin_key(ops.sign_with(signer, payload, passphrase=secret))
        except (keystore.KeyError_, CenterProblem) as e:
            self._failed(e)
            return
        self.say(f"철회했습니다 — {found.key_id}")
        self.refresh()

    def delete_key(self) -> None:
        row = self.selected_key()
        if row is None:
            return
        self.refresh()
        refusal = ops.delete_refusal(self.states, row.key.key_id)
        if refusal is not None:
            self._failed(RuntimeError(refusal))
            return
        warning = ops.delete_warning(self.states, row.key.key_id)
        message = f"{row.key.key_id}를 이 PC에서 지웁니다. 되돌릴 수 없습니다."
        if not self.ask.confirm("키 지우기", f"{message}\n\n{warning}" if warning else message):
            return
        try:
            keystore.delete(row.key.key_id)
        except keystore.KeyError_ as e:
            self._failed(e)
            return
        self.say(f"이 PC에서 지웠습니다 — {row.key.key_id}")
        self.refresh()

    # ── 외부 확장 (ADM-04) ──

    def _signing_key(self, center: Center) -> keystore.StoredKey | None:
        """CLI와 같은 규칙 (`ops.choose_key`). 좁혀지지 않으면 「키」 탭으로 보낸다."""
        try:
            found, _ = ops.choose_key(center)
        except keystore.KeyError_ as e:
            self._failed(RuntimeError(f"{e}\n\n「키」 탭에서 Center에 등록된 키가 하나가 되게 정리하세요."))
            return None
        return found

    def sign_extension(self) -> None:
        path = self.ask.open_file("확장 정의 파일")
        if path is None:
            return
        try:
            definition = ops.read_definition(path)
        except keystore.KeyError_ as e:
            self._failed(e)
            return
        review = ops.review_extension(definition)
        if not self.ask.review(review.lines, review.problems) or review.problems:
            return
        center = self.make_center()
        key = self._signing_key(center)
        if key is None:
            return
        secret = self.ask.passphrase(key.key_id)
        if secret is None:
            return
        try:
            envelope = ops.sign_with(key, review.payload(), passphrase=secret)
            found, created = center.register_extension(definition, envelope)
        except (keystore.KeyError_, CenterProblem) as e:
            self._failed(e)
            return
        if created:
            self.say(f"서명하고 등록했습니다 — {found.id}@{found.version}")
        else:
            self.say(f"이미 같은 정의로 등록되어 있습니다 — {found.id}@{found.version}")
        self.refresh()

    def revoke_extension(self) -> None:
        one = self.selected_extension()
        if one is None:
            return
        reason = self.ask.text("확장 철회", "사유", REVOKE_REASON)
        if reason is None:
            return
        if not self.ask.confirm("확장 철회", ops.REVOKE_EXTENSION_WARNING.format(id=one.id, version=one.version)):
            return
        center = self.make_center()
        key = self._signing_key(center)
        if key is None:
            return
        secret = self.ask.passphrase(key.key_id)
        if secret is None:
            return
        try:
            payload = ops.extension_revoke_payload(one.id, one.version, reason.strip() or REVOKE_REASON)
            center.revoke_extension(ops.sign_with(key, payload, passphrase=secret))
        except (keystore.KeyError_, CenterProblem) as e:
            self._failed(e)
            return
        self.say(f"철회했습니다 — {one.id}@{one.version}")
        self.refresh()

    # ── 연결 (ADM-05) ──

    def disconnect_center(self) -> None:
        """「연결 변경」 — 연결 창을 바로 띄운다 (주로 다른 Center로 바꿀 때).

        묻지 않고 지우지도 않는다 — 새 주소·토큰으로 「연결」되어야 바뀌고, 창을 닫으면 그대로다.
        """
        if self.ask.connection():
            self.say("Center 연결을 바꿨습니다")
            self.refresh()

    def open_settings(self) -> None:
        if self.ask.connection():
            self.say("Center 연결을 저장했습니다")
            self.refresh()


__all__ = ["EXTENSION_STATUS", "WINDOW_TITLE", "AdminWindow"]
