"""확장이 기여하는 Qt 화면 (Bot UI 「도구」 유틸리티 흉내)."""

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class DemoUtility(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("S5 시험 유틸리티")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("확장이 기여한 화면입니다 (한글 확인)"))
