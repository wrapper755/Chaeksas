"""STU-16 「Center에 연결」 — Studio가 Center에 들어오는 창 (ADR-0093).

Bot UI를 처음 켜면 BUI-03이 먼저 뜨는 것과 같은 자리다. **아이디·비밀번호는 없다** — 주소를 넣고
「보내기」를 누르면 등록 요청이 나가고, 관리자가 콘솔 CON-11 「승인 대기」에서 같은 요청 코드를
승인하면 키를 받아 OS 비밀 저장소에 둔다. 판단은 Qt를 모르는 `center_enroll`에 있다.

- 기다리는 동안 **이 창이 열려 있을 때만** 10초마다 묻는다. 승인되면 「연결됨」을 2초 보이고 닫는다.
- 「나중에」는 막지 않는다 — Studio는 Center 없이도 그리고 시험 실행한다. 보낸 요청은 Center에
  24시간 남아 다음에 같은 코드로 다시 뜬다.
- 모든 동작은 **누르는 그 자리에서** 일어난다(「저장」이 없다). 주소도 그때 설정 파일에 적는다.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from chaeksas.studio.center_enroll import Outcome, StudioEnrollment, waiting_text
from chaeksas.studio.credentials import StudioCredentials
from chaeksas.studio.settings import Settings

TITLE = "Center에 연결"
WIDTH, HEIGHT = 480, 260
POLL_MS = 10_000
CLOSE_AFTER_MS = 2_000
NO_ADDRESS = "Center 주소를 넣으세요"
#: 아무 요청도 없을 때 (처음 켰을 때).
FIRST = "Center 주소를 넣고 「보내기」를 누르면 등록 요청을 보냅니다. 관리자가 요청 코드를 승인하면 들어옵니다."
#: 「다시 요청」을 보일 상태 — 거절·만료·키 거부.
_AGAIN_STATES = ("rejected", "expired")


class CenterConnectDialog(QDialog):
    """STU-16. 닫힌 뒤 `connected`가 참이면 키를 받은 것이고, `settings`는 적은 뒤의 설정이다."""

    def __init__(
        self,
        settings: Settings,
        *,
        credentials: StudioCredentials | None = None,
        client: Any = None,
        refused: bool = False,
        send_now: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.credentials = credentials or StudioCredentials()
        self.client = client
        self.connected = False
        #: 키가 거부되어 뜬 것이면 「다시 요청」을 보인다 (STU-16 표).
        self.refused = refused
        self.setWindowTitle(TITLE)
        self.setModal(True)
        self.resize(WIDTH, HEIGHT)

        self.title = QLabel(TITLE)
        self.title.setProperty("role", "h2")
        self.address = QLineEdit(settings.center_url)
        self.address.setPlaceholderText("http://center.example.com:8800")
        self.address.textChanged.connect(lambda _text: self._show())
        self.send = QPushButton("보내기")
        self.send.clicked.connect(self.send_request)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.code = QLabel("")
        self.code.setProperty("role", "h2")
        self.code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.copy = QPushButton("복사")
        self.copy.clicked.connect(self._copy)
        self.later = QPushButton("나중에")
        self.later.clicked.connect(self.reject)
        self.again = QPushButton("다시 요청")
        self.again.clicked.connect(self.ask_again)

        address_row = QHBoxLayout()
        address_row.addWidget(self.address, 1)
        address_row.addWidget(self.send)
        code_row = QHBoxLayout()
        code_row.addWidget(self.code)
        code_row.addWidget(self.copy)
        code_row.addStretch(1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.later)
        buttons.addWidget(self.again)
        layout = QVBoxLayout(self)
        layout.addWidget(self.title)
        layout.addLayout(address_row)
        layout.addWidget(self.status)
        layout.addLayout(code_row)
        layout.addStretch(1)
        layout.addLayout(buttons)

        self.timer = QTimer(self)
        self.timer.setInterval(POLL_MS)
        self.timer.timeout.connect(self.poll)

        current = self._enrollment().current()
        if refused:
            first = "키가 거부되었습니다 — 「다시 요청」으로 새로 승인받으세요"
        elif current is not None:
            first = waiting_text(current)
        else:
            first = FIRST
        self._show(first)
        if send_now:
            self.send_request()
        elif current is not None and current.state == "pending":
            # 기다리던 요청이 있다 — 그사이 승인됐을 수 있으니 한 번 묻고 주기를 켠다.
            self.poll()

    # ── 상태 ──

    def _enrollment(self) -> StudioEnrollment:
        return StudioEnrollment(
            base_url=self.address.text().strip(),
            data_dir=self.settings.data_dir,
            credentials=self.credentials,
            client=self.client,
        )

    def _show(self, text: str | None = None) -> None:
        if text is not None:
            self.status.setText(text)
        current = None if self.connected else self._enrollment().current()
        waiting = current is not None and current.state == "pending"
        has_address = bool(self.address.text().strip())
        self.send.setVisible(not self.connected and current is None and not self.refused)
        self.send.setEnabled(has_address)
        if not has_address and current is None and not self.connected:
            self.status.setText(NO_ADDRESS)
        self.code.setText(current.code if waiting and current is not None else "")
        self.code.setVisible(waiting)
        self.copy.setVisible(waiting)
        closed = current is not None and current.state in _AGAIN_STATES
        self.again.setVisible(not self.connected and (closed or self.refused))
        if waiting:
            self.timer.start()
        else:
            self.timer.stop()

    def _remember(self, outcome: Outcome) -> None:
        """주소는 **그 자리에서** 적는다. 키를 받았으면 이름·만료도 (비밀이 아니다)."""
        made = replace(
            self.settings,
            center_url=self.address.text().strip() or self.settings.center_url,
            center_key_name=outcome.key_name if outcome.got_key else self.settings.center_key_name,
            center_key_expires=outcome.expires_at if outcome.got_key else self.settings.center_key_expires,
        )
        made.save()
        self.settings = made

    def _take(self, outcome: Outcome) -> None:
        self._remember(outcome)
        if outcome.got_key:
            self.connected = True
            self.refused = False
            self._show(outcome.text)
            # 「연결됨」을 잠깐 보이고 닫는다 (STU-16).
            QTimer.singleShot(CLOSE_AFTER_MS, self.accept)
            return
        self._show(outcome.text)

    # ── 단추 ──

    def send_request(self) -> None:
        self._take(self._enrollment().request())

    def poll(self) -> None:
        self._take(self._enrollment().step())

    def ask_again(self) -> None:
        """「다시 요청」 — 들고 있던 키(거부)와 요청(거절·만료)을 버리고 새로 요청한다."""
        self.refused = False
        self._take(self._enrollment().again())

    def _copy(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self.code.text())

    def done(self, result: int) -> None:
        self.timer.stop()
        super().done(result)


__all__ = ["FIRST", "NO_ADDRESS", "TITLE", "CenterConnectDialog"]
