"""시험이 띄우는 가짜 데스크톱 앱 — 진짜 창이라 UIA로 보인다 (데스크톱 백엔드·M4 인수 시험).

    python tests/fake_desktop_apps.py erp [제목 덧붙임]

**제품 코드가 아니다.** 예제가 가리키는 사내 앱(「ERP Client」)을 그 자리에서 흉내 낸다 — 웹 예제가
시험이 띄운 HTML을 쓰는 것과 같다. Qt는 `objectName` 경로를 UIA `AutomationId`로 내보낸다
(`QApplication.poEntry.itemCode`). 시험 프로세스의 `QT_QPA_PLATFORM=offscreen`을 물려받으면 창이
보이지 않으니 부르는 쪽이 지운다.
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

#: 창 제목 — 시험의 창 조건(C9 `window.title`)이 이것을 본다.
ERP_TITLE = "ERP Client - 발주 입력"


def erp(suffix: str = "") -> QWidget:
    """발주 입력 (BX-17 `erp.desktop.po_entry`). 저장할 때마다 발주번호가 하나씩 오른다."""
    window = QWidget()
    window.setObjectName("poEntry")
    window.setWindowTitle(ERP_TITLE + suffix)
    form = QFormLayout(window)

    item = QLineEdit()
    item.setObjectName("itemCode")
    quantity = QSpinBox()
    quantity.setObjectName("quantity")
    quantity.setMaximum(100000)
    warehouse = QComboBox()
    warehouse.setObjectName("warehouse")
    warehouse.addItems(["본사 창고", "제2 물류센터", "외부 보관"])
    save = QPushButton("저장")
    save.setObjectName("saveButton")
    number = QLineEdit()
    number.setObjectName("poNumber")
    number.setReadOnly(True)
    history = QTableWidget(0, 3)
    history.setObjectName("history")
    history.setHorizontalHeaderLabels(["품목", "수량", "발주번호"])

    counter = {"n": 0}

    def on_save() -> None:
        counter["n"] += 1
        made = f"PO-{counter['n']:04d}"
        number.setText(made)
        row = history.rowCount()
        history.insertRow(row)
        for column, text in enumerate((item.text(), str(quantity.value()), made)):
            history.setItem(row, column, QTableWidgetItem(text))

    save.clicked.connect(on_save)
    form.addRow("품목", item)
    form.addRow("수량", quantity)
    form.addRow("창고", warehouse)
    form.addRow(save)
    form.addRow("발주번호", number)
    form.addRow("이력", history)
    window.resize(520, 420)
    return window


APPS = {"erp": erp}


def main() -> None:
    app = QApplication(sys.argv[:1])
    which = sys.argv[1] if len(sys.argv) > 1 else "erp"
    suffix = sys.argv[2] if len(sys.argv) > 2 else ""
    window = APPS[which](suffix)
    window.show()
    window.raise_()
    window.activateWindow()
    app.exec()


if __name__ == "__main__":
    main()
