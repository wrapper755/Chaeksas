"""Qt 테마 — 웹과 같은 토큰으로 밝게/어둡게 (ADR-0017 §2·§3).

화면 없이 돈다 (`QT_QPA_PLATFORM=offscreen`). 생성물(`tokens.py`·`theme-*.qss`)이 원본과 맞는지는
`scripts/gen_tokens.py --check`가 보고, 여기서는 **그것을 적용하는 코드**를 본다.
"""

from __future__ import annotations

import os
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
