"""STU-11 Center 공유 자원 — Center에 올라온 공유 BPM 프로세스·툴팩을 본다.

지키는 것 넷.

- **목록은 C5 패키지 표에서 온다** (`GET /packages?kind=`). 「상태」가 **패키지 상태**(후보·
  승인됨·지원 종료·철회)라서다 — CON-06이 같은 것을 읽는다. 표기와 색은 `status_map`의
  「패키지」에 있는 것만 쓴다.
- **들고 있지 않는다.** 닿지 못하면 그 자리에서 말하고 「새로 고침」을 둔다 (Studio는 현장이
  아니라 개발 도구다 — `services.py`·STU-03·STU-15와 같은 결).
- **설치는 BPM 프로세스 하나에 하는 일이다** (ADR-0048) — 받은 것이 그 작업 폴더의 `libs/`로
  가므로 「설치본」도 **열린 BPM 프로세스 기준**이고, 열린 것이 없으면 끄고 까닭을 적는다 (U3).
  **툴팩 탭의 「설치」는 아직 끈다** — 자리가 아니라 **도구를 싣는 길이 아무 데도 없어서**다
  (`docs/09-gaps.md` §4-5).
- **개수는 매니페스트의 `provides`가 말한다** (C1) — Center가 짓는 값이 아니다. `provides`가
  없으면 **0이 아니라 「매니페스트에 없음」**이다 (CON-06과 같은 규칙: 없는 것과 비어 있는
  것은 다르다).

창은 **Center를 제 손으로 읽는다** — STU-03과 달리 부모 창이 받아 주지 않는다. 뿌리 넷을
한 번에 그리는 탐색기와 달리 여기는 **이 창을 열 때와 「새로 고침」** 두 때만 읽는다.
"""

from __future__ import annotations

import logging
from collections.abc import Collection, Mapping
from dataclasses import dataclass

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from chaeksas.contracts.center_api import PackageInfo
from chaeksas.qt.theme import status_color
from chaeksas.studio import install as installer
from chaeksas.studio.services import CenterReader, CenterUnreachable
from chaeksas.studio.workspace import BpmProcess, InstalledLib, Workspace

log = logging.getLogger(__name__)

TITLE = "Center 공유 자원"
#: 처음 크기 (STU-11 — 760×460).
DEFAULT_SIZE = (760, 460)

COLUMNS = ("이름", "Center 버전", "상태", "설치본", "개수")
NAME, VERSION, STATUS, INSTALLED, COUNT = range(len(COLUMNS))

#: 패키지 갈래 (C1) — 탭 하나가 갈래 하나다.
KIND_LIB = "process_lib"
KIND_TOOLPACK = "toolpack"

#: `status_map`의 묶음. **이 표에 있는 표기만 쓴다** (스타일 가이드 §2-2).
STATUS_GROUP = "패키지"
#: Center 상태 → 그 표의 표기. 모르는 값은 **그대로 보인다** (계약 원칙 10 — 열린 문자열).
STATUS_LABEL = {
    "candidate": "후보",
    "approved": "승인됨",
    "deprecated": "지원 종료",
    "revoked": "철회",
}

#: 「설치본」 칸 — 이 BPM 프로세스에 받아 둔 것이 없다.
NOT_INSTALLED = "—"
#: 설치본이 Center 버전보다 낡았을 때 붙는 말 (STU-11).
NEWER = "(갱신 있음)"
#: Center 목록에 없는데 설치되어 있는 것 (STU-11 「로컬만」).
LOCAL_ONLY = "로컬만"

#: 끄고 적는 까닭 (U3 — 끄고 **가까이에** 적는다).
NO_TOOLPACK_INSTALL = (
    "툴팩 설치는 아직 없습니다 — 받은 도구를 **싣는 길**이 아직 없습니다 "
    "(docs/09-gaps.md §4-5)."
)
NO_PROCESS = "열린 BPM 프로세스가 없습니다 — 설치는 BPM 프로세스 하나에 하는 일입니다 (ADR-0048)."
NO_SELECTION = "설치할 줄을 고르세요."
NO_CENTER = "Center 주소·Studio 키가 설정되지 않았습니다 — 설정 → 「Center」 (STU-10)."

