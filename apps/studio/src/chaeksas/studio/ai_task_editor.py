"""STU-04 AI 태스크 편집기 — `chk:aiTask` (C14 §AI 태스크, ADR-0008·ADR-0028).

속성 패널이 `chk:aiTask`가 있는 태스크를 만나면 탭으로 끼운다. **규약은 결재·보내기·STU-14와 같다**
(`load`/`dump`/`problems`/`changed`).

- **적어 둔 것을 조용히 바꾸지 않는다.** 편집기가 다루지 않는 칸(`web` — 계약에 있지만 웹 환경을 주는
  확장이 없다)은 읽은 그대로 돌려준다.
- 「지시문」(`forbidden_actions`·`confirm_triggers`)과 「제한 시간」(`limits.timeout_s`)은 엔진이 읽는다
  ([ADR-0105](../../../../docs/decisions/0105-ai-task-limits-and-instructions.md)) — 금지 행동은 **모델에게
  주는 말일 뿐**이라 화면도 그렇게 말한다. 비우면 BPM 프로세스 기본값(`chk:defaults`)을 따른다.
  업무 파라미터도 그 줄을 고치지 않았으면 **읽은 값 그대로** 간다(글로 보였다 되읽으면 모양이 바뀔 수 있다).
- 「적용」을 막는 것은 **엔진·검사가 거부할 것**뿐이다 — 결과 이름(빈 칸·겹침·변수 규칙, B8 타입),
  업무 파라미터(빈 이름·겹침·타입에 맞지 않는 값), 도구 없는 `replay: full`(B12), 서버에서 웹·데스크톱(B6).
  내장이 아닌 도구·앱 이름 없는 데스크톱·빈 목표·번호처럼 보이는 `int` 결과는 경고다.
- 허용 도구의 고를 거리는 **내장 도구**(`core.tools`)다 — 확장이 기여하는 도구는 없다(ADR-0050).
  `web`·`desktop` 환경의 도구는 **저절로 허용되므로** 여기 적지 않는다 (C14, ADR-0037).
- 마지막 관문은 계약 모델(`AiTask`)이다 — 여기서 놓친 것도 그것이 잡는다.
- **목표 미리보기**는 엔진이 모델에게 함께 줄 값의 **이름**이다 — 고르는 함수가 엔진과 같다
  (`goal_names`, C14 §AI 태스크가 보는 값). 후보는 「변수」 탭의 고를 거리와 실행이 심는 변수다.
- 「재생 명세」 한 줄은 **열린 작업 폴더의 `memory/specs.json`**을 읽는다 (ADR-0028, `replay_specs`).
  「명세 잊기」는 그림이 아니라 그 파일을 바꾸므로 **「적용」을 기다리지 않고**, 되돌릴 수 없어 확인 창의
  기본이 「취소」다. 시험 실행 중에는 끈다(끝날 때 같은 파일에 배운 것을 적는다).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from pydantic import ValidationError
from PySide6.QtCore import QStringListModel, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from chaeksas.contracts.bpmn_ext import VALUE_TYPES, AiTask, is_var_name, looks_like_code
from chaeksas.contracts.manifest import PC_ONLY_DOMAINS
from chaeksas.contracts.replay import REPLAY_DEFAULT, ReplaySpec
from chaeksas.core.engine import BUILTIN_NOW, BUILTIN_RUN_ID, BUILTIN_TODAY, goal_names
from chaeksas.core.files import Workspace
from chaeksas.core.tools import builtin_tools
from chaeksas.qt.theme import set_role
from chaeksas.qt.theme.tokens import SPACE_2, SPACE_3
from chaeksas.studio.name_pick import NameDelegate
from chaeksas.studio.replay_specs import ReplaySpecs, SpecsUnreadable

#: 탭 이름.
TAB_LABEL = "AI 태스크"

#: 대상 환경 (C1 `KNOWN_DOMAINS`) — 보이는 순서와 글.
DOMAINS = (
    ("llm", "LLM"),
    ("api", "API"),
    ("doc", "문서"),
    ("web", "웹"),
    ("desktop", "데스크톱"),
)

#: `replay` (C14 §재생) — 보이는 순서, 글, 툴팁(좁은 패널에서 라디오 글이 잘리지 않게 설명은 툴팁으로).
REPLAYS = (
    ("plan", "계획 (기본)", "도구 차례를 되밟고 마지막 값 추출만 모델에게 한 번 — 도구가 읽고 모델이 판단할 때"),
    ("full", "전부", "도구 차례를 되밟고 답도 기억에서 — 모델을 부르지 않는다. 도구가 일을 할 때"),
    ("none", "안 함", "기억을 쓰지 않는다 — 결정 수행에서도 모델이 판단한다. 매번 판단이 다를 때"),
)

#: 값 타입 (C14 `VALUE_TYPES`) — 보이는 순서.
TYPES = ("string", "int", "number", "bool", "list", "dict", "date")
assert set(TYPES) == VALUE_TYPES

#: 「틀 넣기」가 넣는 목표의 뼈대 (C14 — 권장 머리말).
GOAL_OUTLINE = "## 상황\n\n\n## 할 일\n\n\n## 판단하지 않는 것\n\n\n## 반환\n"

PARAM_COLUMNS = ("이름", "타입", "값")
RESULT_COLUMNS = ("이름 (변수명)", "타입")
#: 표가 처음부터 보이는 줄 수.
VISIBLE_ROWS = 3

SERVER_NO_SCREEN = "서버 BPM 프로세스는 웹·데스크톱 AI 태스크를 쓸 수 없습니다 (실행 전 검사 B6)."
SCREEN_TOOLS_NOTE = "이 환경의 도구(화면 보기·조작)는 저절로 허용됩니다 — 여기 고르지 않습니다."
NO_WEB_ENVIRONMENT = "웹 환경을 주는 확장이 아직 없습니다 — 실행 전 사전 점검이 막습니다."
FORBIDDEN_NOTE = "모델에게 주는 말입니다 — 막지는 않습니다. 막으려면 허용 도구를 줄이세요."
CONFIRM_NOTE = "이 상황이면 멈춥니다 — PC는 사람 확인, 서버나 ESCALATED 경계가 있으면 오류 경계로."
INSTRUCTIONS_NOTE = "줄마다 하나. 비우면 BPM 프로세스 기본값을 따릅니다."

#: 실행이 심는 변수 — 목표에 이름이 나오면 이것도 모델에게 간다 (엔진 `_seen_by`).
SEEDED_NAMES = (BUILTIN_TODAY, BUILTIN_NOW, BUILTIN_RUN_ID)
GOAL_PREVIEW_NONE = "목표에 이름이 나오는 변수가 없습니다 — 모델은 업무 파라미터만 봅니다."

#: 「재생 명세」 한 줄 (STU-04, ADR-0028).
SPEC_NONE = "명세 없음 — 자율 수행으로 시험 실행하면 배웁니다."
SPEC_NOT_USED = "재생하지 않으므로 명세를 쓰지 않습니다."
SPEC_NO_PROCESS = "열린 BPM 프로세스가 없어 명세를 모릅니다."
SPEC_RUNNING = "시험 실행이 끝난 뒤에 잊을 수 있습니다."
#: 도구 차례를 이만큼까지 보이고 나머지는 「…」 (다 보이는 것은 툴팁).
SPEC_TOOLS_SHOWN = 3
FORGET_TITLE = "명세 잊기"
FORGET_TIP = "이 태스크의 명세만 지웁니다 — 「적용」을 기다리지 않고 곧바로 파일에 씁니다."
FORGET_TEXT = (
    "이 AI 태스크의 재생 명세(도구 {count}단계)를 지웁니다.\n\n"
    "되돌릴 수 없습니다. 다시 배우려면 자율 수행으로 시험 실행하세요."
)

_TRUE = {"true", "예", "참", "1", "yes"}
_FALSE = {"false", "아니오", "거짓", "0", "no"}
#: 표 칸에 읽은 값을 붙여 두는 자리 — 줄을 고치지 않았으면 그 값을 그대로 돌려준다.
_ORIGINAL = Qt.ItemDataRole.UserRole + 1


def builtin_tool_descriptions() -> dict[str, str]:
    """내장 도구 이름 → 설명 (실행 때 모델에게 가는 그 설명이다)."""
    return {name: made.spec.description for name, made in builtin_tools(Workspace()).items()}


class AiTaskEditor(QWidget):
    """AI 태스크 하나. `run_location`이 `server`면 웹·데스크톱을 끈다."""

    changed = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        run_location: str | None = None,
        names: QStringListModel | None = None,
        specs: ReplaySpecs | None = None,
        node_id: str = "",
        running: Callable[[], bool] = lambda: False,
        loop_item: str = "",
    ) -> None:
        super().__init__(parent)
        self.run_location = run_location
        #: 목표 미리보기의 후보 — 「변수」 탭의 고를 거리 (같은 모델을 본다).
        self.names = names
        #: 이 태스크의 명세를 찾는 자리 (`None`이면 열린 BPM 프로세스가 없다).
        self.specs = specs
        self.node_id = node_id
        #: 시험 실행 중인가 — 그동안은 「명세 잊기」를 끈다.
        self.running = running
        #: 이 노드의 반복 항목 (`chk:loop.item`) — 목표에 없어도 모델에게 간다.
        self.loop_item = loop_item
        self._loaded: dict[str, Any] = {}
        self._quiet = False
        self._builtin = builtin_tool_descriptions()
        lines = self.fontMetrics().lineSpacing()

        # 입력
        self.goal_box = QPlainTextEdit(self)
        self.goal_box.setPlaceholderText("Markdown — 값은 적지 않고 변수 이름으로 가리킵니다")
        self.goal_box.setFixedHeight(lines * 9)
        self.outline_button = QPushButton("틀 넣기", self)
        self.outline_button.setObjectName("Secondary")
        self.outline_button.setToolTip("권장 머리말(상황·할 일·판단하지 않는 것·반환)을 넣습니다. 목표가 비었을 때만.")
        self.goal_hint = QLabel("목표에 이름이 나오는 변수와 업무 파라미터만 모델에게 갑니다.", self)
        self.goal_hint.setWordWrap(True)
        set_role(self.goal_hint, "muted")
        self.goal_preview = QLabel("", self)
        self.goal_preview.setWordWrap(True)
        set_role(self.goal_preview, "muted")

        self.domain_picks: dict[str, QRadioButton] = {}
        self.domain_group = QButtonGroup(self)
        for value, text in DOMAINS:
            one = QRadioButton(text, self)
            self.domain_picks[value] = one
            self.domain_group.addButton(one)
        self.domain_picks["llm"].setChecked(True)
        self.domain_note = QLabel("", self)
        self.domain_note.setWordWrap(True)
        set_role(self.domain_note, "muted")
        self.app_box = QLineEdit(self)
        self.app_box.setPlaceholderText("띄울 앱 이름 — 비우면 BPM 프로세스 기본값")
        self.app_box.setToolTip("그 PC Worker의 desktop-apps.json에 같은 이름의 창 조건이 있어야 붙습니다.")

        self.tool_checks: dict[str, QCheckBox] = {}
        self.tools_column = QVBoxLayout()
        self.tools_column.setSpacing(SPACE_2)
        self.tool_input = QLineEdit(self)
        self.tool_input.setPlaceholderText("내장이 아닌 도구 이름 — 「추가」")
        self.add_tool = QPushButton("추가", self)
        self.add_tool.setObjectName("Secondary")
        self.tools_note = QLabel("고른 도구만 모델에게 알려 줍니다. 밖의 도구를 부르면 실행 오류입니다.", self)
        self.tools_note.setWordWrap(True)
        set_role(self.tools_note, "muted")

        self.params = _table(PARAM_COLUMNS, self)
        self.add_param = QPushButton("줄 더하기", self)
        self.add_param.setObjectName("Secondary")
        self.drop_param = QPushButton("줄 삭제", self)
        self.drop_param.setObjectName("Secondary")

        # 출력
        self.results = _table(RESULT_COLUMNS, self)
        self.results.setItemDelegateForColumn(0, NameDelegate(names, self.results))
        self.add_result = QPushButton("줄 더하기", self)
        self.add_result.setObjectName("Secondary")
        self.drop_result = QPushButton("줄 삭제", self)
        self.drop_result.setObjectName("Secondary")

        # 지시문 (ADR-0105)
        self.forbidden_box = QPlainTextEdit(self)
        self.forbidden_box.setPlaceholderText("예: 삭제 버튼을 누르지 않는다")
        self.forbidden_box.setFixedHeight(lines * 4)
        self.confirm_box = QPlainTextEdit(self)
        self.confirm_box.setPlaceholderText("예: 로그인 화면이 나타남")
        self.confirm_box.setFixedHeight(lines * 4)

        # 재생·실행 제한
        self.replay_picks: dict[str, QRadioButton] = {}
        self.replay_group = QButtonGroup(self)
        for value, text, tip in REPLAYS:
            one = QRadioButton(text, self)
            one.setToolTip(tip)
            self.replay_picks[value] = one
            self.replay_group.addButton(one)
        self.replay_picks[REPLAY_DEFAULT].setChecked(True)
        self.spec_line = QLabel("", self)
        self.spec_line.setWordWrap(True)
        self.spec_tools = QLabel("", self)
        self.spec_tools.setWordWrap(True)
        set_role(self.spec_tools, "muted")
        self.forget_button = QPushButton(FORGET_TITLE, self)
        self.forget_button.setObjectName("Secondary")
        self.forget_button.setToolTip(FORGET_TIP)
        self.max_steps_box = QSpinBox(self)
        self.max_steps_box.setRange(0, 500)
        self.max_steps_box.setSpecialValueText("기본")
        self.max_steps_box.setToolTip("비우면 BPM 프로세스 기본값, 그것도 없으면 8단계(웹·데스크톱은 30단계)입니다.")
        self.timeout_box = QSpinBox(self)
        self.timeout_box.setRange(0, 86_400)
        self.timeout_box.setSpecialValueText("없음")
        self.timeout_box.setToolTip(
            "비우면 BPM 프로세스 기본값, 그것도 없으면 한도가 없습니다. 넘으면 업무 실패(TASK_FAILED)입니다 —"
            " 하던 호출은 끊지 않고 다음 일을 시작하기 전에 멈춥니다."
        )

        self.warning = QLabel("", self)
        self.warning.setWordWrap(True)
        set_role(self.warning, "error")
        self.note = QLabel("", self)
        self.note.setWordWrap(True)
        set_role(self.note, "muted")

        #: 파일에서 읽은 이 태스크의 명세와 못 읽은 까닭 (`refresh_spec`이 채운다).
        self._spec: ReplaySpec | None = None
        self._spec_error = ""

        self._build_layout()
        for name in self._builtin:
            self._add_tool_check(name)
        self._wire()
        self.refresh_spec()

    # ── 짜기 ──

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(SPACE_3)
        layout.addWidget(self._goal_box())
        layout.addWidget(self._domain_box())
        layout.addWidget(self._tools_box())
        layout.addWidget(self._table_box("업무 파라미터", self.params, self.add_param, self.drop_param,
                                         "재생 때도 같은 값이 갑니다. 값은 타입에 맞게 — list·dict는 JSON."))
        layout.addWidget(self._table_box("결과 필드", self.results, self.add_result, self.drop_result,
                                         "모델이 돌려줄 필드입니다. 같은 이름의 변수가 됩니다."))
        layout.addWidget(self._instructions_box())
        layout.addWidget(self._replay_box())
        layout.addWidget(self.note)
        layout.addWidget(self.warning)
        layout.addStretch(1)

    def _goal_box(self) -> QGroupBox:
        box = QGroupBox("목표", self)
        column = QVBoxLayout(box)
        _tight(column)
        row = QHBoxLayout()
        row.addWidget(self.goal_hint, 1)
        row.addWidget(self.outline_button)
        column.addLayout(row)
        column.addWidget(self.goal_box)
        column.addWidget(self.goal_preview)
        return box

    def _domain_box(self) -> QGroupBox:
        box = QGroupBox("대상 환경", self)
        column = QVBoxLayout(box)
        _tight(column)
        row = QHBoxLayout()
        row.setSpacing(SPACE_3)
        for one in self.domain_picks.values():
            row.addWidget(one)
        row.addStretch(1)
        column.addLayout(row)
        column.addWidget(self.domain_note)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.addRow("띄울 앱", self.app_box)
        self._domain_form = form
        column.addLayout(form)
        return box

    def _tools_box(self) -> QGroupBox:
        box = QGroupBox("허용 도구", self)
        column = QVBoxLayout(box)
        _tight(column)
        column.addLayout(self.tools_column)
        row = QHBoxLayout()
        row.setSpacing(SPACE_2)
        row.addWidget(self.tool_input, 1)
        row.addWidget(self.add_tool)
        column.addLayout(row)
        column.addWidget(self.tools_note)
        return box

    def _table_box(
        self, title: str, table: QTableWidget, add: QPushButton, drop: QPushButton, hint_text: str
    ) -> QGroupBox:
        box = QGroupBox(title, self)
        column = QVBoxLayout(box)
        _tight(column)
        row = QHBoxLayout()
        hint = QLabel(hint_text, box)
        hint.setWordWrap(True)
        set_role(hint, "muted")
        row.addWidget(hint, 1)
        row.addWidget(add)
        row.addWidget(drop)
        column.addLayout(row)
        column.addWidget(table)
        return box

    def _instructions_box(self) -> QGroupBox:
        box = QGroupBox("지시문", self)
        column = QVBoxLayout(box)
        _tight(column)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.addRow("하지 않을 것", self.forbidden_box)
        form.addRow("", _muted(FORBIDDEN_NOTE, box))
        form.addRow("멈추고 넘길 상황", self.confirm_box)
        form.addRow("", _muted(CONFIRM_NOTE, box))
        column.addLayout(form)
        column.addWidget(_muted(INSTRUCTIONS_NOTE, box))
        return box

    def _replay_box(self) -> QGroupBox:
        box = QGroupBox("재생·실행 제한", self)
        column = QVBoxLayout(box)
        _tight(column)
        row = QHBoxLayout()
        row.setSpacing(SPACE_3)
        row.addWidget(QLabel("결정 수행에서 재생", box))
        for one in self.replay_picks.values():
            row.addWidget(one)
        row.addStretch(1)
        column.addLayout(row)
        column.addWidget(self.spec_line)
        spec_row = QHBoxLayout()
        spec_row.addWidget(self.spec_tools, 1)
        spec_row.addWidget(self.forget_button, 0, Qt.AlignmentFlag.AlignTop)
        column.addLayout(spec_row)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.addRow("최대 단계", self.max_steps_box)
        form.addRow("제한 시간(초)", self.timeout_box)
        column.addLayout(form)
        return box

    def _wire(self) -> None:
        self.goal_box.textChanged.connect(self._touched)
        self.outline_button.clicked.connect(self.insert_outline)
        self.domain_group.buttonToggled.connect(self._touched)
        self.app_box.textChanged.connect(self._touched)
        self.tool_input.textChanged.connect(self._refresh_tool_input)
        self.tool_input.returnPressed.connect(self.add_tool_name)
        self.add_tool.clicked.connect(self.add_tool_name)
        self.params.itemChanged.connect(self._touched)
        self.results.itemChanged.connect(self._touched)
        self.add_param.clicked.connect(lambda: self._add_param("", None, "string"))
        self.drop_param.clicked.connect(lambda: self._drop_row(self.params))
        self.add_result.clicked.connect(lambda: self._add_result("", "string"))
        self.drop_result.clicked.connect(lambda: self._drop_row(self.results))
        self.replay_group.buttonToggled.connect(self._touched)
        self.max_steps_box.valueChanged.connect(self._touched)
        self.timeout_box.valueChanged.connect(self._touched)
        self.forbidden_box.textChanged.connect(self._touched)
        self.confirm_box.textChanged.connect(self._touched)
        self.forget_button.clicked.connect(self.forget_spec)
        if self.names is not None:
            self.names.modelReset.connect(self._refresh_goal_preview)

    # ── 규약 ──

    def load(self, body: Mapping[str, Any]) -> None:
        """그림에 적힌 `chk:aiTask`를 그린다 (없으면 빈 것)."""
        self._quiet = True
        self._loaded = dict(body)
        self.goal_box.setPlainText(str(body.get("goal") or ""))
        domain = str(body.get("domain") or "")
        # 모르는 환경은 어느 것도 고르지 않는다 — `dump`가 읽은 값을 그대로 두고 `problems`가 말한다.
        self.domain_group.setExclusive(False)
        for value, one in self.domain_picks.items():
            one.setChecked(value == (domain or "llm"))
        self.domain_group.setExclusive(True)
        desktop = body.get("desktop")
        self.app_box.setText(str(desktop.get("app") or "") if isinstance(desktop, Mapping) else "")

        for name in [n for n in self.tool_checks if n not in self._builtin]:
            self._remove_tool_check(name)
        tools = [str(t) for t in body.get("tools") or []]
        for name in tools:
            if name not in self.tool_checks:
                self._add_tool_check(name)
        for name, check in self.tool_checks.items():
            check.setChecked(name in tools)
        self.tool_input.clear()

        self.params.setRowCount(0)
        params = body.get("params")
        for name, value in (params.items() if isinstance(params, Mapping) else []):
            self._add_param(str(name), value, _type_of(value), original=True)
        self.results.setRowCount(0)
        results = body.get("results")
        for name, kind in (results.items() if isinstance(results, Mapping) else []):
            self._add_result(str(name), str(kind))

        replay = str(body.get("replay") or REPLAY_DEFAULT)
        self.replay_group.setExclusive(False)
        for value, one in self.replay_picks.items():
            one.setChecked(value == replay)
        self.replay_group.setExclusive(True)
        limits = body.get("limits")
        steps = limits.get("max_steps") if isinstance(limits, Mapping) else None
        self.max_steps_box.setValue(steps if isinstance(steps, int) and steps > 0 else 0)
        timeout = limits.get("timeout_s") if isinstance(limits, Mapping) else None
        self.timeout_box.setValue(timeout if isinstance(timeout, int) and timeout > 0 else 0)
        self.forbidden_box.setPlainText(_lines_of(body.get("forbidden_actions")))
        self.confirm_box.setPlainText(_lines_of(body.get("confirm_triggers")))
        self._quiet = False
        self._refresh()

    def dump(self) -> dict[str, Any]:
        """`chk:aiTask` 본문 — **읽은 것 위에** 고친 칸만 얹는다."""
        out = dict(self._loaded)
        out["goal"] = self.goal_box.toPlainText()
        out["domain"] = self.domain() or str(self._loaded.get("domain") or "")
        _put(out, "tools", self.tools() or ([] if "tools" in self._loaded else None))
        params = {name: value for name, value, _ in self._param_rows()}
        _put(out, "params", params or ({} if "params" in self._loaded else None))
        results = dict(self._result_rows())
        _put(out, "results", results or ({} if "results" in self._loaded else None))
        replay = self.replay()
        # 기본값(`plan`)은 적지 않는다 — 읽은 그림에 있었으면 그대로 둔다.
        _put(out, "replay", replay if replay != REPLAY_DEFAULT or "replay" in self._loaded else None)
        limits = dict(self._loaded["limits"]) if isinstance(self._loaded.get("limits"), Mapping) else {}
        _put(limits, "max_steps", self.max_steps_box.value() or None)
        _put(limits, "timeout_s", self.timeout_box.value() or None)
        _put(out, "limits", limits or None)
        for key, box in (("forbidden_actions", self.forbidden_box), ("confirm_triggers", self.confirm_box)):
            _put(out, key, _lines(box) or ([] if key in self._loaded else None))
        desktop = dict(self._loaded["desktop"]) if isinstance(self._loaded.get("desktop"), Mapping) else {}
        _put(desktop, "app", self.app_box.text().strip() or None)
        _put(out, "desktop", desktop or None)
        return out

    def problems(self) -> tuple[list[str], list[str]]:
        """`(적용을 막는 것, 경고)`."""
        errors: list[str] = []
        warnings: list[str] = []
        domain = self.domain()
        if not domain:
            errors.append(f"대상 환경을 모릅니다: {self._loaded.get('domain')} — 하나를 고르세요.")
        elif domain in PC_ONLY_DOMAINS and self.run_location == "server":
            errors.append(SERVER_NO_SCREEN)
        if not self.goal_box.toPlainText().strip():
            warnings.append("목표가 비어 있습니다.")
        if domain == "desktop" and not self.app_box.text().strip():
            warnings.append(
                "띄울 앱이 없습니다 — BPM 프로세스 기본값(chk:defaults.desktop.app)에도 없으면 실행 때 업무 실패입니다."
            )
        others = [name for name in self.tools() if name not in self._builtin]
        if others:
            warnings.append(
                f"내장 도구가 아닙니다: {', '.join(others)} — 그 PC에 없으면 실행 때 업무 실패입니다 (ADR-0050)."
            )

        seen: set[str] = set()
        for name, _value, row_error in self._param_rows(with_errors=True):
            if row_error:
                errors.append(row_error)
            elif name in seen:
                errors.append(f"업무 파라미터 이름이 겹칩니다: {name}")
            seen.add(name)
        seen = set()
        for name, kind in self._result_rows():
            if not name:
                errors.append("결과 필드 이름을 적으세요.")
            elif not is_var_name(name):
                errors.append(f"결과 필드 이름은 변수 이름이어야 합니다: {name}")
            elif name in seen:
                errors.append(f"결과 필드 이름이 겹칩니다: {name}")
            if kind not in VALUE_TYPES:
                errors.append(f"결과 {name}의 타입을 모릅니다: {kind} (B8)")
            elif kind == "int" and looks_like_code(name):
                warnings.append(f"결과 {name}이 번호·코드처럼 보이는데 int입니다 — 문자열이 아닐까요 (B8).")
            seen.add(name)

        stale = self._spec_tools_not_allowed()
        if stale:
            warnings.append(
                f"명세의 도구 {', '.join(stale)}가 허용 도구에 없습니다 — 결정 수행에서 재생이 실패합니다."
                " 명세를 잊고 다시 배우세요."
            )
        if self.replay() == "full" and not self.tools():
            errors.append("도구가 없는 AI 태스크에는 재생 「전부」(full)를 쓸 수 없습니다 (B12).")
        if not errors:
            try:
                AiTask.model_validate(self.dump())
            except ValidationError as e:
                first = e.errors()[0]
                where = ".".join(str(p) for p in first.get("loc", ()))
                errors.append(f"AI 태스크 칸이 계약과 맞지 않습니다 ({where}): {first.get('msg')}")
        self.warning.setText(errors[0] if errors else "")
        self.note.setText(" ".join(warnings))
        return errors, warnings

    def domain(self) -> str:
        """고른 대상 환경 — 그림의 환경을 모르면 빈 글."""
        return next((v for v, one in self.domain_picks.items() if one.isChecked()), "")

    def replay(self) -> str:
        return next((v for v, one in self.replay_picks.items() if one.isChecked()), REPLAY_DEFAULT)

    def tools(self) -> list[str]:
        """허용 도구 — **읽은 순서를 지키고** 새로 고른 것은 보이는 순서로 뒤에 붙인다."""
        picked = [name for name, check in self.tool_checks.items() if check.isChecked()]
        before = [str(t) for t in self._loaded.get("tools") or []]
        return [n for n in before if n in picked] + [n for n in picked if n not in before]

    def preview_names(self) -> tuple[list[str], str, list[str]]:
        """목표 미리보기 — `(목표에 이름이 나오는 변수, 반복 항목, 업무 파라미터)` (엔진과 같은 규칙)."""
        params = [name for name, _value, _ in self._param_rows(with_errors=True) if name]
        known = list(self.names.stringList()) if self.names is not None else []
        candidates = [n for n in dict.fromkeys([*known, *SEEDED_NAMES]) if n != self.loop_item and n not in params]
        return goal_names(self.goal_box.toPlainText(), candidates), self.loop_item, params

    def forget_spec(self) -> None:
        """「명세 잊기」 — 확인(기본 「취소」) 뒤 이 태스크의 명세 하나만 지운다."""
        self.refresh_spec()  # 창을 연 뒤 시험 실행이 다시 배웠을 수 있다 — 지울 것을 다시 본다
        if self.specs is None or self._spec is None or self.running():
            return
        answer = QMessageBox.question(
            self,
            FORGET_TITLE,
            FORGET_TEXT.format(count=len(self._spec.steps)),
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.specs.forget(self.node_id)
        except (SpecsUnreadable, OSError) as e:
            self.warning.setText(f"명세를 잊지 못했습니다: {e}")
            return
        self.refresh_spec()

    def refresh_spec(self) -> None:
        """「재생 명세」를 파일에서 다시 읽는다 (시험 실행이 끝났을 때 속성 패널이 부른다)."""
        self._spec, self._spec_error = None, ""
        if self.specs is not None:
            try:
                self._spec = self.specs.find(self.node_id)
            except SpecsUnreadable as e:
                self._spec_error = str(e)
        self._refresh()

    def _show_spec(self) -> None:
        """읽어 둔 명세를 한 줄로 — 재생 라디오를 바꿀 때마다 파일을 읽지 않는다."""
        spec = self._spec
        not_used = self.replay() == "none"
        self.spec_tools.setText("")
        self.spec_tools.setToolTip("")
        self.spec_line.setToolTip("")
        if self.specs is None:
            self.spec_line.setText(SPEC_NO_PROCESS)
        elif self._spec_error:
            self.spec_line.setText(self._spec_error)
        elif spec is None:
            self.spec_line.setText(SPEC_NOT_USED if not_used else SPEC_NONE)
        else:
            line = f"명세 있음 · 도구 {len(spec.steps)}단계 · 판 {spec.version}"
            self.spec_line.setText(f"{line} — {SPEC_NOT_USED}" if not_used else line)
            if spec.model:
                self.spec_line.setToolTip(f"적을 때 쓴 모델: {spec.model}")
            tools = [step.tool for step in spec.steps]
            more = " → …" if len(tools) > SPEC_TOOLS_SHOWN else ""
            self.spec_tools.setText(f"({' → '.join(tools[:SPEC_TOOLS_SHOWN])}{more})" if tools else "")
            self.spec_tools.setToolTip(" → ".join(tools))
        busy = spec is not None and self.running()
        self.forget_button.setEnabled(spec is not None and not busy)
        self.forget_button.setToolTip(SPEC_RUNNING if busy else FORGET_TIP)

    def insert_outline(self) -> None:
        """목표가 비었을 때 권장 머리말을 넣는다 (적어 둔 목표를 덮지 않는다)."""
        if self.goal_box.toPlainText().strip():
            return
        self.goal_box.setPlainText(GOAL_OUTLINE)

    def add_tool_name(self) -> None:
        """입력 칸의 도구 이름을 목록에 더하고 고른다 (이미 있으면 고르기만)."""
        name = self.tool_input.text().strip()
        if not name:
            return
        if name not in self.tool_checks:
            self._add_tool_check(name)
        self.tool_checks[name].setChecked(True)
        self.tool_input.clear()

    # ── 안쪽 ──

    def _add_tool_check(self, name: str) -> None:
        text = name if name in self._builtin else f"{name} (내장 아님)"
        check = QCheckBox(text, self)
        check.setToolTip(self._builtin.get(name, "내장 도구가 아닙니다 — 그 PC에 있어야 합니다."))
        check.toggled.connect(self._touched)
        self.tool_checks[name] = check
        self.tools_column.addWidget(check)

    def _remove_tool_check(self, name: str) -> None:
        check = self.tool_checks.pop(name)
        self.tools_column.removeWidget(check)
        check.setParent(None)
        check.deleteLater()

    def _add_param(self, name: str, value: Any, kind: str, *, original: bool = False) -> None:
        quiet, self._quiet = self._quiet, True
        table = self.params
        row = table.rowCount()
        table.insertRow(row)
        table.setItem(row, 0, QTableWidgetItem(name))
        shown = _shown(value)
        cell = QTableWidgetItem(shown)
        if original:
            # 줄을 고치지 않았으면 읽은 값을 그대로 돌려준다 — `(보인 글, 타입, 값)`.
            cell.setData(_ORIGINAL, (shown, kind, value))
        table.setItem(row, 2, cell)
        table.setCellWidget(row, 1, self._type_combo(table, kind))
        self._quiet = quiet
        self._touched()

    def _add_result(self, name: str, kind: str) -> None:
        quiet, self._quiet = self._quiet, True
        table = self.results
        row = table.rowCount()
        table.insertRow(row)
        table.setItem(row, 0, QTableWidgetItem(name))
        table.setCellWidget(row, 1, self._type_combo(table, kind))
        self._quiet = quiet
        self._touched()

    def _type_combo(self, table: QTableWidget, kind: str) -> QComboBox:
        combo = QComboBox(table)
        combo.addItems(list(TYPES))
        if combo.findText(kind) < 0:
            combo.addItem(kind)  # 모르는 타입도 지우지 않는다 — 검사가 말한다
        combo.setCurrentText(kind)
        combo.currentIndexChanged.connect(self._touched)
        row = table.rowCount() - 1
        # 콤보가 줄보다 크면 아래 줄을 덮는다 — 줄을 콤보에 맞춘다.
        table.setRowHeight(row, max(table.rowHeight(row), combo.sizeHint().height()))
        return combo

    def _drop_row(self, table: QTableWidget) -> None:
        rows = sorted({i.row() for i in table.selectedIndexes()}, reverse=True)
        if not rows and table.rowCount():
            rows = [table.rowCount() - 1]
        for row in rows:
            table.removeRow(row)
        self._touched()

    def _param_rows(self, *, with_errors: bool = False) -> list[tuple[str, Any, str]]:
        """업무 파라미터 표 → `(이름, 값, 그 줄의 오류)`. **모두 빈 줄은 건너뛴다**."""
        out: list[tuple[str, Any, str]] = []
        for row in range(self.params.rowCount()):
            name = _text(self.params, row, 0)
            kind = _kind(self.params, row)
            cell = self.params.item(row, 2)
            text = cell.text() if cell is not None else ""
            if not name and not text.strip():
                continue
            original = cell.data(_ORIGINAL) if cell is not None else None
            if original is not None and original[0] == text and original[1] == kind:
                out.append((name, original[2], "" if name else "업무 파라미터 이름을 적으세요."))
                continue
            value, problem = _parse(text, kind)
            if not name:
                problem = "업무 파라미터 이름을 적으세요."
            elif problem:
                problem = f"업무 파라미터 {name}: {problem}"
            out.append((name, value, problem))
        return out if with_errors else [(n, v, "") for n, v, p in out if not p]

    def _result_rows(self) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for row in range(self.results.rowCount()):
            name = _text(self.results, row, 0)
            out.append((name, _kind(self.results, row)))
        return out

    def _refresh_tool_input(self) -> None:
        self.add_tool.setEnabled(bool(self.tool_input.text().strip()))

    def _touched(self, *_args: object) -> None:
        if self._quiet:
            return
        self._refresh()
        self.changed.emit()

    def _spec_tools_not_allowed(self) -> list[str]:
        """명세에 적힌 도구 가운데 지금 허용 도구에 없는 것 (재생이 그 자리에서 실패한다)."""
        if self._spec is None or self.domain() in PC_ONLY_DOMAINS:
            return []  # 웹·데스크톱은 환경의 도구가 저절로 허용된다 — 이름을 여기서 모른다 (ADR-0037)
        allowed = set(self.tools())
        return list(dict.fromkeys(step.tool for step in self._spec.steps if step.tool not in allowed))

    def _refresh_goal_preview(self, *_args: object) -> None:
        found, item, params = self.preview_names()
        parts = []
        if found:
            parts.append(" · ".join(found))
        if item:
            parts.append(f"반복 항목 {item}")
        if params:
            parts.append(f"업무 파라미터 {', '.join(params)}")
        self.goal_preview.setText(f"모델에게 가는 값: {' · '.join(parts)}" if found or item else GOAL_PREVIEW_NONE)

    def _refresh(self) -> None:
        self._refresh_goal_preview()
        self._show_spec()
        domain = self.domain()
        on_server = self.run_location == "server"
        for value in PC_ONLY_DOMAINS:
            one = self.domain_picks[value]
            # 서버에서는 끈다 — **이미 골라 둔 것은 지우지 않는다** (결재의 「현장」과 같은 결).
            one.setEnabled(not on_server or one.isChecked())
        notes = []
        if on_server:
            notes.append(SERVER_NO_SCREEN)
        if domain in PC_ONLY_DOMAINS:
            notes.append(SCREEN_TOOLS_NOTE)
        if domain == "web":
            notes.append(NO_WEB_ENVIRONMENT)
        self.domain_note.setText(" ".join(notes))
        self.domain_note.setVisible(bool(notes))
        self._domain_form.setRowVisible(self.app_box, domain == "desktop")
        self.outline_button.setEnabled(not self.goal_box.toPlainText().strip())
        self._refresh_tool_input()
        self.problems()


def _table(columns: tuple[str, ...], parent: QWidget) -> QTableWidget:
    table = QTableWidget(0, len(columns), parent)
    table.setHorizontalHeaderLabels(list(columns))
    table.verticalHeader().setVisible(False)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    table.setMinimumHeight(
        table.horizontalHeader().sizeHint().height()
        + table.verticalHeader().defaultSectionSize() * VISIBLE_ROWS
        + table.frameWidth() * 2
    )
    return table


def _text(table: QTableWidget, row: int, column: int) -> str:
    found = table.item(row, column)
    return found.text().strip() if found is not None else ""


def _kind(table: QTableWidget, row: int) -> str:
    combo = table.cellWidget(row, 1)
    return combo.currentText() if isinstance(combo, QComboBox) else "string"


def _type_of(value: Any) -> str:
    """읽은 업무 파라미터 값 → 보일 타입 (`bool`이 `int`보다 먼저다 — 파이썬에서 `True`는 `int`다)."""
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return "string"


def _shown(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _parse(text: str, kind: str) -> tuple[Any, str]:
    """표의 글 → `(값, 사유)`. 사유가 있으면 「적용」을 막는다. **빈 값은 받지 않는다** (STU-04)."""
    raw = text.strip()
    if not raw:
        return None, "값을 적으세요."
    if kind in ("string", "date"):
        return text, ""
    if kind == "int":
        try:
            return int(raw), ""
        except ValueError:
            return None, f"정수가 아닙니다: {raw}"
    if kind == "number":
        try:
            number = float(raw)
        except ValueError:
            return None, f"수가 아닙니다: {raw}"
        return (int(number) if number.is_integer() and "." not in raw else number), ""
    if kind == "bool":
        if raw.lower() in _TRUE:
            return True, ""
        if raw.lower() in _FALSE:
            return False, ""
        return None, f"참/거짓이 아닙니다: {raw}"
    if kind in ("list", "dict"):
        try:
            value = json.loads(raw)
        except ValueError:
            return None, f"JSON이 아닙니다: {raw}"
        wanted = list if kind == "list" else dict
        if not isinstance(value, wanted):
            return None, f"{kind}가 아닙니다: {raw}"
        return value, ""
    return None, f"타입을 모릅니다: {kind}"


def _lines(box: QPlainTextEdit) -> list[str]:
    """줄마다 하나 — 빈 줄은 버린다."""
    return [line.strip() for line in box.toPlainText().splitlines() if line.strip()]


def _lines_of(value: Any) -> str:
    return "\n".join(str(one) for one in value) if isinstance(value, list) else ""


def _muted(text: str, parent: QWidget) -> QLabel:
    label = QLabel(text, parent)
    label.setWordWrap(True)
    set_role(label, "muted")
    return label


def _put(out: dict[str, Any], key: str, value: Any) -> None:
    """값이 없으면 칸을 **지운다** (빈 글·빈 목록을 그림에 남기지 않는다)."""
    if value is None:
        out.pop(key, None)
    else:
        out[key] = value


def _tight(layout: Any) -> None:
    """묶음 안쪽 여백 — 결재 편집기와 같다."""
    layout.setContentsMargins(SPACE_2, SPACE_2, SPACE_2, SPACE_2)


__all__ = [
    "CONFIRM_NOTE",
    "DOMAINS",
    "FORBIDDEN_NOTE",
    "GOAL_OUTLINE",
    "NO_WEB_ENVIRONMENT",
    "REPLAYS",
    "SERVER_NO_SCREEN",
    "TAB_LABEL",
    "TYPES",
    "AiTaskEditor",
    "builtin_tool_descriptions",
]
