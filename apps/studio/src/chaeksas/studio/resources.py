"""STU-03 리소스 탐색기 — BPM 프로세스 **밖에서** 가져다 쓰는 것.

지키는 것 다섯.

- **목록은 Center 리소스 목록(C7)에서 온다.** 서비스 앱은 STU-14가 이미 받아 둔 고를 거리를
  그대로 쓰고(`service_catalog.Catalog` — 같은 것을 두 번 받지 않는다), 기여 자원과 툴팩은
  `CenterReader`가 뿌리마다 한 번씩 읽는다.
- **들고 있지 않는다.** 닿지 못하면 그 자리에서 말하고 「새로 고침」을 둔다 — Studio는 현장이
  아니라 개발 도구다 (`services.py`·STU-15와 같은 결, ADR-0007은 현장 쪽 규칙이다).
- **뿌리의 일부는 확장이 선언한다** (`studio.resource_views`) — 이 파일에 확장 이름이 없다
  (ADR-0018). 뿌리 이름·자원 갈래·만들 태스크 종류가 모두 선언에서 온다.
- **`data`를 해석하지 않는다** (C13 §5). 그래서 기여 뿌리는 **한 단계**다 — 항목의 `name`과
  `summary`만 그린다. 「서비스 앱 → 작업」·「툴팩 → 도구」는 **플랫폼이 아는 것**이라(C11
  manifest·C7 `tools`) 둘째 단계를 그린다.
- **쓸 수 없는 뿌리·항목도 사라지지 않는다** — 줄을 끄고 까닭을 적는다 (U3).

「캔버스에 추가」가 만드는 것은 `Create` 하나로 모아 둔다 — 캔버스 명령 하나(`createTask`)가
노드를 만들고 **실행 취소도 한 걸음**이다. 끌어다 놓기는 아직이다 (STU-03 `> 상태:`).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from chaeksas.contracts.extension import ResourceView
from chaeksas.contracts.resources import ContributedResource, ToolpackResource
from chaeksas.studio import service_catalog
from chaeksas.studio.services import CenterReader, CenterUnreachable

log = logging.getLogger(__name__)

HEADERS = ("리소스", "구분", "설명")

#: 고정 뿌리 셋 (STU-03 표). 그 밖의 뿌리는 확장이 선언한다.
ROOT_SHARED = "shared-processes"
ROOT_SERVICE = "service-apps"
ROOT_TOOLPACK = "toolpacks"

SHARED_LABEL = "공유 BPM 프로세스"
SERVICE_LABEL = "서비스 앱"
TOOLPACK_LABEL = "툴팩"

#: 쓸 수 없는 줄의 까닭 (U3 — 끄고 **가까이에** 적는다).
NO_SHARED = "Studio에서 Center로 올리는 길이 아직 없습니다 (docs/09-gaps.md §4-5)."
NO_TOOLPACK_INSTALL = "툴팩 설치·제거는 STU-11 「Center 공유 자원」이 할 일입니다 (docs/09-gaps.md §4-5)."
NO_CENTER = "Center 주소·Studio 키가 설정되지 않았습니다 — 설정 → 「Center」 (STU-10)."

#: 비어 있을 때 할 말 (빈 뿌리를 말없이 두지 않는다).
EMPTY_SERVICE = "Center에 등록된 서비스 앱이 없습니다."
EMPTY_TOOLPACK = "Center에 올라온 툴팩이 없습니다."
EMPTY_VIEW = "Center에 등록된 항목이 없습니다."
EMPTY_TREE = "뿌리를 고르면 그 아래를 봅니다."

#: 만들 노드의 BPMN 종류 — 확장 태스크·서비스 앱 태스크는 둘 다 `serviceTask`다 (C14).
BPMN_SERVICE_TASK = "bpmn:ServiceTask"

OPERATION_KIND = "작업"
TOOL_KIND = "도구"

_KIND = Qt.ItemDataRole.UserRole + 1
_PAYLOAD = Qt.ItemDataRole.UserRole + 2

ROW_ROOT = "root"
ROW_ITEM = "item"


# ─────────────────────────── 담는 것 (Qt 없이 시험한다) ───────────────────────────


@dataclass(frozen=True)
class Create:
    """「캔버스에 추가」로 만들 노드 하나.

    `chk`는 캔버스의 규약 그대로 **`{요소 이름: JSON 글}`**이다 (`setProperties`와 같다).
    """

    bpmn: str
    name: str
    chk: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Item:
    """뿌리 아래 한 줄."""

    id: str
    label: str
    kind: str = ""
    note: str = ""
    tip: str = ""
    #: 「캔버스에 추가」가 만들 것. 없으면 그 항목으로는 노드를 만들 수 없다.
    create: Create | None = None
    #: 「작업 설명 보기」가 띄울 글. 비면 그 항목이 메뉴에 없다.
    detail: str = ""
    #: 「관리 콘솔에서 보기」가 열 주소 (C7 `console_url`). 비면 메뉴에 없다.
    console_url: str = ""
    children: tuple[Item, ...] = ()


@dataclass(frozen=True)
class Root:
    """뿌리 하나."""

    id: str
    label: str
    items: tuple[Item, ...] = ()
    #: 이 뿌리를 쓸 수 없는 까닭 (있으면 줄을 끄고 이것을 보인다, U3).
    off: str = ""
    #: 비어 있을 때 할 말.
    empty: str = ""
    #: 이 뿌리의 항목에 걸 수 있는데 지금은 할 수 없는 일 (U3 — 끄고 이유를 붙인다).
    blocked: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Tree:
    """리소스 탐색기가 그릴 것 한 벌."""

    roots: tuple[Root, ...] = ()
    #: 받지 못한 것들 (안내 줄이 그대로 보인다).
    problems: tuple[str, ...] = ()


# ─────────────────────────── 모으기 ───────────────────────────


def shared_root() -> Root:
    """「공유 BPM 프로세스」 — **올리는 길이 없어 늘 비어 있다**. 뿌리는 두고 까닭을 적는다."""
    return Root(id=ROOT_SHARED, label=SHARED_LABEL, off=NO_SHARED)


def _operation_detail(app: service_catalog.App, operation: service_catalog.Operation) -> str:
    """「작업 설명 보기」가 띄울 글 — manifest·정의가 말해 준 것만 (STU-14와 같은 출처)."""
    lines = [f"{app.name} / {operation.name}", ""]
    if operation.description:
        lines += [operation.description, ""]
    lines.append(f"지원 수행 모드: {', '.join(operation.modes) or '(정의에 없음)'}")
    if operation.timeout_s:
        lines.append(f"제한 시간 기본값: {operation.timeout_s}초")
    if operation.retry_on:
        lines.append(f"다시 부를 상태 코드: {', '.join(str(one) for one in operation.retry_on)}")
    if not operation.has_schema:
        lines += ["", "입력·출력 칸을 정의가 알려 주지 않았습니다 — 편집기에서 직접 적습니다 (C11 선택 칸)."]
        return "\n".join(lines)
    for title, fields in (("입력", operation.inputs), ("출력", operation.outputs)):
        lines += ["", f"{title}:"]
        if not fields:
            lines.append("  (없음)")
        for one in fields:
            mark = " *필수" if one.required else ""
            shown = f"  {one.name} ({one.type or '타입 없음'}){mark}"
            lines.append(f"{shown} — {one.description}" if one.description else shown)
    return "\n".join(lines)


def _operation_tip(operation: service_catalog.Operation) -> str:
    """말풍선 — 서비스 앱 작업은 **입력·출력 칸**이다 (STU-03 「툴팁」)."""
    if not operation.has_schema:
        return "입력·출력 칸을 정의가 알려 주지 않았습니다."
    inputs = ", ".join(one.name for one in operation.inputs) or "(없음)"
    outputs = ", ".join(one.name for one in operation.outputs) or "(없음)"
    return f"입력: {inputs} / 출력: {outputs}"


def _service_call(app: service_catalog.App, operation: service_catalog.Operation) -> Create:
    """`chk:serviceCall` 하나 (C14) — **키 참조는 넣지 않는다**(BPM 프로세스 설정을 상속한다)."""
    body = {"app_id": app.app_id, "operation": operation.name}
    return Create(
        bpmn=BPMN_SERVICE_TASK,
        name=f"{app.name} {operation.name}",
        chk={"serviceCall": json.dumps(body, ensure_ascii=False)},
    )


def service_root(catalog: service_catalog.Catalog | None) -> Root:
    """「서비스 앱」 — 앱 → 작업. 고를 거리는 STU-14와 **같은 것**이다 (`service_catalog`)."""
    apps = catalog.apps if catalog is not None else ()
    items = []
    for app in apps:
        children = tuple(
            Item(
                id=f"{app.app_id}/{operation.name}",
                label=operation.name,
                kind=OPERATION_KIND,
                note=operation.description or ("결정 수행 불가" if not operation.deterministic_ok else ""),
                tip=_operation_tip(operation),
                create=_service_call(app, operation),
                detail=_operation_detail(app, operation),
            )
            for operation in app.operations
        )
        items.append(
            Item(
                id=app.app_id,
                label=app.name,
                kind=f"{app.kind} · {app.tier}" if app.tier else app.kind,
                note=app.status_text,
                tip=app.app_id,
                console_url=app.console_url,
                children=children,
            )
        )
    return Root(id=ROOT_SERVICE, label=SERVICE_LABEL, items=tuple(items), empty=EMPTY_SERVICE)


def toolpack_root(found: Iterable[ToolpackResource]) -> Root:
    """「툴팩」 — 툴팩 → 도구. 끌어다 놓는 자리가 없다 (AI 태스크의 허용 도구에서 고른다)."""
    items = []
    for one in found:
        tools = tuple(
            Item(
                id=f"{one.id}/{tool.get('name') or ''}",
                label=str(tool.get("name") or "(이름 없음)"),
                kind=str(tool.get("domain") or TOOL_KIND),
                note=str(tool.get("description") or ""),
            )
            for tool in one.tools
        )
        items.append(
            Item(
                id=f"{one.id}@{one.version}",
                label=one.id,
                kind=one.version,
                note=f"{one.status} · 도구 {len(tools)}개",
                tip=one.content_hash,
                children=tools,
            )
        )
    return Root(
        id=ROOT_TOOLPACK,
        label=TOOLPACK_LABEL,
        items=tuple(items),
        empty=EMPTY_TOOLPACK,
        blocked=(("설치...", NO_TOOLPACK_INSTALL), ("제거...", NO_TOOLPACK_INSTALL)),
    )


def view_create(view: ResourceView, extension_id: str, resource_id: str, label: str) -> Create | None:
    """기여 뿌리의 「캔버스에 추가」 — **선언대로만** 만든다 (C13 `creates_task_*`).

    `creates_task_field`가 없으면 `data`를 비운 채 만든다 — 플랫폼은 그 확장의 `data` 모양을
    모르므로 **자원 id를 아무 칸에나 넣지 않는다**. 그때는 사람이 편집기에서 고른다.
    """
    if not view.creates_task_type:
        return None
    data: dict[str, Any] = {}
    if view.creates_task_field:
        data[view.creates_task_field] = resource_id
    body = {"type": view.creates_task_type, "extension": extension_id, "data": data}
    return Create(
        bpmn=BPMN_SERVICE_TASK,
        name=label,
        chk={"task": json.dumps(body, ensure_ascii=False)},
    )


def view_item(
    view: ResourceView, extension_id: str, found: ContributedResource, *, console_url: str = ""
) -> Item:
    """기여 자원 한 줄 — **`name`·`summary`만** 쓴다 (`data`는 그 확장의 것이다, C13 §5)."""
    label = found.name or found.id
    tip = found.id if not found.updated_at else f"{found.id} · 바뀐 때 {found.updated_at}"
    return Item(
        id=found.id,
        label=label,
        kind="",
        note=found.summary or "",
        tip=tip,
        create=view_create(view, extension_id, found.id, label),
        console_url=console_url,
    )


def _console_url_for(catalog: service_catalog.Catalog | None, extension_id: str) -> str:
    """그 확장의 서버 부분 관리 콘솔 주소 (C7). 모르면 빈 글이다."""
    if catalog is None:
        return ""
    found = next((one for one in catalog.apps if one.extension_id == extension_id), None)
    return found.console_url if found is not None else ""


def collect(
    views: Sequence[Any] = (),
    *,
    catalog: service_catalog.Catalog | None = None,
    reader: CenterReader | None = None,
) -> Tree:
    """뿌리는 선언에서, 목록은 C7에서 (STU-03).

    `views`는 `ExtensionHost.resource_views()`의 기여들이다 — **라벨 순**으로 그려 확장이
    실리는 순서에 흔들리지 않게 한다. **한 뿌리를 못 받아도 나머지는 그린다.**
    """
    problems: list[str] = list(catalog.problems if catalog is not None else ())
    roots: list[Root] = [shared_root()]
    for one in sorted(views, key=lambda c: c.value.label):
        view: ResourceView = one.value
        items: tuple[Item, ...] = ()
        empty = EMPTY_VIEW
        if reader is None:
            empty = NO_CENTER
        else:
            console = _console_url_for(catalog, one.extension_id)
            try:
                items = tuple(
                    view_item(view, one.extension_id, found, console_url=console)
                    for found in reader.contributed(view.resource_type)
                )
            except CenterUnreachable as e:
                problems.append(f"{view.label}을 받지 못했습니다 — {e}")
                empty = f"받지 못했습니다 — {e}"
        roots.append(Root(id=view.id, label=view.label, items=items, empty=empty))

    roots.append(service_root(catalog))

    toolpack = toolpack_root(())
    if reader is None:
        toolpack = replace(toolpack, empty=NO_CENTER)
    else:
        try:
            toolpack = toolpack_root(reader.toolpacks())
        except CenterUnreachable as e:
            problems.append(f"툴팩 목록을 받지 못했습니다 — {e}")
            toolpack = replace(toolpack, empty=f"받지 못했습니다 — {e}")
    roots.append(toolpack)

    if reader is None:
        problems.append(NO_CENTER)
    return Tree(roots=tuple(roots), problems=tuple(problems))


# ─────────────────────────── 창 ───────────────────────────


class DetailDialog(QDialog):
    """「작업 설명 보기」 — 읽기만 한다 (STU-03 문맥 메뉴)."""

    def __init__(self, title: str, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(560, 420)
        layout = QVBoxLayout(self)
        self.body = QPlainTextEdit(self)
        self.body.setReadOnly(True)
        self.body.setPlainText(text)
        layout.addWidget(self.body)
        close = QPushButton("닫기", self)
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        layout.addLayout(row)


class ResourceExplorer(QWidget):
    """STU-03. 그리기만 하고 **Center를 직접 부르지 않는다** — 받는 일은 메인 창이 한다.

    그래서 「새로 고침」은 `reloading`으로 올라가고, 창은 돌아온 `Tree`를 그린다.
    """

    #: 「새로 고침」 — 메인 창이 Center에서 다시 받아 `show_tree()`로 돌려준다.
    reloading = Signal()
    #: 「캔버스에 추가」 — `Create` 하나 (Qt 신호는 자료형을 모른다).
    adding = Signal(object)
    #: 로그 한 줄 (STU-09 「로그」).
    said = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tree = Tree()

        self.reload_button = QPushButton("새로 고침", self)
        self.reload_button.clicked.connect(self.reloading)
        top = QHBoxLayout()
        top.addWidget(self.reload_button)
        top.addStretch(1)

        self.view = QTreeView(self)
        self._model = QStandardItemModel(self)
        self._model.setHorizontalHeaderLabels(list(HEADERS))
        self.view.setModel(self._model)
        self.view.setAlternatingRowColors(True)
        self.view.setSelectionBehavior(QTreeView.SelectionBehavior.SelectRows)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._menu)
        self.view.doubleClicked.connect(lambda _: self._double_clicked())

        self.note = QLabel(EMPTY_TREE, self)
        self.note.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.view, 1)
        layout.addWidget(self.note)

    # ── 그리기 ──

    def show_tree(self, tree: Tree) -> None:
        """받아 온 것을 그린다. **고른 줄은 잊는다** — 목록이 바뀌었을 수 있다."""
        self.tree = tree
        self._model.removeRows(0, self._model.rowCount())
        for root in tree.roots:
            # 비어 있을 때만 까닭을 적는다 — 항목이 있으면 그것이 답이다.
            row = _cells(root.label, "", (root.off or root.empty) if not root.items else "")
            row[0].setData(ROW_ROOT, _KIND)
            row[0].setData(root.id, _PAYLOAD)
            if root.off:
                for cell in row:
                    cell.setEnabled(False)
                    cell.setToolTip(root.off)
            for item in root.items:
                row[0].appendRow(_item_rows(item, root.id))
            self._model.appendRow(row)
        self.view.expandToDepth(0)
        for column in range(len(HEADERS)):
            self.view.resizeColumnToContents(column)
        self.note.setText(" / ".join(tree.problems) if tree.problems else EMPTY_TREE)

    # ── 고른 줄 ──

    def selection(self) -> tuple[str, str, str] | None:
        """고른 줄의 `(종류, 뿌리 id, 항목 id)`. 고른 것이 없으면 `None`."""
        indexes = self.view.selectedIndexes()
        if not indexes:
            return None
        found = self._model.itemFromIndex(indexes[0].siblingAtColumn(0))
        if found is None:
            return None
        kind = str(found.data(_KIND) or "")
        payload = str(found.data(_PAYLOAD) or "")
        if kind == ROW_ROOT:
            return ROW_ROOT, payload, ""
        root_id, _, item_id = payload.partition("\n")
        return ROW_ITEM, root_id, item_id

    def selected_root(self) -> Root | None:
        found = self.selection()
        if found is None:
            return None
        return next((one for one in self.tree.roots if one.id == found[1]), None)

    def selected_item(self) -> Item | None:
        found = self.selection()
        if found is None or found[0] != ROW_ITEM:
            return None
        root = self.selected_root()
        return _find_item(root.items if root else (), found[2])

    # ── 하는 일 ──

    def _double_clicked(self) -> None:
        """더블클릭은 **만들 수 있을 때만** 추가한다 — 자식이 있는 줄은 펼치는 것이 뜻이다."""
        item = self.selected_item()
        if item is not None and item.create is not None:
            self.add_selected()

    def add_selected(self) -> None:
        """「캔버스에 추가」. 만들 수 없는 줄이면 **까닭을 말한다** (조용히 넘기지 않는다)."""
        item = self.selected_item()
        if item is None:
            return
        if item.create is None:
            self.said.emit(f"{item.label}: 이 항목으로는 태스크를 만들 수 없습니다.")
            return
        self.adding.emit(item.create)

    def show_detail(self) -> None:
        item = self.selected_item()
        if item is None or not item.detail:
            return
        DetailDialog(item.label, item.detail, self).exec()

    def open_console(self) -> None:
        """「관리 콘솔에서 보기」 — 기본 브라우저로 연다 (읽기만 하는 자리다)."""
        from PySide6.QtCore import QUrl  # noqa: PLC0415
        from PySide6.QtGui import QDesktopServices  # noqa: PLC0415

        item = self.selected_item()
        if item is None or not item.console_url:
            return
        QDesktopServices.openUrl(QUrl(item.console_url))
        self.said.emit(f"관리 콘솔을 열었습니다: {item.console_url}")

    def _menu(self, where: Any) -> None:
        found = self.selection()
        if found is None:
            return
        menu = QMenu(self)
        item = self.selected_item()
        if item is not None:
            add = menu.addAction("캔버스에 추가")
            add.setEnabled(item.create is not None)
            add.triggered.connect(self.add_selected)
            if item.detail:
                menu.addAction("작업 설명 보기").triggered.connect(self.show_detail)
            if item.console_url:
                menu.addAction("관리 콘솔에서 보기").triggered.connect(self.open_console)
        root = self.selected_root()
        # 할 수 없는 일도 메뉴에 둔다 — 끄고 까닭을 말풍선에 붙인다 (U3). 뿌리가 꺼진 까닭은
        # 줄 자체가 적고 있으니 메뉴에 다시 쓰지 않는다.
        for label, why in root.blocked if root is not None else ():
            blocked = menu.addAction(label)
            blocked.setEnabled(False)
            blocked.setToolTip(why)
        menu.addSeparator()
        menu.addAction("새로 고침").triggered.connect(self.reloading)
        menu.exec(self.view.viewport().mapToGlobal(where))


def _cells(label: str, kind: str, note: str) -> list[QStandardItem]:
    cells = [QStandardItem(label), QStandardItem(kind), QStandardItem(note)]
    for cell in cells:
        cell.setEditable(False)
    return cells


def _item_rows(item: Item, root_id: str) -> list[QStandardItem]:
    cells = _cells(item.label, item.kind, item.note)
    cells[0].setData(ROW_ITEM, _KIND)
    cells[0].setData(f"{root_id}\n{item.id}", _PAYLOAD)
    if item.tip:
        for cell in cells:
            cell.setToolTip(item.tip)
    for child in item.children:
        cells[0].appendRow(_item_rows(child, root_id))
    return cells


def _find_item(items: Iterable[Item], item_id: str) -> Item | None:
    for one in items:
        if one.id == item_id:
            return one
        found = _find_item(one.children, item_id)
        if found is not None:
            return found
    return None


__all__ = [
    "BPMN_SERVICE_TASK",
    "EMPTY_SERVICE",
    "EMPTY_TOOLPACK",
    "EMPTY_TREE",
    "EMPTY_VIEW",
    "HEADERS",
    "NO_CENTER",
    "NO_SHARED",
    "NO_TOOLPACK_INSTALL",
    "ROOT_SERVICE",
    "ROOT_SHARED",
    "ROOT_TOOLPACK",
    "ROW_ITEM",
    "ROW_ROOT",
    "Create",
    "DetailDialog",
    "Item",
    "ResourceExplorer",
    "Root",
    "Tree",
    "collect",
    "service_root",
    "shared_root",
    "toolpack_root",
    "view_create",
    "view_item",
]