#: 탭 위 한 줄 (STU-11 「각 탭 위에 한 줄 설명」).
LIB_NOTE = (
    "Center에 올라온 공유 BPM 프로세스입니다. 「공유 BPM 프로세스 Center로 올리기」로 올립니다. "
    "「설치」는 **열린 BPM 프로세스**의 `libs/`에 풀어, 그 BPM 프로세스가 Call Activity로 "
    "부를 수 있게 합니다 (시험 실행도 현장과 같은 파일을 봅니다)."
)
TOOLPACK_NOTE = (
    "Center에 올라온 툴팩입니다. AI 태스크의 허용 도구에서 그 도구들을 고릅니다. "
    "「설치」는 아직 없습니다 — 받은 도구를 싣는 길을 먼저 정해야 합니다."
)

EMPTY_LIB = "Center에 올라온 공유 BPM 프로세스가 없습니다."
EMPTY_TOOLPACK = "Center에 올라온 툴팩이 없습니다."
NO_PROVIDES = "매니페스트에 없음"
READY = "Center에서 읽었습니다."


# ─────────────────────────── 담는 것 (Qt 없이 시험한다) ───────────────────────────


@dataclass(frozen=True)
class Row:
    """표 한 줄."""

    package_id: str
    version: str
    status: str
    #: 정의 수 또는 도구 수. 매니페스트에 `provides`가 없으면 `None`이다.
    count: int | None
    name: str = ""
    #: **열린 BPM 프로세스**에 받아 둔 판 (ADR-0048). 없으면 빈 글이다.
    installed: str = ""

    @property
    def label(self) -> str:
        """「이름」 칸 — 매니페스트의 `name`이 있으면 그것, 없으면 id다."""
        return self.name or self.package_id

    @property
    def status_text(self) -> str:
        return LOCAL_ONLY if self.status == LOCAL_ONLY else STATUS_LABEL.get(self.status, self.status)

    @property
    def installed_text(self) -> str:
        """「설치본」 칸 — 설치된 판과, 그것이 낡았으면 「(갱신 있음)」."""
        if not self.installed:
            return NOT_INSTALLED
        if self.status == LOCAL_ONLY or self.installed == self.version:
            return self.installed
        return f"{self.installed} {NEWER}"

    @property
    def count_text(self) -> str:
        return NO_PROVIDES if self.count is None else str(self.count)


@dataclass(frozen=True)
class Listing:
    """한 탭이 그릴 것."""

    rows: tuple[Row, ...] = ()
    #: 비어 있을 때·못 받았을 때 할 말.
    note: str = ""


def count_of(info: PackageInfo, kind: str) -> int | None:
    """「개수」 — 정의 수(`process_lib`) 또는 도구 수(`toolpack`).

    **`provides`가 없으면 `None`이다** — 0으로 적으면 「아무것도 제공하지 않는다」로 읽힌다.
    """
    manifest = info.manifest
    if manifest is None or manifest.provides is None:
        return None
    provides = manifest.provides
    return len(provides.processes if kind == KIND_LIB else provides.tools)


def row_of(
    info: PackageInfo, kind: str, installed: Mapping[str, InstalledLib] | None = None
) -> Row:
    found = (installed or {}).get(info.id)
    return Row(
        package_id=info.id,
        version=info.version,
        status=info.status,
        count=count_of(info, kind),
        name=info.name or "",
        installed=found.version if found is not None else "",
    )


def listing(
    reader: CenterReader | None, kind: str, process: BpmProcess | None = None
) -> Listing:
    """그 갈래 한 탭. **Center가 없으면 두드리지 않는다** (STU-03과 같은 규칙).

    설치된 것이 Center 목록에 없으면 **「로컬만」 줄로 남긴다** (STU-11) — 지워진 패키지를
    쓰고 있다는 것을 사람이 알아야 하고, 그 줄에서 「제거」도 할 수 있어야 한다.
    """
    empty = EMPTY_LIB if kind == KIND_LIB else EMPTY_TOOLPACK
    installed = installer.installed_of(process) if kind == KIND_LIB else {}
    if reader is None:
        return Listing(rows=tuple(_local_only(installed, set())), note=NO_CENTER)
    try:
        found = reader.packages(kind)
    except CenterUnreachable as e:
        return Listing(
            rows=tuple(_local_only(installed, set())), note=f"받지 못했습니다 — {e}"
        )
    rows = [row_of(one, kind, installed) for one in found]
    rows += _local_only(installed, {one.package_id for one in rows})
    return Listing(rows=tuple(sorted(rows, key=_order)), note="" if rows else empty)


