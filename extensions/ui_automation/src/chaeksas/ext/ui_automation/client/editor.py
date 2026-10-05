"""STU-13 UI 태스크 편집기 — 등록된 화면의 요소를 **시맨틱 키로** 조작하는 스텝을 만든다.

**셀렉터는 여기서 보이지 않는다** (ADR-0008). 고를 것은 공개 카탈로그(C9)에서 오고, 거기엔
물리 정보가 없다 — 그래서 키도 필요 없다.

지키는 것 다섯.

- **그 요소가 할 수 있는 동작만** 고르게 한다 (카탈로그의 `actions`).
- **값이 필요한 동작에 값이 없으면 오류**이고 「적용」을 막는다. 읽기에 결과 변수가 없어도
  마찬가지다 — 실행할 때 알면 늦다.
- **등록되지 않은 요소·선행 입력 빠짐은 경고**다 (막지 않는다). 아직 등록 전일 수 있다.
- **서버에 닿지 못해도 고칠 수 있다** — 마지막 목록을 쓰고 「(오프라인)」이라고 말한다.
- 쓰는 모양은 C14 그대로다 (`chk:task` `type="ui_task"`의 `data`).

> 상태: 「이 스텝까지 시험」과 리소스 탐색기 끌어다 놓기는 아직이다. 목표로 계획(자율)은
> 모델이 하는 일이라 칸을 꺼 두고 왜 꺼졌는지 말한다.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from PySide6.QtCore import Qt, Signal
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
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from chaeksas.extension_api import ExtensionContext

log = logging.getLogger(__name__)

#: 스텝 표의 열 (STU-13 [T]).
STEP_COLUMNS = ("#", "요소", "동작", "값", "결과 변수", "화면 이동")

#: 값이 있어야 하는 동작과 결과 변수가 있어야 하는 동작 (C10과 같은 낱말).
NEEDS_VALUE = ("fill", "press", "select")
NEEDS_RESULT = ("read", "read_table", "read_options", "read_selection")

#: 자율 수행이 꺼져 있는 이유 (U3 — 왜 꺼졌는지 말한다).
#: 목표로 계획의 도움말 (STU-13 [G], ADR-0035).
GOAL_HELP = (
    "자율 수행(Studio 시험)에서만 돕니다. Bot(결정 수행)에서는 실패합니다. "
    "쓸 값은 목표 안에 {이름}으로 적습니다 — 그 이름만 모델에 갑니다."
)


def _row_steps(raw: Any) -> list[dict[str, Any]]:
    return [dict(one) for one in (raw or []) if isinstance(one, dict)]


class UiTaskEditor(QWidget):
    """`task_types[].editor` (`kind="builtin"`) — `extension_api.TaskEditor`.

    Studio가 속성 패널에 붙이고 `load()`/`dump()`로 C14 속성을 주고받는다.
    """

    #: 칸이 바뀌었다 — 속성 패널의 「적용」이 이것을 듣는다 (STU-04).
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from chaeksas.ext.ui_automation.client.catalog import Catalog  # noqa: PLC0415

        self.catalog = Catalog()
        self._loaded: dict[str, Any] = {}

        layout = QVBoxLayout(self)
        layout.addWidget(self._screen())
        layout.addWidget(self._options())
        layout.addWidget(self._steps(), 1)
        layout.addWidget(self._goal())
        self.warnings = QLabel("")
        self.warnings.setWordWrap(True)
        layout.addWidget(self.warnings)
        self._sync()

    # ── `extension_api.TaskEditor` ──

    def widget(self, ctx: ExtensionContext) -> object:
        """Studio가 부른다 — 주소는 **호스트가** 준다 (C13 예약 키 `service.base_url`)."""
        from chaeksas.contracts import SERVICE_URL_SETTING  # noqa: PLC0415

        found = ctx.setting(SERVICE_URL_SETTING)
        self.catalog.base_url = str(found) if found else None
        self.reload()
        return self

    def load(self, properties: Mapping[str, Any]) -> None:
        """BPMN `chk:task`의 `data`(C14)를 칸에 채운다."""
        found = dict(properties)
        self._loaded = found
        self.page_id.setCurrentText(str(found.get("page_id") or ""))
        self.start_url.setText(str(found.get("start_url") or ""))
        self.key_ref.setText(str(found.get("key_ref") or ""))
        self.heal.setChecked(bool(found.get("heal", True)))
        self.close_browser.setChecked(bool(found.get("close_browser", False)))
        self.goal.setText(str(found.get("goal") or ""))
        self.results.setText(", ".join(str(one) for one in (found.get("results") or [])))
        self.use_goal.setChecked(bool(found.get("goal")))

        self.steps.setRowCount(0)
        for step in _row_steps(found.get("steps")):
            self._add_row(
                str(step.get("key") or ""),
                str(step.get("action") or ""),
                str(step.get("value") or ""),
                str(step.get("result") or ""),
                bool(step.get("navigates")),
            )
        self._sync()

    def dump(self) -> Mapping[str, Any]:
        """칸의 값을 C14 속성으로. **비어 있는 것은 적지 않는다** (그림이 지저분해진다)."""
        out: dict[str, Any] = {"page_id": self.page_id.currentText().strip()}
        if self.start_url.text().strip():
            out["start_url"] = self.start_url.text().strip()
        if self.key_ref.text().strip():
            out["key_ref"] = self.key_ref.text().strip()
        out["steps"] = self.step_rows()
        if self.use_goal.isChecked() and self.goal.text().strip():
            out["goal"] = self.goal.text().strip()
            results = self.result_names()
            if results:
                out["results"] = results
        out["heal"] = self.heal.isChecked()
        out["close_browser"] = self.close_browser.isChecked()
        return out

    # ── 만들기 ──

    def _screen(self) -> QWidget:
        box = QGroupBox("화면")
        row = QHBoxLayout(box)
        self.page_id = QComboBox()
        self.page_id.setEditable(True)
        self.page_id.setMinimumWidth(260)
        self.page_id.currentTextChanged.connect(self._page_changed)
        self.reload_button = QPushButton("다시 읽기")
        self.reload_button.clicked.connect(self.reload)
        self.source = QLabel("")
        self.source.setEnabled(False)
        row.addWidget(self.page_id, 1)
        row.addWidget(self.reload_button)
        row.addWidget(self.source)
        return box

    def _options(self) -> QWidget:
        box = QGroupBox("옵션")
        outer = QVBoxLayout(box)
        first = QHBoxLayout()
        self.start_url = QLineEdit()
        self.start_url.setPlaceholderText("시작 주소 (비우면 화면의 기본 주소, 또는 이어서)")
        self.key_ref = QLineEdit()
        self.key_ref.setPlaceholderText("UI 자동화 앱 키 참조 (비우면 BPM 프로세스 설정)")
        for line in (self.start_url, self.key_ref):
            line.textChanged.connect(lambda *_: self._sync())
        first.addWidget(QLabel("시작 주소"))
        first.addWidget(self.start_url, 2)
        first.addWidget(QLabel("키 참조"))
        first.addWidget(self.key_ref, 1)
        outer.addLayout(first)

        second = QHBoxLayout()
        self.heal = QCheckBox("자가 치유 사용")
        self.heal.setChecked(True)
        self.heal.setToolTip("켜 두면 결정 수행 Bot도 실패한 요소에 한해 LLM 치유를 씁니다.")
        self.close_browser = QCheckBox("실행 후 브라우저 닫기")
        for checkbox in (self.heal, self.close_browser):
            checkbox.toggled.connect(lambda *_: self._sync())
        second.addWidget(self.heal)
        second.addWidget(self.close_browser)
        second.addStretch(1)
        outer.addLayout(second)
        return box

    def _steps(self) -> QWidget:
        box = QGroupBox("스텝")
        layout = QVBoxLayout(box)
        self.steps = QTableWidget(0, len(STEP_COLUMNS))
        self.steps.setHorizontalHeaderLabels(list(STEP_COLUMNS))
        self.steps.verticalHeader().setVisible(False)
        self.steps.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.steps.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.steps.itemChanged.connect(lambda *_: self._sync())
        layout.addWidget(self.steps)

        row = QHBoxLayout()
        self.add_button = QPushButton("스텝 추가")
        self.add_button.clicked.connect(lambda: self._add_row("", "", "", "", False))
        self.drop_button = QPushButton("삭제")
        self.drop_button.clicked.connect(self.remove_step)
        self.up_button = QPushButton("위로")
        self.up_button.clicked.connect(lambda: self.move_step(-1))
        self.down_button = QPushButton("아래로")
        self.down_button.clicked.connect(lambda: self.move_step(1))
        self.test_button = QPushButton("이 스텝까지 시험")
        self.test_button.setEnabled(False)
        self.test_button.setToolTip("Bot UI의 「UI 셀렉터 등록 › 시험」(BUI-08)에서 돌려 보세요.")
        row.addStretch(1)
        for one in (self.add_button, self.drop_button, self.up_button, self.down_button, self.test_button):
            row.addWidget(one)
        layout.addLayout(row)
        return box

    def _goal(self) -> QWidget:
        box = QGroupBox("목표로 계획")
        row = QHBoxLayout(box)
        self.use_goal = QCheckBox("스텝 대신 목표로 실행")
        self.use_goal.setToolTip(GOAL_HELP)
        self.goal = QLineEdit()
        self.goal.setPlaceholderText("목표 (예: {신청.등록번호}를 넣고 상신한 뒤 접수번호를 읽는다)")
        self.goal.setToolTip(GOAL_HELP)
        self.results = QLineEdit()
        self.results.setPlaceholderText("결과 변수 (쉼표로 여럿)")
        self.results.setToolTip("읽은 값을 담을 변수 이름. 모델은 이 중에서만 고릅니다.")
        row.addWidget(self.use_goal)
        row.addWidget(self.goal, 3)
        row.addWidget(self.results, 1)
        self.use_goal.toggled.connect(lambda *_: self._sync())
        self.goal.textChanged.connect(lambda *_: self._sync())
        self.results.textChanged.connect(lambda *_: self._sync())
        return box

    def result_names(self) -> list[str]:
        return [one.strip() for one in self.results.text().split(",") if one.strip()]

    # ── 동작 ──

    def reload(self) -> None:
        """카탈로그를 다시 읽는다. **실패해도 들고 있던 목록은 쓴다** (오프라인)."""
        self.catalog.reload()
        text = self.page_id.currentText()
        self.page_id.blockSignals(True)  # noqa: FBT003 — Qt 이름
        self.page_id.clear()
        self.page_id.addItems([one.page_id for one in self.catalog.pages])
        self.page_id.setCurrentText(text)
        self.page_id.blockSignals(False)  # noqa: FBT003
        for index, one in enumerate(self.catalog.pages):
            self.page_id.setItemData(index, one.label, Qt.ItemDataRole.ToolTipRole)
        self.source.setText(f"(오프라인) {self.catalog.last_error}" if self.catalog.offline else "")
        self._page_changed()

    def _page_changed(self) -> None:
        """화면이 바뀌면 고를 수 있는 요소도 바뀐다 — 이미 적은 키는 **지우지 않는다**."""
        for row in range(self.steps.rowCount()):
            self._fill_choices(row)
        self._sync()

    def page(self) -> Any:
        return self.catalog.page(self.page_id.currentText().strip())

    def _add_row(self, key: str, action: str, value: str, result: str, navigates: bool) -> None:
        row = self.steps.rowCount()
        self.steps.insertRow(row)

        number = QTableWidgetItem(str(row + 1))
        number.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.steps.setItem(row, 0, number)

        element = QComboBox()
        element.setEditable(True)
        element.currentTextChanged.connect(lambda _=None, r=row: self._element_changed(r))
        self.steps.setCellWidget(row, 1, element)
        action_box = QComboBox()
        self.steps.setCellWidget(row, 2, action_box)
        action_box.currentTextChanged.connect(lambda *_: self._sync())

        self.steps.setItem(row, 3, QTableWidgetItem(value))
        self.steps.setItem(row, 4, QTableWidgetItem(result))
        moved = QTableWidgetItem()
        moved.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        moved.setCheckState(Qt.CheckState.Checked if navigates else Qt.CheckState.Unchecked)
        self.steps.setItem(row, 5, moved)

        self._fill_choices(row, key=key, action=action)
        self._sync()

    def _fill_choices(self, row: int, *, key: str | None = None, action: str | None = None) -> None:
        """그 화면의 요소와 **그 요소가 할 수 있는 동작만** 담는다 (STU-13 [T])."""
        element = self.steps.cellWidget(row, 1)
        action_box = self.steps.cellWidget(row, 2)
        if not isinstance(element, QComboBox) or not isinstance(action_box, QComboBox):
            return
        wanted = key if key is not None else element.currentText()
        page = self.page()

        element.blockSignals(True)  # noqa: FBT003
        element.clear()
        if page is not None:
            element.addItems([one.semantic_key for one in page.elements])
        element.setCurrentText(wanted)
        element.blockSignals(False)  # noqa: FBT003

        chosen = action if action is not None else action_box.currentText()
        found = page.element(wanted) if page is not None else None
        allowed = list(found.actions) if found is not None else []
        # **적어 둔 것을 조용히 바꾸지 않는다.** 그 요소가 할 수 없는 동작이어도 그대로 두고
        # 경고로 말한다 — 고르는 목록에서 빼면 값이 소리 없이 바뀐다 (시험이 잡았다).
        if chosen and chosen not in allowed:
            allowed.insert(0, chosen)
        action_box.blockSignals(True)  # noqa: FBT003
        action_box.clear()
        action_box.addItems(allowed)
        action_box.setCurrentText(chosen)
        action_box.blockSignals(False)  # noqa: FBT003

    def _element_changed(self, row: int) -> None:
        self._fill_choices(row)
        self._sync()

    def remove_step(self) -> None:
        for row in sorted({index.row() for index in self.steps.selectedIndexes()}, reverse=True):
            self.steps.removeRow(row)
        self._renumber()

    def move_step(self, delta: int) -> None:
        rows = {index.row() for index in self.steps.selectedIndexes()}
        if len(rows) != 1:
            return
        row = rows.pop()
        target = row + delta
        if not (0 <= target < self.steps.rowCount()):
            return
        steps = self.step_rows()
        steps[row], steps[target] = steps[target], steps[row]
        self.steps.setRowCount(0)
        for one in steps:
            self._add_row(
                one["key"], one["action"], str(one.get("value") or ""),
                str(one.get("result") or ""), bool(one.get("navigates")),
            )
        self.steps.selectRow(target)

    def _renumber(self) -> None:
        for row in range(self.steps.rowCount()):
            cell = self.steps.item(row, 0)
            if cell is not None:
                cell.setText(str(row + 1))
        self._sync()

    def step_rows(self) -> list[dict[str, Any]]:
        """C14 `steps[]` 모양. **빈 칸은 넣지 않는다.**"""
        out = []
        for row in range(self.steps.rowCount()):
            element = self.steps.cellWidget(row, 1)
            action_box = self.steps.cellWidget(row, 2)
            value = self.steps.item(row, 3)
            result = self.steps.item(row, 4)
            moved = self.steps.item(row, 5)
            key = element.currentText().strip() if isinstance(element, QComboBox) else ""
            if not key:
                continue
            step: dict[str, Any] = {
                "key": key,
                "action": action_box.currentText() if isinstance(action_box, QComboBox) else "",
            }
            if value is not None and value.text().strip():
                step["value"] = value.text().strip()
            if result is not None and result.text().strip():
                step["result"] = result.text().strip()
            if moved is not None and moved.checkState() == Qt.CheckState.Checked:
                step["navigates"] = True
            out.append(step)
        return out

    # ── 검사 (STU-13 [W]) ──

    def problems(self) -> tuple[list[str], list[str]]:
        """`(오류, 경고)` — **오류는 「적용」을 막고, 경고는 막지 않는다**."""
        errors: list[str] = []
        warnings: list[str] = []
        page = self.page()
        if not self.page_id.currentText().strip():
            errors.append("화면을 고르세요.")
        elif page is None and not self.catalog.offline:
            warnings.append(f"등록되지 않은 화면입니다 — {self.page_id.currentText().strip()}")

        seen: list[str] = []
        for index, step in enumerate(self.step_rows(), start=1):
            key, action = step["key"], step["action"]
            if not action:
                errors.append(f"{index}번 스텝: 동작을 고르세요.")
            if action in NEEDS_VALUE and not step.get("value"):
                errors.append(f"{index}번 스텝({key}): {action}에는 값이 필요합니다.")
            if action in NEEDS_RESULT and not step.get("result"):
                errors.append(f"{index}번 스텝({key}): 읽기에는 결과 변수가 필요합니다.")

            found = page.element(key) if page is not None else None
            if page is not None and found is None:
                warnings.append(f"{index}번 스텝: 등록되지 않은 요소입니다 — {key}")
            elif found is not None:
                if action and found.actions and action not in found.actions:
                    warnings.append(f"{index}번 스텝({key}): 이 요소가 할 수 없는 동작입니다 — {action}")
                missing = [one for one in found.depends_on if one not in seen]
                if missing:
                    # 선행 입력이 앞 스텝에 없다 — 실행하면 비활성 칸을 누를 수 있다.
                    warnings.append(
                        f"{index}번 스텝({key}): 선행 입력이 앞에 없습니다 — {', '.join(missing)}"
                    )
            seen.append(key)

        if self.use_goal.isChecked():
            goal = self.goal.text().strip()
            if not goal:
                errors.append("목표가 비었습니다.")
            elif "{" not in goal:
                # 값을 넣는 스텝을 세울 수 없다 — 모델은 이름만 받는다 (ADR-0035).
                warnings.append("목표에 {이름}이 없습니다 — 값을 넣는 스텝을 세울 수 없습니다.")
        elif not self.step_rows():
            errors.append("스텝이 없습니다.")
        return errors, warnings

    def valid(self) -> bool:
        errors, _ = self.problems()
        return not errors

    def _sync(self) -> None:
        errors, warnings = self.problems()
        lines = [f"오류: {one}" for one in errors] + [f"경고: {one}" for one in warnings]
        self.warnings.setText("\n".join(lines))
        self.warnings.setProperty("role", "error" if errors else "")
        goal_mode = self.use_goal.isChecked()
        # 목표로 실행하면 스텝 표는 흐려진다 — 실행 때 앱이 세운 스텝을 쓴다 (STU-13 [G]).
        self.steps.setEnabled(not goal_mode)
        self.goal.setEnabled(goal_mode)
        self.results.setEnabled(goal_mode)
        rows = self.steps.rowCount()
        self.drop_button.setEnabled(bool(rows))
        self.up_button.setEnabled(bool(rows))
        self.down_button.setEnabled(bool(rows))
        self.changed.emit()


__all__ = ["GOAL_HELP", "NEEDS_RESULT", "NEEDS_VALUE", "STEP_COLUMNS", "UiTaskEditor"]
