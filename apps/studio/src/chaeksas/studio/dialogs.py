"""STU-05 새 BPM 프로세스, 예제 가져오기 고르기.

작은 대화상자는 여기 모은다 (STU-04 속성 패널·STU-08 실행 대화상자는 각자 파일로 갈 만큼 크다).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from chaeksas.contracts.bpmn_ext import BpmnReadError, read_process
from chaeksas.studio.workspace import (
    DEFAULT_GROUP,
    ID_PATTERN,
    BpmProcess,
    Definition,
    Workspace,
    WorkspaceError,
)

#: 저장소 뿌리에서 본 업무 예제 자리.
EXAMPLES_PARTS = ("docs", "08-business-examples", "bpmn")


def _examples_dir() -> Path:
    """업무 예제가 사는 곳 — **위로 올라가며 찾는다** (체크아웃에서만 있다, 설치본에는 들어가지 않는다).

    단계 수를 세어 적으면 폴더를 한 번 옮길 때 조용히 어긋난다 — 시험이 모두 폴더를 직접 넘겨
    기본값을 밟지 않아, 현장 리허설에서 「예제를 찾지 못했습니다」로야 드러났다. 못 찾으면 체크아웃
    기준 자리를 돌려주고 창이 그 경로로 「못 찾았다」고 말한다.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        found = parent.joinpath(*EXAMPLES_PARTS)
        if found.is_dir():
            return found
    return here.parents[5].joinpath(*EXAMPLES_PARTS)


#: 업무 예제가 사는 곳 (체크아웃 안).
EXAMPLES_DIR = _examples_dir()

#: 「id」 칸과 그 이름표의 툴팁 (STU-05 — 창 아래에 따로 줄을 두지 않는다).
HINT = "id는 소문자·숫자·`.`·`_`·`-`만 쓰고 소문자나 숫자로 시작합니다 (C1과 같은 규칙)."

#: 「지금 열린 정의 복사」를 끌 때 옆에 적는 까닭 (U3).
NO_OPEN_DEFINITION = "열린 정의가 없습니다"
#: 「예제에서 가져오기」를 끌 때 옆에 적는 까닭 — 예제는 체크아웃에만 있다 (설치본에는 없다).
NO_EXAMPLES = "예제를 찾지 못했습니다"

#: 「파일에서 BPM 프로세스 가져오기」 안내 — 따라가지 않는 것을 미리 말한다 (STU-05).
FILE_HINT = "그 파일 하나만 가져옵니다. 쓰는 결정(DMN)·호출 대상은 실행 전 검사가 알려 줍니다."


def pick_bpmn_file(parent: QWidget | None) -> Path | None:
    """STU-01 「파일에서 BPM 프로세스 가져오기...」의 첫 걸음 — 가져올 `.bpmn` 하나."""
    path, _ = QFileDialog.getOpenFileName(parent, "가져올 BPMN 파일", "", "BPMN (*.bpmn)")
    return Path(path) if path else None


