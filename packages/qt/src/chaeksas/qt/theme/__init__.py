"""Qt 테마 — 웹과 **같은 토큰**으로 밝게/어둡게 (ADR-0017 §2·§3).

쓰는 쪽은 한 줄이면 된다. Studio·Bot UI가 시작할 때 부른다.

    app = QApplication(sys.argv)
    apply_theme(app)                       # 설정이 「시스템 따름」일 때
    apply_theme(app, choice=THEME_DARK)    # 「어둡게」를 골랐을 때

이 폴더에서 **생성물**은 `tokens.py`·`theme-light.qss`·`theme-dark.qss`다
(`design/tokens.json` → `scripts/gen_tokens.py`). 색·크기를 여기 적지 않는다.
`icon-*.svg`는 **Lucide를 그대로 옮긴 것**이다 (스타일 가이드 §6, ISC — `icons-LICENSE.txt`).
웹의 `lucide-react`와 같은 판에서 꺼냈고 `currentColor`를 `icon()`이 칠한다.

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
    from PySide6.QtGui import QFont, QIcon, QPalette
    from PySide6.QtWidgets import QApplication, QWidget

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


def current(app: QApplication) -> str:
    """이 앱에 지금 입혀진 테마 (`light`/`dark`) — `apply_theme`이 적어 둔 고른 값을 다시 푼다.

    창 밖에 그리는 것(캔버스의 웹 페이지)이 창과 같은 색을 쓰려고 묻는다.
    """
    return resolve(str(getattr(app, "_chk_theme_choice", THEME_SYSTEM)), app=app)


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
    load_translations(app)
    load_fonts()
    # 지금 고른 값을 적어 둔다 — 「시스템 따름」에서 밝게로 바꾼 뒤에는 OS를 따라가지 않는다 (ADR-0073).
    # 팔레트보다 **먼저** 적는다 — 팔레트 변경을 받은 위젯이 `current()`로 새 테마를 묻는다 (ADR-0101).
    app._chk_theme_choice = choice  # type: ignore[attr-defined]
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
            hints.colorSchemeChanged.connect(lambda _scheme: _follow_system(app))
            app._chk_theme_following = True  # type: ignore[attr-defined]
    return theme


def load_translations(app: QApplication) -> None:
    """Qt 자체 글(표준 단추 「OK」·「Cancel」·「Save」 등)을 한국어로 — 앱 하나에 한 번만 단다.

    OS 언어를 따르지 않는다 — 우리 화면은 한국어뿐이라 단추만 영어로 남으면 섞인다.
    번역 파일(`qtbase_ko.qm`)은 PySide6에 들어 있다. 못 읽으면 영어로 두고 로그만 남긴다.
    """
    if getattr(app, "_chk_translator", None) is not None:
        return
    from PySide6.QtCore import QLibraryInfo, QTranslator  # noqa: PLC0415

    translator = QTranslator(app)
    where = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if not translator.load("qtbase_ko", where):
        LOG.warning("Qt 한국어 번역을 읽지 못했습니다: %s", where)
        return
    app.installTranslator(translator)
    app._chk_translator = translator  # type: ignore[attr-defined]


def _follow_system(app: QApplication) -> None:
    """OS가 테마를 바꿨다 — **지금도** 「시스템 따름」일 때만 다시 입힌다."""
    if getattr(app, "_chk_theme_choice", THEME_SYSTEM) == THEME_SYSTEM:
        apply_theme(app, choice=THEME_SYSTEM)


#: 단추·탐색 아이콘 크기 (스타일 가이드 §6 — 20). 고해상도 화면용으로 두 배도 함께 그린다.
ICON_SIZE = 20


def icon(name: str, color: str) -> QIcon:
    """Lucide 아이콘 하나 (`icon-<name>.svg`) — `currentColor`를 `color`(토큰에서 온 색)로 칠한다.

    없는 이름은 `FileNotFoundError`다 — 빈 아이콘으로 조용히 넘어가지 않는다.
    """
    from PySide6.QtCore import QByteArray, Qt  # noqa: PLC0415
    from PySide6.QtGui import QIcon, QPainter, QPixmap  # noqa: PLC0415
    from PySide6.QtSvg import QSvgRenderer  # noqa: PLC0415

    svg = (files(__package__ or "chaeksas.qt.theme") / f"icon-{name}.svg").read_text(encoding="utf-8")
    renderer = QSvgRenderer(QByteArray(svg.replace("currentColor", color).encode("utf-8")))
    found = QIcon()
    for size in (ICON_SIZE, ICON_SIZE * 2):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        found.addPixmap(pixmap)
    return found


def set_role(widget: QWidget, role: str) -> None:
    """글자의 뜻(`role` — 스타일 가이드 §4-2)을 주고 **그 자리에서 다시 칠한다**.

    Qt는 스타일시트를 위젯이 처음 보일 때(또는 `setVisible`이 부를 때) 한 번 입히고, 그 뒤에
    속성을 바꿔도 다시 보지 않는다 — 그래서 `setVisible` 뒤에 `setProperty("role", …)`를 부르면
    「빨간 글자」가 검게 남았다. `setProperty`를 직접 부르지 않는다.
    """
    widget.setProperty("role", role)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)


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
    "ICON_SIZE",
    "THEME_CHOICES",
    "THEME_DARK",
    "THEME_LIGHT",
    "THEME_SYSTEM",
    "apply_theme",
    "current",
    "icon",
    "load_fonts",
    "load_translations",
    "palette",
    "qss",
    "resolve",
    "set_role",
    "status_color",
    "tokens",
]
