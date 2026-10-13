"""STU-01 창 배치 기억 (`studio/layout.py`) — 「크기·위치를 기억한다」·「레이아웃 초기화」.

**진짜 메인 창을 띄우지 않는다** — 담고 되돌리는 일은 `QMainWindow`·`QSplitter`의 것이라
맨 위젯으로 본다 (캔버스는 QtWebEngine이라 단위 시험에 들이지 않는다, `04-setup` §7).

거듭 보는 것 셋.

1. **설정 파일과 따로 둔다** — 사람이 고치는 설정에 Qt 바이트 뭉치를 섞지 않는다.
2. **깨진 파일은 없는 것으로 본다** — 배치 하나 때문에 Studio가 뜨지 않으면 안 된다.
3. **「초기화」는 파일을 지운다** — 다음에 뜰 때도 기본 배치여야 한다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from chaeksas.studio import layout  # noqa: E402


@pytest.fixture(scope="module")
def app() -> Any:
    from PySide6.QtWidgets import QApplication

    try:
        return QApplication.instance() or QApplication([])
    except Exception as e:  # noqa: BLE001 - 환경 문제면 건너뛴다
        pytest.skip(f"Qt를 띄울 수 없다: {type(e).__name__}: {e}")


def parts(app: Any) -> tuple[Any, Any, Any]:
    """창 하나 + 분할자 둘 (메인 창이 쥐는 것과 같은 모양)."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMainWindow, QSplitter, QTextEdit

    window = QMainWindow()
    window.resize(1400, 860)
    middle = QSplitter(Qt.Orientation.Horizontal, window)
    middle.setObjectName("middleSplit")
    for _ in range(2):
        middle.addWidget(QTextEdit(middle))
    split = QSplitter(Qt.Orientation.Vertical, window)
    split.setObjectName("bottomSplit")
    split.addWidget(middle)
    split.addWidget(QTextEdit(split))
    window.setCentralWidget(split)
    window.show()
    return window, middle, split


def test_the_layout_goes_to_its_own_file_next_to_the_settings(tmp_path: Path) -> None:
    assert layout.layout_path(tmp_path) == tmp_path / "layout.json"
    assert layout.layout_path(tmp_path).name != "settings.json"


def ratio(sizes: list[int]) -> float:
    return sizes[0] / max(sum(sizes), 1)


def test_what_was_captured_comes_back(app: Any, tmp_path: Path) -> None:
    """담고 → 쓰고 → 읽고 → 되돌린다. **창 크기는 그대로, 분할 비율은 그대로** 온다.

    분할자는 픽셀이 아니라 **비율**을 담는다 (Qt가 지금 폭에 맞춰 늘린다) — 그래서 크기를
    글자 그대로 견주지 않는다. 창 크기는 `restoreGeometry`가 그 자리에서 되돌린다.
    """
    window, middle, split = parts(app)
    window.resize(1234, 777)
    middle.setSizes([900, 300])
    split.setSizes([700, 160])
    path = layout.write(tmp_path / "layout.json", layout.capture(window, middle, split, collapsed=True))

    found = layout.read(path)
    assert found is not None and found.properties_collapsed is True

    again, again_middle, again_split = parts(app)
    assert layout.apply(found, again, again_middle, again_split) is True, "Qt가 받아들였다"
    assert ratio(again_middle.sizes()) == pytest.approx(ratio(middle.sizes()), abs=0.02)
    assert ratio(again_split.sizes()) == pytest.approx(ratio(split.sizes()), abs=0.02)
    # 창 크기는 **견주지 않는다** — 화면에 맞춰 깎인다 (offscreen 화면은 800×600이다).


def test_a_broken_or_missing_file_is_read_as_nothing(tmp_path: Path) -> None:
    """**배치 하나 때문에 Studio가 뜨지 않으면 안 된다** (작업 폴더 기록과 같은 결)."""
    assert layout.read(tmp_path / "없다.json") is None
    broken = tmp_path / "layout.json"
    broken.write_text("{ 깨진", encoding="utf-8")
    assert layout.read(broken) is None
    broken.write_text('["목록이 왔다"]', encoding="utf-8")
    assert layout.read(broken) is None


def test_a_layout_from_a_newer_schema_is_ignored(tmp_path: Path) -> None:
    """모르는 판은 **기본 배치로** 뜬다 — 모양이 바뀌었을 수 있다."""
    path = tmp_path / "layout.json"
    path.write_text(json.dumps({"schema": layout.SCHEMA + 1, "geometry": "x"}), encoding="utf-8")
    assert layout.read(path) is None


def test_empty_fields_are_left_alone(app: Any, tmp_path: Path) -> None:
    """비어 있는 칸은 건드리지 않는다 — Qt에 빈 바이트를 먹이면 배치가 무너진다."""
    window, middle, split = parts(app)
    middle.setSizes([800, 400])
    before = middle.sizes()
    layout.apply(layout.Layout(), window, middle, split)
    assert middle.sizes() == before


def test_resetting_deletes_the_file(tmp_path: Path) -> None:
    path = layout.write(tmp_path / "layout.json", layout.Layout(geometry="x"))
    layout.clear(path)
    assert not path.exists()
    layout.clear(path)  # 두 번 해도 터지지 않는다


def test_the_file_is_utf8_json_with_a_schema(app: Any, tmp_path: Path) -> None:
    window, middle, split = parts(app)
    path = layout.write(tmp_path / "layout.json", layout.capture(window, middle, split, collapsed=False))
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["schema"] == layout.SCHEMA
    assert raw["properties_collapsed"] is False
    assert raw["geometry"] and raw["window_state"], "Qt 바이트 뭉치는 base64 글자로 간다"