class NewProcessDialog(QDialog):
    """STU-05. id·이름·버전·그룹·설명·담당자와 「첫 정의」를 받는다.

    「첫 정의」가 「빈 정의로 시작」이면 정의 파일은 캔버스가 저장할 때 생기고, 「지금 열린 정의
    복사」면 **그 파일을 작업 폴더가 복사한다** (`Workspace.create`의 `first`) — 그때 `made`의
    진입 정의가 이미 디스크에 있다.

    **「파일에서 BPM 프로세스 가져오기...」도 이 창이다** (`imported`) — 파일은 메뉴가 먼저
    고르고, 창은 「첫 정의」 대신 그 파일을 보이며 이름·id를 그림에서 채워 둔다.

    **「예제에서 가져오기」는 「첫 정의」의 셋째 줄이다** — 고른 예제로 id·이름을 채우되 사람이
    고쳐 적은 칸은 덮지 않는다. 「확인」은 `Workspace.import_example`로 DMN·호출 대상·케이스를
    함께 가져온다. 파일 메뉴 「예제 BPM 프로세스 가져오기...」는 이 줄을 골라 둔 채로 연다
    (`example=True`).

    **「다른 이름으로 저장...」(STU-01)도 이 창이다** — 받는 칸이 같고 다른 것은 「만든다」와
    「복사한다」뿐이다 (`source`). 그래서 그룹 만들기·오류 보이기가 한 자리에 있다. 그때는
    설명·담당자·「첫 정의」를 두지 않는다 (한 벌을 통째로 옮긴다).
    """

    def __init__(
        self,
        parent: QWidget | None,
        workspace: Workspace,
        *,
        source: BpmProcess | None = None,
        opened: Path | None = None,
        imported: Path | None = None,
        example: bool = False,
        examples: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.workspace = workspace
        self.examples = examples or EXAMPLES_DIR
        #: 예제를 고를 때 마지막으로 채운 `(id, 이름)` — 이것과 같은 칸만 바꾼다.
        self._filled = ("", "")
        self.source = source
        self.opened = opened if opened is not None and opened.is_file() else None
        self.imported = imported
        self.made: BpmProcess | None = None
        title = "새 BPM 프로세스"
        if source is not None:
            title = "다른 이름으로 저장"
        elif imported is not None:
            title = "파일에서 BPM 프로세스 가져오기"
        self.setWindowTitle(title)

        self.id_box = QLineEdit(self)
        self.id_box.setPlaceholderText("finance.invoice-reconcile")
        self.id_box.setToolTip(HINT)
        self.name_box = QLineEdit(self)
        self.name_box.setPlaceholderText("청구서 대사")
        self.version_box = QLineEdit("0.1.0", self)
        self.group_box = QLineEdit(DEFAULT_GROUP, self)
        if source is not None:
            # **베껴 온 값으로 채운다** — 복사하는 사람이 버전·그룹을 다시 적지 않는다.
            # id는 비워 둔다 (겹치면 안 되는 유일한 칸이다).
            self.name_box.setText(source.display)
            self.version_box.setText(source.version)
            self.group_box.setText(source.group)
        if imported is not None:
            self._fill_from(imported)

        form = QFormLayout()
        id_label = QLabel("id", self)
        id_label.setToolTip(HINT)
        form.addRow(id_label, self.id_box)
        form.addRow("이름", self.name_box)
        form.addRow("버전", self.version_box)
        form.addRow("그룹", self.group_box)
        if source is None:
            self.description_box = QPlainTextEdit(self)
            self.description_box.setFixedHeight(self.fontMetrics().lineSpacing() * 4)
            self.owner_box = QLineEdit(self)
            form.addRow("설명", self.description_box)
            form.addRow("담당자", self.owner_box)
            if imported is None:
                form.addRow("첫 정의", self._first_choice())
                if example and self.example_pick.isEnabled():
                    self.example_pick.setChecked(True)
            else:
                shown = QLabel(str(imported), self)
                shown.setWordWrap(True)
                form.addRow("가져올 파일", shown)
                hint = QLabel(FILE_HINT, self)
                hint.setWordWrap(True)
                form.addRow("", hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, parent=self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _first_choice(self) -> QWidget:
        """「빈 정의로 시작」 / 「지금 열린 정의 복사」 / 「예제에서 가져오기」 (파일은 따로 메뉴다)."""
        box = QWidget(self)
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        self.blank_pick = QRadioButton("빈 정의로 시작", box)
        self.blank_pick.setChecked(True)
        opened = f"지금 열린 정의 복사 ({self.opened.name})" if self.opened else (
            f"지금 열린 정의 복사 — {NO_OPEN_DEFINITION}"
        )
        self.opened_pick = QRadioButton(opened, box)
        self.opened_pick.setEnabled(self.opened is not None)
        self.example_list = QComboBox(box)
        for example_id in example_ids(self.examples):
            self.example_list.addItem(_example_label(self.examples, example_id), example_id)
        found = self.example_list.count() > 0
        self.example_pick = QRadioButton(
            "예제에서 가져오기" if found else f"예제에서 가져오기 — {NO_EXAMPLES}", box
        )
        self.example_pick.setEnabled(found)
        self.example_list.setEnabled(False)
        self.example_list.setVisible(found)
        self.picks = QButtonGroup(box)
        for one in (self.blank_pick, self.opened_pick):
            self.picks.addButton(one)
            column.addWidget(one)
        self.picks.addButton(self.example_pick)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.example_pick)
        row.addWidget(self.example_list, 1)
        column.addLayout(row)
        self.example_pick.toggled.connect(self._example_toggled)
        self.example_list.currentIndexChanged.connect(lambda _i: self._fill_from_example())
        return box

    def _example_toggled(self, on: bool) -> None:
        self.example_list.setEnabled(on)
        if on:
            self._fill_from_example()

    def picked_example(self) -> str | None:
        """「예제에서 가져오기」로 고른 예제 id — 다른 줄이면 `None`."""
        if not hasattr(self, "example_pick") or not self.example_pick.isChecked():
            return None
        found = self.example_list.currentData()
        return str(found) if found else None

    def _fill_from_example(self) -> None:
        """고른 예제로 id·이름을 채운다 — **사람이 고쳐 적은 칸은 덮지 않는다**."""
        example_id = self.picked_example()
        if example_id is None:
            return
        wanted_id = example_id.replace("_", "-")
        wanted_name = _example_name(self.examples, example_id)
        last_id, last_name = self._filled
        if self.id_box.text().strip() in ("", last_id):
            self.id_box.setText(wanted_id)
        if self.name_box.text().strip() in ("", last_name):
            self.name_box.setText(wanted_name)
        self._filled = (wanted_id, wanted_name)

    def _fill_from(self, path: Path) -> None:
        """그림의 이름과 (C1 규칙에 맞으면) process id로 채워 둔다 — 못 읽으면 비워 둔다.

        읽지 못하는 파일인지는 「확인」이 작업 폴더를 거쳐 말한다 (한 자리에서 거부한다).
        """
        try:
            drawing = read_process(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, BpmnReadError):
            return
        if drawing.name:
            self.name_box.setText(drawing.name)
        if ID_PATTERN.match(drawing.id) and self.workspace.find(drawing.id) is None:
            self.id_box.setText(drawing.id)

    def first(self) -> Path | None:
        """고른 「첫 정의」 파일 — 빈 정의면 `None`."""
        if self.source is not None:
            return None
        if self.imported is not None:
            return self.imported
        return self.opened if self.opened_pick.isChecked() else None

    def accept(self) -> None:
        group = self.group_box.text().strip() or DEFAULT_GROUP
        if not (self.workspace.root / group).is_dir():
            try:
                self.workspace.create_group(group)
            except WorkspaceError as e:
                QMessageBox.warning(self, self.windowTitle(), str(e))
                return
        process_id = self.id_box.text().strip()
        name = self.name_box.text().strip()
        version = self.version_box.text().strip() or "0.1.0"
        try:
            example_id = self.picked_example()
            if self.source is not None:
                self.made = self.workspace.copy(
                    self.source, process_id, name=name, version=version, group=group
                )
            elif example_id is not None:
                self.made = self.workspace.import_example(
                    self.examples,
                    example_id,
                    new_id=process_id,
                    name=name,
                    version=version,
                    group=group,
                    description=self.description_box.toPlainText().strip(),
                    owner=self.owner_box.text().strip(),
                )
            else:
                self.made = self.workspace.create(
                    process_id,
                    name=name,
                    version=version,
                    group=group,
                    description=self.description_box.toPlainText().strip(),
                    owner=self.owner_box.text().strip(),
                    first=self.first(),
                )
        except (WorkspaceError, OSError) as e:
            # **창을 닫지 않는다** — 적은 것을 버리지 않고 고칠 기회를 준다 (STU-05).
            QMessageBox.warning(self, self.windowTitle(), str(e))
            return
        super().accept()

    @classmethod
    def ask(
        cls,
        parent: QWidget | None,
        workspace: Workspace,
        *,
        source: BpmProcess | None = None,
        opened: Path | None = None,
        imported: Path | None = None,
        example: bool = False,
    ) -> BpmProcess | None:
        dialog = cls(parent, workspace, source=source, opened=opened, imported=imported, example=example)
        return dialog.made if dialog.exec() == QDialog.DialogCode.Accepted else None


class ShareDefinitionsDialog(QDialog):
    """STU-12 「공유 BPM 프로세스로 내보내기...」 — 담을 정의를 고른다.

    **「올리기」는 아직 없다** (Center 올리기 자체가 없다, `docs/09-gaps.md` §4-5) — 창은 파일로
    내보내는 쪽만 가진다. 읽지 못한 정의는 **고를 수 없게** 두고 사유를 옆에 적는다 (U3).
    """

    #: 하나도 고르지 않으면 「내보내기」가 꺼진다 (STU-12 「하나 이상 필수」).
    HINT = "고른 정의가 공유 BPM 프로세스 패키지(`process_lib`)에 담깁니다. 결정(DMN)은 모두 함께 담깁니다."

    def __init__(self, parent: QWidget | None, process: BpmProcess) -> None:
        super().__init__(parent)
        self.process = process
        self.setWindowTitle("공유 BPM 프로세스로 내보내기")

        self.boxes: list[tuple[QCheckBox, Definition]] = []
        picks = QVBoxLayout()
        for definition in process.definitions:
            box = QCheckBox(definition.path.name, self)
            if definition.process is None:
                box.setEnabled(False)
                box.setText(f"{definition.path.name} — 읽지 못했습니다 ({definition.problem or '사유 없음'})")
            else:
                box.toggled.connect(self._refresh)
            picks.addWidget(box)
            self.boxes.append((box, definition))

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, parent=self
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("내보내기")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"BPM 프로세스: {process.display} {process.version}", self))
        layout.addWidget(QLabel("공유할 정의", self))
        layout.addLayout(picks)
        layout.addWidget(QLabel(self.HINT, self))
        layout.addWidget(self.buttons)
        self._refresh()

    def _refresh(self) -> None:
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(self.picked()))

    def picked(self) -> list[Definition]:
        return [d for box, d in self.boxes if box.isChecked() and d.process is not None]

    @classmethod
    def ask(cls, parent: QWidget | None, process: BpmProcess) -> list[Definition] | None:
        dialog = cls(parent, process)
        return dialog.picked() if dialog.exec() == QDialog.DialogCode.Accepted else None


def example_ids(source: Path | None = None) -> list[str]:
    """가져올 수 있는 예제 목록 (`bpmn/*.bpmn`의 이름)."""
    folder = source or EXAMPLES_DIR
    if not folder.is_dir():
        return []
    return sorted(path.stem for path in folder.glob("*.bpmn"))


def _example_name(folder: Path, example_id: str) -> str:
    """예제 그림의 process 이름 — 못 읽으면 빈 글 (목록이 그 하나 때문에 비지 않게)."""
    try:
        return read_process((folder / f"{example_id}.bpmn").read_text(encoding="utf-8")).name or ""
    except (OSError, UnicodeDecodeError, BpmnReadError):
        return ""


def _example_label(folder: Path, example_id: str) -> str:
    name = _example_name(folder, example_id)
    return f"{example_id} — {name}" if name else example_id


__all__ = [
    "EXAMPLES_DIR",
    "HINT",
    "NO_EXAMPLES",
    "NewProcessDialog",
    "ShareDefinitionsDialog",
    "example_ids",
]
