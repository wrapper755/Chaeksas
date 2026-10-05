"""시험이 띄우는 가짜 데스크톱 앱 — 진짜 창이라 UIA로 보인다 (데스크톱 백엔드·M4 인수 시험).

    python tests/fake_desktop_apps.py erp|taxbook|calc [제목 덧붙임]

**제품 코드가 아니다.** 예제가 가리키는 사내 앱(「ERP Client」)을 그 자리에서 흉내 낸다 — 웹 예제가
시험이 띄운 HTML을 쓰는 것과 같다. Qt는 `objectName` 경로를 UIA `AutomationId`로 내보낸다
(`QApplication.poEntry.itemCode`). 시험 프로세스의 `QT_QPA_PLATFORM=offscreen`을 물려받으면 창이
보이지 않으니 부르는 쪽이 지운다.
"""

from __future__ import annotations

import os
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


#: 회계 프로그램의 창 제목 (BX-04 `accounting.taxbook.sheet`).
TAXBOOK_TITLE = "회계 프로그램 - 세금계산서 발행대장"


def taxbook(suffix: str = "") -> QWidget:
    """세금계산서 발행대장 (BX-04). 「다음 줄」 칸에 줄 하나(JSON 사전)를 넣고 저장하면 시트에 붙는다.

    합계 칸은 **계산된 값**을 보인다 (예제의 교훈 — 셀 읽기가 수식을 돌려주면 안 된다).
    """
    import json  # noqa: PLC0415

    window = QWidget()
    window.setObjectName("taxbook")
    window.setWindowTitle(TAXBOOK_TITLE + suffix)
    form = QFormLayout(window)

    next_row = QLineEdit()
    next_row.setObjectName("nextRow")
    save = QPushButton("저장")
    save.setObjectName("saveMenu")
    sheet = QTableWidget(0, 0)
    sheet.setObjectName("sheet")
    total = QLineEdit("0")
    total.setObjectName("total")
    total.setReadOnly(True)
    state: dict[str, list[str]] = {"columns": []}

    def on_save() -> None:
        row = json.loads(next_row.text())
        if not state["columns"]:
            state["columns"] = [str(one) for one in row]
            sheet.setColumnCount(len(state["columns"]))
            sheet.setHorizontalHeaderLabels(state["columns"])
        at = sheet.rowCount()
        sheet.insertRow(at)
        for column, name in enumerate(state["columns"]):
            sheet.setItem(at, column, QTableWidgetItem(str(row.get(name, ""))))
        amount = state["columns"].index("금액") if "금액" in state["columns"] else -1
        if amount >= 0:
            found = (sheet.item(r, amount) for r in range(sheet.rowCount()))
            total.setText(str(sum(int(item.text()) for item in found if item is not None and item.text())))
        next_row.clear()

    save.clicked.connect(on_save)
    form.addRow("다음 줄", next_row)
    form.addRow(save)
    form.addRow("발행대장", sheet)
    form.addRow("합계", total)
    window.resize(560, 420)
    return window


#: 계산기의 창 제목 (FX-05 — 등록되지 않은 앱을 AI가 보고 조작한다).
CALC_TITLE = "계산기"


def calc(suffix: str = "") -> QWidget:
    """작은 계산기 (FX-05). 단추를 눌러 식을 만들고 `=`이면 표시 칸에 결과가 나온다.

    **화면 등록이 없다** — AI가 UIA 트리를 보고 단추를 고른다 (ADR-0037).
    """
    from PySide6.QtWidgets import QGridLayout  # noqa: PLC0415

    window = QWidget()
    window.setObjectName("calculator")
    window.setWindowTitle(CALC_TITLE + suffix)
    grid = QGridLayout(window)
    display = QLineEdit("0")
    display.setObjectName("display")
    display.setReadOnly(True)
    grid.addWidget(display, 0, 0, 1, 4)
    typed: list[str] = []

    def press(symbol: str) -> None:
        if symbol == "C":
            typed.clear()
            display.setText("0")
            return
        if symbol == "=":
            expression = "".join(typed)
            # 숫자와 사칙연산만 — 시험용 앱이라도 `eval`에 아무것이나 넣지 않는다.
            if expression and all(ch in "0123456789+-*/" for ch in expression):
                value = eval(expression, {"__builtins__": {}}, {})  # noqa: S307
                display.setText(str(int(value) if float(value).is_integer() else value))
            typed.clear()
            return
        typed.append(symbol)
        display.setText("".join(typed))

    keys = [("7", "key7"), ("8", "key8"), ("9", "key9"), ("/", "divide"),
            ("4", "key4"), ("5", "key5"), ("6", "key6"), ("*", "times"),
            ("1", "key1"), ("2", "key2"), ("3", "key3"), ("-", "minus"),
            ("0", "key0"), ("C", "clear"), ("=", "equals"), ("+", "plus")]
    labels = {"*": "×", "/": "÷"}
    for index, (symbol, name) in enumerate(keys):
        button = QPushButton(labels.get(symbol, symbol))
        button.setObjectName(name)
        button.clicked.connect(lambda _=False, s=symbol: press(s))
        grid.addWidget(button, 1 + index // 4, index % 4)
    window.resize(280, 320)
    return window


APPS = {"erp": erp, "taxbook": taxbook, "calc": calc}


def main() -> None:
    # **늘 보이는 창으로** 뜬다 — Worker가 띄우면(desktop-apps.json) 시험 프로세스의 offscreen을
    # 물려받는다. 보이지 않는 창은 UIA에 안 보인다.
    os.environ.pop("QT_QPA_PLATFORM", None)
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
