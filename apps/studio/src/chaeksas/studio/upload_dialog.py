"""STU-12b 「Center로 올리기」 확인 창 — **업무 자리를 고른다** (C16, ADR-0127).

고른 자리는 매니페스트(C1 `place`)에 실려 승인과 함께 고정된다 — Center는 보여 주기만 한다. 목록은 이
Studio 키로 읽은 **제 회사의 조직**이고, 읽지 못하면 「회사 공통」만 켠다.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from chaeksas.studio.upload import Organization, OrgChoice
from chaeksas.studio.workspace import BpmProcess

NOTE = "업무 자리는 패키지에 들어가 승인과 함께 고정됩니다. 바꾸려면 버전을 올려 다시 올리세요."
NO_ORG = "Center에서 조직을 읽지 못해 「회사 공통」만 고를 수 있습니다."
NOBODY = "(없음)"


class UploadDialog(QDialog):
    """「회사」(글로만)와 「업무 자리」(회사 공통 / 부서 / 직원)."""

    def __init__(self, parent: QWidget | None, process: BpmProcess, org: Organization | None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Center로 올리기 — {process.display} {process.version}")
        self.org = org

        self.company = QRadioButton("회사 공통", self)
        self.department = QRadioButton("부서", self)
        self.staff = QRadioButton("직원", self)
        self.group = QButtonGroup(self)
        for one in (self.company, self.department, self.staff):
            self.group.addButton(one)
            one.toggled.connect(self._refresh)
        self.departments = self._combo(org.departments if org else ())
        self.people = self._combo(org.staff if org else ())

        form = QFormLayout()
        form.addRow("회사", QLabel(org.company_name if org else "—", self))
        form.addRow("업무 자리", self.company)
        form.addRow(self.department, self.departments)
        form.addRow(self.staff, self.people)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, parent=self
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("올리기")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        self.note = QLabel(NOTE if org else NO_ORG, self)
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        layout.addWidget(self.buttons)
        self._preselect(process.place)

    def _combo(self, items: tuple[OrgChoice, ...]) -> QComboBox:
        box = QComboBox(self)
        for one in items:
            box.addItem(one.label, one.id)
        if not items:
            box.addItem(NOBODY, None)
        return box

    def _preselect(self, place: dict[str, str] | None) -> None:
        """지난번 고른 것을 미리 고른다 — 지금 목록에 없으면 회사 공통으로 돌아간다."""
        scope = (place or {}).get("scope")
        for button, combo, key in ((self.department, self.departments, "department"),
                                   (self.staff, self.people, "staff")):
            if scope == key and combo.findData((place or {}).get(key)) >= 0:
                combo.setCurrentIndex(combo.findData((place or {}).get(key)))
                button.setChecked(True)
                return
        self.company.setChecked(True)

    def _refresh(self) -> None:
        has_departments = self.departments.currentData() is not None
        has_staff = self.people.currentData() is not None
        self.department.setEnabled(self.org is not None and has_departments)
        self.staff.setEnabled(self.org is not None and has_staff)
        self.departments.setEnabled(self.department.isChecked())
        self.people.setEnabled(self.staff.isChecked())

    def place(self) -> dict[str, str] | None:
        """고른 자리 (C16 `Place`의 JSON). 회사 공통이면 `None` — 매니페스트에 넣지 않는다."""
        if self.department.isChecked() and self.departments.currentData():
            return {"scope": "department", "department": str(self.departments.currentData())}
        if self.staff.isChecked() and self.people.currentData():
            return {"scope": "staff", "staff": str(self.people.currentData())}
        return None

    @classmethod
    def ask(
        cls, parent: QWidget | None, process: BpmProcess, org: Organization | None
    ) -> tuple[bool, dict[str, str] | None]:
        """`(올리나, 자리)` — 「취소」면 `(False, None)`."""
        dialog = cls(parent, process, org)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False, None
        return True, dialog.place()


__all__ = ["NOTE", "NO_ORG", "UploadDialog"]
