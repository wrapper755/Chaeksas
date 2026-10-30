"""TOL-03 「UI 셀렉터 등록」 — 담기·검증 (C10 §5).

Tool UI의 도구 「UI 셀렉터 등록」 안 「등록」 탭이다 (ADR-0077). 화면을 열고, 분석해 요소를 표에 담고, 시맨틱
키를 고치고, 사다리를 **지금 열린 화면에서** 검증한다.

지키는 것 다섯.

- **안내 줄 하나로만 말한다** ([H]) — 진행·결과·오류가 다른 데로 새지 않는다.
- **범위가 아무것도 못 찾으면 전체로 몰래 넓히지 않는다** (2번). 사람이 범위를 잘못 적은
  것을 알아야 한다.
- **잘렸으면 잘렸다고 말한다** (2번) — 조용히 자르면 없는 것을 없다고 단정한다.
- **검증을 마쳐야 등록이 켜진다**. 그 뒤 표를 바꾸면 다시 꺼진다 (단추 켜짐 규칙).
- 검증 결과는 **막지 않는다** (7번) — 사람이 보고 정한다.

데스크톱 창에서도 담는다 (「방식」 콤보) — 창에 **붙기만** 하고 띄우거나 닫지 않는다 (사용자의
업무 앱이다). 「직접 고르기」·「표시」는 브라우저만 한다.

> 상태: 「직접 고르기」·「등록」·TOL-04·TOL-05은 다음 조각이다. 지금은 꺼 두고 왜 꺼졌는지
> 툴팁으로 말한다 — **없는 것을 되는 척하지 않는다.**
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPalette
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
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from chaeksas.ext.ui_automation.contracts.plan import DESKTOP, LocatorSpec, WindowSpec
from chaeksas.ext.ui_automation.contracts.registration import (
    DEFAULT_MAX,
    KEY_SAFE,
    MAX_MAX,
    MIN_MAX,
    AnalyzeRequest,
    Candidate,
    VerifyResult,
    ladder_for,
    suggest_key,
)
from chaeksas.ext.ui_automation.contracts.registry import (
    WEB,
    CatalogEntry,
    ElementHint,
    PageRegistration,
)
from chaeksas.ext.ui_automation.contracts.worker_local import DEFAULT_PORT

log = logging.getLogger(__name__)

#: 요소 표의 열 (TOL-03 [E]). 「CSS 후보」는 **등록 화면에서만** 보이는 물리 정보다 (C10 §5).
ELEMENT_COLUMNS = (
    "쓸 것", "시맨틱 키", "종류", "가능한 동작", "계획 정보",
    "태그", "역할", "접근성 이름", "id", "CSS 후보",
)
#: 검증 표의 열 (TOL-03 [V]).
CHECK_COLUMNS = ("시맨틱 키", "순위", "전략", "셀렉터", "결과", "사유")

KIND_LABEL = {"control": "조작", "list": "목록", "table": "표", "text": "글자"}

#: 분석 「최대」 칸의 눈금 (TOL-03 — 10~2000, 50 단위).
MAX_STEP = 50

#: 고른 것을 받아 오는 주기 (ms). **밀려 있는 것을 비워 가져온다** — 하나씩 기다리지 않는다.
PICK_POLL_MS = 400

#: 호스트가 채워 주는 예약 설정 키 (C13).
PORT_SETTING = "runtime.worker.port"
TOKEN_DIR_SETTING = "runtime.worker.token_dir"


#: 레지스트리를 부를 수 없을 때의 한 줄. **왜 안 되는지와 어디서 고치는지**를 적는다.
NO_REGISTRY = (
    "이 PC는 셀렉터 등록이 허락되지 않았습니다 — 관리자에게 Center 콘솔 「PC 실행기 현황」에서 "
    "이 PC의 「셀렉터 등록」을 켜 달라고 하세요."
)

#: 「방식」 콤보 (TOL-03 [C]).
MODE_BROWSER = "브라우저"
MODE_DESKTOP = "데스크톱 창"
#: 데스크톱 「직접 고르기」의 안내 — 누르지 않고 **올려 두고 Ctrl**이다 (ADR-0072, 입력을 가로채지 않는다).
DESKTOP_PICKING = "고르는 중… 담을 요소 위에 마우스를 올리고 Ctrl을 누르세요 (Esc로 끝)."
#: 데스크톱 「표시」 테두리가 떠 있는 시간 (ms).
FLASH_MS = 1500

#: `page_id`에 남기는 글자 (C9와 같은 모양 — 영소문자·숫자·`_`·`.`).
KEY_SAFE_DOT = re.compile(r"[^a-z0-9_.]+")


@dataclass
class Row:
    """표 한 줄 — 담은 요소 하나와 사람이 고친 키."""

    candidate: Candidate
    key: str
    use: bool = True
    #: TOL-04 — 이 요소를 조작하기 전에 채워야 하는 요소들.
    depends_on: list[str] = field(default_factory=list)
    #: TOL-04 — 이 요소를 가리키는 업무 용어 (자연어 목표 계획이 쓴다).
    concepts: list[str] = field(default_factory=list)
    #: 서버에서 불러온 줄이면 그때의 사다리 (다시 등록해도 정의가 바뀌지 않게, TOL-03 9번).
    loaded: list[LocatorSpec] | None = None

    def ladder(self) -> list[LocatorSpec]:
        return self.loaded if self.loaded is not None else ladder_for(self.candidate)


@dataclass
class Session:
    """열린 등록 세션. **비밀은 연 쪽만 안다** (C10)."""

    session_id: str
    secret: str
    url: str = ""
    #: 데스크톱이면 붙은 창 — `{title, process}` (등록의 창 조건이 된다, C9).
    window: dict[str, str] | None = None


class RegistrationWidget(QWidget):
    """TOL-03의 화면. Worker를 부르는 길은 `client`(C10) 하나뿐이다."""

    def __init__(
        self,
        client: Any,
        registry: Any = None,
        pending: Any = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        #: 밀린 등록 (TOL-03 8번). 없으면 쌓지 않고 「다시 누르세요」로 말한다.
        self._pending = pending
        #: 레지스트리를 부르는 쪽 (C9). **없으면 등록할 수 없다** — 설정이 비었다는 뜻이다.
        self._registry = registry
        #: 마지막으로 조회한 화면 (`None`이면 아직 모른다).
        self._known: PageRegistration | None = None
        self._looked_up = ""
        self._session: Session | None = None
        self._rows: list[Row] = []
        self._verified: VerifyResult | None = None
        self._filling = False
        #: 데스크톱 「표시」 테두리 창 (잠깐 떠 있다 — ADR-0072).
        self._overlay: QWidget | None = None
        #: 고른 것을 받아 오는 타이머 (TOL-03 3번). **스레드를 만들지 않는다.**
        self._picking = QTimer(self)
        self._picking.setInterval(PICK_POLL_MS)
        self._picking.timeout.connect(self._collect_picked)

        layout = QVBoxLayout(self)
        layout.addWidget(self._page_row())
        layout.addWidget(self._collector())
        self.hint = QLabel("브라우저를 열고 등록할 화면으로 이동한 뒤 「분석」을 누르세요.")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        layout.addWidget(self._elements(), 3)
        layout.addWidget(self._checks(), 2)
        layout.addLayout(self._footer())
        self.flush()
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
        if editor is not None:
            editor.editingFinished.connect(self.look_up)
        row.addWidget(self.page_id)

        self.load_button = QPushButton("불러오기")
        self.load_button.clicked.connect(self.load_page)
        row.addWidget(self.load_button)

        self.page_state = QLabel("화면 ID를 적으면 조회합니다.")
        self.page_state.setWordWrap(True)
        row.addWidget(self.page_state, 1)

        self.drop_element = QPushButton("요소 등록 취소...")
        self.drop_element.clicked.connect(lambda: self.unregister(element=True))
        self.drop_page = QPushButton("화면 등록 취소...")
        self.drop_page.clicked.connect(lambda: self.unregister(element=False))
        row.addWidget(self.drop_element)
        row.addWidget(self.drop_page)
        return box

    def _collector(self) -> QWidget:
        box = QGroupBox("화면에서 담기")
        outer = QVBoxLayout(box)

        self.mode = QComboBox()
        self.mode.addItems([MODE_BROWSER, MODE_DESKTOP])
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.browser_row = QWidget()
        first = QHBoxLayout(self.browser_row)
        first.setContentsMargins(0, 0, 0, 0)
        self.start_url = QLineEdit()
        self.start_url.setPlaceholderText("시작 주소 (예: https://erp.example/orders)")
        self.open_button = QPushButton("브라우저 열기")
        self.open_button.clicked.connect(self.open_browser)
        self.pick_button = QPushButton("직접 고르기")
        self.pick_button.setCheckable(True)
        self.pick_button.clicked.connect(self.toggle_pick)
        self.analyze_button = QPushButton("분석")
        self.analyze_button.clicked.connect(self.analyze)
        self.close_button = QPushButton("브라우저 닫기")
        self.close_button.clicked.connect(self.close_browser)
        first.addWidget(self.start_url, 1)
        for one in (self.open_button, self.pick_button, self.analyze_button, self.close_button):
            first.addWidget(one)

        self.desktop_row = QWidget()
        desk = QHBoxLayout(self.desktop_row)
        desk.setContentsMargins(0, 0, 0, 0)
        self.window_pick = QComboBox()
        self.window_pick.setMinimumWidth(280)
        self.refresh_windows_button = QPushButton("새로 고침")
        self.refresh_windows_button.clicked.connect(self.refresh_windows)
        self.attach_button = QPushButton("창에 붙기")
        self.attach_button.clicked.connect(self.attach_window)
        self.desktop_pick_button = QPushButton("직접 고르기")
        self.desktop_pick_button.setCheckable(True)
        self.desktop_pick_button.clicked.connect(self._desktop_pick_clicked)
        self.desktop_analyze_button = QPushButton("분석")
        self.desktop_analyze_button.clicked.connect(self.analyze)
        self.release_button = QPushButton("놓기")
        self.release_button.clicked.connect(self.close_browser)
        desk.addWidget(self.window_pick, 1)
        for one in (
            self.refresh_windows_button,
            self.attach_button,
            self.desktop_pick_button,
            self.desktop_analyze_button,
            self.release_button,
        ):
            desk.addWidget(one)
        self.desktop_row.setVisible(False)

        top = QHBoxLayout()
        top.addWidget(self.mode)
        top.addWidget(self.browser_row, 1)
        top.addWidget(self.desktop_row, 1)
        outer.addLayout(top)

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
        self.elements.itemDoubleClicked.connect(lambda item: self.open_hints(item.row()))
        self.elements.itemSelectionChanged.connect(self._selection_changed)
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
        #: TOL-03 「시험...」 — 「시험」 탭으로 간다. 받는 쪽은 도구(`utility.py`)다 (`on_try(page_id, keys)`).
        self.try_button = QPushButton("시험...")
        self.try_button.clicked.connect(self.try_selected)
        self.on_try: Any = None
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.try_button)
        row.addWidget(self.verify_button)
        layout.addLayout(row)
        return box

    def _footer(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.reset_button = QPushButton("초기화")
        self.reset_button.clicked.connect(self.reset)
        self.register_button = QPushButton("등록")
        self.register_button.clicked.connect(self.register)
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

    # ── 데스크톱 창 (TOL-03 1-1번) ──

    def desktop(self) -> bool:
        return self.mode.currentText() == MODE_DESKTOP

    def _mode_changed(self) -> None:
        desktop = self.desktop()
        self.browser_row.setVisible(not desktop)
        self.desktop_row.setVisible(desktop)
        if desktop:
            self.say("등록할 화면을 띄운 창을 고르고 「창에 붙기」를 누르세요.")
            if not self.window_pick.count():
                self.refresh_windows()
        else:
            self.say("브라우저를 열고 등록할 화면으로 이동한 뒤 「분석」을 누르세요.")
        self._sync()

    def _desktop_pick_clicked(self) -> None:
        """데스크톱 줄의 「직접 고르기」 — 고르는 길은 **브라우저와 하나**다 (`toggle_pick`)."""
        self.pick_button.setChecked(self.desktop_pick_button.isChecked())
        self.toggle_pick()

    def refresh_windows(self) -> None:
        """지금 떠 있는 창을 콤보에 채운다 — `제목 — 프로세스`."""
        try:
            found = self._client.registration_windows()
        except Exception as e:  # noqa: BLE001 — UIA가 없는 PC일 수 있다
            self.say(self._why(e))
            return
        self.window_pick.clear()
        for one in found:
            label = f"{one['title']} — {one['process']}" if one.get("process") else one["title"]
            self.window_pick.addItem(label, one)
        self.say(f"창 {len(found)}개를 찾았습니다." if found else "붙을 창이 없습니다 — 등록할 앱을 띄우세요.")
        self._sync()

    def attach_window(self) -> None:
        """고른 창에 붙는다. **창을 띄우지도 닫지도 않는다** — 사용자의 업무 앱이다."""
        chosen = self.window_pick.currentData()
        if self._session is not None or not isinstance(chosen, dict):
            return
        window = {"title": "^" + re.escape(chosen["title"]) + "$"}
        if chosen.get("process"):
            window["process"] = chosen["process"]
        try:
            info = self._client.open_registration_desktop(window)
        except Exception as e:  # noqa: BLE001
            code = getattr(e, "code", "")
            if code == "window_ambiguous":
                self.say("같은 조건의 창이 여럿입니다 — 하나만 남기세요.")
            elif code == "app_not_running":
                self.say("그 창이 없습니다 — 「새로 고침」으로 다시 고르세요.")
            else:
                self.say(self._why(e))
            return
        self._session = Session(
            session_id=info.session_id, secret=info.session_secret, window=window
        )
        self.say(f"붙었습니다 — {chosen['title']}. 등록할 화면을 띄워 둔 채 「분석」을 누르세요.")
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
            scope_css=None if found.window is not None else (self.scope.text().strip() or None),
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
        if not self.page_id.currentText().strip() and found.window is not None:
            # 창 제목에는 문서 이름이 섞인다 — **지어 채우지 않는다** (TOL-03 1-1번).
            self.say(f"{said} 화면 ID를 적으세요.")
        elif not self.page_id.currentText().strip():
            # 화면 ID가 비어 있으면 주소에서 채운다 (사람이 고친 뒤에는 건드리지 않는다).
            self.page_id.setCurrentText(page_id_from(found.url))
        self.look_up()
        self._sync()

    def verify(self) -> None:
        """TOL-03 7번. **하나에 맞아야** 통과다 — 결과가 등록을 막지는 않는다."""
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

    # ── 직접 고르기 (TOL-03 3번) ──

    def toggle_pick(self) -> None:
        """브라우저에서 사람이 누른 요소를 표에 담는다. 다시 누르거나 Esc로 끝난다."""
        found = self._session
        if found is None:
            self.pick_button.setChecked(False)
            return
        on = self.pick_button.isChecked()
        try:
            self._client.pick(found.session_id, found.secret, on=on)
        except Exception as e:  # noqa: BLE001
            self.pick_button.setChecked(False)
            self._picking.stop()
            self.say(self._why(e))
            return
        if on:
            self._picking.start()
            if found.window is not None:
                self.say(DESKTOP_PICKING)
            else:
                self.say("고르는 중… 브라우저에서 요소를 누르세요 (Shift+클릭은 둘러싼 표, Esc로 끝).")
        else:
            self._picking.stop()
            self.say(f"고르기를 끝냈습니다 — 담은 요소 {len(self._rows)}개.")
        self._sync()

    def _collect_picked(self) -> None:
        """담긴 것을 **비워** 가져온다 — 한 번 받은 것은 다시 오지 않는다 (C10 §5)."""
        found = self._session
        if found is None:
            self._picking.stop()
            return
        try:
            candidates, picking = self._client.picked(found.session_id, found.secret)
        except Exception as e:  # noqa: BLE001 — 화면이 사라졌을 수 있다
            self._picking.stop()
            self.pick_button.setChecked(False)
            self.say(self._why(e))
            self._sync()
            return

        for one in candidates:
            self._add_picked(one)
        if not picking:
            # 사람이 화면에서 Esc로 끝냈다 — 토글도 내린다.
            self._picking.stop()
            self.pick_button.setChecked(False)
            self.say(f"고르기를 끝냈습니다 — 담은 요소 {len(self._rows)}개.")
            self._sync()

    def _add_picked(self, candidate: Candidate) -> None:
        """고른 것 하나를 표에 더한다. **이미 있으면 더하지 않는다.**"""
        where = _same_as(candidate, self._rows)
        if where is not None:
            self.say(f"이미 표에 있습니다 — {candidate.name or candidate.tag}")
            self.elements.selectRow(where)
            return
        key = suggest_key(candidate, {row.key for row in self._rows if row.key})
        self._rows.append(Row(candidate=candidate, key=key))
        self._verified = None
        self._fill_elements()
        self.elements.selectRow(len(self._rows) - 1)
        self.say(f"골랐습니다 — {candidate.name or candidate.tag} → `{key}`")
        self._sync()

    def show_selected(self) -> None:
        """TOL-03 5번 「표시」 — 고른 줄을 화면에서 파란 테두리로 보인다."""
        found = self._session
        rows = {index.row() for index in self.elements.selectedIndexes()}
        if found is None or len(rows) != 1:
            return
        row = rows.pop()
        if not (0 <= row < len(self._rows)):
            return
        ladder = self._rows[row].ladder()
        if found.window is not None:
            self._show_desktop(found, ladder)
            return
        if not any(one.type == "css" for one in ladder):
            # **못 하는 것을 못 찾았다고 하지 않는다** — 표시는 CSS로만 한다.
            self.say("CSS 후보가 없어 화면에 표시할 수 없습니다.")
            return
        try:
            count = self._client.highlight(found.session_id, found.secret, ladder)
        except Exception as e:  # noqa: BLE001
            self.say(self._why(e))
            return
        if count == 1:
            self.say("화면에 표시했습니다.")
        elif count == 0:
            self.say("화면에서 찾지 못했습니다.")
        else:
            self.say(f"**{count}개가 잡힙니다** — 모호해서 실패합니다.")

    def _show_desktop(self, found: Session, ladder: list[LocatorSpec]) -> None:
        """데스크톱 「표시」 — Worker는 사각형만 주고 **그리는 것은 여기다** (ADR-0072)."""
        try:
            count, rect = self._client.highlight_rect(found.session_id, found.secret, ladder)
        except Exception as e:  # noqa: BLE001
            self.say(self._why(e))
            return
        if count == 1 and rect is not None:
            self._flash(rect)
            self.say("화면에 표시했습니다.")
        elif count == 0:
            self.say("화면에서 찾지 못했습니다.")
        else:
            self.say(f"**{count}개가 잡힙니다** — 모호해서 실패합니다.")

    def _flash(self, rect: list[int]) -> None:
        """그 자리에 잠깐 테두리 창을 띄운다 — **입력은 통과한다**. 색은 테마의 강조색이다."""
        self._overlay = flash_frame(rect, self.palette().color(QPalette.ColorRole.Highlight).name())
        QTimer.singleShot(FLASH_MS, self._overlay.close)

    # ── 레지스트리 (C9) ──

    def flush(self) -> None:
        """밀린 등록을 올려 본다 (창을 열 때·등록·삭제 뒤). **조용히 실패하지 않는다.**"""
        if self._pending is None or self._registry is None or not self._pending.count():
            return
        sent, problems = self._pending.flush(self._registry)
        if sent:
            self.say(f"밀린 등록 {sent}건을 올렸습니다.")
        for one in problems:
            self.say(f"밀린 등록을 올리지 못했습니다 — {one}")
        left = self._pending.count()
        if left:
            self.say(f"아직 {left}건이 남아 있습니다 (서버가 돌아오면 다시 올립니다).")

    def look_up(self, *, force: bool = False) -> None:
        """등록 상태를 조회한다 (TOL-03 [P]).

        **일을 시작할 때만** 묻는다 — 화면 ID 입력이 끝났을 때, 분석·검증·등록·삭제 뒤.
        """
        page_id = self.page_id.currentText().strip()
        if not page_id:
            self._known, self._looked_up = None, ""
            self.page_state.setText("화면 ID를 적으면 조회합니다.")
            self._sync()
            return
        if page_id == self._looked_up and not force:
            return
        if self._registry is None:
            self.page_state.setText(NO_REGISTRY)
            return
        self._looked_up = page_id
        try:
            found, _ = self._registry.get_page(page_id)
        except Exception as e:  # noqa: BLE001 — 없는 화면·닿지 못함을 가려 보여 준다
            self._known = None
            if getattr(e, "code", "") == "not_found":
                self.page_state.setText("**새 화면** — 등록하면 만들어집니다.")
            elif getattr(e, "permanent", False):
                self.page_state.setText(f"조회하지 못했습니다 — {e}")
            else:
                # **모르는 것을 안다고 하지 않는다** (U8).
                self.page_state.setText("서버에 닿지 못해 **기존 여부를 알 수 없습니다**.")
            self._sync()
            return
        self._known = found
        self.page_state.setText(
            f"**기존 화면** — 요소 {len(found.locators)}개가 등록돼 있습니다 (여기에 더합니다)."
        )
        self._sync()

    def load_page(self) -> None:
        """TOL-03 9번 — 등록된 것을 표로 가져온다. **담아 둔 것을 덮는다**."""
        page = self._known
        if page is None:
            return
        if self._rows:
            answer = QMessageBox.question(
                self,
                "불러올까요?",
                f"표에 {len(self._rows)}개 행이 있습니다. {page.page_id}에 등록된 것으로 "
                f"**바꿉니다.** 담아 둔 것은 사라집니다.",
                QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
                QMessageBox.StandardButton.Cancel,  # 기본은 「취소」
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._rows = [
            Row(
                candidate=_candidate_of(key, page),
                key=key,
                loaded=list(ladder),  # 다시 등록해도 **정의가 바뀌지 않는다** (TOL-03 9번)
                depends_on=list(page.catalog[key].depends_on) if key in page.catalog else [],
                concepts=list(page.catalog[key].concepts) if key in page.catalog else [],
            )
            for key, ladder in page.locators.items()
        ]
        self._verified = None
        self._fill_elements()
        self.say(f"{page.page_id}에 등록된 요소 {len(self._rows)}개를 가져왔습니다.")
        self._sync()

    def register(self) -> None:
        """TOL-03 8번 — 레지스트리에 올린다 (C9). **더하기다** (기존 것을 지우지 않는다)."""
        if self._registry is None:
            self.say(NO_REGISTRY)
            return
        page_id = self.page_id.currentText().strip()
        if not page_id:
            self.say("화면 ID를 적으세요.")
            return
        self.say("서버에 등록하는 중…")
        page = self._page(page_id)
        try:
            found = self._registry.register(page)
        except Exception as e:  # noqa: BLE001 — 거부·닿지 못함을 가려 보여 준다
            if not getattr(e, "permanent", False) and self._pending is not None:
                # **사람이 한 일을 네트워크 때문에 잃지 않는다** (TOL-03 8번).
                self._pending.add(page)
                self.say(
                    "서버에 닿지 못해 **등록을 큐에 쌓았습니다.** 서버가 돌아오면 저절로 "
                    f"올라갑니다 (밀린 등록 {self._pending.count()}건)."
                )
                self._sync()
                return
            self.say(self._registry_why(e))
            return
        if found.unchanged:
            self.say("이미 등록된 것과 같습니다.")
        else:
            self.say(
                f"등록했습니다 — {found.page_id} (새 로케이터 {len(found.created)}개, "
                f"그대로 둔 것 {len(found.kept)}개). 새 로케이터는 **검증 전**으로 들어가 "
                f"3회 연속 성공하면 사용 중으로 올라갑니다."
            )
        self.flush()
        self.look_up(force=True)

    def _page(self, page_id: str) -> PageRegistration:
        """표 → 등록 단위 (C9). **고른 줄만** 간다."""
        chosen = [row for row in self._rows if row.use and row.key]
        window = self._session.window if self._session is not None else None
        return PageRegistration(
            schema=1,
            page_id=page_id,
            platform=DESKTOP if window is not None else WEB,
            name=self._known.name if self._known is not None else "",
            url_pattern=self._session.url if self._session is not None and window is None else None,
            window=WindowSpec.model_validate(window) if window is not None else None,
            locators={row.key: row.ladder() for row in chosen},
            elements={
                row.key: ElementHint(
                    name=row.candidate.name, role=row.candidate.role, kind=row.candidate.kind
                )
                for row in chosen
            },
            catalog={
                row.key: CatalogEntry(
                    actions=list(row.candidate.actions),
                    depends_on=list(row.depends_on),
                    concepts=list(row.concepts),
                )
                for row in chosen
            },
        )

    def unregister(self, *, element: bool) -> None:
        """TOL-03 10번 — **되돌릴 수 없다.** 경고 창, 기본 「취소」 (U9)."""
        if self._registry is None:
            self.say(NO_REGISTRY)
            return
        page_id = self.page_id.currentText().strip()
        key = self.selected_key() if element else None
        if not page_id or (element and not key):
            return
        warning = (
            f"{page_id}의 `{key}`를 지웁니다. 그 요소의 사다리와 통계가 사라집니다."
            if element
            else f"{page_id}을 레지스트리에서 통째로 지웁니다. 쌓아 온 통계·승격·치유 이력이 "
            f"함께 사라지고 되돌릴 수 없습니다. 화면이 바뀐 것이라면 지우지 말고 다시 등록하세요."
        )
        if not self._confirm("등록을 취소할까요?", warning):
            return
        self._delete(page_id, key, force=False)

    def _delete(self, page_id: str, key: str | None, *, force: bool) -> None:
        try:
            found = self._registry.delete(page_id, key, force=force)
        except Exception as e:  # noqa: BLE001
            if getattr(e, "code", "") == "has_links" and not force:
                links = ", ".join(
                    f"{one.get('page_id')}·{one.get('semantic_key')}"
                    for one in (getattr(e, "detail", {}) or {}).get("links", [])
                )
                if self._confirm(
                    "그래도 지울까요?",
                    f"다른 화면이 가리키고 있습니다 — {links}. 지우면 그 경로가 끊깁니다.",
                ):
                    self._delete(page_id, key, force=True)
                return
            self.say(self._registry_why(e))
            return
        # **지운 화면을 나중에 되살리지 않는다** — 큐에 남아 있던 등록을 함께 버린다.
        dropped = self._pending.drop(page_id) if self._pending is not None and not key else False
        broken = f" · 끊긴 경로 {len(found.broken_links)}개" if found.broken_links else ""
        self.say(
            f"지웠습니다 — {found.page_id}{'·' + key if key else ''} "
            f"(요소 {found.elements}개, 로케이터 {found.locators}개){broken}."
            + (" 큐에 남아 있던 등록도 함께 버렸습니다." if dropped else "")
        )
        self.look_up(force=True)

    def open_hints(self, row: int) -> None:
        """TOL-04 요소 계획 정보 — 선행 입력·업무 개념."""
        if not (0 <= row < len(self._rows)):
            return
        found = self._rows[row]
        made = HintDialog(found, self)
        if made.exec():
            found.depends_on, found.concepts = made.values()
            found.use = found.use or bool(found.depends_on or found.concepts)
            self._verified = None
            self._fill_elements()
            self._sync()

    def selected_key(self) -> str | None:
        rows = {index.row() for index in self.elements.selectedIndexes()}
        if len(rows) != 1:
            return None
        row = rows.pop()
        return self._rows[row].key if 0 <= row < len(self._rows) else None

    def _confirm(self, title: str, text: str) -> bool:
        answer = QMessageBox.question(
            self,
            title,
            text,
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel,  # 기본은 「취소」 (U9)
        )
        return answer == QMessageBox.StandardButton.Yes

    def _registry_why(self, error: Exception) -> str:
        """등록·삭제 실패를 사람 말로. **다시 눌러도 될지**까지 적는다."""
        if getattr(error, "permanent", False):
            return f"서버가 거부했습니다 ({getattr(error, 'code', '')}) — {error}. 보낸 내용을 고쳐야 합니다."
        return f"서버에 닿지 못했습니다 — {error}. 서버가 돌아오면 다시 누르세요."

    def shared_session(self) -> tuple[str, str] | None:
        """지금 연 화면 `(session_id, secret)` — 「시험」 탭이 **이어 쓴다** (TOL-05, C10 `…/plan`)."""
        found = self._session
        return (found.session_id, found.secret) if found is not None else None

    def try_selected(self) -> None:
        """TOL-03 「시험...」 — 등록된 화면이어야 한다 (계획은 레지스트리에서 온다)."""
        page_id = self.page_id.currentText().strip()
        if self._known is None or not page_id or self.on_try is None:
            self.say("등록된 화면만 시험합니다 — 먼저 등록하세요.")
            return
        rows = sorted({index.row() for index in self.elements.selectedIndexes()})
        keys = [self._rows[row].key for row in rows if 0 <= row < len(self._rows) and self._rows[row].key]
        self.on_try(page_id, keys)

    def close_browser(self) -> None:
        found = self._session
        if found is None:
            return
        try:
            self._client.close(found.session_id, found.secret)
        except Exception as e:  # noqa: BLE001 — 이미 닫혔을 수 있다. 화면은 놓아 준다
            log.debug("세션을 닫지 못했다: %s", e)
        self._picking.stop()
        self.pick_button.setChecked(False)
        self._session = None
        if found.window is not None:
            self.say("창을 놓았습니다 (창은 그대로 둡니다). 담아 둔 요소는 그대로입니다.")
        else:
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
        """TOL-03 「초기화」 — 표·검증·화면 ID를 비운다. **브라우저는 유지한다.**"""
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
                hints = " · ".join(
                    filter(
                        None,
                        (
                            f"선행 {len(row.depends_on)}" if row.depends_on else "",
                            f"개념 {len(row.concepts)}" if row.concepts else "",
                        ),
                    )
                )
                rest = (
                    KIND_LABEL.get(one.kind, one.kind),
                    ", ".join(one.actions),
                    hints,
                    one.tag,
                    one.role,
                    one.name,
                    one.element_id,
                    " · ".join(one.css) or one.class_name,
                )
                for column, text in enumerate(rest, start=2):
                    cell = QTableWidgetItem(text)
                    cell.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                    self.elements.setItem(index, column, cell)
        finally:
            self._filling = False
        self._mark_duplicates()

    def _selection_changed(self) -> None:
        self._sync()
        if self._session is not None:
            self.show_selected()

    def _element_edited(self, item: QTableWidgetItem) -> None:
        if self._filling or not (0 <= item.row() < len(self._rows)):
            return
        row = self._rows[item.row()]
        if item.column() == 0:
            row.use = item.checkState() == Qt.CheckState.Checked
        elif item.column() == 1:
            row.key = item.text().strip()
            # 키를 고치면 자동 체크, 지우면 체크 해제 (TOL-03 4번).
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
        """키가 겹치면 빨간 바탕 (TOL-03 [E]) — 겹친 채로 등록하면 하나가 사라진다."""
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
        """단추 켜짐 규칙 (TOL-03)."""
        open_now = self._session is not None
        desktop = self.desktop()
        # 열린 세션의 방식을 중간에 바꾸지 않는다 — 놓거나 닫은 뒤에 바꾼다.
        self.mode.setEnabled(not open_now)
        self.open_button.setText("주소로 이동" if open_now else "브라우저 열기")
        self.analyze_button.setEnabled(open_now)
        self.pick_button.setEnabled(open_now and not desktop)
        self.desktop_pick_button.setEnabled(open_now and desktop)
        self.desktop_pick_button.setChecked(self.pick_button.isChecked())
        self.desktop_pick_button.setText(
            "고르는 중… (누르면 종료)" if self.pick_button.isChecked() else "직접 고르기"
        )
        self.scope.setEnabled(not desktop)
        self.scope.setToolTip("데스크톱은 붙은 창 하나가 범위입니다." if desktop else "")
        self.attach_button.setEnabled(not open_now and self.window_pick.count() > 0)
        self.desktop_analyze_button.setEnabled(open_now)
        self.release_button.setEnabled(open_now)
        self.pick_button.setText("고르는 중… (누르면 종료)" if self.pick_button.isChecked() else "직접 고르기")
        self.close_button.setEnabled(open_now)
        has_rows = bool(self._rows)
        self.delete_selected.setEnabled(has_rows)
        self.delete_all.setEnabled(has_rows)
        self.verify_button.setEnabled(open_now and has_rows)
        if not open_now:
            self.verify_button.setToolTip(
                "검증은 지금 열린 화면에서 합니다 — "
                + ("창에 붙으세요." if desktop else "브라우저를 여세요.")
            )
        else:
            self.verify_button.setToolTip("" if has_rows else "담은 요소가 없습니다.")

        known = self._known is not None
        self.try_button.setEnabled(known and self.on_try is not None)
        self.try_button.setToolTip("" if known else "등록된 화면만 시험합니다 — 먼저 등록하세요.")
        self.load_button.setEnabled(known)
        self.load_button.setToolTip("" if known else "등록된 화면일 때만 불러옵니다.")
        self.drop_page.setEnabled(known)
        self.drop_element.setEnabled(known and self.selected_key() is not None)
        # **검증을 마쳐야 등록이 켜진다.** 그 뒤 표를 바꾸면 다시 꺼진다 (단추 켜짐 규칙).
        ready = self._verified is not None and bool(self.page_id.currentText().strip())
        self.register_button.setEnabled(ready and self._registry is not None)
        if self._registry is None:
            self.register_button.setToolTip(NO_REGISTRY)
        else:
            self.register_button.setToolTip("" if ready else "먼저 「검증」을 누르세요.")

    def _why(self, error: Exception) -> str:
        """오류를 사람 말로. **무엇을 해야 하는지**까지 적는다."""
        text = str(error)
        if "worker_busy" in text or "사용 중" in text:
            return f"Worker가 사용 중입니다 — {text}"
        if "browser_unavailable" in text and self.desktop():
            return "데스크톱 창을 다룰 수단이 없습니다 — 이 PC에서는 UIA를 쓸 수 없습니다 (Windows 전용)."
        if "browser_unavailable" in text:
            return (
                "화면을 조작할 수단이 없습니다 — 이 PC에 브라우저 자동화가 설치되지 않았습니다 "
                "(Playwright)."
            )
        return text


class HintDialog(QDialog):
    """TOL-04 요소 계획 정보 — 선행 입력·업무 개념.

    화면 이동(`navigates_to`)은 여기서 묻지 않는다 (TOL-04).
    """

    def __init__(self, row: Row, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{row.key} — 계획에 줄 정보")
        layout = QVBoxLayout(self)
        note = QLabel(
            "선행 입력은 **이 요소를 조작하기 전에 채워야 하는** 요소의 시맨틱 키입니다. "
            "업무 개념은 자연어 목표 계획이 이 요소를 찾을 때 쓰는 말입니다. 쉼표로 나눕니다."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        form = QFormLayout()
        self.depends_on = QLineEdit(", ".join(row.depends_on))
        self.concepts = QLineEdit(", ".join(row.concepts))
        form.addRow("선행 입력", self.depends_on)
        form.addRow("업무 개념", self.concepts)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("확인")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> tuple[list[str], list[str]]:
        return _split(self.depends_on.text()), _split(self.concepts.text())


def flash_frame(rect: list[int], color: str) -> QWidget:
    """물리 픽셀 사각형(UIA, ADR-0021) 위에 테두리 창 하나 — 그 화면의 배율로 나눠 논리 좌표로 둔다.

    **입력을 통과시킨다** (`WindowTransparentForInput`) — 사람이 그 자리를 눌러도 업무 앱에 간다.
    """
    from PySide6.QtCore import QRect  # noqa: PLC0415
    from PySide6.QtGui import QGuiApplication  # noqa: PLC0415

    left, top, right, bottom = rect
    cx, cy = (left + right) / 2, (top + bottom) / 2
    screen = QGuiApplication.primaryScreen()
    for one in QGuiApplication.screens():
        geo, ratio = one.geometry(), one.devicePixelRatio()
        if geo.left() * ratio <= cx < (geo.left() + geo.width()) * ratio and geo.top() * ratio <= cy < (
            geo.top() + geo.height()
        ) * ratio:
            screen = one
            break
    ratio = screen.devicePixelRatio() if screen is not None else 1.0
    pad = 4
    frame = QWidget()
    frame.setWindowFlags(
        Qt.WindowType.FramelessWindowHint
        | Qt.WindowType.WindowStaysOnTopHint
        | Qt.WindowType.Tool
        | Qt.WindowType.WindowTransparentForInput
    )
    frame.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    frame.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    frame.setGeometry(
        QRect(
            round(left / ratio) - pad,
            round(top / ratio) - pad,
            round((right - left) / ratio) + 2 * pad,
            round((bottom - top) / ratio) + 2 * pad,
        )
    )
    border = QWidget(frame)
    border.setGeometry(0, 0, frame.width(), frame.height())
    border.setStyleSheet(f"border: 3px solid {color}; background: transparent;")
    frame.show()
    return frame


def _split(text: str) -> list[str]:
    return [one.strip() for one in text.split(",") if one.strip()]


def _candidate_of(key: str, page: PageRegistration) -> Candidate:
    """불러온 요소 하나를 표의 줄로 (물리 정보는 사다리에 있다)."""
    hint = page.elements.get(key)
    entry = page.catalog.get(key)
    return Candidate(
        role=hint.role if hint else "",
        name=hint.name if hint else "",
        kind=hint.kind if hint else "control",
        actions=list(entry.actions) if entry else [],
        css=[one.value for one in page.locators.get(key, []) if one.type == "css"],
        suggested_key=key,
    )


def _same_as(candidate: Candidate, rows: list[Row]) -> int | None:
    """표에 이미 있는 줄인가 — **같은 요소를 두 번 담지 않는다** (TOL-03 3번)."""
    for index, row in enumerate(rows):
        one = row.candidate
        if candidate.test_id and candidate.test_id == one.test_id:
            return index
        if candidate.element_id and candidate.element_id == one.element_id:
            return index
        if candidate.css and candidate.css == one.css:
            return index
    return None


def page_id_from(url: str) -> str:
    """주소에서 화면 ID를 지어 본다 (TOL-03 2번 — 사람이 고친다).

    `https://erp.example/orders/new` → `erp.example.orders.new`. **영문·숫자만** 남긴다
    (C9의 `semantic_key`·`page_id` 모양).
    """
    from urllib.parse import urlsplit  # noqa: PLC0415

    parts = urlsplit(url)
    pieces = [*parts.netloc.split("."), *[one for one in parts.path.split("/") if one]]
    made = ".".join(KEY_SAFE.sub("_", one.lower()).strip("_") for one in pieces if one)
    return KEY_SAFE_DOT.sub("", made).strip(".")[:120]


def summary_of(result: VerifyResult) -> str:
    """TOL-03 7번의 요약. Worker의 `summarize()`와 **같은 말**을 쓴다."""
    from chaeksas.ext.ui_automation.worker.registration import summarize  # noqa: PLC0415

    return summarize(result)


def registry_client(ctx: Any) -> Any:
    """레지스트리를 부르는 쪽 (C9). **Center 주소·호출 토큰이 없으면 `None`** — 등록이 꺼진다.

    둘 다 호스트가 준다 (C13 `center.url`·비밀 `call_token`). 등록 작업은 그 PC에 「셀렉터 등록」
    (CON-03)이 켜졌을 때만 Center가 받는다 (C15). C11 `caller.type`은 **도구를 띄운 호스트**다.
    """
    from chaeksas.contracts.extension import CALL_TOKEN_SECRET, CENTER_URL_SETTING  # noqa: PLC0415
    from chaeksas.ext.ui_automation.client.registry_client import RegistryClient  # noqa: PLC0415

    base_url = ctx.setting(CENTER_URL_SETTING)
    token = ctx.secret(CALL_TOKEN_SECRET)
    if not base_url or not token:
        return None
    host = getattr(ctx, "host", None)
    if host:
        return RegistryClient(base_url=str(base_url), call_token=str(token), caller_type=str(host))
    return RegistryClient(base_url=str(base_url), call_token=str(token))


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
    "DESKTOP_PICKING",
    "FLASH_MS",
    "MODE_BROWSER",
    "MODE_DESKTOP",
    "ELEMENT_COLUMNS",
    "NO_REGISTRY",
    "PICK_POLL_MS",
    "KIND_LABEL",
    "PORT_SETTING",
    "TOKEN_DIR_SETTING",
    "RegistrationWidget",
    "Row",
    "Session",
    "summary_of",
    "worker_client",
]
