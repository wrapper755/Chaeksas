"""STU-04 속성 패널 — 캔버스에서 고른 요소를 편집한다.

조각 3e-2는 **모든 요소에 바로 쓸모 있는 것**부터 한다.

| 탭 | 무엇 | 어느 요소에 |
| --- | --- | --- |
| 「폼」 | 이름·설명, 흐름 조건식, 스크립트 | 전부 |
| 「JSON」 | `chk:*` 본문을 **C14 모델로 검증**하며 고친다 | `chk:*`를 가질 수 있는 요소 |

요소별 전용 폼(AI 태스크의 재생 명세·허용 도구, 결재 폼 칸 표, DMN 격자 …)은 다음 조각이다 —
툴팩·리소스 목록처럼 아직 없는 것에 기대기 때문이다. **지금은 JSON 탭이 그 자리를 메운다.**

적용은 **bpmn-js의 `modeling`으로** 한다 (캔버스 `setProperties`) — 그래야 실행 취소와
「저장 안 한 변경」이 함께 움직인다. 표준 속성(이름·설명·조건식·스크립트)은 한 번에 바꿔 실행
취소 한 걸음이 되지만, **`chk:*`를 함께 고치면 걸음이 여럿이 된다** — bpmn-js에 여러 명령을
한 걸음으로 묶는 간단한 길이 없다. 한 걸음으로 묶는 일은 전용 명령 처리기가 생길 때 한다.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from chaeksas.contracts.bpmn_ext import ELEMENT_MODELS

EMPTY_TEXT = "캔버스에서 요소를 선택하면 속성을 편집할 수 있습니다."

#: BPMN 요소 이름 → 한국어 종류 (STU-04 머리, 용어집 §2 「태스크 종류」).
KINDS = {
    "Process": "BPM 프로세스",
    "StartEvent": "시작 이벤트",
    "EndEvent": "종료 이벤트",
    "IntermediateCatchEvent": "중간 받기",
    "IntermediateThrowEvent": "중간 던지기",
    "BoundaryEvent": "경계 이벤트",
    "ServiceTask": "서비스 태스크 (AI·UI·서비스 앱·파일 목록)",
    "UserTask": "결재",
    "ManualTask": "확인",
    "ScriptTask": "스크립트",
    "BusinessRuleTask": "규칙 (DMN)",
    "SendTask": "보내기 (메일·웹훅)",
    "ReceiveTask": "메시지 받기",
    "CallActivity": "BPM 프로세스 호출",
    "SubProcess": "하위 프로세스",
    "ExclusiveGateway": "배타 게이트웨이",
    "ParallelGateway": "병렬 게이트웨이",
    "InclusiveGateway": "포함 게이트웨이",
    "SequenceFlow": "순서 흐름",
    "DataObjectReference": "데이터 객체 (파일 출력)",
    "TextAnnotation": "주석",
}

#: 조건식을 쓸 수 있는 요소 (C14 — 게이트웨이의 나가는 흐름).
CONDITION_KINDS = frozenset({"SequenceFlow"})
#: 스크립트를 쓸 수 있는 요소.
SCRIPT_KINDS = frozenset({"ScriptTask"})


def kind_label(bpmn_type: str) -> str:
    return KINDS.get(bpmn_type, bpmn_type)


def check_chk(text: str) -> tuple[dict[str, str], str | None]:
    """JSON 탭의 글 → `{요소 이름: 본문}`. 틀리면 `(빈 것, 사유 한 줄)`.

    **C14 모델로 검증한다** (B1과 같은 눈) — 저장한 뒤 실행 전 검사에서야 아는 것보다 낫다.
    """
    body = text.strip()
    if not body:
        return {}, None
    try:
        raw = json.loads(body)
    except ValueError as e:
        return {}, f"JSON이 아닙니다: {e}"
    if not isinstance(raw, dict):
        return {}, "맨 바깥은 `{\"aiTask\": {…}}` 꼴의 객체여야 합니다."

    out: dict[str, str] = {}
    for name, value in raw.items():
        model = ELEMENT_MODELS.get(name)
        if model is None:
            known = ", ".join(sorted(ELEMENT_MODELS))
            return {}, f"모르는 `chk:` 요소입니다: {name} (쓸 수 있는 것: {known})"
        payload = value.get("data", value) if name == "task" and isinstance(value, dict) else value
        try:
            model.model_validate(_for_model(name, value))
        except ValidationError as e:
            first = e.errors()[0] if e.errors() else {"loc": (), "msg": "?"}
            where = ".".join(str(p) for p in first["loc"])
            return {}, f"chk:{name} — {where}: {first['msg']}" if where else f"chk:{name} — {first['msg']}"
        out[name] = json.dumps(payload if name == "task" else value, ensure_ascii=False, indent=2)
    return out, None


def _for_model(name: str, value: Any) -> Any:
    """`chk:task`만 XML 속성(`type`·`extension`)이 따로다 (C14 §태스크 종류)."""
    if name != "task" or not isinstance(value, dict):
        return value
    return {
        "type": value.get("type", ""),
        "extension": value.get("extension", ""),
        "data": value.get("data", {}),
    }


def as_text(chk: dict[str, str]) -> str:
    """캔버스가 준 `{요소: 본문 글}` → JSON 탭에 보일 한 덩어리."""
    if not chk:
        return ""
    body: dict[str, Any] = {}
    for name, raw in sorted(chk.items()):
        try:
            body[name] = json.loads(raw) if raw.strip() else {}
        except ValueError:
            body[name] = raw  # 읽지 못한 것도 **숨기지 않고** 글 그대로 보인다
    return json.dumps(body, ensure_ascii=False, indent=2)


class Properties(QWidget):
    """STU-04. 「적용」을 누를 때만 캔버스로 간다 — 타이핑마다 그림을 흔들지 않는다."""

    #: `(노드 id, 고칠 것)` — 메인 창이 캔버스에 넘긴다.
    applying = Signal(str, dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.node_id = ""
        self.loaded: dict[str, Any] = {}

        self.head = QLabel(EMPTY_TEXT, self)
        self.head.setWordWrap(True)
        self.head.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        self.name_box = QLineEdit(self)
        self.doc_box = QPlainTextEdit(self)
        self.doc_box.setMaximumHeight(80)
        self.condition_box = QLineEdit(self)
        self.condition_box.setPlaceholderText("비우면 항상 진행합니다 (chk-expr)")
        self.script_box = QPlainTextEdit(self)
        self.script_box.setPlaceholderText("변수 = 식  (한 줄에 하나, ADR-0025)")

        self.form = QWidget(self)
        form_layout = QFormLayout(self.form)
        form_layout.addRow("이름", self.name_box)
        form_layout.addRow("설명", self.doc_box)
        self.condition_row = ("조건식", self.condition_box)
        self.script_row = ("스크립트", self.script_box)
        form_layout.addRow(*self.condition_row)
        form_layout.addRow(*self.script_row)
        self._form_layout = form_layout

        self.json_box = QPlainTextEdit(self)
        self.json_box.setFont(QFont("JetBrains Mono"))
        self.json_box.setPlaceholderText('{\n  "aiTask": {"goal": "…", "domain": "llm"}\n}')

        self.tabs = QTabWidget(self)
        self.tabs.addTab(self.form, "폼")
        self.tabs.addTab(self.json_box, "JSON")

        self.error = QLabel("", self)
        self.error.setWordWrap(True)
        self.error.setProperty("role", "error")
        self.apply_button = QPushButton("적용", self)
        self.apply_button.clicked.connect(self.apply)

        bottom = QHBoxLayout()
        bottom.addWidget(self.error, 1)
        bottom.addWidget(self.apply_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.head)
        layout.addWidget(self.tabs, 1)
        layout.addLayout(bottom)

        for box in (self.name_box, self.condition_box):
            box.textChanged.connect(self._refresh_apply)
        for area in (self.doc_box, self.script_box, self.json_box):
            area.textChanged.connect(self._refresh_apply)
        self.show_nothing()

    # ── 보이기 ──

    def show_nothing(self) -> None:
        self.node_id = ""
        self.loaded = {}
        self.head.setText(EMPTY_TEXT)
        self.tabs.setVisible(False)
        self.error.setText("")
        self.apply_button.setEnabled(False)

    def show_element(self, found: dict[str, Any]) -> None:
        """캔버스의 `properties(id)` 결과를 그린다."""
        self.node_id = str(found.get("id") or "")
        self.loaded = dict(found)
        bpmn_type = str(found.get("type") or "")
        self.head.setText(
            f"<b>{found.get('name') or self.node_id}</b> · {kind_label(bpmn_type)}"
            f" <span style='opacity:0.6'>{self.node_id}</span>"
        )
        self.tabs.setVisible(True)
        self.name_box.setText(str(found.get("name") or ""))
        self.doc_box.setPlainText(str(found.get("documentation") or ""))
        self.condition_box.setText(str(found.get("condition") or ""))
        self.script_box.setPlainText(str(found.get("script") or ""))
        self.json_box.setPlainText(as_text(dict(found.get("chk") or {})))

        self._show_row(self.condition_row, bpmn_type in CONDITION_KINDS)
        self._show_row(self.script_row, bpmn_type in SCRIPT_KINDS)
        self.error.setText("")
        self.apply_button.setEnabled(False)

    def _show_row(self, row: tuple[str, QWidget], visible: bool) -> None:
        label, widget = row
        widget.setVisible(visible)
        found = self._form_layout.labelForField(widget)
        if found is not None:
            found.setVisible(visible)

    # ── 적용 ──

    def patch(self) -> tuple[dict[str, Any], str | None]:
        """고친 것만 모은다. 틀린 JSON이면 `(빈 것, 사유)`."""
        changes: dict[str, Any] = {}
        if self.name_box.text() != (self.loaded.get("name") or ""):
            changes["name"] = self.name_box.text()
        if self.doc_box.toPlainText() != (self.loaded.get("documentation") or ""):
            changes["documentation"] = self.doc_box.toPlainText()
        bpmn_type = str(self.loaded.get("type") or "")
        if bpmn_type in CONDITION_KINDS and self.condition_box.text() != (self.loaded.get("condition") or ""):
            changes["condition"] = self.condition_box.text()
        if bpmn_type in SCRIPT_KINDS and self.script_box.toPlainText() != (self.loaded.get("script") or ""):
            changes["script"] = self.script_box.toPlainText()

        text = self.json_box.toPlainText()
        if text.strip() != as_text(dict(self.loaded.get("chk") or {})).strip():
            wanted, problem = check_chk(text)
            if problem is not None:
                return {}, problem
            before = dict(self.loaded.get("chk") or {})
            # 없어진 것은 `None`으로 적어 캔버스가 지우게 한다.
            chk: dict[str, Any] = {name: None for name in before if name not in wanted}
            chk.update(wanted)
            changes["chk"] = chk
        return changes, None

    @property
    def unapplied(self) -> bool:
        """적용 안 한 편집이 있나 (STU-04 — 저장·전환 전에 묻는다)."""
        if not self.node_id:
            return False
        changes, problem = self.patch()
        return bool(changes) or problem is not None

    def _refresh_apply(self) -> None:
        if not self.node_id:
            return
        changes, problem = self.patch()
        self.error.setText(problem or "")
        self.apply_button.setEnabled(bool(changes) and problem is None)

    def apply(self) -> bool:
        changes, problem = self.patch()
        if problem is not None:
            self.error.setText(problem)
            return False
        if not changes:
            return True
        self.applying.emit(self.node_id, changes)
        return True


__all__ = [
    "CONDITION_KINDS",
    "EMPTY_TEXT",
    "KINDS",
    "SCRIPT_KINDS",
    "Properties",
    "as_text",
    "check_chk",
    "kind_label",
]
