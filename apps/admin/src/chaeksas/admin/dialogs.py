"""Admin UI가 사람에게 묻는 창들 (ADM-04·05·06, ADR-0089).

창(`window.py`)은 **`Prompter`를 거쳐서만** 묻는다 — 시험은 이것을 갈아 끼워 짜 둔 답을 준다
(화면 없이 `QT_QPA_PLATFORM=offscreen`). 암호는 받아 넘기기만 하고 **쥐고 있지 않는다**.

Center 연결(ADM-05)과 첫 키의 서버 셸(ADM-06)은 **쓰는 때가 달라 다른 창**이다 — 연결은 Center를
부르는 모든 동작이 쓰고, 셸은 Center에 Admin 키가 없을 때 한 번만 쓴다.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QToolButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from chaeksas.admin import connection, ops
from chaeksas.admin import keys as keystore
from chaeksas.admin.client import Center, CenterProblem

#: ADM-06 「서버 셸」의 고를 거리 (첫 키를 넣을 때만 연다 — 「없음」은 고를 거리가 아니다).
SHELL_LABELS = {connection.SHELL_LOCAL: "이 PC", connection.SHELL_SSH: "SSH"}

#: ADM-05 토큰 안내 — 관리자 토큰을 **어디서 받는지** 화면에 적는다.
TOKEN_GUIDE = (
    "관리자 토큰은 Center 담당자에게 받으세요.\n"
    "받은 값을 이 칸에 붙여 넣고 「연결」을 누르면 됩니다.\n"
    "토큰은 이 PC에만 안전하게 저장됩니다."
)


class Prompter:
    """사람에게 묻는 자리 하나. 모두 **취소하면 `None`·`False`**다."""

    def __init__(self, parent: QWidget | None = None) -> None:
        self.parent = parent

    def text(self, title: str, label: str, default: str = "") -> str | None:
        found, ok = QInputDialog.getText(self.parent, title, label, text=default)
        return str(found) if ok else None

    def passphrase(self, key_id: str) -> str | None:
        """서명할 때마다 묻는다 (ADR-0089 §1)."""
        found, ok = QInputDialog.getText(
            self.parent, "서명 키 암호", f"{key_id}의 암호", QLineEdit.EchoMode.Password
        )
        return str(found) if ok else None

    def new_key(self) -> tuple[str, str] | None:
        """「새 키」 — 이름·암호·암호 확인을 **창 하나**에서. 만들 값이면 `(이름, 암호)`."""
        dialog = NewKeyDialog(self.parent)
        return dialog.values if dialog.exec() == QDialog.DialogCode.Accepted else None

    def new_passphrase(self) -> str | None:
        first, ok = QInputDialog.getText(self.parent, "새 키 암호", "암호", QLineEdit.EchoMode.Password)
        if not ok:
            return None
        again, ok = QInputDialog.getText(self.parent, "새 키 암호", "한 번 더", QLineEdit.EchoMode.Password)
        if not ok:
            return None
        if first != again:
            self.fail("암호가 서로 다릅니다 — 키를 만들지 않았습니다")
            return None
        return str(first)

    def confirm(self, title: str, message: str) -> bool:
        """**기본은 「취소」**다 (U9 — 되돌릴 수 없는 일)."""
        box = QMessageBox(QMessageBox.Icon.Warning, title, message, parent=self.parent)
        yes = box.addButton("계속", QMessageBox.ButtonRole.AcceptRole)
        no = box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(no)
        box.exec()
        return box.clickedButton() is yes

    def choose(self, title: str, label: str, items: list[str]) -> str | None:
        found, ok = QInputDialog.getItem(self.parent, title, label, items, 0, False)
        return str(found) if ok else None

    def open_file(self, title: str) -> str | None:
        found, _ = QFileDialog.getOpenFileName(self.parent, title, "", "확장 정의 (*.json);;모든 파일 (*)")
        return str(found) or None

    def review(self, lines: list[str], problems: list[str]) -> bool:
        """서명 **전에** 무엇에 서명하는지 보인다. 문제가 있으면 서명 단추가 없다."""
        return ReviewDialog(lines, problems, self.parent).exec() == QDialog.DialogCode.Accepted

    def first_key(self, key: keystore.StoredKey, url: str, *, run: Any = None) -> connection.ServerShell | None:
        """ADM-06 — 첫 키를 넣을 서버 셸. 「넣기」면 그 셸, 닫으면 `None`."""
        dialog = FirstKeyDialog(key, url, self.parent, run=run)
        return dialog.chosen if dialog.exec() == QDialog.DialogCode.Accepted else None

    def connection(self, reason: str = "") -> bool:
        """ADM-05. 확인하고 저장했으면 `True`. `reason`은 저절로 띄운 까닭(맨 위 한 줄)."""
        dialog = ConnectionDialog(self.parent, reason=reason)
        return bool(dialog.exec()) and dialog.saved

    def fail(self, message: str) -> None:
        QMessageBox.warning(self.parent, "Admin", message)


class NewKeyDialog(QDialog):
    """「새 키」 — 이름·암호·암호 확인을 한 창에서 받는다 (ADM-01).

    틀리면 **닫지 않고** 아래 한 줄에 말한다. 이름은 이 PC의 다른 키와 겹치지 않아야 한다 —
    겹치면 표에서 어느 것이 어느 것인지 사람이 가를 수 없다.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("새 키")
        self.values: tuple[str, str] | None = None
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("예: 홍길동 노트북")
        self.secret = QLineEdit()
        self.secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.again = QLineEdit()
        self.again.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("이름", self.name)
        form.addRow("암호", self.secret)
        form.addRow("암호 확인", self.again)
        layout.addLayout(form)
        self.problem = QLabel("")
        self.problem.setWordWrap(True)
        layout.addWidget(self.problem)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("만들기")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.accepted.connect(self.make)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.setMinimumWidth(380)

    def make(self) -> None:
        name = self.name.text().strip()
        taken = {(one.label or "").strip() for one in keystore.listing()}
        if not name:
            self.problem.setText("이름을 적으세요 — 키가 여럿일 때 이것으로 가릅니다")
        elif name in taken:
            self.problem.setText(f"이 PC에 「{name}」 키가 이미 있습니다 — 다른 이름을 적으세요")
        elif not self.secret.text():
            self.problem.setText("암호를 적으세요 — 키를 암호 없이 두지 않습니다")
        elif self.secret.text() != self.again.text():
            self.problem.setText("암호와 암호 확인이 다릅니다")
        else:
            self.values = (name, self.secret.text())
            self.accept()


