"""STU-05 새 BPM 프로세스, 예제 가져오기 고르기.

작은 대화상자는 여기 모은다 (STU-04 속성 패널·STU-08 실행 대화상자는 각자 파일로 갈 만큼 크다).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from chaeksas.studio.workspace import DEFAULT_GROUP, BpmProcess, Definition, Workspace, WorkspaceError

#: 업무 예제가 사는 곳 (저장소 안). 설치본에는 함께 들어간다.
EXAMPLES_DIR = Path(__file__).resolve().parents[4] / "docs" / "08-business-examples" / "bpmn"

HINT = "id는 소문자·숫자·`.`·`_`·`-`만 쓰고 소문자나 숫자로 시작합니다 (C1과 같은 규칙)."


class NewProcessDialog(QDialog):
    """STU-05. id·이름·버전·그룹을 받는다. 정의 파일은 캔버스가 저장할 때 생긴다."""

    def __init__(self, parent: QWidget | None, workspace: Workspace) -> None:
        super().__init__(parent)
        self.workspace = workspace
        self.made: BpmProcess | None = None
        self.setWindowTitle("새 BPM 프로세스")

        self.id_box = QLineEdit(self)
        self.id_box.setPlaceholderText("finance.invoice-reconcile")
        self.name_box = QLineEdit(self)
        self.name_box.setPlaceholderText("청구서 대사")
        self.version_box = QLineEdit("0.1.0", self)
        self.group_box = QLineEdit(DEFAULT_GROUP, self)

        form = QFormLayout()
        form.addRow("id", self.id_box)
        form.addRow("이름", self.name_box)
        form.addRow("버전", self.version_box)
        form.addRow("그룹", self.group_box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, parent=self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(QLabel(HINT, self))
        layout.addWidget(buttons)

    def accept(self) -> None:
        group = self.group_box.text().strip() or DEFAULT_GROUP
        if not (self.workspace.root / group).is_dir():
            try:
                self.workspace.create_group(group)
            except WorkspaceError as e:
                QMessageBox.warning(self, "새 BPM 프로세스", str(e))
                return
        try:
            self.made = self.workspace.create(
                self.id_box.text().strip(),
                name=self.name_box.text().strip(),
                version=self.version_box.text().strip() or "0.1.0",
                group=group,
            )
        except WorkspaceError as e:
            QMessageBox.warning(self, "새 BPM 프로세스", str(e))
            return
        super().accept()

    @classmethod
    def ask(cls, parent: QWidget | None, workspace: Workspace) -> BpmProcess | None:
        dialog = cls(parent, workspace)
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


def pick_example(parent: QWidget | None, source: Path | None = None) -> tuple[Path, str] | None:
    """「예제 BPM 프로세스 가져오기...」 — 고른 `(예제 폴더, 예제 id)`."""
    folder = source or EXAMPLES_DIR
    names = example_ids(folder)
    if not names:
        QMessageBox.information(parent, "예제 가져오기", f"예제를 찾지 못했습니다: {folder}")
        return None
    picked, ok = QInputDialog.getItem(parent, "예제 BPM 프로세스 가져오기", "예제", names, 0, False)
    return (folder, picked) if ok and picked else None


__all__ = [
    "EXAMPLES_DIR",
    "HINT",
    "NewProcessDialog",
    "ShareDefinitionsDialog",
    "example_ids",
    "pick_example",
]
