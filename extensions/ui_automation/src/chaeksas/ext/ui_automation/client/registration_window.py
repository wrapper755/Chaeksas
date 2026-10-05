"""BUI-06 「UI 셀렉터 등록」 — 담기·검증 (C10 §5).

Bot UI의 「도구」에서 열리는 유틸리티 창이다. 화면을 열고, 분석해 요소를 표에 담고, 시맨틱
키를 고치고, 사다리를 **지금 열린 화면에서** 검증한다.

지키는 것 다섯.

- **안내 줄 하나로만 말한다** ([H]) — 진행·결과·오류가 다른 데로 새지 않는다.
- **범위가 아무것도 못 찾으면 전체로 몰래 넓히지 않는다** (2번). 사람이 범위를 잘못 적은
  것을 알아야 한다.
- **잘렸으면 잘렸다고 말한다** (2번) — 조용히 자르면 없는 것을 없다고 단정한다.
- **검증을 마쳐야 등록이 켜진다**. 그 뒤 표를 바꾸면 다시 꺼진다 (단추 켜짐 규칙).
- 검증 결과는 **막지 않는다** (7번) — 사람이 보고 정한다.

> 상태: 「직접 고르기」·「등록」·BUI-07·BUI-08은 다음 조각이다. 지금은 꺼 두고 왜 꺼졌는지
> 툴팁으로 말한다 — **없는 것을 되는 척하지 않는다.**
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from chaeksas.ext.ui_automation.contracts.plan import LocatorSpec
from chaeksas.ext.ui_automation.contracts.registration import (
    DEFAULT_MAX,
    MAX_MAX,
    MIN_MAX,
    AnalyzeRequest,
    Candidate,
    VerifyResult,
    ladder_for,
)
from chaeksas.ext.ui_automation.contracts.worker_local import DEFAULT_PORT

log = logging.getLogger(__name__)

#: 요소 표의 열 (BUI-06 [E]). 「CSS 후보」는 **등록 화면에서만** 보이는 물리 정보다 (C10 §5).
ELEMENT_COLUMNS = ("쓸 것", "시맨틱 키", "종류", "가능한 동작", "태그", "역할", "접근성 이름", "id", "CSS 후보")
#: 검증 표의 열 (BUI-06 [V]).
CHECK_COLUMNS = ("시맨틱 키", "순위", "전략", "셀렉터", "결과", "사유")

KIND_LABEL = {"control": "조작", "list": "목록", "table": "표", "text": "글자"}

#: 분석 「최대」 칸의 눈금 (BUI-06 — 10~2000, 50 단위).
MAX_STEP = 50

#: 호스트가 채워 주는 예약 설정 키 (C13).
PORT_SETTING = "runtime.worker.port"
TOKEN_DIR_SETTING = "runtime.worker.token_dir"


@dataclass
class Row:
    """표 한 줄 — 담은 요소 하나와 사람이 고친 키."""

    candidate: Candidate
    key: str
    use: bool = True

    def ladder(self) -> list[LocatorSpec]:
        return ladder_for(self.candidate)


@dataclass
class Session:
    """열린 등록 세션. **비밀은 연 쪽만 안다** (C10)."""

    session_id: str
    secret: str
    url: str = ""


class RegistrationWidget(QWidget):
    """BUI-06의 화면. Worker를 부르는 길은 `client`(C10) 하나뿐이다."""

    def __init__(self, client: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._client = client
        self._session: Session | None = None
        self._rows: list[Row] = []
        self._verified: VerifyResult | None = None
        self._filling = False

        layout = QVBoxLayout(self)
        layout.addWidget(self._page_row())
        layout.addWidget(self._collector())
        self.hint = QLabel("브라우저를 열고 등록할 화면으로 이동한 뒤 「분석」을 누르세요.")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        layout.addWidget(self._elements(), 3)
        layout.addWidget(self._checks(), 2)
        layout.addLayout(self._footer())
        self._sync()

    # ── 만들기 ──

    def _page_row(self) -> QWidget:
        box = QGroupBox("화면")
        row = QHBoxLayout(box)
        self.page_id = QComboBox()
        self.page_id.setEditable(True)
        self.page_id.setMinimumWidth(280)
        editor = self.page_id.lineEdit()
        if editor is not None:
            editor.setPlaceholderText("화면 ID (예: erp.order.form)")
        row.addWidget(self.page_id)
        self.page_state = QLabel("아직 조회하지 않았습니다 — 등록은 다음 조각입니다.")
        self.page_state.setEnabled(False)
        row.addWidget(self.page_state, 1)
        return box

    def _collector(self) -> QWidget:
        box = QGroupBox("브라우저에서 담기")
        outer = QVBoxLayout(box)

        first = QHBoxLayout()
        self.start_url = QLineEdit()
        self.start_url.setPlaceholderText("시작 주소 (예: https://erp.example/orders)")
        self.open_button = QPushButton("브라우저 열기")
        self.open_button.clicked.connect(self.open_browser)
        self.pick_button = QPushButton("직접 고르기")
        self.pick_button.setEnabled(False)
        self.pick_button.setToolTip("직접 고르기는 다음 조각입니다 (C10 §5 `pick`).")
        self.analyze_button = QPushButton("분석")
        self.analyze_button.clicked.connect(self.analyze)
        self.close_button = QPushButton("브라우저 닫기")
        self.close_button.clicked.connect(self.close_browser)
        first.addWidget(self.start_url, 1)
        for one in (self.open_button, self.pick_button, self.analyze_button, self.close_button):
            first.addWidget(one)
        outer.addLayout(first)

        second = QHBoxLayout()
        self.scope = QLineEdit()
        self.scope.setPlaceholderText("분석 범위 (CSS, 비우면 전체)")
        self.max_count = QSpinBox()
        self.max_count.setRange(MIN_MAX, MAX_MAX)
        self.max_count.setSingleStep(MAX_STEP)
        self.max_count.setValue(DEFAULT_MAX)
        self.include_read = QCheckBox("읽기 대상 포함")
        second.addWidget(self.scope, 1)
        second.addWidget(QLabel("최대"))
        second.addWidget(self.max_count)
        second.addWidget(self.include_read)
        outer.addLayout(second)
        return box

    def _elements(self) -> QWidget:
        box = QGroupBox("요소")
        layout = QVBoxLayout(box)
        self.elements = QTableWidget(0, len(ELEMENT_COLUMNS))
        self.elements.setHorizontalHeaderLabels(list(ELEMENT_COLUMNS))
        self.elements.verticalHeader().setVisible(False)
        self.elements.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.elements.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.elements.itemChanged.connect(self._element_edited)
        layout.addWidget(self.elements)

        row = QHBoxLayout()
        self.delete_selected = QPushButton("선택 삭제")
        self.delete_selected.clicked.connect(self.remove_selected)
        self.delete_all = QPushButton("전체 삭제")
        self.delete_all.clicked.connect(self.remove_all)
        row.addStretch(1)
        row.addWidget(self.delete_selected)
        row.addWidget(self.delete_all)
        layout.addLayout(row)
        return box

    def _checks(self) -> QWidget:
        box = QGroupBox("검증")
        layout = QVBoxLayout(box)
        self.checks = QTableWidget(0, len(CHECK_COLUMNS))
        self.checks.setHorizontalHeaderLabels(list(CHECK_COLUMNS))
        self.checks.verticalHeader().setVisible(False)
        self.checks.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.checks.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.checks)
        self.verify_button = QPushButton("검증")
        self.verify_button.clicked.connect(self.verify)
        layout.addWidget(self.verify_button, alignment=Qt.AlignmentFlag.AlignRight)
        return box

    def _footer(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.reset_button = QPushButton("초기화")
        self.reset_button.clicked.connect(self.reset)
        self.register_button = QPushButton("등록")
        self.register_button.setEnabled(False)
        self.register_button.setToolTip("레지스트리에 올리는 것(C9)은 다음 조각입니다.")
        row.addWidget(self.reset_button)
        row.addStretch(1)
        row.addWidget(self.register_button)
        return row

    # ── 동작 ──

    def say(self, message: str) -> None:
        """안내 줄 [H] — **진행·결과·오류의 유일한 통로**다."""
        self.hint.setText(message)

    def open_browser(self) -> None:
        if self._session is not None:
            self._goto()
            return
        self.say("브라우저를 띄우는 중…")
        try:
            info = self._client.open_registration(self.start_url.text().strip())
        except Exception as e:  # noqa: BLE001 — Worker가 거절할 수 있다 (사용 중·브라우저 없음)
            self.say(self._why(e))
            return
        self._session = Session(
            session_id=info.session_id, secret=info.session_secret, url=info.current_url or ""
        )
        self.say(
            f"열렸습니다 — {self._session.url or '빈 화면'}. 등록할 화면까지 브라우저에서 직접 "
            f"이동한 뒤 「분석」을 누르세요."
        )
        self._sync()

    def _goto(self) -> None:
        found = self._session
        if found is None:
            return
        url = self.start_url.text().strip()
        if not url:
            self.say("이동할 주소를 적으세요.")
            return
        try:
            info = self._client.call(
                "POST", f"/v1/sessions/{found.session_id}/goto", body={"url": url}, secret=found.secret
            )
        except Exception as e:  # noqa: BLE001
            self.say(self._why(e))
            return
        found.url = str(info.get("current_url") or url)
        self.say(f"이동했습니다 — {found.url}")

    def analyze(self) -> None:
        found = self._session
        if found is None:
            return
        self.say("화면을 분석하는 중…")
        request = AnalyzeRequest(
            schema=1,
            scope_css=self.scope.text().strip() or None,
            max=self.max_count.value(),
            include_read=self.include_read.isChecked(),
        )
        try:
            result = self._client.analyze(found.session_id, found.secret, request)
        except Exception as e:  # noqa: BLE001
            self.say(self._why(e))
            return

        if result.scope_empty:
            # **전체로 몰래 넓히지 않는다** — 범위를 잘못 적은 것을 알아야 한다 (2번).
            self.say(f"범위 선택자가 아무것도 찾지 못했습니다 — {request.scope_css}")
            return
        self._rows = [Row(candidate=one, key=one.suggested_key) for one in result.candidates]
        self._verified = None
        self._fill_elements()
        said = f"{result.total}개를 찾았습니다."
        if result.truncated:
            said = (
                f"{result.total}개 중 {len(result.candidates)}개만 가져왔습니다. "
                f"범위를 좁히거나 최대치를 올리세요."
            )
        self.say(said)
        self._sync()

    def verify(self) -> None:
        """BUI-06 7번. **하나에 맞아야** 통과다 — 결과가 등록을 막지는 않는다."""
        found = self._session
        if found is None:
            return
        ladders = {row.key: row.ladder() for row in self._rows if row.use and row.key}
        if not ladders:
            self.say("쓸 요소를 고르세요 (「쓸 것」을 켜고 시맨틱 키를 채우세요).")
            return
        if len(ladders) != len([row for row in self._rows if row.use and row.key]):
            self.say("시맨틱 키가 겹칩니다 — 같은 키를 두 요소가 쓸 수 없습니다.")
            return
        self.say("지금 열린 화면에서 사다리를 시험하는 중…")
        try:
            result = self._client.verify(found.session_id, found.secret, ladders)
        except Exception as e:  # noqa: BLE001
            self.say(self._why(e))
            return
        self._verified = result
        self._fill_checks(result)
        self.say(summary_of(result))
        self._sync()

    def close_browser(self) -> None:
        found = self._session
        if found is None:
            return
        try:
            self._client.close(found.session_id, found.secret)
        except Exception as e:  # noqa: BLE001 — 이미 닫혔을 수 있다. 화면은 놓아 준다
            log.debug("세션을 닫지 못했다: %s", e)
        self._session = None
        self.say("브라우저를 닫았습니다. 담아 둔 요소는 그대로입니다.")
        self._sync()

    def remove_selected(self) -> None:
        rows = sorted({index.row() for index in self.elements.selectedIndexes()}, reverse=True)
        for row in rows:
            if 0 <= row < len(self._rows):
                del self._rows[row]
        self._verified = None
        self._fill_elements()
        self._sync()

    def remove_all(self) -> None:
        self._rows = []
        self._verified = None
        self._fill_elements()
        self._sync()

    def reset(self) -> None:
        """BUI-06 「초기화」 — 표·검증·화면 ID를 비운다. **브라우저는 유지한다.**"""
        self._rows = []
        self._verified = None
        self.page_id.setCurrentText("")
        self._fill_elements()
        self._fill_checks(VerifyResult())
        self.say("비웠습니다. 브라우저는 열어 두었습니다.")
        self._sync()

    def release(self) -> None:
        """창을 닫을 때 — **UI 세션을 놓는다** (한 번에 하나다, ADR-0014)."""
        self.close_browser()

    # ── 그리기 ──

    def _fill_elements(self) -> None:
        self._filling = True
        try:
            self.elements.setRowCount(len(self._rows))
            for index, row in enumerate(self._rows):
                one = row.candidate
                check = QTableWidgetItem()
                check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                check.setCheckState(Qt.CheckState.Checked if row.use else Qt.CheckState.Unchecked)
                self.elements.setItem(index, 0, check)

                key = QTableWidgetItem(row.key)
                self.elements.setItem(index, 1, key)
                rest = (
                    KIND_LABEL.get(one.kind, one.kind),
                    ", ".join(one.actions),
                    one.tag,
                    one.role,
                    one.name,
                    one.element_id,
                    " · ".join(one.css),
                )
                for column, text in enumerate(rest, start=2):
                    cell = QTableWidgetItem(text)
                    cell.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                    self.elements.setItem(index, column, cell)
        finally:
            self._filling = False
        self._mark_duplicates()

    def _element_edited(self, item: QTableWidgetItem) -> None:
        if self._filling or not (0 <= item.row() < len(self._rows)):
            return
        row = self._rows[item.row()]
        if item.column() == 0:
            row.use = item.checkState() == Qt.CheckState.Checked
        elif item.column() == 1:
            row.key = item.text().strip()
            # 키를 고치면 자동 체크, 지우면 체크 해제 (BUI-06 4번).
            row.use = bool(row.key)
            self._filling = True
            box = self.elements.item(item.row(), 0)
            if box is not None:
                box.setCheckState(Qt.CheckState.Checked if row.use else Qt.CheckState.Unchecked)
            self._filling = False
        # 표를 바꾸면 검증을 다시 해야 한다 (단추 켜짐 규칙).
        self._verified = None
        self._mark_duplicates()
        self._sync()

    def _mark_duplicates(self) -> None:
        """키가 겹치면 빨간 바탕 (BUI-06 [E]) — 겹친 채로 등록하면 하나가 사라진다."""
        from PySide6.QtGui import QBrush, QColor  # noqa: PLC0415 — 그릴 때만 든다

        counts: dict[str, int] = {}
        for row in self._rows:
            if row.use and row.key:
                counts[row.key] = counts.get(row.key, 0) + 1
        for index, row in enumerate(self._rows):
            cell = self.elements.item(index, 1)
            if cell is None:
                continue
            clash = row.use and row.key and counts.get(row.key, 0) > 1
            cell.setBackground(QBrush(QColor("#f8d7da")) if clash else QBrush())

    def _fill_checks(self, result: VerifyResult) -> None:
        self.checks.setRowCount(len(result.rows))
        for index, row in enumerate(result.rows):
            cells = (
                row.semantic_key,
                str(row.rank + 1),
                row.strategy,
                row.selector,
                "통과" if row.passed else "실패",
                row.reason,
            )
            for column, text in enumerate(cells):
                self.checks.setItem(index, column, QTableWidgetItem(text))

    def _sync(self) -> None:
        """단추 켜짐 규칙 (BUI-06)."""
        open_now = self._session is not None
        self.open_button.setText("주소로 이동" if open_now else "브라우저 열기")
        self.analyze_button.setEnabled(open_now)
        self.close_button.setEnabled(open_now)
        has_rows = bool(self._rows)
        self.delete_selected.setEnabled(has_rows)
        self.delete_all.setEnabled(has_rows)
        self.verify_button.setEnabled(open_now and has_rows)
        if not open_now:
            self.verify_button.setToolTip("검증은 지금 열린 화면에서 합니다 — 브라우저를 여세요.")
        else:
            self.verify_button.setToolTip("" if has_rows else "담은 요소가 없습니다.")

    def _why(self, error: Exception) -> str:
        """오류를 사람 말로. **무엇을 해야 하는지**까지 적는다."""
        text = str(error)
        if "worker_busy" in text or "사용 중" in text:
            return f"Worker가 사용 중입니다 — {text}"
        if "browser_unavailable" in text:
            return (
                "화면을 조작할 수단이 없습니다 — 이 PC에 브라우저 자동화가 설치되지 않았습니다 "
                "(Playwright)."
            )
        return text


def summary_of(result: VerifyResult) -> str:
    """BUI-06 7번의 요약. Worker의 `summarize()`와 **같은 말**을 쓴다."""
    from chaeksas.ext.ui_automation.worker.registration import summarize  # noqa: PLC0415

    return summarize(result)


@dataclass
class Opened:
    """유틸리티가 들고 있는 것 — 창 하나와 그 창이 쓰는 Worker 클라이언트."""

    widget: RegistrationWidget
    client: Any = field(default=None)


def worker_client(settings: Any) -> Any:
    """호스트가 채운 **예약 설정 키**로 Worker를 찾는다 (C13).

    포트를 다시 계산하거나 토큰 파일 자리를 추측하지 않는다 — 호스트가 띄운 그것을 쓴다.
    """
    from chaeksas.ext.ui_automation.client.task import WorkerClient  # noqa: PLC0415

    where = settings.get(TOKEN_DIR_SETTING)
    port = int(settings.get(PORT_SETTING) or DEFAULT_PORT)
    return WorkerClient(token_dir=Path(where) if where else Path.cwd(), port=port)


__all__ = [
    "CHECK_COLUMNS",
    "ELEMENT_COLUMNS",
    "KIND_LABEL",
    "PORT_SETTING",
    "TOKEN_DIR_SETTING",
    "RegistrationWidget",
    "Row",
    "Session",
    "summary_of",
    "worker_client",
]
