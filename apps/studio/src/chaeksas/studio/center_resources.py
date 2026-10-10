"""STU-11 Center 공유 자원 — Center에 올라온 공유 BPM 프로세스·툴팩을 본다.

지키는 것 넷.

- **목록은 C5 패키지 표에서 온다** (`GET /packages?kind=`). 「상태」가 **패키지 상태**(후보·
  승인됨·지원 종료·철회)라서다 — CON-06이 같은 것을 읽는다. 표기와 색은 `status_map`의
  「패키지」에 있는 것만 쓴다.
- **들고 있지 않는다.** 닿지 못하면 그 자리에서 말하고 「새로 고침」을 둔다 (Studio는 현장이
  아니라 개발 도구다 — `services.py`·STU-03·STU-15와 같은 결).
- **「설치」·「제거」는 아직 끄고 까닭을 적는다** (U3). 받은 패키지를 **어디에 풀고** 시험
  실행의 `requires.libs`를 거기서 어떻게 찾는지가 정해지지 않았다 — 자리를 ADR로 정해야 하는
  일이고, 그 전에 화면만 켜면 「눌렀는데 아무 일도 없다」가 된다 (`docs/09-gaps.md` §4-5).
- **개수는 매니페스트의 `provides`가 말한다** (C1) — Center가 짓는 값이 아니다. `provides`가
  없으면 **0이 아니라 「매니페스트에 없음」**이다 (CON-06과 같은 규칙: 없는 것과 비어 있는
  것은 다르다).

창은 **Center를 제 손으로 읽는다** — STU-03과 달리 부모 창이 받아 주지 않는다. 뿌리 넷을
한 번에 그리는 탐색기와 달리 여기는 **이 창을 열 때와 「새로 고침」** 두 때만 읽는다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from chaeksas.contracts.center_api import PackageInfo
from chaeksas.qt.theme import status_color
from chaeksas.studio.services import CenterReader, CenterUnreachable

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

#: 「설치본」 칸 — 받아 둘 자리가 아직 없다 (§판단 1).
NOT_INSTALLED = "—"

#: 끄고 적는 까닭 (U3 — 끄고 **가까이에** 적는다).
NO_INSTALL = (
    "설치·제거는 아직 없습니다 — 받은 패키지를 둘 자리를 정해야 합니다 "
    "(docs/09-gaps.md §4-5)."
)
NO_CENTER = "Center 주소·Studio 키가 설정되지 않았습니다 — 설정 → 「Center」 (STU-10)."

#: 탭 위 한 줄 (STU-11 「각 탭 위에 한 줄 설명」).
LIB_NOTE = (
    "Center에 올라온 공유 BPM 프로세스입니다. 「공유 BPM 프로세스 Center로 올리기」로 올립니다. "
    "「설치본」은 이 PC에 받아 둔 판인데, 아직 받는 길이 없어 비어 있습니다."
)
TOOLPACK_NOTE = (
    "Center에 올라온 툴팩입니다. AI 태스크의 허용 도구에서 그 도구들을 고릅니다. "
    "「설치본」은 이 PC에 받아 둔 판인데, 아직 받는 길이 없어 비어 있습니다."
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
    #: 이 PC에 받아 둔 판. 아직 받는 길이 없어 늘 빈 글이다.
    installed: str = ""

    @property
    def label(self) -> str:
        """「이름」 칸 — 매니페스트의 `name`이 있으면 그것, 없으면 id다."""
        return self.name or self.package_id

    @property
    def status_text(self) -> str:
        return STATUS_LABEL.get(self.status, self.status)

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


def row_of(info: PackageInfo, kind: str) -> Row:
    return Row(
        package_id=info.id,
        version=info.version,
        status=info.status,
        count=count_of(info, kind),
        name=info.name or "",
        installed="",
    )


def listing(reader: CenterReader | None, kind: str) -> Listing:
    """그 갈래 한 탭. **Center가 없으면 두드리지 않는다** (STU-03과 같은 규칙)."""
    empty = EMPTY_LIB if kind == KIND_LIB else EMPTY_TOOLPACK
    if reader is None:
        return Listing(note=NO_CENTER)
    try:
        found = reader.packages(kind)
    except CenterUnreachable as e:
        return Listing(note=f"받지 못했습니다 — {e}")
    rows = tuple(sorted((row_of(one, kind) for one in found), key=_order))
    return Listing(rows=rows, note="" if rows else empty)


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
                row.version,
                row.status_text,
                row.installed or NOT_INSTALLED,
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
                if column == INSTALLED and not row.installed:
                    item.setToolTip(NO_INSTALL)
                self.table.setItem(at, column, item)

    def selected(self) -> Row | None:
        found = {index.row() for index in self.table.selectedIndexes()}
        at = next(iter(sorted(found)), None)
        return self.rows[at] if at is not None and at < len(self.rows) else None


class CenterResourcesDialog(QDialog):
    """STU-11. 읽기만 한다 — 「설치」·「제거」는 끄고 까닭을 붙인다."""

    def __init__(self, reader: CenterReader | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.reader = reader
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
        # **할 수 없는 일도 둔다** — 끄고 까닭을 말풍선에 붙인다 (U3).
        self.install_button = QPushButton("설치", self)
        self.remove_button = QPushButton("제거...", self)
        for one in (self.install_button, self.remove_button):
            one.setEnabled(False)
            one.setToolTip(NO_INSTALL)
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

        self.refresh()

    def refresh(self) -> None:
        """두 탭을 다시 받는다. **한 탭을 못 받아도 나머지는 그린다.**"""
        self.problems = []
        for tab in (self.libs, self.toolpacks):
            found = listing(self.reader, tab.kind)
            tab.show_listing(found)
            if found.note and not found.rows:
                self.problems.append(f"{self.tabs.tabText(self.tabs.indexOf(tab))}: {found.note}")
        self.note.setText(" / ".join(self.problems) if self.problems else READY)


__all__ = [
    "COLUMNS",
    "DEFAULT_SIZE",
    "EMPTY_LIB",
    "EMPTY_TOOLPACK",
    "KIND_LIB",
    "KIND_TOOLPACK",
    "NOT_INSTALLED",
    "NO_CENTER",
    "NO_INSTALL",
    "NO_PROVIDES",
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