def _local_only(installed: Mapping[str, InstalledLib], seen: Collection[str]) -> list[Row]:
    """Center 목록에 없는데 설치되어 있는 것 (STU-11 「로컬만」).

    **STU-03은 이 줄을 그리지 않는다** (ADR-0051) — 둘째 단계와 「받는 것·내놓는 것」은
    매니페스트의 `provides`가 주는 것이고 Center 목록에서 빠진 패키지는 그것을 주지 않는다.
    """
    return [
        Row(
            package_id=package_id,
            version="",
            status=LOCAL_ONLY,
            count=None,
            installed=lib.version,
        )
        for package_id, lib in sorted(installed.items())
        if package_id not in seen
    ]


def _order(row: Row) -> tuple[str, str]:
    return (row.label, row.version)


# ─────────────────────────── 창 ───────────────────────────


class _Tab(QWidget):
    """탭 하나 — 설명 한 줄 + 표. 「새로 고침」·단추는 창이 들고 있다."""

    def __init__(self, kind: str, note: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kind = kind
        self.rows: list[Row] = []

        self.description = QLabel(note, self)
        self.description.setWordWrap(True)

        self.table = QTableWidget(0, len(COLUMNS), self)
        self.table.setObjectName(f"packages-{kind}")
        self.table.setHorizontalHeaderLabels(list(COLUMNS))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(NAME, QHeaderView.ResizeMode.Stretch)
        for column in (VERSION, STATUS, INSTALLED, COUNT):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)

        layout = QVBoxLayout(self)
        layout.addWidget(self.description)
        layout.addWidget(self.table, 1)

    def show_listing(self, found: Listing) -> None:
        self.rows = list(found.rows)
        self.table.setRowCount(len(self.rows))
        for at, row in enumerate(self.rows):
            texts = (
                row.label,
                row.version or NOT_INSTALLED,
                row.status_text,
                row.installed_text,
                row.count_text,
            )
            for column, text in enumerate(texts):
                item = QTableWidgetItem(text)
                if column == NAME:
                    item.setToolTip(row.package_id)
                if column == STATUS:
                    # 색은 **그 표기의 것**만 (스타일 가이드 §2-2). 모르는 상태는 색이 없다.
                    color = status_color(STATUS_GROUP, row.status_text, part="fg")
                    if color is not None:
                        item.setForeground(QColor(color))
                self.table.setItem(at, column, item)

    def selected(self) -> Row | None:
        found = {index.row() for index in self.table.selectedIndexes()}
        at = next(iter(sorted(found)), None)
        return self.rows[at] if at is not None and at < len(self.rows) else None


