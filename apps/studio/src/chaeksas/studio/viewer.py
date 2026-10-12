"""읽기 전용 다이어그램 보기 — STU-03 「열기 (읽기 전용)」
([ADR-0051](../../../../../docs/decisions/0051-shared-process-conveniences.md)).

지키는 것 셋.

- **정말 못 고친다.** 페이지가 bpmn-js **뷰어**(`VIEW_PAGE`)라 편집 기능이 아예 없다 — 팔레트만
  가린 편집기를 「읽기 전용」이라 부르지 않는다 (고친 것이 닫으면 사라지고 아무도 안 물어본다).
- **네트워크를 타지 않는다.** 보는 것은 받아 둔 `libs/`의 그 파일이고(ADR-0048) Center에서 다시
  받지 않는다 — 보는 것과 실행이 **같은 파일**이다.
- **띄워 놓고 바로 밀어 넣지 않는다.** 페이지가 `opened`로 답한 뒤에 그림을 넣는다 (캔버스 규약,
  ADR-0022). 아직 안 떴으면 들고 있다가 그때 넣는다.
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from chaeksas.studio.canvas import VIEW_PAGE, Canvas, CanvasError

log = logging.getLogger(__name__)

TITLE = "다이어그램 보기"
#: 처음 크기 — 캔버스가 들어가야 하니 STU-11보다 크다.
DEFAULT_SIZE = (900, 620)

#: 머리 한 줄 — **어디서 온 것인지와 못 고친다는 것**을 함께 말한다.
HEADER = "{what} — 읽기 전용입니다 (편집할 수 없습니다)."


class DiagramViewer(QDialog):
    """BPMN 하나를 읽기 전용으로 보인다. 단추는 「닫기」뿐이다."""

    def __init__(self, what: str, xml: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._xml = xml
        self._ready = False

        self.setWindowTitle(f"{TITLE} — {what}")
        self.resize(*DEFAULT_SIZE)

        self.header = QLabel(HEADER.format(what=what), self)
        self.header.setWordWrap(True)
        #: 못 읽었을 때 할 말 (빈 창을 말없이 두지 않는다).
        self.note = QLabel("", self)
        self.note.setWordWrap(True)

        self.canvas = Canvas(self)
        self.canvas.opened.connect(self._on_ready)

        self.close_button = QPushButton("닫기", self)
        self.close_button.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.header)
        layout.addWidget(self.canvas, 1)
        layout.addWidget(self.note)
        layout.addLayout(buttons)

        try:
            self.canvas.boot(page=VIEW_PAGE)
        except CanvasError as e:
            self.note.setText(str(e))

    def _on_ready(self) -> None:
        self._ready = True
        self.canvas.load_xml(self._xml, then=self._on_loaded)

    def _on_loaded(self, found: dict[str, Any]) -> None:
        if not found.get("ok"):
            self.note.setText(f"그림을 읽지 못했습니다: {found.get('error')}")
            return
        warnings = found.get("warnings")
        count = len(warnings) if isinstance(warnings, list) else 0
        # 경고는 **남의 정의의 것**이라 고칠 수 없다 — 수만 말한다.
        self.note.setText(f"경고 {count}개" if count else "")


__all__ = ["DEFAULT_SIZE", "HEADER", "TITLE", "DiagramViewer"]