class ReviewDialog(QDialog):
    """외부 확장 서명 전 확인 (ADM-04) — 줄은 CLI와 **같은 함수**(`ops.review_extension`)에서 온다."""

    def __init__(self, lines: list[str], problems: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("외부 확장 서명")
        layout = QVBoxLayout(self)
        body = QPlainTextEdit("\n".join(lines))
        body.setReadOnly(True)
        layout.addWidget(body)
        if problems:
            said = QLabel("정의에 문제가 있습니다 — 서명하지 않습니다:\n" + "\n".join(f"  {one}" for one in problems))
            said.setWordWrap(True)
            layout.addWidget(said)
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            buttons.button(QDialogButtonBox.StandardButton.Close).setText("닫기")
        else:
            layout.addWidget(QLabel("서명하고 Center에 등록할까요?"))
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            buttons.button(QDialogButtonBox.StandardButton.Ok).setText("서명하고 등록")
            cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
            cancel.setText("취소")
            cancel.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(560, 360)


def _copy_row(label: str, value: str) -> QWidget:
    holder = QWidget()
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    row.addWidget(QLabel(label))
    field = QLineEdit(value)
    field.setReadOnly(True)
    row.addWidget(field, 1)
    copy = QPushButton("복사")
    copy.clicked.connect(lambda: QApplication.clipboard().setText(value))
    row.addWidget(copy)
    return holder


class ManualFirstKeyDialog(QDialog):
    """「직접 넣기...」 — 서버 셸을 쓸 수 없을 때 그 서버에서 칠 명령과 공개키 (복사만)."""

    def __init__(self, key: keystore.StoredKey, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("직접 넣기")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("그 서버에서 아래 명령을 실행한 뒤 「새로 고침」을 누르세요."))
        layout.addWidget(_copy_row("공개키", key.public_path.read_text(encoding="utf-8").strip()))
        layout.addWidget(_copy_row("명령", ops.bootstrap_command(key)))
        self.setMinimumWidth(520)
        self.adjustSize()


class FirstKeyDialog(QDialog):
    """ADM-06 — 첫 키를 **서버 셸에서** 넣는다 (C2, ADR-0089 §6). 암호 칸은 없다.

    필요한 것만 보인다: 서버 고르기, SSH 칸은 SSH일 때만, 「Center 명령」은 「고급」 안.
    「넣기」가 Center를 찾아보고, 찾았을 때만 닫힌다(못 찾으면 까닭 한 줄). 셸을 쓸 수 없으면
    왼쪽 아래 「직접 넣기...」가 명령·공개키를 따로 띄운다.
    """

    def __init__(self, key: keystore.StoredKey, url: str, parent: QWidget | None = None, *, run: Any = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("첫 Admin 키 넣기")
        self.key = key
        self.url = url
        #: 시험이 끼우는 셸 실행.
        self.run = run
        self.chosen: connection.ServerShell | None = None
        layout = QVBoxLayout(self)
        intro = QLabel(f"{key.label or key.key_id}({key.key_id[:8]}…)을 첫 Admin 키로 넣습니다.")
        intro.setWordWrap(True)
        # 왜 서버에서만 넣는지는 **툴팁**이다 (C2).
        intro.setToolTip(
            f"Center {url}에 Admin 키가 없습니다.\n"
            "첫 키는 Center 서버에서만 넣습니다 — 관리자 토큰이 새도 다른 사람이 자기 키를 넣지 못하게."
        )
        layout.addWidget(intro)

        stored = connection.stored_shell()
        form = QFormLayout()
        self.shell_kind = QComboBox()
        for kind, label in SHELL_LABELS.items():
            self.shell_kind.addItem(label, kind)
        default = stored.kind or (connection.SHELL_LOCAL if ops.is_loopback(url) else connection.SHELL_SSH)
        self.shell_kind.setCurrentIndex(max(0, self.shell_kind.findData(default)))
        self.shell_kind.setToolTip("Center가 이 PC에 있으면 「이 PC」, 다른 서버면 「SSH」")
        form.addRow("서버", self.shell_kind)

        # SSH 대상과 포트는 한 줄 — SSH를 고를 때만 보인다.
        self.ssh_row = QWidget()
        ssh = QHBoxLayout(self.ssh_row)
        ssh.setContentsMargins(0, 0, 0, 0)
        self.ssh_target = QLineEdit(stored.ssh_target)
        self.ssh_target.setPlaceholderText("사용자@호스트")
        self.ssh_target.setToolTip("SSH 키로 들어갑니다 — 암호는 묻지 않습니다")
        self.ssh_port = QSpinBox()
        self.ssh_port.setRange(1, 65535)
        self.ssh_port.setValue(stored.ssh_port)
        self.ssh_port.setToolTip("SSH 포트")
        ssh.addWidget(self.ssh_target, 1)
        ssh.addWidget(QLabel(":"))
        ssh.addWidget(self.ssh_port)
        self.ssh_label = QLabel("SSH 대상")
        form.addRow(self.ssh_label, self.ssh_row)
        layout.addLayout(form)

        # 「고급」 — docker 없이 띄운 Center일 때만 쓰는 칸이라 접어 둔다.
        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setText("고급")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.advanced_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.advanced = QWidget()
        advanced = QFormLayout(self.advanced)
        advanced.setContentsMargins(0, 0, 0, 0)
        self.center_command = QLineEdit(stored.center_command)
        self.center_command.setPlaceholderText("비우면 Center 컨테이너를 찾습니다")
        self.center_command.setToolTip("docker 없이 띄운 Center일 때만 — 그 서버에서 Center를 부르는 명령")
        advanced.addRow("Center 명령", self.center_command)
        self.advanced_toggle.toggled.connect(self._show_advanced)
        layout.addWidget(self.advanced_toggle)
        layout.addWidget(self.advanced)
        self.advanced_toggle.setChecked(bool(stored.center_command))
        self._show_advanced(bool(stored.center_command))

        self.shell_line = QLabel("")
        self.shell_line.setWordWrap(True)
        layout.addWidget(self.shell_line)

        # 아래 줄: 왼쪽 「직접 넣기...」, 오른쪽 「넣기」 하나 (닫기는 창의 X).
        bottom = QHBoxLayout()
        manual = QPushButton("직접 넣기...")
        manual.setToolTip("서버에 들어갈 수 없을 때 — 그 서버에서 칠 명령과 공개키")
        manual.clicked.connect(lambda: ManualFirstKeyDialog(self.key, self).exec())
        bottom.addWidget(manual)
        bottom.addStretch(1)
        self.put_button = QPushButton("넣기")
        self.put_button.setDefault(True)
        self.put_button.clicked.connect(self.put)
        bottom.addWidget(self.put_button)
        layout.addLayout(bottom)

        self.shell_kind.currentIndexChanged.connect(self._refresh)
        self._refresh()
        self.setMinimumWidth(460)
        self.adjustSize()

    def _show_advanced(self, shown: bool) -> None:
        self.advanced.setVisible(shown)
        self.advanced_toggle.setArrowType(Qt.ArrowType.DownArrow if shown else Qt.ArrowType.RightArrow)
        self.adjustSize()

    def shell(self) -> connection.ServerShell:
        return connection.ServerShell(
            kind=str(self.shell_kind.currentData() or ""),
            ssh_target=self.ssh_target.text().strip(),
            ssh_port=int(self.ssh_port.value()),
            center_command=self.center_command.text().strip(),
        )

    def _refresh(self) -> None:
        """SSH 칸은 SSH를 고를 때만 **보인다** (끄기만 하면 자리를 차지한다)."""
        ssh = self.shell_kind.currentData() == connection.SHELL_SSH
        self.ssh_row.setVisible(ssh)
        self.ssh_label.setVisible(ssh)
        self.adjustSize()

    def _find(self) -> ops.FoundCenter:
        kwargs = {"run": self.run} if self.run is not None else {}
        return ops.find_center(self.shell(), self.url, **kwargs)

    def probe(self) -> None:
        """셸에 들어가 Center를 찾아만 본다 (사람이 누를 때만)."""
        found = self._find()
        self.shell_line.setText(found.problem or f"찾았습니다 — {found.describe()}")

    def put(self) -> None:
        """찾았을 때만 닫는다 — 셸 설정은 남겨 둔다 (다음에 다시 적지 않게)."""
        found = self._find()
        if not found.ok:
            self.shell_line.setText(found.problem)
            return
        now = connection.current()
        connection.save(url=connection.stored_url() or now.url, token=None, shell=found.shell)
        self.chosen = found.shell
        self.accept()


def connected(line: str) -> bool:
    """`describe()`의 줄이 「연결됨 …」인가 — Center가 주소·토큰을 받아들였다."""
    return line.startswith("연결됨")


def describe(center: Center) -> str:
    """창 제목·「연결」 결과의 한 줄 (ADM-05). 키 값·토큰은 넣지 않는다."""
    if not center.base_url:
        return "Center 주소가 없습니다"
    if not center.token:
        return "관리자 토큰이 없습니다"
    try:
        found = center.admin_keys()
    except CenterProblem as e:
        if e.code == "token_not_ascii":
            return str(e)
        if e.status in (401, 403):
            return "토큰이 거부되었습니다 — 토큰 값을 확인하세요"
        if e.status:
            return f"Center가 거절했습니다 ({e.status}) — {e}"
        return "닿지 못했습니다 — 주소를 확인하세요"
    active = [one for one in found if not one.revoked]
    if not active:
        return "연결됨 · Admin 키 없음"
    return f"연결됨 · Admin 키 {len(active)}개"


class ConnectionDialog(QDialog):
    """ADM-05 — 주소는 설정 파일, 토큰은 OS 비밀 저장소. **「저장」 전에는 아무것도 바뀌지 않는다.**"""

    def __init__(self, parent: QWidget | None = None, *, client: object = None, reason: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("Center 연결")
        #: 시험이 끼우는 HTTP 클라이언트 (「연결」).
        self.client = client
        self.saved = False
        now = connection.current()
        layout = QVBoxLayout(self)
        if reason:
            # 저절로 떴으면 **왜 떴는지** 한 줄로 (토큰이 바뀌었다·닿지 못한다).
            why = QLabel(reason)
            why.setWordWrap(True)
            layout.addWidget(why)
        form = QFormLayout()
        self.url = QLineEdit(connection.stored_url() or now.url)
        self.url.setPlaceholderText("https://center.example.com")
        self.token = QLineEdit()
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.token.setPlaceholderText("저장됨" if connection.stored_token() else "")
        # 토큰을 어디서 받는지는 **툴팁**이다 — 창에 늘 펴 두지 않는다.
        self.token.setToolTip(TOKEN_GUIDE)
        form.addRow("Center 주소", self.url)
        # 「?」에 올리거나 누르면 토큰 얻는 법이 뜬다 — 칸의 툴팁만으로는 있는 줄을 모른다.
        # 「?」는 **이름 쪽**에 둔다 — 칸 쪽에 두면 주소 칸과 끝이 어긋난다.
        token_label = QWidget()
        label_row = QHBoxLayout(token_label)
        label_row.setContentsMargins(0, 0, 0, 0)
        label_row.addWidget(QLabel("관리자 토큰"))
        self.token_help = QToolButton()
        self.token_help.setText("?")
        self.token_help.setToolTip(TOKEN_GUIDE)
        self.token_help.clicked.connect(
            lambda: QToolTip.showText(self.token_help.mapToGlobal(self.token_help.rect().bottomLeft()), TOKEN_GUIDE)
        )
        label_row.addWidget(self.token_help)
        form.addRow(token_label, self.token)
        if now.url_from_env:
            form.addRow("", QLabel(f"환경변수 {connection.ENV_CENTER_URL}가 있어 그 값이 이깁니다."))
        if now.token_from_env:
            form.addRow("", QLabel(f"환경변수 {connection.ENV_ADMIN_TOKEN}가 있어 그 값이 이깁니다."))
        layout.addLayout(form)
        # 단추는 「연결」 하나다 — 확인하고, 맞으면 저장하고 닫는다. 그만두려면 창을 닫는다.
        self.connect_button = QPushButton("연결")
        self.connect_button.setDefault(True)
        self.connect_button.clicked.connect(self.save)
        self.result_line = QLabel("")
        self.result_line.setWordWrap(True)
        layout.addWidget(self.result_line)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(self.connect_button)
        layout.addLayout(bottom)
        self.setMinimumWidth(420)
        self.adjustSize()

    def _center(self) -> Center:
        """지금 친 값으로 — 저장하지 않고 본다."""
        now = connection.current()
        typed_url = self.url.text().strip()
        url = now.url if now.url_from_env else (typed_url or connection.DEFAULT_CENTER_URL)
        token = now.token if now.token_from_env else (self.token.text().strip() or now.token)
        return Center(base_url=url, token=token, timeout_s=5.0, client=self.client)

    def test(self) -> None:
        self.result_line.setText(describe(self._center()))

    def save(self) -> None:
        """**확인한 뒤에만** 저장한다 — 맞지 않는 연결을 남기면 다음 시작이 또 막힌다."""
        line = describe(self._center())
        self.result_line.setText(line)
        if not connected(line):
            return
        typed = self.token.text().strip()
        try:
            connection.save(url=self.url.text(), token=typed if typed else None)
        except connection.SecretsUnavailable as e:
            # **분명히 실패하고 창을 닫지 않는다** — 평문으로 흘리지 않는다.
            self.result_line.setText(str(e))
            return
        self.saved = True
        self.accept()


__all__ = [
    "TOKEN_GUIDE",
    "ConnectionDialog",
    "FirstKeyDialog",
    "ManualFirstKeyDialog",
    "NewKeyDialog",
    "Prompter",
    "ReviewDialog",
    "connected",
    "describe",
]
