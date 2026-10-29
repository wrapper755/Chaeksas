"""STU-04 게이트웨이 편집기 — 기본 흐름 하나 (C14 B3).

속성 패널이 배타·포함·병렬 게이트웨이를 만나면 탭으로 끼운다. **규약은 결재·STU-14와 같다**
(`load`/`dump`/`problems`/`changed`).

- 고치는 것은 **표준 `default` 하나**다 — `dump()`가 `{"default": 흐름 id | ""}`를 준다.
  가지의 조건식은 **보이기만** 한다. 고치는 자리는 그 순서 흐름의 「폼」 탭 하나다(같은 값을 두 곳에서
  고치면 어느 쪽이 이겼는지 모른다).
- 조건식이 있는 흐름은 **기본으로 고를 수 없다** — 엔진은 기본 흐름의 조건을 보지 않으므로 적힌 조건이
  보이지 않게 된다.
- 병렬 게이트웨이는 기본이 없다 — 모든 나가는 흐름으로 간다.
- 조건도 기본도 아닌 흐름(B3)은 **경고**다. 조건은 그 흐름에서 적으므로 여기서 막으면 고칠 길이 없다.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QGroupBox,
    QHeaderView,
    QLabel,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from chaeksas.qt.theme import set_role
from chaeksas.qt.theme.tokens import SPACE_2, SPACE_3

#: 탭 이름.
TAB_LABEL = "게이트웨이"

#: 기본 흐름을 고를 수 있는 게이트웨이 (병렬은 모든 흐름으로 간다).
DEFAULT_KINDS = frozenset({"ExclusiveGateway", "InclusiveGateway"})

PARALLEL_NOTE = "모든 나가는 흐름으로 갑니다 — 조건·기본을 보지 않습니다."
CONDITION_EDIT_NOTE = "조건식은 그 흐름을 골라 「폼」 탭에서 고칩니다."
ALWAYS = "(항상)"
HAS_CONDITION = "조건식이 있는 흐름은 기본으로 고를 수 없습니다 — 엔진은 기본 흐름의 조건을 보지 않습니다."
DEFAULT_HAS_CONDITION = (
    "기본 흐름 {flow}에 조건식이 있습니다 — 엔진은 그 조건을 보지 않습니다. "
    "다른 흐름을 고르거나 그 흐름의 조건식을 지우세요."
)
UNCONDITIONAL = "조건도 기본도 아닌 흐름이 있습니다: {flows} — 기본으로 고르거나 그 흐름에 조건식을 적으세요 (B3)."
PARALLEL_CONDITION = "병렬 게이트웨이는 조건식을 보지 않습니다: {flows}"

#: 「나가는 흐름」 표의 열.
COLUMNS = ("기본", "흐름", "대상", "조건식")


class GatewayEditor(QWidget):
    """게이트웨이 하나."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None, *, kind: str = "ExclusiveGateway") -> None:
        super().__init__(parent)
        self.kind = kind
        self._quiet = False
        self._outgoing: list[dict[str, str]] = []

        self.incoming_label = QLabel("", self)
        self.incoming_label.setWordWrap(True)

        self.none_pick = QRadioButton("기본 없음", self)
        self.group = QButtonGroup(self)
        self.group.addButton(self.none_pick)
        self.none_pick.setChecked(True)
        self._picks: dict[str, QRadioButton] = {}

        self.table = QTableWidget(0, len(COLUMNS), self)
        self.table.setHorizontalHeaderLabels(list(COLUMNS))
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)

        self.parallel_note = QLabel(PARALLEL_NOTE, self)
        self.parallel_note.setWordWrap(True)
        set_role(self.parallel_note, "muted")
        self.condition_note = QLabel(CONDITION_EDIT_NOTE, self)
        self.condition_note.setWordWrap(True)
        set_role(self.condition_note, "muted")
        self.warning = QLabel("", self)
        self.warning.setWordWrap(True)
        set_role(self.warning, "error")
        self.note = QLabel("", self)
        self.note.setWordWrap(True)
        set_role(self.note, "muted")

        incoming = QGroupBox("들어오는 흐름", self)
        incoming_layout = QVBoxLayout(incoming)
        _tight(incoming_layout)
        incoming_layout.addWidget(self.incoming_label)

        outgoing = QGroupBox("나가는 흐름", self)
        outgoing_layout = QVBoxLayout(outgoing)
        _tight(outgoing_layout)
        outgoing_layout.addWidget(self.none_pick)
        outgoing_layout.addWidget(self.parallel_note)
        outgoing_layout.addWidget(self.table)
        outgoing_layout.addWidget(self.condition_note)

        layout = QVBoxLayout(self)
        layout.setSpacing(SPACE_3)
        layout.addWidget(incoming)
        layout.addWidget(outgoing)
        layout.addWidget(self.warning)
        layout.addWidget(self.note)
        layout.addStretch(1)

        self.group.buttonToggled.connect(self._touched)
        self._refresh()

    # ── 규약 ──

    def load(self, found: Mapping[str, Any]) -> None:
        """캔버스 `properties()`의 `gateway` — `{default, incoming[], outgoing[]}`."""
        self._quiet = True
        incoming = [dict(one) for one in found.get("incoming") or [] if isinstance(one, Mapping)]
        self.incoming_label.setText(_incoming_text(incoming))
        self._outgoing = [
            {key: str(one.get(key) or "") for key in ("id", "name", "to", "condition")}
            for one in found.get("outgoing") or []
            if isinstance(one, Mapping)
        ]
        for pick in self._picks.values():
            self.group.removeButton(pick)
        self._picks = {}
        self.table.setRowCount(len(self._outgoing))
        for row, flow in enumerate(self._outgoing):
            pick = QRadioButton(self.table)
            if flow["condition"]:
                pick.setEnabled(False)
                pick.setToolTip(HAS_CONDITION)
            self.group.addButton(pick)
            self._picks[flow["id"]] = pick
            self.table.setCellWidget(row, 0, _centered(pick, self.table))
            self.table.setItem(row, 1, _cell(flow["name"] or flow["id"], flow["id"]))
            self.table.setItem(row, 2, _cell(flow["to"]))
            self.table.setItem(row, 3, _cell(flow["condition"] or ALWAYS))
        chosen = str(found.get("default") or "")
        (self._picks.get(chosen) or self.none_pick).setChecked(True)
        self.table.resizeColumnsToContents()
        self._fit_table()
        self._quiet = False
        self._refresh()

    def chosen(self) -> str:
        return next((flow_id for flow_id, pick in self._picks.items() if pick.isChecked()), "")

    def dump(self) -> dict[str, Any]:
        """병렬 게이트웨이는 고를 칸을 숨긴다 — 읽은 것이 그대로 나가 바뀐 것이 없다."""
        return {"default": self.chosen()}

    def problems(self) -> tuple[list[str], list[str]]:
        """`(적용을 막는 것, 경고)`."""
        errors: list[str] = []
        warnings: list[str] = []
        by_id = {flow["id"]: flow for flow in self._outgoing}
        if self.kind in DEFAULT_KINDS:
            chosen = by_id.get(self.chosen())
            if chosen is not None and chosen["condition"]:
                errors.append(DEFAULT_HAS_CONDITION.format(flow=_flow_label(chosen)))
            if len(self._outgoing) > 1:
                bare = [
                    _flow_label(flow)
                    for flow in self._outgoing
                    if not flow["condition"] and flow["id"] != self.chosen()
                ]
                if bare:
                    warnings.append(UNCONDITIONAL.format(flows=", ".join(bare)))
        else:
            guarded = [_flow_label(flow) for flow in self._outgoing if flow["condition"]]
            if guarded:
                warnings.append(PARALLEL_CONDITION.format(flows=", ".join(guarded)))
        self.warning.setText(errors[0] if errors else "")
        self.note.setText(" ".join(warnings))
        return errors, warnings

    # ── 안쪽 ──

    def _fit_table(self) -> None:
        """표는 흐름 수만큼만 높다 — 흐름은 몇 개 안 되고, 빈 줄이 남으면 「더 있다」로 읽힌다."""
        rows = sum(self.table.rowHeight(row) for row in range(self.table.rowCount()))
        frame = 2 * self.table.frameWidth()
        self.table.setFixedHeight(self.table.horizontalHeader().height() + rows + frame)

    def _touched(self, *_args: object) -> None:
        if self._quiet:
            return
        self._refresh()
        self.changed.emit()

    def _refresh(self) -> None:
        picks_on = self.kind in DEFAULT_KINDS
        self.none_pick.setVisible(picks_on)
        self.table.setColumnHidden(0, not picks_on)
        self.parallel_note.setVisible(not picks_on)
        self.problems()


