"""공용 물음 창 — 앱마다 같은 말로 묻는다.

Qt 번역(`qtbase_ko`)은 「Discard」를 「무시」로 옮긴다 — 저장 안 한 변경을 물을 때는 뜻이
틀리므로 그 단추만 우리 말로 바꾼다 (화면 문서 U11 「저장」/「저장 안 함」/「취소」).
"""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget

DISCARD_LABEL = "저장 안 함"


def ask_unsaved(parent: QWidget | None, title: str, text: str) -> QMessageBox.StandardButton:
    """「저장」/「저장 안 함」/「취소」를 묻고 누른 단추를 돌려준다 (기본은 「저장」)."""
    box = QMessageBox(QMessageBox.Icon.Question, title, text, parent=parent)
    box.setStandardButtons(
        QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel
    )
    box.setDefaultButton(QMessageBox.StandardButton.Save)
    box.button(QMessageBox.StandardButton.Discard).setText(DISCARD_LABEL)
    box.exec()
    return box.standardButton(box.clickedButton())


__all__ = ["DISCARD_LABEL", "ask_unsaved"]
