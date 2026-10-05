"""BUI-08 셀렉터 시험 — 등록된 화면을 **계획을 받아 실제로 돌려 본다**.

Bot 실행과는 별개의 시험이다. 보고는 **`origin: test`**로 가고 승격 통계에 들어가지
않는다 (C8) — 그 순간 그 화면에서 한 번 됐다고 「사용 중」으로 올리면 안 된다.

지키는 것 다섯.

- **출력 상자 하나로만 말한다.** 계획 출처·스텝·결과·시도·전환이 한 곳에 쌓인다.
- **읽어온 값은 화면에만** 보인다 — 보고에는 들어가지 않는다 (원칙 6).
- **기본은 보고하지 않는다.** 시험이 서버 통계를 건드리지 않게.
- **끝나도 브라우저를 열어 둔다** (기본) — 무엇이 잘못됐는지 보려면 화면이 있어야 한다.
- **전환은 실패가 아니다** — 사람이 봐야 한다는 뜻으로 적는다.

> 상태: 자연어 **목표로 계획**(자율 수행)은 모델이 하는 일이라 아직 없다 — 칸은 꺼 두고
> 왜 꺼졌는지 말한다. 스텝은 등록된 요소에서 「가져오기」로 채우고 사람이 고친다.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from typing import Any

from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from chaeksas.ext.ui_automation.contracts.worker_local import (
    CALLER_REGISTRATION,
    MUTATING_ACTIONS,
    READING_ACTIONS,
    Caller,
    SessionRequest,
    StepRequest,
)

log = logging.getLogger(__name__)

#: 스텝 표의 열 (BUI-08).
STEP_COLUMNS = ("시맨틱 키", "동작", "값")

#: 고를 수 있는 동작 — 조작 먼저, 읽기 나중 (C10 `KNOWN_ACTIONS`).
ACTIONS = (*MUTATING_ACTIONS, *READING_ACTIONS)

#: 요소 종류 → 「가져오기」가 넣어 주는 기본 동작.
DEFAULT_ACTION = {"control": "click", "list": "read_options", "table": "read_table", "text": "read"}

#: 자연어 목표가 꺼져 있는 이유 (U3 — 왜 꺼졌는지 말한다).
NO_GOAL = "셀렉터 시험은 등록된 요소의 스텝으로 합니다 — 목표로 계획은 Studio UI 태스크(STU-13)의 자율 수행에서 씁니다."

PLAN_SOURCE = {"server": "서버", "cache": "로컬 캐시 (오프라인)"}


@dataclass
class Trial:
    """시험 한 번의 세션."""

    session_id: str
    secret: str


class TrialWidget(QWidget):
    """BUI-08의 화면. Worker(C10)와 레지스트리(C9)를 모두 부른다."""

    def __init__(
        self,
        client: Any,
        registry: Any = None,
        service_key: str | None = None,
        release_other: Any = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._registry = registry
        self._service_key = service_key
        #: 다른 탭이 쥔 UI 세션을 놓게 하는 길 (세션은 한 번에 하나다, ADR-0014).
        self._release_other = release_other
        self._trial: Trial | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(self._setup())
        layout.addWidget(self._steps(), 2)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        layout.addWidget(self.output, 3)
        self._sync()

    # ── 만들기 ──

    def _setup(self) -> QWidget:
        box = QGroupBox("시험")
        outer = QVBoxLayout(box)

        first = QHBoxLayout()
        self.page_id = QComboBox()
        self.page_id.setEditable(True)
        self.page_id.setMinimumWidth(240)
        self.goal = QLineEdit()
        self.goal.setPlaceholderText("목표 (예: 공급자 등록번호를 넣고 상신)")
        self.goal.setEnabled(False)
        self.goal.setToolTip(NO_GOAL)
        self.fetch_button = QPushButton("가져오기")
        self.fetch_button.clicked.connect(self.fetch)
        first.addWidget(QLabel("화면"))
        first.addWidget(self.page_id)
        first.addWidget(self.goal, 1)
        first.addWidget(self.fetch_button)
        outer.addLayout(first)

        second = QHBoxLayout()
        self.start_url = QLineEdit()
        self.start_url.setPlaceholderText("시작 주소 (비우면 계획의 값)")
        second.addWidget(QLabel("시작 주소"))
        second.addWidget(self.start_url, 1)
        outer.addLayout(second)

        third = QHBoxLayout()
        self.heal = QCheckBox("자가 치유 사용")
        self.heal.setChecked(True)
        self.report = QCheckBox("결과를 서버에 보고")  # 기본 끔 — 시험이 통계를 건드리지 않게
        self.keep_open = QCheckBox("끝나도 브라우저 열어 두기")
        self.keep_open.setChecked(True)
        self.close_button = QPushButton("브라우저 닫기")
        self.close_button.clicked.connect(self.close_browser)
        self.run_button = QPushButton("실행")
        self.run_button.clicked.connect(self.run)
        for one in (self.heal, self.report, self.keep_open):
            third.addWidget(one)
        third.addStretch(1)
        third.addWidget(self.close_button)
        third.addWidget(self.run_button)
        outer.addLayout(third)
        return box

    def _steps(self) -> QWidget:
        box = QGroupBox("스텝")
        layout = QVBoxLayout(box)
        self.steps = QTableWidget(0, len(STEP_COLUMNS))
        self.steps.setHorizontalHeaderLabels(list(STEP_COLUMNS))
        self.steps.verticalHeader().setVisible(False)
        self.steps.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.steps.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.steps)

        row = QHBoxLayout()
        self.add_step = QPushButton("줄 추가")
        self.add_step.clicked.connect(lambda: self._add_step("", "click", ""))
        self.drop_step = QPushButton("줄 삭제")
        self.drop_step.clicked.connect(self.remove_step)
        row.addStretch(1)
        row.addWidget(self.add_step)
        row.addWidget(self.drop_step)
        layout.addLayout(row)
        return box

    # ── 동작 ──

    def say(self, line: str) -> None:
        """출력 상자 — **진행·결과의 유일한 통로**다."""
        self.output.appendPlainText(line)

    def fetch(self) -> None:
        """BUI-08 「가져오기」 — 등록된 요소로 스텝 표를 채운다.

        자연어 목표가 없으니 **등록된 것에서 출발**한다 — 사람이 동작과 값을 고친다.
        """
        page_id = self.page_id.currentText().strip()
        if self._registry is None or not page_id:
            self.say("화면 ID를 적으세요 (등록 담당자 키가 있어야 조회합니다).")
            return
        try:
            page, warnings = self._registry.get_page(page_id)
        except Exception as e:  # noqa: BLE001
            self.say(f"가져오지 못했습니다 — {e}")
            return

        self.steps.setRowCount(0)
        for key in page.locators:
            hint = page.elements.get(key)
            kind = hint.kind if hint is not None else "control"
            self._add_step(key, DEFAULT_ACTION.get(kind, "click"), "")
        if not self.start_url.text().strip() and page.url_pattern:
            self.start_url.setText(page.url_pattern)
        self.say(f"{page_id} · 요소 {len(page.locators)}개를 가져왔습니다 (판 {page.revision}).")
        for one in warnings:
            self.say(f"경고: {one}")
        self._sync()

    def _add_step(self, key: str, action: str, value: str) -> None:
        row = self.steps.rowCount()
        self.steps.insertRow(row)
        self.steps.setItem(row, 0, QTableWidgetItem(key))
        chooser = QComboBox()
        chooser.addItems(ACTIONS)
        if action in ACTIONS:
            chooser.setCurrentText(action)
        self.steps.setCellWidget(row, 1, chooser)
        self.steps.setItem(row, 2, QTableWidgetItem(value))

    def remove_step(self) -> None:
        for row in sorted({index.row() for index in self.steps.selectedIndexes()}, reverse=True):
            self.steps.removeRow(row)
        self._sync()

    def plan_steps(self) -> list[tuple[str, str, str]]:
        out = []
        for row in range(self.steps.rowCount()):
            key = self.steps.item(row, 0)
            chooser = self.steps.cellWidget(row, 1)
            value = self.steps.item(row, 2)
            if key is None or not key.text().strip():
                continue
            action = chooser.currentText() if isinstance(chooser, QComboBox) else "click"
            out.append((key.text().strip(), action, value.text() if value is not None else ""))
        return out

    def run(self) -> None:
        """BUI-08 「실행」 — 세션을 열고 스텝을 하나씩 보낸다."""
        steps = self.plan_steps()
        if not steps:
            self.say("스텝이 없습니다 — 「가져오기」를 누르거나 줄을 더하세요.")
            return
        if not self._service_key:
            self.say("등록 담당자 키가 없어 계획을 받아 올 수 없습니다 (설정에서 넣으세요).")
            return

        self.output.clear()
        if self._trial is None and self._release_other is not None:
            # **세션은 한 번에 하나다** (ADR-0014) — 등록 탭이 쥐고 있으면 놓게 한다.
            self._release_other()
        if not self._open():
            return
        found = self._trial
        assert found is not None

        done = 0
        escalated = False
        for index, (key, action, value) in enumerate(steps, start=1):
            request = StepRequest(
                semantic_key=key, action=action, value=value or None if action in MUTATING_ACTIONS else None
            )
            try:
                result = self._client.step(found.session_id, found.secret, request)
            except Exception as e:  # noqa: BLE001 — 계획에 없는 키 등
                self.say(f"{index}. {key} · {action} → 실패: {e}")
                break
            mark = "O" if result.ok else ("△" if result.escalated else "X")
            line = f"{index}. {key} · {action} → {mark}"
            if result.fallback_depth:
                line += f" (사다리 {result.fallback_depth + 1}번째 칸)"
            if result.healed:
                line += " · 자가 치유"
            self.say(line)
            if result.text:
                # **읽어온 값은 화면에만** 보인다 (원칙 6 — 보고에는 들어가지 않는다).
                for one in str(result.text).splitlines():
                    self.say(f"    {one}")
            if result.escalated:
                escalated = True
                self.say(f"    사람에게 전환: {result.error or '사다리가 모두 실패했습니다'}")
                break
            if not result.ok:
                self.say(f"    실패: {result.error_code or ''} {result.error or ''}".rstrip())
                break
            done += 1

        self._finish(done, len(steps), escalated=escalated)

    def _open(self) -> bool:
        """시험용 세션. **등록 세션과 같은 종류**라 보고가 `test`로 간다 (C8)."""
        page_id = self.page_id.currentText().strip()
        request = SessionRequest(
            schema=1,
            caller=Caller(type=CALLER_REGISTRATION),
            mode="deterministic",
            business_key=f"reg_{secrets.token_hex(4)}",
            page_id=page_id,
            start_url=self.start_url.text().strip() or None,
            headed=True,
            heal=self.heal.isChecked(),
            report=self.report.isChecked(),
            service_key=self._service_key,
        )
        try:
            info = self._client.open(request)
        except Exception as e:  # noqa: BLE001
            self.say(f"시작하지 못했습니다 — {e}")
            return False
        self._trial = Trial(session_id=info.session_id, secret=info.session_secret)
        source = PLAN_SOURCE.get(info.plan_source, info.plan_source)
        self.say(f"[계획 출처: {source}] {page_id} · {self.steps.rowCount()}스텝")
        self._sync()
        return True

    def _finish(self, done: int, total: int, *, escalated: bool) -> None:
        found = self._trial
        if found is None:
            return
        result = "사람에게 전환" if escalated else ("성공" if done == total else "실패")
        self.say(f"결과: {result} — {done}/{total} 스텝")
        if not self.keep_open.isChecked():
            self.close_browser()
            return
        self.say("브라우저를 열어 두었습니다.")
        self._sync()

    def close_browser(self) -> None:
        """닫으면서 보고한다 (켜 두었을 때만). **보고는 `test`로 간다** (승격에 안 들어간다)."""
        found = self._trial
        if found is None:
            return
        try:
            closed = self._client.close(found.session_id, found.secret)
        except Exception as e:  # noqa: BLE001 — 이미 닫혔을 수 있다
            log.debug("세션을 닫지 못했다: %s", e)
            self._trial = None
            self._sync()
            return
        self._trial = None
        if not self.report.isChecked():
            self.say("보고하지 않았습니다 (「결과를 서버에 보고」가 꺼져 있습니다).")
        elif closed.report == "sent":
            self.say("보고 전송됨 — 「시험」으로 표시되어 승격 통계에는 들어가지 않습니다.")
        else:
            self.say("보고를 큐에 쌓았습니다 (서버에 닿지 못함).")
        self._sync()

    def release(self) -> None:
        """창을 닫을 때 — UI 세션을 놓는다."""
        self.close_browser()

    def _sync(self) -> None:
        running = self._trial is not None
        self.close_button.setEnabled(running)
        self.run_button.setEnabled(bool(self.steps.rowCount()))
        self.drop_step.setEnabled(bool(self.steps.rowCount()))
        self.fetch_button.setEnabled(self._registry is not None)
        if self._registry is None:
            self.fetch_button.setToolTip("등록 담당자 키가 있어야 조회합니다 (설정).")


__all__ = ["ACTIONS", "DEFAULT_ACTION", "NO_GOAL", "PLAN_SOURCE", "STEP_COLUMNS", "Trial", "TrialWidget"]