class CenterResourcesDialog(QDialog):
    """STU-11. Center는 **읽기만** 하고, 설치는 **작업 폴더에** 쓴다 (ADR-0048).

    설치는 **열린 BPM 프로세스 하나**에 하는 일이라 그 창을 들고 있어야 한다. 열린 것이 없으면
    표는 그대로 보이고 단추만 꺼진다 (U3 — 읽기는 되는 자리다).
    """

    def __init__(
        self,
        reader: CenterReader | None,
        parent: QWidget | None = None,
        *,
        workspace: Workspace | None = None,
        process: BpmProcess | None = None,
    ) -> None:
        super().__init__(parent)
        self.reader = reader
        self.workspace = workspace
        self.process = process
        #: 마지막으로 못 받은 사유들 (아래 한 줄이 그대로 보인다).
        self.problems: list[str] = []

        self.setWindowTitle(TITLE)
        self.resize(*DEFAULT_SIZE)

        self.tabs = QTabWidget(self)
        self.libs = _Tab(KIND_LIB, LIB_NOTE, self)
        self.toolpacks = _Tab(KIND_TOOLPACK, TOOLPACK_NOTE, self)
        self.tabs.addTab(self.libs, "공유 BPM 프로세스")
        self.tabs.addTab(self.toolpacks, "툴팩")

        #: 아래 한 줄 (STU-11 「아래 상태 줄」).
        self.note = QLabel("", self)
        self.note.setWordWrap(True)

        self.refresh_button = QPushButton("새로 고침", self)
        self.refresh_button.clicked.connect(self.refresh)
        self.install_button = QPushButton("설치", self)
        self.install_button.clicked.connect(self.install_selected)
        self.remove_button = QPushButton("제거...", self)
        self.remove_button.clicked.connect(self.remove_selected)
        self.close_button = QPushButton("닫기", self)
        self.close_button.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        for one in (self.refresh_button, self.install_button, self.remove_button):
            buttons.addWidget(one)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(self.note)
        layout.addLayout(buttons)

        self.tabs.currentChanged.connect(lambda _: self.update_buttons())
        for tab in (self.libs, self.toolpacks):
            tab.table.itemSelectionChanged.connect(self.update_buttons)
        self.refresh()

    # ── 읽기 ──

    def refresh(self) -> None:
        """두 탭을 다시 받는다. **한 탭을 못 받아도 나머지는 그린다.**"""
        self.problems = []
        for tab in (self.libs, self.toolpacks):
            found = listing(self.reader, tab.kind, self.process)
            tab.show_listing(found)
            if found.note and not found.rows:
                self.problems.append(f"{self.tabs.tabText(self.tabs.indexOf(tab))}: {found.note}")
        self.note.setText(" / ".join(self.problems) if self.problems else READY)
        self.update_buttons()

    def current_tab(self) -> _Tab:
        found = self.tabs.currentWidget()
        return found if isinstance(found, _Tab) else self.libs

    def update_buttons(self) -> None:
        """**할 수 없으면 끄고 까닭을 붙인다** (U3) — 까닭이 넷이라 하나씩 가른다."""
        tab = self.current_tab()
        row = tab.selected()
        if tab.kind != KIND_LIB:
            why = NO_TOOLPACK_INSTALL
        elif self.process is None or self.workspace is None:
            why = NO_PROCESS
        elif row is None:
            why = NO_SELECTION
        else:
            why = ""
        can_install = not why and row is not None and row.status != LOCAL_ONLY
        self.install_button.setEnabled(bool(can_install))
        self.install_button.setText(
            "갱신" if row is not None and row.installed and can_install else "설치"
        )
        self.install_button.setToolTip(
            why or ("Center 목록에 없는 판은 받을 수 없습니다." if not can_install else "")
        )
        self.remove_button.setEnabled(bool(not why and row is not None and row.installed))
        self.remove_button.setToolTip(
            why or ("" if row is not None and row.installed else "이 BPM 프로세스에 설치된 것이 없습니다.")
        )

    # ── 쓰기 (작업 폴더에만 — Center는 읽기만 한다) ──

    def install_selected(self) -> None:
        row = self.current_tab().selected()
        if row is None or self.workspace is None:
            return
        try:
            done = installer.install(
                self.workspace,
                self.process,
                self.reader,
                package_id=row.package_id,
                version=row.version,
            )
        except installer.InstallFailed as e:
            self.note.setText(str(e))
            return
        self.refresh()
        self.note.setText(done.message)

    def remove_selected(self) -> None:
        """제거는 **되돌릴 수 없어** 묻는다 — 부르는 노드가 있으면 수를 말한다 (U9)."""
        row = self.current_tab().selected()
        if row is None or self.workspace is None or self.process is None:
            return
        found = next((one for one in self.process.libs if one.package_id == row.package_id), None)
        if found is None:
            return
        callers = installer.callers_of(self.process, found)
        tail = f"\n\n이 공유 BPM 프로세스를 부르는 곳이 {len(callers)}개 있습니다." if callers else ""
        answer = QMessageBox.question(
            self,
            "제거",
            f"{found.ref}을 {self.process.display}에서 지웁니다. 되돌릴 수 없습니다.{tail}",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            message = installer.remove(self.workspace, self.process, package_id=row.package_id)
        except installer.InstallFailed as e:
            self.note.setText(str(e))
            return
        self.refresh()
        self.note.setText(message)


__all__ = [
    "COLUMNS",
    "DEFAULT_SIZE",
    "EMPTY_LIB",
    "EMPTY_TOOLPACK",
    "KIND_LIB",
    "KIND_TOOLPACK",
    "LOCAL_ONLY",
    "NEWER",
    "NOT_INSTALLED",
    "NO_CENTER",
    "NO_PROCESS",
    "NO_PROVIDES",
    "NO_SELECTION",
    "NO_TOOLPACK_INSTALL",
    "READY",
    "STATUS_GROUP",
    "STATUS_LABEL",
    "TITLE",
    "CenterResourcesDialog",
    "Listing",
    "Row",
    "count_of",
    "listing",
    "row_of",
]