def _incoming_text(incoming: list[dict[str, Any]]) -> str:
    if not incoming:
        return "없습니다."
    sources = ", ".join(str(one.get("from") or one.get("id") or "") for one in incoming)
    if len(incoming) > 1:
        return f"{len(incoming)}개 — {sources} (합류)"
    return f"1개 — {sources}"


def _flow_label(flow: Mapping[str, str]) -> str:
    return flow.get("name") or flow.get("id") or ""


def _cell(text: str, tip: str = "") -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    if tip:
        item.setToolTip(tip)
    return item


def _centered(widget: QWidget, parent: QWidget) -> QWidget:
    """표 칸 가운데에 라디오 하나."""
    holder = QWidget(parent)
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(widget, alignment=Qt.AlignmentFlag.AlignCenter)
    return holder


def _tight(layout: Any) -> None:
    """묶음 안쪽 여백 — 결재 편집기와 같다."""
    layout.setContentsMargins(SPACE_2, SPACE_2, SPACE_2, SPACE_2)


__all__ = [
    "ALWAYS",
    "DEFAULT_HAS_CONDITION",
    "DEFAULT_KINDS",
    "HAS_CONDITION",
    "PARALLEL_CONDITION",
    "PARALLEL_NOTE",
    "TAB_LABEL",
    "UNCONDITIONAL",
    "GatewayEditor",
]
