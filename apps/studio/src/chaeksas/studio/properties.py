"""STU-04 속성 패널 — 캔버스에서 고른 요소를 편집한다.

조각 3e-2는 **모든 요소에 바로 쓸모 있는 것**부터 한다.

| 탭 | 무엇 | 어느 요소에 |
| --- | --- | --- |
| 「폼」 | 이름·설명, 흐름 조건식, 스크립트 | 전부 |
| 「JSON」 | `chk:*` 본문을 **C14 모델로 검증**하며 고친다 | `chk:*`를 가질 수 있는 요소 |

요소별 전용 폼(AI 태스크의 재생 명세·허용 도구, 결재 폼 칸 표, DMN 격자 …)은 다음 조각이다.
**지금은 JSON 탭이 그 자리를 메운다.**

적용은 **bpmn-js의 `modeling`으로** 한다 (캔버스 `setProperties`) — 그래야 실행 취소와
「저장 안 한 변경」이 함께 움직인다. 표준 속성(이름·설명·조건식·스크립트)은 한 번에 바꿔 실행
취소 한 걸음이 되지만, **`chk:*`를 함께 고치면 걸음이 여럿이 된다** — bpmn-js에 여러 명령을
한 걸음으로 묶는 간단한 길이 없다. 한 걸음으로 묶는 일은 전용 명령 처리기가 생길 때 한다.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from pydantic import ValidationError
from PySide6.QtCore import QStringListModel, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from chaeksas.contracts.bpmn_ext import ELEMENT_MODELS
from chaeksas.qt.theme import set_role
from chaeksas.studio.service_catalog import CallTarget, Catalog

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
#: 결재·확인 편집기를 붙이는 요소 (C14 `chk:approval` — 결재는 userTask, 확인은 manualTask).
APPROVAL_KINDS = frozenset({"UserTask", "ManualTask"})
#: 보내기 편집기를 붙이는 요소 (C14 `chk:email`·`chk:webhook`).
SEND_KINDS = frozenset({"SendTask"})
#: 보내기 편집기가 고르는 `chk:` 요소 — 하나만 남긴다.
SEND_CHANNELS = ("email", "webhook")
#: 호출 편집기를 붙이는 요소 (표준 `calledElement` + C14 `chk:call`).
CALL_KINDS = frozenset({"CallActivity"})
#: 반복 편집기를 붙이는 요소 (C14 §반복 — AI·UI·서비스 앱·규칙 태스크와 호출). 다른 편집기 **옆에** 붙는다.
LOOP_KINDS = frozenset({"ServiceTask", "BusinessRuleTask", "CallActivity"})


#: `chk:*`를 갖지 않는 게이트웨이 — 가지의 조건은 나가는 순서 흐름에 있다 (C14).
GATEWAY_KINDS = frozenset({"ExclusiveGateway", "ParallelGateway", "InclusiveGateway"})


def kind_label(bpmn_type: str) -> str:
    return KINDS.get(bpmn_type, bpmn_type)


def empty_chk_hint(bpmn_type: str) -> str:
    """「JSON」 탭이 비었을 때의 안내. **JSON 모양의 예시를 두지 않는다** — 흐린 글이어도
    적혀 있는 값으로 읽힌다 (게이트웨이에 `aiTask` 예시가 보여 「항목이 안 보인다」가 됐다).
    """
    if bpmn_type in GATEWAY_KINDS:
        return (
            "게이트웨이에는 chk:* 설정이 없습니다.\n"
            "가지마다의 조건식은 나가는 순서 흐름을 골라 「폼」 탭에서 봅니다."
        )
    return (
        "이 요소에는 chk:* 설정이 없습니다.\n"
        "더하려면 설정 이름을 맨 바깥 키로 적습니다 (C14 — aiTask·rule·email 등)."
    )


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
        try:
            model.model_validate(_for_model(name, value))
        except ValidationError as e:
            first = e.errors()[0] if e.errors() else {"loc": (), "msg": "?"}
            where = ".".join(str(p) for p in first["loc"])
            return {}, f"chk:{name} — {where}: {first['msg']}" if where else f"chk:{name} — {first['msg']}"
        # **`chk:task`는 통째로 오간다** — `type`·`extension`은 XML 속성이지만 그것까지
        # 함께 보내야 캔버스가 속성에 쓸 수 있다 (안 그러면 고칠 때마다 종류가 날아간다).
        out[name] = json.dumps(value, ensure_ascii=False, indent=2)
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


def _body_of(chk: dict[str, str], name: str) -> dict[str, Any] | None:
    """`chk:<name>`의 본문 글 → 사전. 읽지 못하면 `None`.

    **캔버스는 `{요소: JSON 글}`을 준다** — 사전이 아니다. 글로 받은 것을 여기서 한 번만 읽는다.
    """
    raw = chk.get(name)
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        found = json.loads(raw)
    except ValueError:
        return None
    return found if isinstance(found, dict) else None


def _task_of(chk: dict[str, str]) -> dict[str, Any] | None:
    """`chk:task` 본문 글 → `{type, extension, data}`. 읽지 못하면 `None`."""
    return _body_of(chk, "task")


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

    def __init__(self, parent: QWidget | None = None, extensions: Any = None) -> None:
        super().__init__(parent)
        self.node_id = ""
        self.loaded: dict[str, Any] = {}
        #: 확장이 기여한 편집기를 찾는 쪽 (C13). 없으면 JSON 탭이 그 자리를 메운다.
        self.extensions = extensions
        #: 지금 붙어 있는 편집기와 붙일 때의 값 (바뀐 것만 보내려고).
        self._editor: Any = None
        #: 편집기를 담은 스크롤 영역 — 탭에 들어가는 것은 이것이다 (STU-14).
        self._editor_holder: QScrollArea | None = None
        self._editor_baseline: dict[str, Any] = {}
        #: 그 편집기가 고치는 자리 — `"task"`(STU-13) 또는 `"serviceCall"`(STU-14).
        self._editor_key = ""
        #: 반복 편집기 — 다른 편집기와 **함께** 붙으므로 자리가 따로다 (`chk:loop`만 만진다).
        self._loop_editor: Any = None
        self._loop_holder: QScrollArea | None = None
        self._loop_baseline: dict[str, Any] = {}
        #: STU-14가 고를 거리 (Center 리소스 목록). 메인 창이 실행·선택 전에 채운다.
        self.catalog: Catalog = Catalog()
        #: 열린 BPM 프로세스의 실행 위치 (`chk:process.run_location`) — 결재 편집기가 서버에서
        #: 「현장 PC에서만」을 끈다 (B6과 같은 판정). 메인 창이 정의를 열 때 채운다.
        self.run_location: str | None = None
        #: 변수 이름 칸의 고를 거리 — 「변수」 탭의 이름 (STU-04). 메인 창이 그림을 읽을 때 채우고
        #: 편집기들이 **같은 모델**을 본다 (열린 편집기의 목록도 따라 바뀐다).
        self.known_names = QStringListModel(self)
        #: 이 패키지에서 부를 수 있는 정의 (`call_editor.local_targets`) — 메인 창이 열린 BPM
        #: 프로세스에서 **고를 때마다** 읽게 꽂는다(설치·저장 뒤에도 낡지 않게). `None`이면 모른다.
        self.call_targets: Callable[[], Mapping[str, CallTarget] | None] = lambda: None

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
        outer = QVBoxLayout(self.form)
        form_layout = QFormLayout()
        outer.addLayout(form_layout)
        # 칸들은 늘어나지 않는다 — 남는 높이를 아래로 모은다 (없으면 칸 사이가 벌어진다).
        outer.addStretch(1)
        form_layout.addRow("이름", self.name_box)
        form_layout.addRow("설명", self.doc_box)
        self.condition_row = ("조건식", self.condition_box)
        self.script_row = ("스크립트", self.script_box)
        form_layout.addRow(*self.condition_row)
        form_layout.addRow(*self.script_row)
        self._form_layout = form_layout

        self.json_box = QPlainTextEdit(self)
        self.json_box.setFont(QFont("JetBrains Mono"))

        self.tabs = QTabWidget(self)
        self.tabs.addTab(self.form, "폼")
        self.tabs.addTab(self.json_box, "JSON")

        self.error = QLabel("", self)
        self.error.setWordWrap(True)
        set_role(self.error, "error")
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
        self._detach_editor()
        self._detach_loop_editor()
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
        self.json_box.setPlaceholderText(empty_chk_hint(bpmn_type))
        self.json_box.setPlainText(as_text(dict(found.get("chk") or {})))
        self._show_editor(dict(found.get("chk") or {}))
        self._show_loop_editor(dict(found.get("chk") or {}))

        self._show_row(self.condition_row, bpmn_type in CONDITION_KINDS)
        self._show_row(self.script_row, bpmn_type in SCRIPT_KINDS)
        self.error.setText("")
        self.apply_button.setEnabled(False)

    def _show_editor(self, chk: dict[str, Any]) -> None:
        """태스크에 맞는 편집기를 탭으로 끼운다.

        둘이 있고 **규약은 하나다** (`load`/`dump`/`problems`/`changed`) — 여기서는 어느 쪽인지
        신경 쓰지 않는다.

        - `chk:serviceCall` → **플랫폼이 가진** STU-14 편집기 (`service_editor`).
        - `chk:task` → **확장이 기여한** 편집기 (STU-13). **Studio는 어느 확장인지 모른다** —
          `type`으로 찾아 붙일 뿐이다 (ADR-0018).
        """
        self._detach_editor()
        if str(self.loaded.get("type") or "") in CALL_KINDS:
            self._attach_call_editor(chk)
            return
        if "serviceCall" in chk:
            self._attach_service_editor(chk)
            return
        if "aiTask" in chk:
            self._attach_ai_task_editor(chk)
            return
        if "approval" in chk or str(self.loaded.get("type") or "") in APPROVAL_KINDS:
            self._attach_approval_editor(chk)
            return
        if any(name in chk for name in SEND_CHANNELS) or str(self.loaded.get("type") or "") in SEND_KINDS:
            self._attach_send_editor(chk)
            return
        if self.extensions is None:
            return
        task = _task_of(chk)
        if task is None:
            return
        task_type = str(task.get("type") or "")
        if not task_type:
            return
        found = self.extensions.editor(task_type)
        if found is None:
            return
        data = task.get("data")
        found.load(dict(data) if isinstance(data, dict) else {})
        self._attach(found, self.extensions.label(task_type), key="task")

    def _attach_service_editor(self, chk: dict[str, Any]) -> None:
        """STU-14. 고를 거리가 **Center에서** 온다 (`catalog`) — 없으면 편집기가 그렇게 말한다."""
        from chaeksas.studio.service_editor import TAB_LABEL, ServiceTaskEditor  # noqa: PLC0415

        made = ServiceTaskEditor(self.catalog, self, names=self.known_names)
        made.load(_body_of(chk, "serviceCall") or {})
        self._attach(made, TAB_LABEL, key="serviceCall")

    def _attach_ai_task_editor(self, chk: dict[str, Any]) -> None:
        """AI 태스크 (`chk:aiTask`). 서버 BPM 프로세스면 웹·데스크톱을 끈다 (B6과 같은 판정)."""
        from chaeksas.studio.ai_task_editor import TAB_LABEL, AiTaskEditor  # noqa: PLC0415

        made = AiTaskEditor(self, run_location=self.run_location, names=self.known_names)
        made.load(_body_of(chk, "aiTask") or {})
        self._attach(made, TAB_LABEL, key="aiTask")

    def _attach_approval_editor(self, chk: dict[str, Any]) -> None:
        """결재·확인 (`chk:approval`) — 아직 없는 사람 태스크에도 붙는다 (적용하면 생긴다)."""
        from chaeksas.studio.approval_editor import (  # noqa: PLC0415
            TAB_APPROVAL,
            TAB_CONFIRMATION,
            ApprovalEditor,
        )

        made = ApprovalEditor(self, run_location=self.run_location, names=self.known_names)
        made.load(_body_of(chk, "approval") or {})
        manual = str(self.loaded.get("type") or "") == "ManualTask"
        self._attach(made, TAB_CONFIRMATION if manual else TAB_APPROVAL, key="approval")

    def _attach_send_editor(self, chk: dict[str, Any]) -> None:
        """보내기 (`chk:email`·`chk:webhook`) — 아직 없는 보내기 태스크에도 붙는다 (적용하면 생긴다)."""
        from chaeksas.studio.send_editor import TAB_LABEL, SendEditor  # noqa: PLC0415

        made = SendEditor(self, names=self.known_names)
        bodies = {name: _body_of(chk, name) for name in SEND_CHANNELS}
        made.load({name: body for name, body in bodies.items() if body is not None})
        self._attach(made, TAB_LABEL, key="send")

    def _attach_call_editor(self, chk: dict[str, Any]) -> None:
        """BPM 프로세스 호출 (`calledElement` + `chk:call`). 위임 대상은 Center 목록(`catalog.bots`)이다."""
        from chaeksas.studio.call_editor import TAB_LABEL, CallEditor  # noqa: PLC0415

        made = CallEditor(
            self,
            run_location=self.run_location,
            targets=self.call_targets(),
            bots=self.catalog.bots,
        )
        made.load({"calledElement": str(self.loaded.get("calledElement") or ""), "call": _body_of(chk, "call") or {}})
        self._attach(made, TAB_LABEL, key="call")

    def _show_loop_editor(self, chk: dict[str, Any]) -> None:
        """반복을 쓸 수 있는 요소에 「반복」 탭을 **하나 더** 끼운다 — 다른 편집기 탭 뒤에, 고르지는 않는다."""
        self._detach_loop_editor()
        if str(self.loaded.get("type") or "") not in LOOP_KINDS:
            return
        from chaeksas.studio.loop_editor import TAB_LABEL, LoopEditor  # noqa: PLC0415

        made = LoopEditor(self, run_location=self.run_location, names=self.known_names)
        made.load({"multiInstance": str(self.loaded.get("multiInstance") or ""), "loop": _body_of(chk, "loop")})
        self._loop_editor = made
        self._loop_baseline = dict(made.dump())
        made.changed.connect(self._refresh_apply)
        holder = self._holder_for(made)
        self._loop_holder = holder
        self.tabs.insertTab(self.tabs.indexOf(self.json_box), holder, TAB_LABEL)

    def _detach_loop_editor(self) -> None:
        found = self._loop_editor
        if found is None:
            return
        try:
            found.changed.disconnect(self._refresh_apply)
        except (RuntimeError, TypeError):  # pragma: no cover — 이미 끊겼다
            pass
        holder = self._loop_holder
        if holder is not None:
            index = self.tabs.indexOf(holder)
            if index >= 0:
                self.tabs.removeTab(index)
            holder.takeWidget()
            holder.deleteLater()
        self._loop_holder = None
        found.setParent(None)
        self._loop_editor = None
        self._loop_baseline = {}

    def _holder_for(self, found: QWidget) -> QScrollArea:
        """**세로로 스크롤되게 담는다** — 창이 낮아도 편집기의 표가 한 줄로 찌그러지지 않는다."""
        holder = QScrollArea(self)
        holder.setWidgetResizable(True)
        holder.setFrameShape(QFrame.Shape.NoFrame)
        holder.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        holder.setWidget(found)
        return holder

    def _attach(self, found: Any, label: str, *, key: str) -> None:
        self._editor = found
        self._editor_key = key
        self._editor_baseline = dict(found.dump())
        changed = getattr(found, "changed", None)
        if changed is not None:
            changed.connect(self._refresh_apply)
        holder = self._holder_for(found)
        self._editor_holder = holder
        self.tabs.insertTab(1, holder, label)
        self.tabs.setCurrentIndex(1)

    def _detach_editor(self) -> None:
        found = self._editor
        if found is None:
            return
        changed = getattr(found, "changed", None)
        if changed is not None:
            try:
                changed.disconnect(self._refresh_apply)
            except (RuntimeError, TypeError):  # pragma: no cover — 이미 끊겼다
                pass
        holder = self._editor_holder
        if holder is not None:
            index = self.tabs.indexOf(holder)
            if index >= 0:
                self.tabs.removeTab(index)
            holder.takeWidget()
            holder.deleteLater()
        self._editor_holder = None
        found.setParent(None)
        self._editor = None
        self._editor_key = ""
        self._editor_baseline = {}

    def _editor_patch(self) -> tuple[dict[str, Any] | None, str | None]:
        """편집기가 바꾼 것 → `chk.task.data`. 오류가 있으면 **「적용」을 막는다**."""
        found = self._editor
        if found is None:
            return None, None
        wanted = dict(found.dump())
        if wanted == self._editor_baseline:
            return None, None
        valid = getattr(found, "problems", None)
        if callable(valid):
            errors, _ = valid()
            if errors:
                return None, errors[0]
        return wanted, None

    def _show_row(self, row: tuple[str, QWidget], visible: bool) -> None:
        label, widget = row
        widget.setVisible(visible)
        found = self._form_layout.labelForField(widget)
        if found is not None:
            found.setVisible(visible)

    # ── 적용 ──

    def patch(self) -> tuple[dict[str, Any], str | None]:
        """고친 것만 모은다. 틀린 JSON이면 `(빈 것, 사유)`.

        반복 편집기의 것은 **마지막에 얹는다** — 다른 편집기가 고친 `chk:*`와 한 묶음으로 가되
        `chk:loop` 자리만 쓴다 (서로의 칸을 지우지 않는다).
        """
        changes, problem = self._patch_main()
        if problem is not None:
            return {}, problem
        loop, problem = self._loop_patch()
        if problem is not None:
            return {}, problem
        if loop:
            if "multiInstance" in loop:
                changes["multiInstance"] = loop["multiInstance"]
            if "loop" in loop:
                changes["chk"] = {**changes.get("chk", {}), "loop": loop["loop"]}
        return changes, None

    def _loop_patch(self) -> tuple[dict[str, Any], str | None]:
        """반복 편집기가 바꾼 것 → `{"multiInstance": …, "loop": 글 | None}` 중 바뀐 쪽만."""
        found = self._loop_editor
        if found is None:
            return {}, None
        wanted = dict(found.dump())
        if wanted == self._loop_baseline:
            return {}, None
        errors, _ = found.problems()
        if errors:
            return {}, errors[0]
        out: dict[str, Any] = {}
        if wanted["multiInstance"] != self._loop_baseline.get("multiInstance"):
            out["multiInstance"] = wanted["multiInstance"]
        if wanted["loop"] != self._loop_baseline.get("loop"):
            body = wanted["loop"]
            # 그림에 없던 것을 지우라고 보내지 않는다 — 캔버스는 없는 것을 지우며 걸음만 늘린다.
            had = _body_of(dict(self.loaded.get("chk") or {}), "loop") is not None
            if body is not None:
                out["loop"] = json.dumps(body, ensure_ascii=False, indent=2)
            elif had:
                out["loop"] = None
        return out, None

    def _patch_main(self) -> tuple[dict[str, Any], str | None]:
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

        data, problem = self._editor_patch()
        if problem is not None:
            return {}, problem
        if data is not None:
            if self._editor_key in ("serviceCall", "approval", "aiTask"):
                # STU-14·결재·AI 태스크는 `chk:<이름>` **통째로** 쓴다 (`data` 같은 포장이 없다).
                changes["chk"] = {self._editor_key: json.dumps(data, ensure_ascii=False, indent=2)}
                return changes, None
            if self._editor_key == "call":
                # 표준 속성 하나와 `chk:call` **통째로** — 바뀐 쪽만 보낸다(빈 `chk:call`을 새로 달지 않는다).
                if data["calledElement"] != str(self.loaded.get("calledElement") or ""):
                    changes["calledElement"] = data["calledElement"]
                if data["call"] != (_body_of(dict(self.loaded.get("chk") or {}), "call") or {}):
                    changes["chk"] = {"call": json.dumps(data["call"], ensure_ascii=False, indent=2)}
                return changes, None
            if self._editor_key == "send":
                # 고른 채널 하나만 남긴다 — 다른 쪽이 그림에 있었으면 `None`으로 적어 캔버스가 지운다.
                before = dict(self.loaded.get("chk") or {})
                sent: dict[str, Any] = {name: None for name in SEND_CHANNELS if name in before and name not in data}
                sent.update({name: json.dumps(body, ensure_ascii=False, indent=2) for name, body in data.items()})
                changes["chk"] = sent
                return changes, None
            # `chk:task`는 `{type, extension, data}` **통째로** 오간다 — 본문만 보내면
            # 고칠 때마다 `type`·`extension`이 날아간다 (C1 — 패키지가 그 확장을 요구하지 않게 된다).
            task = _task_of(dict(self.loaded.get("chk") or {})) or {}
            whole = {**task, "data": data}
            changes["chk"] = {"task": json.dumps(whole, ensure_ascii=False, indent=2)}
            return changes, None

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
    "CALL_KINDS",
    "CONDITION_KINDS",
    "EMPTY_TEXT",
    "GATEWAY_KINDS",
    "KINDS",
    "LOOP_KINDS",
    "SCRIPT_KINDS",
    "SEND_KINDS",
    "Properties",
    "as_text",
    "check_chk",
    "empty_chk_hint",
    "kind_label",
]
