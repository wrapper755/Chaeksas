"""변수 이름 칸의 고를 거리 (STU-04·STU-14) — 「변수」 탭의 이름이 목록으로 뜬다.

**고르게 할 뿐 막지 않는다** — 새 변수를 만드는 칸(결과 저장·답한 사람)이 있어서다. 이름 목록은
모델 하나(`QStringListModel`)를 메인 창이 채우고 편집기들이 **같은 모델**을 본다 — 그림이 바뀌면
열린 편집기의 목록도 따라 바뀐다.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractItemModel, QModelIndex, QPersistentModelIndex, QStringListModel, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCompleter,
    QLineEdit,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

#: 칸 끝 단추의 툴팁.
PICK_TIP = "변수 고르기 — 「변수」 탭의 입력·출력·그림이 만드는 변수"


def attach(line: QLineEdit, names: QStringListModel | None) -> QAction | None:
    """칸에 고를 거리를 단다 — 적기 시작하면 맞는 이름이, 끝의 「▾」를 누르면 전부가 뜬다.

    돌려주는 것은 그 「▾」다 — 칸의 뜻이 바뀌는 자리(담당자: 이름 목록 ↔ 변수 이름)가 숨긴다.
    """
    if names is None:
        return None
    completer = QCompleter(names, line)
    completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    completer.setFilterMode(Qt.MatchFlag.MatchContains)
    line.setCompleter(completer)
    icon = line.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown)
    action = line.addAction(icon, QLineEdit.ActionPosition.TrailingPosition)
    action.setToolTip(PICK_TIP)

    def everything() -> None:
        completer.setCompletionPrefix("")
        completer.complete()

    action.triggered.connect(everything)
    return action


class NameDelegate(QStyledItemDelegate):
    """표의 변수 이름 칸 — 고칠 때 뜨는 칸에 고를 거리를 단다."""

    def __init__(self, names: QStringListModel | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.names = names

    def createEditor(  # noqa: N802 — Qt 이름 그대로
        self,
        parent: QWidget,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> QWidget:
        line = QLineEdit(parent)
        attach(line, self.names)
        return line

    def setEditorData(self, editor: QWidget, index: QModelIndex | QPersistentModelIndex) -> None:  # noqa: N802
        assert isinstance(editor, QLineEdit)
        editor.setText(str(index.data(Qt.ItemDataRole.EditRole) or ""))

    def setModelData(  # noqa: N802
        self, editor: QWidget, model: QAbstractItemModel, index: QModelIndex | QPersistentModelIndex
    ) -> None:
        assert isinstance(editor, QLineEdit)
        model.setData(index, editor.text(), Qt.ItemDataRole.EditRole)


__all__ = ["PICK_TIP", "NameDelegate", "attach"]
