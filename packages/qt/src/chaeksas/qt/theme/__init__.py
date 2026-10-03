"""Qt 테마 — 웹과 **같은 토큰**으로 밝게/어둡게 (ADR-0017 §2·§3).

쓰는 쪽은 한 줄이면 된다. Studio·Bot UI가 시작할 때 부른다.

    app = QApplication(sys.argv)
    apply_theme(app)                       # 설정이 「시스템 따름」일 때
    apply_theme(app, choice=THEME_DARK)    # 「어둡게」를 골랐을 때

이 폴더에서 **생성물**은 `tokens.py`·`theme-light.qss`·`theme-dark.qss`다
(`design/tokens.json` → `scripts/gen_tokens.py`). 색·크기를 여기 적지 않는다.

세 가지를 함께 적용한다. QSS만으로는 모자라기 때문이다.

1. **글꼴** — Pretendard를 앱에 포함해 등록한다 (`fonts/`). 현장 PC에 글꼴이 없을 수 있다.
2. **QSS** — 위젯 모양 (생성물).
3. **팔레트** — QSS가 닿지 않는 곳 (선택 영역 색, 비활성 글자, 기본 창 배경). 팔레트를 함께
   맞추지 않으면 어둡게에서 선택한 글자가 보이지 않는 등 구멍이 생긴다.
"""

from __future__ import annotations

import logging
from importlib.resources import as_file, files
from pathlib import Path
from typing import TYPE_CHECKING

from chaeksas.qt.theme import tokens

if TYPE_CHECKING:  # QApplication을 타입으로만 쓴다 (import 비용을 줄인다)
    from PySide6.QtGui import QFont, QPalette
    from PySide6.QtWidgets import QApplication

LOG = logging.getLogger(__name__)

#: 설정에 저장하는 값 (스타일 가이드 §4-2 — STU-10 「외형」, Bot UI도 같다).
THEME_SYSTEM = "system"
THEME_LIGHT = "light"
THEME_DARK = "dark"
THEME_CHOICES = (THEME_SYSTEM, THEME_LIGHT, THEME_DARK)
#: 생성된 QSS 안의 그림 경로 자리 — `qss()`가 이 패키지 폴더의 실제 경로로 바꾼다.
THEME_DIR_PLACEHOLDER = "@THEME_DIR@"

#: 앱에 포함하는 글꼴 파일이 있는 곳 (`packages/qt/src/chaeksas/qt/fonts/`).
FONT_PACKAGE = "chaeksas.qt.fonts"
FONT_SUFFIXES = (".otf", ".ttf")


def resolve(choice: str, *, app: QApplication | None = None) -> str:
    """고른 값 → 실제로 쓸 테마 (`light` 또는 `dark`).

    `system`이면 OS 설정을 따른다 (Qt 6.5+ `styleHints().colorScheme()`). OS가 알려 주지
    않으면(`Unknown` — 리눅스 일부, offscreen) **밝게**로 둔다.
    """
    if choice == THEME_LIGHT or choice == THEME_DARK:
        return choice
    if choice != THEME_SYSTEM:
        LOG.warning("모르는 테마 값 %r — 시스템 따름으로 본다", choice)
    if app is None:
        return THEME_LIGHT
    from PySide6.QtCore import Qt

    return THEME_DARK if app.styleHints().colorScheme() == Qt.ColorScheme.Dark else THEME_LIGHT


def qss(theme: str) -> str:
    """그 테마의 QSS (생성물). QSS에는 변수가 없어 테마마다 파일이 하나씩이다."""
    name = f"theme-{THEME_DARK if theme == THEME_DARK else THEME_LIGHT}.qss"
    root = files(__package__ or "chaeksas.qt.theme")
    # QSS의 그림(`url(...)`)은 실행 위치 기준이라, 생성물의 `@THEME_DIR@`를 이 패키지 폴더의 실제 경로로 바꾼다.
    # 설치본(PyInstaller onedir)에서도 패키지 데이터는 실제 파일이다 (ADR-0024).
    return (root / name).read_text(encoding="utf-8").replace(THEME_DIR_PLACEHOLDER, Path(str(root)).as_posix())


def load_fonts() -> list[str]:
    """포함한 글꼴을 등록하고, 등록된 패밀리 이름을 돌려준다.

    **글꼴이 없어도 멈추지 않는다.** 빈 목록을 돌려주고, QSS의 대체 글꼴(맑은 고딕 →
    시스템)이 쓰인다. 글꼴 파일은 라이선스(OFL) 때문에 따로 넣는다 — `fonts/README.md`.
    """
    from PySide6.QtGui import QFontDatabase

    families: list[str] = []
    try:
        root = files(FONT_PACKAGE)
    except ModuleNotFoundError:
        LOG.info("포함된 글꼴이 없다 — 시스템 글꼴로 보인다 (fonts/README.md)")
        return families

    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if not entry.name.lower().endswith(FONT_SUFFIXES):
            continue
        # 묶인 앱(PyInstaller) 안에서도 실제 파일 경로가 필요하다 (Qt가 경로로 읽는다).
        with as_file(entry) as path:
            font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:
            LOG.warning("글꼴을 등록하지 못했다: %s", entry.name)
            continue
        families += QFontDatabase.applicationFontFamilies(font_id)

    unique = list(dict.fromkeys(families))
    if unique:
        LOG.debug("글꼴 등록: %s", unique)
    return unique


