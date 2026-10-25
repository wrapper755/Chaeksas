"""STU-06 BPM 프로세스 정보 — 폴더 하나의 성질을 고치는 창.

고치는 것이 **두 곳에 산다**. 그래서 저장도 두 걸음이고, 창이 그것을 숨기지 않는다.

- **작업 폴더 기록**(`process.json`): 이름·버전·설명·담당자·태그. Studio 안에서만 쓰는
  기록이라 계약이 아니다 (`workspace.py`). **설명만 패키지로 간다** (C1 `description`) —
  담당자·태그는 매니페스트에 칸이 없어 설계자가 보는 메모로 남는다.
- **진입 정의의 `chk:process`**(C14): 실행 위치·서비스 앱 키 참조. 이것은 **그림**이므로
  **캔버스를 거쳐야** 고칠 수 있다 — XML을 파이썬이 직접 만지면 실행 취소와 「저장 안 한
  변경」이 깨진다 (ADR-0022, STU-04와 같은 규칙). 그래서 **진입 정의가 열려 있을 때만**
  그 두 칸이 켜지고, 아니면 끄고 까닭을 적는다 (U3).

지키는 것 셋.

- **「서버로 바꾸면 무엇이 걸리나」는 검사와 같은 함수로 센다** (`contracts.server_blockers`) —
  베껴 두면 창이 「바꿔도 된다」고 하고 F6이 막는 일이 생긴다. **저장을 막지는 않는다**
  (화면 설계서 STU-06) — 사람이 고칠 거리를 알려 줄 뿐이다. 확장 태스크는 실행 위치를
  **확장 정의만** 아니(C13·ADR-0018) 부르는 쪽이 표를 넘긴다 — F6이 쓰는 것과 같은 표다.
- **키 값은 여기 넣지 않는다** (ADR-0013) — 참조 이름만이다. 「이 PC의 값」은 Studio 설정에
  그 값이 있나를 **읽어서** 보이고, 넣는 자리는 STU-10이다.
- **읽고 쓰는 것은 진입 정의 하나다.** 하위 정의가 적은 `service_keys`를 섞어 보이면 저장이
  그것을 진입으로 옮기는 셈이 된다. 태스크가 따로 적은 참조는 **「태스크에서 바꾼 곳」**이
  세어 보인다 (읽기만 한다).
- **그림은 캔버스의 지금 것을 읽는다** — 진입 정의가 열려 있으면 메인 창이 캔버스에서 읽어
  `drawn`으로 넘긴다. 파일에서 읽으면 「적용」한 것이 다시 열었을 때 안 보인다.
- **키 표의 줄은 노드가 부르는 앱**과 적혀 있지만 쓰는 노드가 없는 것이다. 「추가」는 없다.
  **키를 받지 않는 앱**(C13 `auth`가 없는 외부 앱, ADR-0091)은 적혀 있을 때만 지울 줄로 남는다.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, replace

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from chaeksas.contracts.bpmn_ext import BpmnProcess, ProcessInfo, server_blockers
from chaeksas.studio.service_editor import NOT_LISTED
from chaeksas.studio.workspace import BpmProcess, Definition, Workspace, WorkspaceError, write_record

log = logging.getLogger(__name__)

TITLE = "BPM 프로세스 정보"
#: 처음 크기 — STU-10과 같은 폭을 쓴다 (키 표가 들어간다).
DEFAULT_SIZE = (720, 620)

#: 실행 위치 (ADR-0015). 글은 STU-05와 **같은 말**을 쓴다.
LOCATIONS = (("server", "서버 — 대부분의 업무. 여러 건 동시에"), ("pc", "PC (Bot UI) — 화면 조작·현장 확인"))
#: 생략하면 서버다 (C1 R1·ADR-0016).
DEFAULT_LOCATION = "server"

KEY_COLUMNS = ("서비스 앱", "키 참조 이름", "적힌 곳", "이 PC의 값", "쓰는 노드", "태스크에서 바꾼 곳")
APP, REF, WRITTEN, VALUE, USERS, OVERRIDES = range(len(KEY_COLUMNS))

#: 「적힌 곳」 — 기본값 줄도 「적용」하면 적힌다는 것이 보이게 (STU-06).
WRITTEN_YES = "그림에 적힘"
WRITTEN_DEFAULT = "기본값 — 적용하면 적힘"

#: 키 참조 이름 규칙 (C1 — 영문 소문자·숫자·`-`, 1~40자).
REF_PATTERN = re.compile(r"^[a-z0-9-]{1,40}$")

#: 「이 PC의 값」 (Studio 설정 기준 — 읽기만 한다).
VALUE_OK = "정상"
VALUE_MISSING = "없음 — 설정 → 서비스 앱 키"
#: 키를 받지 않는 앱 (C13 `auth` 없음, ADR-0091).
VALUE_KEYLESS = "키를 받지 않음"

#: 단추 위 한 줄 — 「적용」이 어디로 가나 (STU-04 「적용」과 같은 말).
APPLY_NOTE = (
    "실행 위치·키 참조는 그림에 적용됩니다 — 파일에는 Ctrl+S로 저장됩니다. "
    "이름·버전·설명·담당자·태그는 바로 저장됩니다."
)
APPLY_NOTE_RECORD_ONLY = "이름·버전·설명·담당자·태그는 바로 저장됩니다."

#: 그림을 고칠 수 없는 까닭 (U3 — 끄고 **가까이에** 적는다).
NO_CANVAS = (
    "실행 위치와 키 참조는 **그림**에 있습니다 (`chk:process`) — 진입 정의 「{entry}」를 열면 "
    "고칠 수 있습니다."
)
NO_ENTRY = "정의가 없어 실행 위치와 키 참조를 적을 자리가 없습니다 — 먼저 정의를 저장하세요."

#: 「학습 상태 요약」 (ADR-0028).
NO_MEMORY = "재생 명세가 없습니다 (자율 수행으로 한 번 돌리면 배웁니다)."

NOTHING = "(없음)"


# ─────────────────────────── 담는 것 (Qt 없이 시험한다) ───────────────────────────


@dataclass(frozen=True)
class KeyRow:
    """「서비스 앱 키」 표 한 줄."""

    app_id: str
    ref: str
    #: 이 PC(Studio 설정)에 그 참조의 값이 있나.
    has_value: bool
    #: 이 참조를 쓰지 않고 다른 참조로 바꾼 태스크들 (`<정의>/<노드>`).
    overrides: tuple[str, ...] = ()
    #: 그림(`chk:process.service_keys`)에 적혀 있나 — 아니면 **기본값을 미리 넣은 줄**이다.
    written: bool = True
    #: 그 앱을 부르는 노드들 (`<정의>/<이름 또는 id>`).
    users: tuple[str, ...] = ()
    #: 고를 거리(Center 목록)에 있나. 목록을 받지 못했으면 `None` — 모르는 것으로 말하지 않는다.
    listed: bool | None = None
    #: 키를 받는 앱인가 (ADR-0091).
    takes_key: bool = True

    @property
    def value_text(self) -> str:
        if not self.takes_key:
            return VALUE_KEYLESS
        return VALUE_OK if self.has_value else VALUE_MISSING

    @property
    def written_text(self) -> str:
        return WRITTEN_YES if self.written else WRITTEN_DEFAULT

    @property
    def app_text(self) -> str:
        """「서비스 앱」 칸 — 목록에 없으면 STU-14와 **같은 말**을 붙인다."""
        return self.app_id if self.listed is not False else f"{self.app_id} — {NOT_LISTED}"

    @property
    def removable(self) -> bool:
        """「삭제」가 켜지나 — 쓰는 노드가 없거나 키를 받지 않는 앱이다 (부르는 앱의 줄은 지워도
        기본값으로 다시 생길 뿐이다)."""
        return not self.users or not self.takes_key


def default_ref(process_id: str) -> str:
    """기본 키 참조 이름 — BPM 프로세스 id의 `.`·`_`를 `-`로 (C1)."""
    return re.sub(r"[._]", "-", process_id)[:40]


def learning(process: BpmProcess) -> str:
    """「학습 상태 요약」 — 재생 명세가 몇 개인가 (ADR-0028). 읽기 전용이다."""
    specs = process.memory().specs
    if not specs:
        return NO_MEMORY
    nodes = ", ".join(sorted(one.key.rpartition(":")[2] for one in specs))
    return f"재생 명세 {len(specs)}개 — {nodes}"


def users_of(definitions: Sequence[Definition]) -> dict[str, tuple[str, ...]]:
    """앱 id → 그 앱을 부르는 노드들 (`<정의>/<이름 또는 id>`). 앱은 **이름순**이다.

    서비스 앱 태스크의 `app_id`와, 키 참조를 적은 확장 태스크의 확장 id다 (C13 — 서버 부분을
    가진 확장은 그 id로 키를 쓴다).
    """
    found: dict[str, list[str]] = {}
    for definition in definitions:
        if definition.process is None:
            continue
        for node in definition.process.all_nodes():
            where = f"{definition.name}/{node.name or node.id}"
            call = node.prop("serviceCall")
            if call is not None and call.app_id:
                found.setdefault(str(call.app_id), []).append(where)
            task = node.prop("task")
            if task is not None and task.extension and task.data.get("key_ref"):
                found.setdefault(str(task.extension), []).append(where)
    return {app_id: tuple(found[app_id]) for app_id in sorted(found)}


def apps_in(definitions: Sequence[Definition]) -> list[str]:
    """그림이 부르는 서비스 앱들 (서비스 앱 태스크·확장 태스크). **이름순**이다."""
    return list(users_of(definitions))


def with_drawn(process: BpmProcess, drawn: BpmnProcess | None) -> list[Definition]:
    """정의 목록에서 **진입 정의만 캔버스의 지금 그림으로** 바꾼 것 (없으면 그대로).

    열린 것은 진입 정의 하나라 나머지는 파일의 것이 지금 것이다.
    """
    entry = process.entry_definition
    if drawn is None or entry is None:
        return list(process.definitions)
    return [replace(one, process=drawn) if one.path == entry.path else one for one in process.definitions]


def overrides_of(definitions: Sequence[Definition], app_id: str, ref: str) -> tuple[str, ...]:
    """그 앱을 부르면서 **다른 참조**를 적은 태스크들 (STU-06 「태스크에서 바꾼 곳」).

    참조를 적지 않은 태스크는 상속하므로 **바꾼 것이 아니다.**
    """
    out = []
    for definition in definitions:
        if definition.process is None:
            continue
        for node in definition.process.all_nodes():
            call = node.prop("serviceCall")
            if call is not None and call.app_id == app_id and call.key_ref and call.key_ref != ref:
                out.append(f"{definition.name}/{node.id}")
            task = node.prop("task")
            if task is None or task.extension != app_id:
                continue
            theirs = str(task.data.get("key_ref") or "")
            if theirs and theirs != ref:
                out.append(f"{definition.name}/{node.id}")
    return tuple(out)


def key_rows(
    process: BpmProcess,
    info: ProcessInfo,
    *,
    has_value: Callable[[str], bool],
    definitions: Sequence[Definition] | None = None,
    listed: Collection[str] | None = None,
    keyless_apps: Collection[str] = (),
) -> list[KeyRow]:
    """표 한 벌 — **노드가 부르는 앱**과 **진입 정의가 적어 둔** 참조를 합친다.

    적어 두지 않은 앱도 줄로 보인다 (기본 참조 이름을 미리 넣어 둔다) — 빠진 것을 사람이
    찾아다니지 않게. 「실행 전 검사」가 빠진 참조를 오류로 말하는 것과 같은 줄이다.
    **키를 받지 않는 앱**(ADR-0091)은 적혀 있을 때만 줄이 된다(지울 수 있게).

    `definitions`는 지금 그림이다 (`with_drawn`) — 주지 않으면 파일의 것. `listed`는 고를 거리
    (Center 목록)에 있는 앱 id들이고 **받지 못했으면 `None`**이다.
    """
    drawn = list(process.definitions) if definitions is None else list(definitions)
    users = users_of(drawn)
    called = [one for one in users if one not in keyless_apps]
    apps = dict.fromkeys([*info.service_keys, *called])
    out = []
    for app_id in sorted(apps):
        written = str(info.service_keys.get(app_id) or "")
        ref = written or default_ref(process.id)
        out.append(
            KeyRow(
                app_id=app_id,
                ref=ref,
                has_value=has_value(ref),
                overrides=overrides_of(drawn, app_id, written) if written else (),
                written=bool(written),
                users=users.get(app_id, ()),
                listed=None if listed is None else app_id in listed,
                takes_key=app_id not in keyless_apps,
            )
        )
    return out


def server_warning(blockers: Sequence[str]) -> str:
    """「서버」를 골랐을 때 보일 한 줄 (STU-06). 걸리는 것이 없으면 빈 글이다."""
    if not blockers:
        return ""
    return (
        f"서버에서 실행할 수 없는 태스크 {len(blockers)}개 — 실행 전 검사에서 오류로 "
        "표시됩니다: " + ", ".join(blockers)
    )


def check(*, name: str, version: str, rows: Sequence[KeyRow], taken: Sequence[str]) -> str:
    """저장 전 검사. 빈 글이면 괜찮다 — **첫 흠 하나만** 말한다 (빨간 글자 한 줄이다)."""
    if not name.strip():
        return "이름을 적으세요."
    if name.strip() in taken:
        return f"같은 이름의 BPM 프로세스가 있습니다: {name.strip()}"
    if not re.fullmatch(r"\d+\.\d+\.\d+", version.strip()):
        return f"버전은 `1.0.0` 모양입니다 (받은 값 {version.strip() or '빈 값'})."
    seen: set[str] = set()
    for row in rows:
        if not REF_PATTERN.fullmatch(row.ref):
            return f"키 참조 이름 「{row.ref}」: 영문 소문자·숫자·`-`로 1~40자입니다."
        if row.ref in seen:
            return f"키 참조 이름이 겹칩니다: {row.ref}"
        seen.add(row.ref)
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
        has_value: Callable[[str], bool],
        editable: bool = True,
        task_type_locations: Mapping[str, Sequence[str]] | None = None,
        drawn: BpmnProcess | None = None,
        listed: Collection[str] | None = None,
        keyless_apps: Collection[str] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.process = process
        self.workspace = workspace
        self.has_value = has_value
        #: 확장 태스크 종류 → 실행 위치 (확장 호스트가 C13에서 읽어 준다). **F6과 같은 표**여야
        #: 한다 — 창이 세지 못하는 것을 검사가 막으면 사람이 영문을 모른다.
        self.task_type_locations = task_type_locations
        #: 진입 정의가 열려 있나 — **그림을 고칠 수 있는가**다 (아니면 두 칸이 꺼진다).
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
        #: 고를 거리(STU-14와 같은 Center 목록)의 앱 id들 — 받지 못했으면 `None`.
        self.listed = listed
        self.keyless_apps = tuple(keyless_apps)

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

        self.keys = QTableWidget(0, len(KEY_COLUMNS), self)
        self.keys.setObjectName("serviceKeys")
        self.keys.setHorizontalHeaderLabels(list(KEY_COLUMNS))
        self.keys.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.keys.verticalHeader().setVisible(False)
        header = self.keys.horizontalHeader()
        header.setSectionResizeMode(APP, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(REF, QHeaderView.ResizeMode.Stretch)
        for column in (WRITTEN, VALUE, USERS, OVERRIDES):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        #: 표의 줄과 같은 차례 — 앱 id·적힌 곳·쓰는 노드는 **표가 아니라 여기서** 읽는다.
        self._rows: list[KeyRow] = []
        for row in key_rows(
            process,
            self.info,
            has_value=has_value,
            definitions=self.definitions,
            listed=listed,
            keyless_apps=self.keyless_apps,
        ):
            self._add_row(row)

        # 「추가」는 없다 — 노드가 부르지 않는 앱의 키는 쓸 데가 없다 (STU-06).
        self.drop_key = QPushButton("삭제", self)
        self.drop_key.setToolTip("쓰는 노드가 없는 줄만 지웁니다")
        self.drop_key.clicked.connect(self._drop_selected)
        self.drop_key.setEnabled(False)
        self.keys.itemSelectionChanged.connect(self._refresh_drop)

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

        keys_row = QHBoxLayout()
        keys_row.addStretch(1)
        keys_row.addWidget(self.drop_key)

        warning_row = QHBoxLayout()
        warning_row.addWidget(self.warning, 1)
        warning_row.addWidget(self.to_pc)
        warning_row.addWidget(self.to_split)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(warning_row)
        layout.addWidget(QLabel("서비스 앱 키 — **참조 이름만** 적습니다 (값은 설정 → 서비스 앱 키).", self))
        layout.addWidget(self.keys, 1)
        layout.addLayout(keys_row)
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

    def _fixed_item(self, text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return item

    def _add_row(self, row: KeyRow) -> None:
        at = self.keys.rowCount()
        self.keys.insertRow(at)
        self._rows.append(row)
        app = self._fixed_item(row.app_text)
        if row.listed is False:
            # 오류색 — 토큰에서 온 팔레트의 것이다 (STU-14와 같은 색·같은 말).
            app.setForeground(self.keys.palette().brush(QPalette.ColorRole.BrightText))
            app.setToolTip(
                f"그림이 부르는 「{row.app_id}」은 Center 목록에 없습니다 — 그 노드에서 서비스 앱을 다시 고르세요."
            )
        self.keys.setItem(at, APP, app)
        ref = QTableWidgetItem(row.ref)
        if not row.written:
            # 기본값을 미리 넣은 줄은 흐리게 — 「적용」하면 적힌다 (「적힌 곳」 칸이 말한다).
            ref.setForeground(self.keys.palette().brush(QPalette.ColorRole.PlaceholderText))
        self.keys.setItem(at, REF, ref)
        self.keys.setItem(at, WRITTEN, self._fixed_item(row.written_text))
        self.keys.setItem(at, VALUE, self._fixed_item(row.value_text))
        users = self._fixed_item(str(len(row.users)))
        if row.users:
            users.setToolTip("\n".join(row.users))
        self.keys.setItem(at, USERS, users)
        count = self._fixed_item(str(len(row.overrides)) if row.overrides else "—")
        if row.overrides:
            # 누르면 목록 — 말풍선으로 보인다 (창을 또 띄우지 않는다).
            count.setToolTip("\n".join(row.overrides))
        self.keys.setItem(at, OVERRIDES, count)

    def _lock_graph_fields(self) -> None:
        """그림을 고칠 수 없으면 **두 칸만** 끄고 까닭을 적는다 (나머지는 저장된다)."""
        if self._graph_open():
            return
        why = NO_ENTRY if self.entry is None else NO_CANVAS.format(entry=self.entry.path.name)
        for one in (self.location_box, self.keys, self.drop_key):
            one.setEnabled(False)
            one.setToolTip(why)
        self.note.setText(why)
        self.note.setTextFormat(Qt.TextFormat.MarkdownText)

    # ── 표 읽기 ──

    def rows(self) -> list[KeyRow]:
        """표의 지금 모습 — 사람이 고칠 수 있는 것은 참조 이름뿐이다."""
        out = []
        for at, row in enumerate(self._rows):
            ref = self._cell(at, REF)
            out.append(replace(row, ref=ref, has_value=self.has_value(ref)))
        return out

    def _cell(self, at: int, column: int) -> str:
        item = self.keys.item(at, column)
        return item.text().strip() if item is not None else ""

    def _selected(self) -> list[int]:
        return sorted({index.row() for index in self.keys.selectedIndexes()})

    def _refresh_drop(self) -> None:
        """「삭제」는 **쓰는 노드가 없는 줄만** 켠다 (`KeyRow.removable`)."""
        picked = self._selected()
        self.drop_key.setEnabled(
            self.keys.isEnabled() and bool(picked) and all(self._rows[at].removable for at in picked)
        )

    def _drop_selected(self) -> None:
        for at in reversed(self._selected()):
            if not self._rows[at].removable:
                continue
            self.keys.removeRow(at)
            del self._rows[at]
        self._refresh_drop()

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
        rows = self.rows() if self.keys.isEnabled() else []
        problem = check(
            name=self.name_box.text(), version=self.version_box.text(), rows=rows, taken=taken
        )
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
        if self.keys.isEnabled():
            self.process_patch = self._patch(rows)
        self.accept()

    def _patch(self, rows: Sequence[KeyRow]) -> str:
        """캔버스에 넘길 `chk:process` 본문 (JSON 글 그대로 — `setProperties`의 규약).

        **읽은 것을 통째로 되돌려 쓴다** — `extensions`·`inputs`·`outputs`를 빼면 그 선언이
        사라진다 (창이 모르는 칸도 지키는 자리다).
        """
        made = self.info.model_copy(deep=True)
        made.run_location = self.location()  # type: ignore[assignment]
        made.service_keys = {row.app_id: row.ref for row in rows if row.app_id and row.ref}
        return json.dumps(made.to_json_dict(), ensure_ascii=False, indent=2)


__all__ = [
    "DEFAULT_LOCATION",
    "DEFAULT_SIZE",
    "KEY_COLUMNS",
    "LOCATIONS",
    "NO_CANVAS",
    "NO_ENTRY",
    "APPLY_NOTE",
    "APPLY_NOTE_RECORD_ONLY",
    "NO_MEMORY",
    "REF_PATTERN",
    "TITLE",
    "VALUE_MISSING",
    "VALUE_KEYLESS",
    "VALUE_OK",
    "WRITTEN_DEFAULT",
    "WRITTEN_YES",
    "KeyRow",
    "ProcessInfoDialog",
    "apps_in",
    "check",
    "default_ref",
    "key_rows",
    "learning",
    "overrides_of",
    "server_warning",
    "users_of",
    "with_drawn",
]
