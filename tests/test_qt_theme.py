"""Qt 테마 — 웹과 같은 토큰으로 밝게/어둡게 (ADR-0017 §2·§3).

화면 없이 돈다 (`QT_QPA_PLATFORM=offscreen`). 생성물(`tokens.py`·`theme-*.qss`)이 원본과 맞는지는
`scripts/gen_tokens.py --check`가 보고, 여기서는 **그것을 적용하는 코드**를 본다.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Any

import pytest

# PySide6를 불러오기 **전에** 정해야 한다. 화면·디스플레이 없이 돌린다.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from chaeksas.qt.theme import (  # noqa: E402
    THEME_CHOICES,
    THEME_DARK,
    THEME_LIGHT,
    THEME_SYSTEM,
    apply_theme,
    load_fonts,
    palette,
    qss,
    resolve,
    status_color,
    tokens,
    unhinted,
)


@pytest.fixture(scope="session")
def app() -> Any:
    """QApplication 하나 (한 프로세스에 하나만 만들 수 있다).

    Qt 플랫폼 플러그인이 뜨지 않는 환경(그래픽 라이브러리가 없는 최소 컨테이너)에서는 건너뛴다.
    CI는 필요한 라이브러리를 깔아 실제로 돈다 (`.github/workflows/ci.yml`).
    """
    from PySide6.QtWidgets import QApplication

    existing = QApplication.instance()
    if existing is not None:
        return existing
    try:
        return QApplication([])
    except Exception as e:  # pragma: no cover - 환경 문제
        pytest.skip(f"Qt 플랫폼 플러그인을 띄울 수 없다: {e}")


# ─────────────────────────── 테마 고르기 ───────────────────────────


def test_explicit_choice_wins() -> None:
    assert resolve(THEME_LIGHT) == THEME_LIGHT
    assert resolve(THEME_DARK) == THEME_DARK


def test_system_without_app_falls_back_to_light() -> None:
    """OS가 알려 주지 않으면 밝게. 어둡게를 기본으로 두면 밝은 OS에서 눈이 아프다."""
    assert resolve(THEME_SYSTEM) == THEME_LIGHT


def test_unknown_choice_is_treated_as_system() -> None:
    """설정 파일에 모르는 값이 들어와도 멈추지 않는다 (계약 원칙 10과 같은 태도)."""
    assert resolve("무지개") == THEME_LIGHT


def test_system_follows_the_os(app: Any) -> None:
    from PySide6.QtCore import Qt

    scheme = app.styleHints().colorScheme()
    expected = THEME_DARK if scheme == Qt.ColorScheme.Dark else THEME_LIGHT
    assert resolve(THEME_SYSTEM, app=app) == expected


def test_choices_are_the_three_the_screens_offer() -> None:
    """STU-10 「외형」의 세 가지 (스타일 가이드 §4-2)."""
    assert THEME_CHOICES == (THEME_SYSTEM, THEME_LIGHT, THEME_DARK)


# ─────────────────────────── 생성물 읽기 ───────────────────────────


def test_qss_differs_by_theme_and_uses_tokens() -> None:
    light, dark = qss(THEME_LIGHT), qss(THEME_DARK)
    assert light != dark
    # 각 테마의 바탕색이 그 테마 QSS에 들어 있다.
    assert tokens.LIGHT["bg.canvas"] in light
    assert tokens.DARK["bg.canvas"] in dark
    assert tokens.DARK["bg.canvas"] not in light


def test_group_box_titles_have_room_and_labels_take_the_box_color() -> None:
    """테두리 입힌 QGroupBox는 제목 자리·::title이 없으면 제목이 첫 줄과 겹친다 (이슈 #3)."""
    for theme in (THEME_LIGHT, THEME_DARK):
        sheet = qss(theme)
        assert "QGroupBox::title" in sheet and "subcontrol-origin: margin" in sheet
        assert "QLabel, QCheckBox, QRadioButton { background-color: transparent; }" in sheet


def test_spinbox_arrows_point_at_real_files() -> None:
    """▲▼ 단추를 꾸미면 화살표를 직접 줘야 한다 — 생성한 SVG의 경로가 실제 파일이어야 한다 (이슈 #3, 150%)."""
    import re  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    for theme in (THEME_LIGHT, THEME_DARK):
        sheet = qss(theme)
        assert "@THEME_DIR@" not in sheet
        images = re.findall(r"url\(([^)]+)\)", sheet)
        assert {Path(i).name for i in images} == {f"arrow-up-{theme}.svg", f"arrow-down-{theme}.svg"}
        assert all(Path(i).is_file() for i in images), images


def test_qss_falls_back_to_light_for_unknown_theme() -> None:
    assert qss("무지개") == qss(THEME_LIGHT)


def test_tokens_have_the_same_color_names_in_both_themes() -> None:
    """밝게/어둡게가 같은 이름을 가져야 테마를 바꿔도 구멍이 생기지 않는다."""
    assert set(tokens.LIGHT) == set(tokens.DARK)


# ─────────────────────────── 적용 ───────────────────────────


def test_palette_uses_token_colors() -> None:
    for theme, table in ((THEME_LIGHT, tokens.LIGHT), (THEME_DARK, tokens.DARK)):
        pal = palette(theme)
        assert pal.window().color().name().lower() == table["bg.canvas"].lower()
        assert pal.base().color().name().lower() == table["bg.surface"].lower()
        assert pal.highlight().color().name().lower() == table["primary"].lower()


def test_palette_covers_disabled_text() -> None:
    """QSS가 닿지 않는 자리. 비우면 어둡게에서 꺼진 글자가 거의 안 보인다."""
    from PySide6.QtGui import QPalette

    pal = palette(THEME_DARK)
    disabled = pal.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
    assert disabled.name().lower() == tokens.DARK["text.muted"].lower()


def test_apply_theme_sets_stylesheet_and_palette(app: Any) -> None:
    assert apply_theme(app, choice=THEME_DARK) == THEME_DARK
    assert app.styleSheet() == qss(THEME_DARK)
    assert app.palette().window().color().name().lower() == tokens.DARK["bg.canvas"].lower()

    assert apply_theme(app, choice=THEME_LIGHT) == THEME_LIGHT
    assert app.styleSheet() == qss(THEME_LIGHT)


def test_the_app_font_is_unhinted(app: Any) -> None:
    """Windows에서 Pretendard의 「으·스·그」 가로획이 힌팅으로 사라졌다 (이슈 #3) — 앱 글꼴의 힌팅을 끈다."""
    from PySide6.QtGui import QFont  # noqa: PLC0415

    # Windows 플랫폼은 메뉴·대화상자에 시스템 글꼴을 클래스 글꼴로 따로 준다. offscreen에는 없으니 심어 둔다.
    for widget_class in ("QMenu", "QMessageBox"):
        app.setFont(QFont("Malgun Gothic"), widget_class)
    apply_theme(app, choice=THEME_LIGHT)
    assert app.font().hintingPreference() == QFont.HintingPreference.PreferNoHinting
    # 메뉴·대화상자는 클래스 글꼴을 따로 쓰고, 스타일시트가 그것을 되돌린다 — 위젯에서 확인한다.
    from PySide6.QtWidgets import QMenu, QMessageBox  # noqa: PLC0415

    for widget in (QMenu(), QMessageBox()):
        widget.ensurePolished()
        assert widget.font().hintingPreference() == QFont.HintingPreference.PreferNoHinting, type(widget).__name__
        widget.deleteLater()
    original = QFont("Pretendard")
    assert unhinted(original).hintingPreference() == QFont.HintingPreference.PreferNoHinting
    assert original.hintingPreference() == QFont.HintingPreference.PreferDefaultHinting  # 사본만 바뀐다


def test_following_the_system_connects_once(app: Any) -> None:
    """「시스템 따름」을 여러 번 적용해도 신호를 한 번만 잇는다 (테마가 겹쳐 적용되지 않게)."""
    apply_theme(app, choice=THEME_SYSTEM)
    apply_theme(app, choice=THEME_SYSTEM)
    apply_theme(app, choice=THEME_SYSTEM)
    assert getattr(app, "_chk_theme_following", False) is True


def test_load_fonts_registers_the_bundled_families(app: Any) -> None:
    """포함한 글꼴이 실제로 등록되는가 (`fonts/README.md`).

    현장 PC에 Pretendard가 없어서 저장소에 넣었다 — 등록이 안 되면 한글이 시스템 글꼴로
    떨어지고, 화면 폭 계산이 설계서와 달라진다.
    """
    from PySide6.QtGui import QFontDatabase

    families = load_fonts()
    assert "Pretendard" in families, families
    assert "JetBrains Mono" in families, families
    # QSS의 글꼴 스택이 가리키는 이름으로 잡혀야 한다.
    assert "Pretendard" in QFontDatabase.families()
    # 스타일 가이드가 쓰는 네 굵기 (400·500·600·700).
    assert {"Regular", "Medium", "SemiBold", "Bold"} <= set(QFontDatabase.styles("Pretendard"))


def test_fonts_ship_with_the_license() -> None:
    """OFL은 재배포할 때 라이선스를 함께 두라고 한다."""
    from importlib.resources import files

    names = {entry.name for entry in files("chaeksas.qt.fonts").iterdir()}
    assert {"OFL-Pretendard.txt", "OFL-JetBrainsMono.txt"} <= names, sorted(names)


# ─────────────────────────── 상태 색 ───────────────────────────


def test_status_color_matches_the_status_map() -> None:
    assert status_color("Bot", "실행 중") == tokens.LIGHT["status.active.solid"]
    assert status_color("Bot", "실행 중", part="bg") == tokens.LIGHT["status.active.bg"]
    assert status_color("Bot", "실행 중", theme=THEME_DARK) == tokens.DARK["status.active.solid"]


def test_status_color_of_an_unknown_label_is_none() -> None:
    """상태 값은 열린 문자열이다 (계약 원칙 10) — 모르는 값 하나로 화면이 깨지지 않는다."""
    assert status_color("Bot", "처음 보는 상태") is None
    assert status_color("없는 묶음", "실행 중") is None


def test_every_status_label_has_a_color() -> None:
    """`status_map`의 모든 표기가 실제 색으로 풀리는가 (토큰 이름이 바뀌면 여기서 걸린다)."""
    for group, mapping in tokens.STATUS_MAP.items():
        for label in mapping:
            for part in ("fg", "bg", "solid"):
                assert status_color(group, label, part=part), f"{group}/{label}/{part}"


_NATIVE_MENU_CHECK = """
import sys
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox
from chaeksas.qt.theme import apply_theme
app = QApplication(sys.argv[:1])
apply_theme(app, choice="light")
for widget in (QMenu(), QMessageBox()):
    widget.ensurePolished()
    print(type(widget).__name__, widget.font().hintingPreference().name)
"""


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 플랫폼 플러그인의 클래스 글꼴 동작")
def test_menus_are_unhinted_on_the_native_windows_platform() -> None:
    """Windows 플랫폼은 스타일시트를 입힐 때 메뉴·대화상자 글꼴을 시스템 값으로 되돌린다 (이슈 #3).

    offscreen에는 그 동작이 없어 위 시험으로는 안 잡힌다 — 네이티브 플랫폼으로 따로 띄워 본다.
    """
    env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}
    done = subprocess.run(
        [sys.executable, "-c", _NATIVE_MENU_CHECK], capture_output=True, text=True, encoding="utf-8",
        errors="replace", env={**env, "PYTHONUTF8": "1"}, timeout=60, check=False,
    )
    if done.returncode != 0 and "platform plugin" in done.stderr:
        pytest.skip(f"네이티브 Qt 플랫폼을 띄울 수 없다: {done.stderr.strip()[:200]}")
    assert done.returncode == 0, done.stderr
    assert done.stdout.split() == ["QMenu", "PreferNoHinting", "QMessageBox", "PreferNoHinting"], done.stdout
