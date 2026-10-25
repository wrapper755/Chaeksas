"""STU-06 BPM 프로세스 정보 — 폴더 하나의 성질을 고치는 창.

고치는 것이 **두 곳에 산다**. 그래서 저장도 두 걸음이고, 창이 그것을 숨기지 않는다.

- **작업 폴더 기록**(`process.json`): 이름·버전·설명·담당자·태그. Studio 안에서만 쓰는
  기록이라 계약이 아니다 (`workspace.py`). **설명만 패키지로 간다** (C1 `description`) —
  담당자·태그는 매니페스트에 칸이 없어 설계자가 보는 메모로 남는다.
- **진입 정의의 `chk:process`**(C14): 실행 위치. 이것은 **그림**이므로
  **캔버스를 거쳐야** 고칠 수 있다 — XML을 파이썬이 직접 만지면 실행 취소와 「저장 안 한
  변경」이 깨진다 (ADR-0022, STU-04와 같은 규칙). 그래서 **진입 정의가 열려 있을 때만**
  그 칸이 켜지고, 아니면 끄고 까닭을 적는다 (U3).

지키는 것 셋.

- **「서버로 바꾸면 무엇이 걸리나」는 검사와 같은 함수로 센다** (`contracts.server_blockers`) —
  베껴 두면 창이 「바꿔도 된다」고 하고 F6이 막는 일이 생긴다. **저장을 막지는 않는다**
  (화면 설계서 STU-06) — 사람이 고칠 거리를 알려 줄 뿐이다. 확장 태스크는 실행 위치를
  **확장 정의만** 아니(C13·ADR-0018) 부르는 쪽이 표를 넘긴다 — F6이 쓰는 것과 같은 표다.
- **「서비스 앱 키」 섹션은 없다** (ADR-0094) — 키는 Center가 (Bot × 배포 대상 × 앱)마다 지어
  내려 주고, 참조 이름은 받은 키를 찾는 이름일 뿐이라 사람이 판단하거나 고칠 것이 없다. 참조
  이름은 빌드가 짓는다(그림에 적힌 `service_keys`가 있으면 그것, 없으면 기본값). **그림에 이미
  적힌 값은 그대로 둔다** — 저장이 읽은 `chk:process`를 통째로 되돌려 쓴다.
- **읽고 쓰는 것은 진입 정의 하나다.**
- **그림은 캔버스의 지금 것을 읽는다** — 진입 정의가 열려 있으면 메인 창이 캔버스에서 읽어
  `drawn`으로 넘긴다. 파일에서 읽으면 「적용」한 것이 다시 열었을 때 안 보인다.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from chaeksas.contracts.bpmn_ext import BpmnProcess, ProcessInfo, server_blockers
from chaeksas.studio.workspace import BpmProcess, Definition, Workspace, WorkspaceError, write_record

log = logging.getLogger(__name__)

TITLE = "BPM 프로세스 정보"
#: 처음 크기 — STU-10과 같은 폭을 쓴다.
DEFAULT_SIZE = (720, 440)

#: 실행 위치 (ADR-0015). 글은 STU-05와 **같은 말**을 쓴다.
LOCATIONS = (("server", "서버 — 대부분의 업무. 여러 건 동시에"), ("pc", "PC (Bot UI) — 화면 조작·현장 확인"))
#: 생략하면 서버다 (C1 R1·ADR-0016).
DEFAULT_LOCATION = "server"

#: 단추 위 한 줄 — 「적용」이 어디로 가나 (STU-04 「적용」과 같은 말).
APPLY_NOTE = (
    "실행 위치는 그림에 적용됩니다 — 파일에는 Ctrl+S로 저장됩니다. "
    "이름·버전·설명·담당자·태그는 바로 저장됩니다."
)
APPLY_NOTE_RECORD_ONLY = "이름·버전·설명·담당자·태그는 바로 저장됩니다."

#: 그림을 고칠 수 없는 까닭 (U3 — 끄고 **가까이에** 적는다).
NO_CANVAS = (
    "실행 위치는 **그림**에 있습니다 (`chk:process`) — 진입 정의 「{entry}」를 열면 고칠 수 있습니다."
)
NO_ENTRY = "정의가 없어 실행 위치를 적을 자리가 없습니다 — 먼저 정의를 저장하세요."

#: 「학습 상태 요약」 (ADR-0028).
NO_MEMORY = "재생 명세가 없습니다 (자율 수행으로 한 번 돌리면 배웁니다)."

NOTHING = "(없음)"


# ─────────────────────────── 담는 것 (Qt 없이 시험한다) ───────────────────────────


def learning(process: BpmProcess) -> str:
    """「학습 상태 요약」 — 재생 명세가 몇 개인가 (ADR-0028). 읽기 전용이다."""
    specs = process.memory().specs
    if not specs:
        return NO_MEMORY
    nodes = ", ".join(sorted(one.key.rpartition(":")[2] for one in specs))
    return f"재생 명세 {len(specs)}개 — {nodes}"


def with_drawn(process: BpmProcess, drawn: BpmnProcess | None) -> list[Definition]:
    """정의 목록에서 **진입 정의만 캔버스의 지금 그림으로** 바꾼 것 (없으면 그대로).

    열린 것은 진입 정의 하나라 나머지는 파일의 것이 지금 것이다.
    """
    entry = process.entry_definition
    if drawn is None or entry is None:
        return list(process.definitions)
    return [replace(one, process=drawn) if one.path == entry.path else one for one in process.definitions]


def server_warning(blockers: Sequence[str]) -> str:
    """「서버」를 골랐을 때 보일 한 줄 (STU-06). 걸리는 것이 없으면 빈 글이다."""
    if not blockers:
        return ""
    return (
        f"서버에서 실행할 수 없는 태스크 {len(blockers)}개 — 실행 전 검사에서 오류로 "
        "표시됩니다: " + ", ".join(blockers)
    )


def check(*, name: str, version: str, taken: Sequence[str]) -> str:
    """저장 전 검사. 빈 글이면 괜찮다 — **첫 흠 하나만** 말한다 (빨간 글자 한 줄이다)."""
    if not name.strip():
        return "이름을 적으세요."
    if name.strip() in taken:
        return f"같은 이름의 BPM 프로세스가 있습니다: {name.strip()}"
    if not re.fullmatch(r"\d+\.\d+\.\d+", version.strip()):
        return f"버전은 `1.0.0` 모양입니다 (받은 값 {version.strip() or '빈 값'})."
    return ""


# ─────────────────────────── 창 ───────────────────────────


class ProcessInfoDialog(QDialog):
    """STU-06. **「적용」을 누를 때까지 아무것도 바뀌지 않는다** (STU-10과 같은 결).

    「적용」은 기록을 바로 쓰고 그림은 캔버스에만 넘긴다 — 파일로 가는 것은 Ctrl+S다.
    """

    def __init__(
        self,
        process: BpmProcess,
        workspace: Workspace,
        *,
        editable: bool = True,
        task_type_locations: Mapping[str, Sequence[str]] | None = None,
        drawn: BpmnProcess | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.process = process
        self.workspace = workspace
        #: 확장 태스크 종류 → 실행 위치 (확장 호스트가 C13에서 읽어 준다). **F6과 같은 표**여야
        #: 한다 — 창이 세지 못하는 것을 검사가 막으면 사람이 영문을 모른다.
        self.task_type_locations = task_type_locations
        #: 진입 정의가 열려 있나 — **그림을 고칠 수 있는가**다 (아니면 실행 위치가 꺼진다).
        self.editable = editable
        #: 「저장」을 눌러 바뀐 것. 부르는 쪽이 캔버스에 넘길 `chk:process`가 여기 있다.
        self.saved: BpmProcess | None = None
        self.process_patch: str | None = None
        #: 「이 부분을 PC BPM 프로세스로 나누기...」를 눌렀다 — 창은 저장하지 않고 닫히고 메인 창이
        #: STU-06a를 연다 (ADR-0071). 그림을 바꾸는 것은 캔버스를 쥔 메인 창의 일이다.
        self.split_requested = False

        entry = process.entry_definition
        self.entry = entry
        #: 지금 그림 — 진입 정의가 열려 있으면 **캔버스의 것**(`drawn`)이다. 파일에서 읽으면
        #: 「적용」한 것이 다시 열었을 때 안 보인다 (Ctrl+S 전에는 파일에 없다).
        self.drawn = drawn if editable else None
        self.definitions = with_drawn(process, self.drawn)
        found = self.drawn or (entry.process if entry is not None else None)
        self.info = found.info.model_copy(deep=True) if found is not None else ProcessInfo()

        self.setWindowTitle(TITLE)
        self.resize(*DEFAULT_SIZE)

        self.name_box = QLineEdit(process.name, self)
        self.version_box = QLineEdit(process.version, self)
        self.description_box = QPlainTextEdit(process.description, self)
        self.description_box.setFixedHeight(72)
        self.owner_box = QLineEdit(process.owner, self)
        self.tags_box = QLineEdit(", ".join(process.tags), self)
        self.tags_box.setPlaceholderText("재무, 월말")

        self.location_box = QComboBox(self)
        for value, label in LOCATIONS:
            self.location_box.addItem(label, value)
        at = self.location_box.findData(self.info.run_location or DEFAULT_LOCATION)
        self.location_box.setCurrentIndex(max(0, at))
        self.location_box.currentIndexChanged.connect(self._refresh_warning)

        self.to_pc = QPushButton("실행 위치를 PC로 바꾸기", self)
        self.to_pc.clicked.connect(self._choose_pc)
        self.to_split = QPushButton("이 부분을 PC BPM 프로세스로 나누기...", self)
        self.to_split.setObjectName("splitToPc")
        self.to_split.clicked.connect(self._ask_split)
        self.warning = QLabel("", self)
        self.warning.setWordWrap(True)
        self.warning.setObjectName("serverWarning")

        form = QFormLayout()
        form.addRow("id", self._fixed(process.id))
        form.addRow("폴더", self._fixed(process.folder.as_posix()))
        form.addRow("학습 상태", self._fixed(learning(process)))
        form.addRow("이름", self.name_box)
        form.addRow("버전", self.version_box)
        form.addRow("설명", self.description_box)
        form.addRow("담당자", self.owner_box)
        form.addRow("태그 (쉼표)", self.tags_box)
        form.addRow("실행 위치", self.location_box)

        #: 아래 한 줄 — 검사 오류와 안내를 여기로만 말한다 (STU-10과 같은 결).
        self.note = QLabel("", self)
        self.note.setWordWrap(True)

        #: 단추 위 한 줄 — 「적용」이 어디로 가나 (STU-04 「적용」과 같은 말).
        self.apply_note = QLabel(APPLY_NOTE if self._graph_open() else APPLY_NOTE_RECORD_ONLY, self)
        self.apply_note.setWordWrap(True)
        self.apply_note.setProperty("role", "muted")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel, parent=self
        )
        buttons.button(QDialogButtonBox.StandardButton.Apply).setText("적용")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.save)
        buttons.rejected.connect(self.reject)
        self.buttons = buttons

        warning_row = QHBoxLayout()
        warning_row.addWidget(self.warning, 1)
        warning_row.addWidget(self.to_pc)
        warning_row.addWidget(self.to_split)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(warning_row)
        layout.addStretch(1)
        layout.addWidget(self.note)
        layout.addWidget(self.apply_note)
        layout.addWidget(buttons)

        self._lock_graph_fields()
        self._refresh_warning()

    # ── 짜기 ──

    def _fixed(self, text: str) -> QLabel:
        found = QLabel(text or NOTHING, self)
        found.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        found.setWordWrap(True)
        return found

    def _graph_open(self) -> bool:
        return self.editable and self.entry is not None

    def _lock_graph_fields(self) -> None:
        """그림을 고칠 수 없으면 **실행 위치만** 끄고 까닭을 적는다 (나머지는 저장된다)."""
        if self._graph_open():
            return
        why = NO_ENTRY if self.entry is None else NO_CANVAS.format(entry=self.entry.path.name)
        self.location_box.setEnabled(False)
        self.location_box.setToolTip(why)
        self.note.setText(why)
        self.note.setTextFormat(Qt.TextFormat.MarkdownText)

    # ── 실행 위치 ──

    def location(self) -> str:
        found = self.location_box.currentData()
        return str(found or DEFAULT_LOCATION)

    def blockers(self) -> list[str]:
        """서버에서 걸리는 것들 — **검사와 같은 함수**다 (`contracts.server_blockers`).

        확장 태스크도 센다 — 부르는 쪽이 넘긴 표로 본다 (`task_type_locations`). F6이 **같은
        표**를 쓰므로 둘이 같은 것을 말한다 (어긋나면 「검사는 통과했는데 창이 막는다」가 된다).
        **표에 없는 종류는 세지 않는다** — 그 확장이 깔려 있지 않으면 실행 위치를 모른다.
        """
        found = self.drawn or (self.entry.process if self.entry is not None else None)
        if found is None:
            return []
        return server_blockers(found, self.task_type_locations)

    def _refresh_warning(self) -> None:
        """「서버」일 때만 센다. **저장을 막지 않는다** (화면 설계서 STU-06)."""
        found = server_warning(self.blockers()) if self.location() == "server" else ""
        self.warning.setText(found)
        self.warning.setVisible(bool(found))
        self.to_pc.setVisible(bool(found) and self.location_box.isEnabled())
        self.to_split.setVisible(bool(found) and self.location_box.isEnabled())

    def _ask_split(self) -> None:
        """STU-06a로 간다 — **이 창에서 고친 것은 저장되지 않는다**고 먼저 말한다."""
        answer = QMessageBox.question(
            self,
            "PC BPM 프로세스로 나누기",
            "이 창을 닫고 「나누기」 창을 엽니다. 이 창에서 고친 것은 저장되지 않습니다.",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Ok:
            return
        self.split_requested = True
        self.reject()

    def _choose_pc(self) -> None:
        at = self.location_box.findData("pc")
        if at >= 0:
            self.location_box.setCurrentIndex(at)

    # ── 저장 ──

    def save(self) -> None:
        """두 곳에 쓴다 — 기록은 여기서, **그림은 부르는 쪽이 캔버스로** (XML을 만지지 않는다).

        검사에 걸리면 **창을 닫지 않는다** (STU-10과 같은 결).
        """
        taken = [
            one.name
            for group in self.workspace.groups()
            for one in group.processes
            if one.id != self.process.id and one.name
        ]
        problem = check(name=self.name_box.text(), version=self.version_box.text(), taken=taken)
        if problem:
            self.note.setText(problem)
            self.note.setTextFormat(Qt.TextFormat.PlainText)
            return

        made = BpmProcess(
            id=self.process.id,
            folder=self.process.folder,
            group=self.process.group,
            name=self.name_box.text().strip(),
            version=self.version_box.text().strip(),
            entry=self.process.entry,
            description=self.description_box.toPlainText().strip(),
            owner=self.owner_box.text().strip(),
            tags=tuple(one.strip() for one in self.tags_box.text().split(",") if one.strip()),
            definitions=self.process.definitions,
        )
        try:
            write_record(made)
        except (OSError, WorkspaceError) as e:
            self.note.setText(f"기록을 쓰지 못했습니다: {e}")
            return

        self.saved = made
        # 그림 쪽은 **고칠 수 있을 때만** 짓는다 — 꺼져 있으면 `None`이고 부르는 쪽이 넘기지 않는다.
        if self.location_box.isEnabled():
            self.process_patch = self._patch()
        self.accept()

    def _patch(self) -> str:
        """캔버스에 넘길 `chk:process` 본문 (JSON 글 그대로 — `setProperties`의 규약).

        **읽은 것을 통째로 되돌려 쓴다** — `extensions`·`inputs`·`outputs`를 빼면 그 선언이
        사라진다 (창이 모르는 칸도 지키는 자리다). 그림에 적힌 `service_keys`도 **그대로** 간다.
        """
        made = self.info.model_copy(deep=True)
        made.run_location = self.location()  # type: ignore[assignment]
        return json.dumps(made.to_json_dict(), ensure_ascii=False, indent=2)


__all__ = [
    "DEFAULT_LOCATION",
    "DEFAULT_SIZE",
    "LOCATIONS",
    "NO_CANVAS",
    "NO_ENTRY",
    "APPLY_NOTE",
    "APPLY_NOTE_RECORD_ONLY",
    "NO_MEMORY",
    "TITLE",
    "ProcessInfoDialog",
    "check",
    "learning",
    "server_warning",
    "with_drawn",
]