def palette(theme: str) -> QPalette:
    """토큰 색으로 만든 팔레트. QSS가 닿지 않는 곳을 메운다."""
    from PySide6.QtGui import QColor, QPalette

    c = tokens.colors(dark=theme == THEME_DARK)
    pal = QPalette()
    role = QPalette.ColorRole
    group = QPalette.ColorGroup

    def put(color_role: QPalette.ColorRole, token: str) -> None:
        pal.setColor(color_role, QColor(c[token]))

    put(role.Window, "bg.canvas")
    put(role.WindowText, "text.primary")
    put(role.Base, "bg.surface")
    put(role.AlternateBase, "bg.subtle")
    put(role.Text, "text.primary")
    put(role.PlaceholderText, "text.muted")
    put(role.Button, "bg.surface")
    put(role.ButtonText, "text.primary")
    put(role.Highlight, "primary")
    put(role.HighlightedText, "primary.fg")
    put(role.Link, "primary")
    put(role.LinkVisited, "primary.hover")
    put(role.ToolTipBase, "bg.inverse")
    put(role.ToolTipText, "text.inverse")

    # 비활성 글자는 흐리게 — 색을 따로 두지 않고 muted를 쓴다 (토큰을 늘리지 않는다).
    for disabled_role in (role.Text, role.WindowText, role.ButtonText):
        pal.setColor(group.Disabled, disabled_role, QColor(c["text.muted"]))
    return pal


#: Windows에서 Qt가 앱 글꼴과 **따로** 주는 클래스 글꼴 (시스템 메뉴·대화상자 글꼴). 앱 글꼴만 바꾸면
#: 이 위젯들은 힌팅이 그대로라 메뉴의 「서비스」가 「서비ㅅ」로 보였다 (이슈 #3).
CLASS_FONTS = ("QMenu", "QMenuBar", "QMessageBox", "QToolTip", "QTipLabel", "QStatusBar", "QMdiSubWindowTitleBar")


def unhinted(font: QFont) -> QFont:
    """힌팅을 끈 사본.

    Windows(DirectWrite)는 Pretendard(CFF 외곽선)를 작은 크기에서 힌팅하다 얇은 가로획을 지운다 —
    14px에서 「으·스」, 12px에서 「그」의 「ㅡ」가 사라졌다 (이슈 #3). 힌팅을 끄면 크기와 상관없이 그려진다.
    QSS는 글꼴 이름·크기만 정하고 힌팅은 정하지 못하므로 앱 글꼴에 둔다 (QSS가 이 위에 얹힌다).
    """
    from PySide6.QtGui import QFont

    copy = QFont(font)
    copy.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return copy


def apply_theme(app: QApplication, *, choice: str = THEME_SYSTEM) -> str:
    """글꼴·QSS·팔레트를 적용하고, 실제로 쓴 테마(`light`/`dark`)를 돌려준다.

    「시스템 따름」이면 OS가 테마를 바꿀 때 다시 적용한다 (Qt가 신호를 준다).
    """
    theme = resolve(choice, app=app)
    load_fonts()
    app.setPalette(palette(theme))
    app.setStyleSheet(qss(theme))
    # 스타일시트를 입히면 Qt가 클래스 글꼴을 시스템 기본값으로 되돌린다 — 힌팅 끄기는 그 **뒤에** 한다.
    app.setFont(unhinted(app.font()))
    for widget_class in CLASS_FONTS:
        # PySide6 타입 정보는 클래스 이름 인자를 모른다 (`font(str)` 없음, `setFont`는 bytes만) — 실행은 된다.
        app.setFont(unhinted(app.font(widget_class)), widget_class)  # type: ignore[call-overload, arg-type]

    if choice == THEME_SYSTEM:
        hints = app.styleHints()
        # 같은 app에 여러 번 붙지 않게 한 번만 잇는다.
        if not getattr(app, "_chk_theme_following", False):
            hints.colorSchemeChanged.connect(lambda _scheme: apply_theme(app, choice=THEME_SYSTEM))
            app._chk_theme_following = True  # type: ignore[attr-defined]
    return theme


def status_color(group: str, label: str, *, theme: str = THEME_LIGHT, part: str = "solid") -> str | None:
    """상태 표기 → 색 (스타일 가이드 §2-2). 웹의 `statusToken()`과 같은 표를 쓴다.

    `part`는 `fg`(글자)·`bg`(배지 바탕)·`solid`(점·막대) 중 하나다. 모르는 표기면 `None` —
    계약의 상태 값은 열린 문자열이라(계약 원칙 10) 모르는 값 하나로 화면이 깨지지 않는다.
    """
    token = tokens.STATUS_MAP.get(group, {}).get(label)
    if token is None:
        return None
    return tokens.colors(dark=theme == THEME_DARK)[f"status.{token}.{part}"]


__all__ = [
    "FONT_PACKAGE",
    "THEME_CHOICES",
    "THEME_DARK",
    "THEME_LIGHT",
    "THEME_SYSTEM",
    "apply_theme",
    "load_fonts",
    "palette",
    "qss",
    "resolve",
    "status_color",
    "tokens",
]
