"""STU-04 반복 편집기 — 다중 인스턴스 표시와 `bpm:loop` (C14 §반복, ADR-0087).

속성 패널이 반복을 쓸 수 있는 요소(서비스·규칙 태스크, Call Activity)를 만나면 탭으로 끼운다.
**규약은 결재·STU-14와 같다** (`load`/`dump`/`problems`/`changed`) — 다른 것은 둘이다.

- 고치는 것이 **표준 속성 하나와 `bpm:` 요소 하나**라 `dump()`가
  `{"multiInstance": "" | "sequential" | "parallel", "loop": 본문 | None}`을 준다.
  「반복 안 함」이면 **둘을 함께 지운다** — 하나만 남으면 보이지 않는 설정이 된다(엔진은 `bpm:loop`만
  있어도 차례로 돈다).
- **그 요소의 다른 편집기 옆에 하나 더** 붙는다(AI 태스크·호출·확장 태스크 …). 속성 패널이 두 편집기의
  고친 것을 합친다 — 이 편집기는 `bpm:loop`만 만진다.

- 「함께」는 **도는 그림이 서버일 때만** 함께 돈다(ADR-0087). PC에서는 끄지 않고 말한다 — 그림은 맞다.
- **적어 둔 것을 조용히 바꾸지 않는다.** 편집기가 다루지 않는 칸은 읽은 그대로 돌려준다.
- 「적용」을 막는 것은 **엔진·검사가 거부할 것**뿐이다 — 빈 목록·읽을 수 없는 식, 빈 「한 건 이름」,
  빈 「모은 목록」(B4), 변수 이름 규칙 위반. 마지막 관문은 계약 모델(`Loop`)이다.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError
from PySide6.QtCore import QStringListModel, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from chaeksas.contracts.bpmn_ext import Loop, is_var_name
from chaeksas.core.expr import ExprError, parse
from chaeksas.qt.theme import set_role
from chaeksas.qt.theme.tokens import SPACE_2, SPACE_3
from chaeksas.studio.name_pick import attach

#: 탭 이름.
TAB_LABEL = "반복"

#: 돌기 셋 — 캔버스 `properties()`의 `multiInstance` 값 그대로다.
MODE_NONE = ""
MODE_SEQUENTIAL = "sequential"
MODE_PARALLEL = "parallel"
MODES = (
    (MODE_NONE, "반복 안 함"),
    (MODE_SEQUENTIAL, "차례로"),
    (MODE_PARALLEL, "함께"),
)

PC_RUNS_IN_TURN = "PC BPM 프로세스에서는 함께 그려도 차례로 돕니다 (ADR-0087)."
NO_RESULT = "「한 건의 결과」가 없으면 모은 목록은 늘 빈 목록입니다."
SAME_NAME = "같은 이름이 두 칸에 있습니다: {name} — 한 번 돌 때마다 서로를 덮습니다."


class LoopEditor(QWidget):
    """반복 하나."""

    changed = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        run_location: str | None = None,
        names: QStringListModel | None = None,
    ) -> None:
        super().__init__(parent)
        self.run_location = run_location
        self._loaded: dict[str, Any] = {}
        self._quiet = False

        self.mode_picks: dict[str, QRadioButton] = {value: QRadioButton(text, self) for value, text in MODES}
        self.mode_picks[MODE_SEQUENTIAL].setToolTip("한 건씩 앞에서부터 돕니다.")
        self.mode_picks[MODE_PARALLEL].setToolTip(
            "서버 BPM 프로세스에서는 건마다 함께 기다립니다. 결과는 그래도 입력 순서로 모입니다."
        )
        self.mode_group = QButtonGroup(self)
        for one in self.mode_picks.values():
            self.mode_group.addButton(one)
        self.mode_picks[MODE_NONE].setChecked(True)

        self.collection_box = QLineEdit(self)
        self.collection_box.setPlaceholderText("목록 변수 또는 식 (필수)")
        self.item_box = QLineEdit(self)
        self.item_box.setPlaceholderText("변수 이름 (필수)")
        self.item_box.setToolTip("한 번 돌 때 그 건이 이 변수에 들어갑니다.")
        self.result_box = QLineEdit(self)
        self.result_box.setPlaceholderText("변수 이름 — 그 태스크의 출력 중 하나")
        self.result_box.setToolTip("한 번 돈 뒤 이 변수의 값을 모읍니다.")
        self.collect_box = QLineEdit(self)
        self.collect_box.setPlaceholderText("변수 이름 (필수)")
        self.collect_box.setToolTip("한 건의 결과를 입력 순서로 모은 목록이 이 변수에 들어갑니다 (B4).")
        for line in (self.collection_box, self.item_box, self.result_box, self.collect_box):
            attach(line, names)

        self.pc_note = QLabel(PC_RUNS_IN_TURN, self)
        self.pc_note.setWordWrap(True)
        set_role(self.pc_note, "muted")
        self.warning = QLabel("", self)
        self.warning.setWordWrap(True)
        set_role(self.warning, "error")
        self.note = QLabel("", self)
        self.note.setWordWrap(True)
        set_role(self.note, "muted")

        modes = QGroupBox("돌기", self)
        row = QHBoxLayout()
        for one in self.mode_picks.values():
            row.addWidget(one)
        row.addStretch(1)
        mode_layout = QVBoxLayout(modes)
        _tight(mode_layout)
        mode_layout.addLayout(row)
        mode_layout.addWidget(self.pc_note)

        self.fields = QGroupBox("목록과 결과", self)
        form = QFormLayout(self.fields)
        _tight(form)
        form.addRow("목록", self.collection_box)
        form.addRow("한 건 이름", self.item_box)
        form.addRow("한 건의 결과", self.result_box)
        form.addRow("모은 목록", self.collect_box)

        layout = QVBoxLayout(self)
        layout.setSpacing(SPACE_3)
        layout.addWidget(modes)
        layout.addWidget(self.fields)
        layout.addWidget(self.warning)
        layout.addWidget(self.note)
        layout.addStretch(1)

        for line in (self.collection_box, self.item_box, self.result_box, self.collect_box):
            line.textChanged.connect(self._touched)
        self.mode_group.buttonToggled.connect(self._touched)
        self._refresh()

    # ── 규약 ──

    def load(self, found: Mapping[str, Any]) -> None:
        """`{"multiInstance": 돌기, "loop": 본문}`을 그린다.

        표시는 없는데 `bpm:loop`가 있으면 **차례로** 보인다 — 엔진이 그렇게 돈다.
        """
        self._quiet = True
        loop = found.get("loop")
        self._loaded = dict(loop) if isinstance(loop, Mapping) else {}
        mode = str(found.get("multiInstance") or "")
        if mode not in self.mode_picks:
            mode = MODE_NONE
        if mode == MODE_NONE and self._loaded:
            mode = MODE_SEQUENTIAL
        self.mode_picks[mode].setChecked(True)
        self.collection_box.setText(str(self._loaded.get("collection") or ""))
        self.item_box.setText(str(self._loaded.get("item") or ""))
        self.result_box.setText(str(self._loaded.get("result") or ""))
        self.collect_box.setText(str(self._loaded.get("collect_into") or ""))
        self._quiet = False
        self._refresh()

    def mode(self) -> str:
        return next((value for value, pick in self.mode_picks.items() if pick.isChecked()), MODE_NONE)

    def dump(self) -> dict[str, Any]:
        """돌기와 본문 — 본문은 **읽은 것 위에** 고친 칸만 얹는다. 「반복 안 함」이면 본문이 `None`이다."""
        mode = self.mode()
        if mode == MODE_NONE:
            return {"multiInstance": MODE_NONE, "loop": None}
        out = dict(self._loaded)
        out["collection"] = self.collection_box.text().strip()
        out["item"] = self.item_box.text().strip()
        _put(out, "result", self.result_box.text().strip() or None)
        _put(out, "collect_into", self.collect_box.text().strip() or None)
        return {"multiInstance": mode, "loop": out}

    def problems(self) -> tuple[list[str], list[str]]:
        """`(적용을 막는 것, 경고)`."""
        errors: list[str] = []
        warnings: list[str] = []
        if self.mode() != MODE_NONE:
            collection = self.collection_box.text().strip()
            if not collection:
                errors.append("반복할 목록을 적으세요.")
            else:
                try:
                    parse(collection)
                except ExprError as e:
                    errors.append(f"목록 식을 읽을 수 없습니다: {e}")
            names = {
                "한 건 이름": self.item_box.text().strip(),
                "한 건의 결과": self.result_box.text().strip(),
                "모은 목록": self.collect_box.text().strip(),
            }
            if not names["한 건 이름"]:
                errors.append("「한 건 이름」을 적으세요.")
            if not names["모은 목록"]:
                errors.append("「모은 목록」을 적으세요 — 없으면 반복이 멈춥니다 (B4).")
            errors.extend(
                f"「{label}」에 변수 이름으로 쓸 수 없는 것이 있습니다: {name}"
                for label, name in names.items()
                if name and not is_var_name(name)
            )
            if not names["한 건의 결과"]:
                warnings.append(NO_RESULT)
            seen: set[str] = set()
            for name in names.values():
                if name and name in seen:
                    warnings.append(SAME_NAME.format(name=name))
                seen.add(name)
            if not errors:
                try:
                    Loop.model_validate(self.dump()["loop"])
                except ValidationError as e:
                    first = e.errors()[0]
                    where = ".".join(str(p) for p in first.get("loc", ()))
                    errors.append(f"반복 칸이 계약과 맞지 않습니다 ({where}): {first.get('msg')}")
        self.warning.setText(errors[0] if errors else "")
        self.note.setText(" ".join(warnings))
        return errors, warnings

    # ── 안쪽 ──

    def _touched(self, *_args: object) -> None:
        if self._quiet:
            return
        self._refresh()
        self.changed.emit()

    def _refresh(self) -> None:
        on = self.mode() != MODE_NONE
        self.fields.setVisible(on)
        self.pc_note.setVisible(self.mode() == MODE_PARALLEL and self.run_location != "server")
        self.problems()


def _put(out: dict[str, Any], key: str, value: Any) -> None:
    """값이 없으면 칸을 **지운다** (빈 글을 그림에 남기지 않는다)."""
    if value is None:
        out.pop(key, None)
    else:
        out[key] = value


def _tight(layout: Any) -> None:
    """묶음 안쪽 여백 — 결재 편집기와 같다."""
    layout.setContentsMargins(SPACE_2, SPACE_2, SPACE_2, SPACE_2)


__all__ = [
    "MODE_NONE",
    "MODE_PARALLEL",
    "MODE_SEQUENTIAL",
    "NO_RESULT",
    "PC_RUNS_IN_TURN",
    "SAME_NAME",
    "TAB_LABEL",
    "LoopEditor",
]
