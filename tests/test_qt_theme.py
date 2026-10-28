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


def test_work_areas_are_cards_split_by_gaps() -> None:
    """STU-01 — 영역은 카드(바탕 + 테두리)이고 사이는 틈이다. 분할자에 선을 긋지 않는다(두 겹이 된다)."""
    for theme, colors in ((THEME_LIGHT, tokens.LIGHT), (THEME_DARK, tokens.DARK)):
        sheet = qss(theme)
        card = sheet.split("QFrame#Pane, QTabWidget#PaneTabs::pane {", 1)[1].split("}", 1)[0]
        assert colors["bg.surface"] in card
        assert f"1px solid {colors['border.default']}" in card
        for rule in ("QSplitter::handle:horizontal", "QSplitter::handle:vertical"):
            assert "border" not in sheet.split(rule, 1)[1].split("}", 1)[0], rule
        assert "QFrame#Rule" in sheet


def test_group_box_titles_have_room_and_labels_take_the_box_color() -> None:
    """테두리 입힌 QGroupBox는 제목 자리·::title이 없으면 제목이 첫 줄과 겹친다 (이슈 #3).

    제목은 **카드 안쪽 맨 위**다 (스타일 가이드 §3 Section) — 그래서 위 패딩이 제목 위 여백 +
    제목 줄 + 제목 아래 간격을 모두 담아야 한다. 강조 막대와 진한 글자로 묶음을 가른다.
    """
    import json  # noqa: PLC0415
    import math  # noqa: PLC0415
    import re  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    tokens = json.loads((Path(__file__).resolve().parents[1] / "design" / "tokens.json").read_text(encoding="utf-8"))
    line = math.ceil(tokens["font"]["size.body-lg"] * tokens["font"]["line.heading"])
    for theme in (THEME_LIGHT, THEME_DARK):
        sheet = qss(theme)
        box = sheet.split("QGroupBox {", 1)[1].split("}", 1)[0]
        title = sheet.split("QGroupBox::title {", 1)[1].split("}", 1)[0]
        assert "subcontrol-origin: padding" in title
        pad_top = int(re.search(r"padding: (\d+)px", box).group(1))  # type: ignore[union-attr]
        top = int(re.search(r"top: (\d+)px", title).group(1))  # type: ignore[union-attr]
        assert pad_top > top + line, "제목 아래에 간격이 남아야 첫 줄과 붙지 않는다"
        assert "border-left: 3px solid" in title
        assert tokens["color"][theme]["text.primary"] in title
        assert "QLabel, QCheckBox, QRadioButton { background-color: transparent; }" in sheet


def test_spinbox_arrows_point_at_real_files() -> None:
    """▲▼ 단추를 꾸미면 화살표를 직접 줘야 한다 — 생성한 SVG의 경로가 실제 파일이어야 한다 (이슈 #3, 150%)."""
    import re  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    for theme in (THEME_LIGHT, THEME_DARK):
        sheet = qss(theme)
        assert "@THEME_DIR@" not in sheet
        images = re.findall(r"url\(([^)]+)\)", sheet)
        names = {Path(i).name for i in images}
        # 화살표는 반드시 있고, **쓰는 그림 전부**가 실제 파일이어야 한다 (체크박스 ✓도 여기 걸린다).
        assert {f"arrow-up-{theme}.svg", f"arrow-down-{theme}.svg"} <= names
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


def test_widgets_hearing_the_palette_change_already_see_the_new_theme(app: Any) -> None:
    """팔레트 변경을 받은 위젯이 `current()`로 물으면 새 테마다 — 캔버스가 그렇게 묻는다 (ADR-0101)."""
    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtWidgets import QWidget

    from chaeksas.qt.theme import current

    heard: list[str] = []

    class Ear(QObject):
        def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
            if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange):
                heard.append(current(app))
            return False

    widget, ear = QWidget(), Ear()
    widget.installEventFilter(ear)
    widget.show()
    try:
        apply_theme(app, choice=THEME_DARK)
        assert heard and heard[-1] == THEME_DARK
        apply_theme(app, choice=THEME_LIGHT)
        assert heard[-1] == THEME_LIGHT
    finally:
        widget.close()
        apply_theme(app, choice=THEME_LIGHT)


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


def test_a_fixed_choice_stops_following_the_system(app: Any, monkeypatch: Any) -> None:
    """「시스템 따름」 뒤에 밝게·어둡게를 고르면 OS가 바꿔도 다시 입히지 않는다 (ADR-0073, STU-10 「외형」).

    신호는 한 번 붙으면 떼지 않으므로 **받는 쪽이** 지금 고른 값을 본다.
    """
    from chaeksas.qt import theme as theme_module  # noqa: PLC0415

    apply_theme(app, choice=THEME_SYSTEM)
    apply_theme(app, choice=THEME_DARK)
    seen: list[str] = []

    def record(_app: Any, *, choice: str) -> str:
        seen.append(choice)
        return choice

    monkeypatch.setattr(theme_module, "apply_theme", record)
    theme_module._follow_system(app)
    assert seen == [], "고정한 테마는 OS를 따라가지 않는다"
    app._chk_theme_choice = THEME_SYSTEM
    theme_module._follow_system(app)
    assert seen == [THEME_SYSTEM]


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


# ─────────────────────── 체크박스 표시기 (이슈 #3 꼬리) ───────────────────────


def test_checkbox_indicator_is_drawn_by_the_stylesheet() -> None:
    """QCheckBox에 스타일을 주면 Qt가 **기본 표시기를 그리지 않는다** — 직접 그려야 한다.

    고치기 전에는 체크된 칸이 상자 없이 ✓만 보였다 (이슈 #3).
    """
    for theme in (THEME_LIGHT, THEME_DARK):
        text = qss(theme)
        assert "QCheckBox::indicator" in text
        assert "QRadioButton::indicator" in text
        # 켜진 칸은 채우고 ✓를 올린다 (✓는 생성한 SVG).
        assert f"check-{theme}.svg" in text
        # 고른 라디오는 **테두리 두께를 바꾸지 않고** 점을 그림으로 얹는다 — 두껍게 하면 상자가 커져
        # 둥글기가 지름의 절반이 아니게 되고 모서리만 둥근 네모가 된다.
        assert f"dot-{theme}.svg" in text
        checked = text.split("QRadioButton::indicator:checked {", 1)[1].split("}", 1)[0]
        assert "border:" not in checked and "border-color" in checked
        for state in (":hover", ":checked", ":disabled"):
            assert f"QCheckBox::indicator{state}" in text, (theme, state)


def test_the_checkbox_indicator_really_has_a_box(app: Any) -> None:
    """**그려 보고** 확인한다 — QSS에 규칙이 있어도 Qt가 적용하는지는 별 문제다.

    테마를 입힌 체크박스를 실제로 그려, 켜진 표시기에 바탕색(primary)과 ✓ 색(primary.fg)이
    둘 다 있는지 본다. 고치기 전에는 바탕이 없어 ✓만 떠 있었다 (이슈 #3).
    """
    from PySide6.QtWidgets import QCheckBox

    apply_theme(app, choice=THEME_LIGHT)
    colors = tokens.colors(dark=False)
    box = QCheckBox("확인")
    box.setChecked(True)
    box.resize(160, 28)
    box.show()
    app.processEvents()

    image = box.grab().toImage()
    # 표시기는 왼쪽에 있다 (space.4 = 16px + 여백).
    seen = {image.pixelColor(x, y).name().upper() for x in range(20) for y in range(image.height())}
    box.hide()
    box.deleteLater()
    app.processEvents()

    assert colors["primary"].upper() in seen, "켜진 표시기의 바탕이 없다"
    assert colors["primary.fg"].upper() in seen, "✓가 없다"


def test_standard_buttons_speak_korean(app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Qt 표준 단추(OK·Cancel·Save)가 영어로 남지 않는다 — 테마를 입히면 번역도 단다."""
    from PySide6.QtWidgets import QDialogButtonBox, QMessageBox  # noqa: PLC0415

    from chaeksas.qt.messages import DISCARD_LABEL, ask_unsaved  # noqa: PLC0415

    apply_theme(app)
    apply_theme(app)  # 두 번 입혀도 번역은 하나다
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    assert sorted(b.text() for b in buttons.buttons()) == sorted(["확인", "취소"])

    seen: list[str] = []

    def answer(box: QMessageBox) -> int:  # 모달 루프 없이 — 단추 글을 보고 「저장 안 함」을 누른다
        seen.extend(b.text() for b in box.buttons())
        box.button(QMessageBox.StandardButton.Discard).click()
        return 0

    monkeypatch.setattr(QMessageBox, "exec", answer)
    assert ask_unsaved(None, "제목", "본문") == QMessageBox.StandardButton.Discard
    assert sorted(seen) == sorted(["저장", DISCARD_LABEL, "취소"])


ROLE_SOURCES = ("apps", "packages", "extensions")


def roles_in_code() -> set[str]:
    """코드가 `set_role(…, "…")`(또는 `setProperty("role", "…")`)로 쓰는 글자 뜻들."""
    import re  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    root = Path(__file__).resolve().parent.parent
    found: set[str] = set()
    for top in ROLE_SOURCES:
        for path in (root / top).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            found |= set(re.findall(r'setProperty\(\s*"role",\s*"([a-z0-9_]+)"', text))
            found |= set(re.findall(r'set_role\(\s*[\w.]+,\s*"([a-z0-9_]+)"', text))
    return found


def test_every_role_the_code_uses_has_a_rule() -> None:
    """`role`을 적어 놓고 QSS에 규칙이 없으면 조용히 기본 글자다 — 「빨간 글자」가 검게 보였다."""
    used = roles_in_code()
    assert "error" in used, "찾는 규칙이 틀렸다 — error는 쓰는 곳이 여럿이다"
    for theme in (THEME_LIGHT, THEME_DARK):
        sheet = qss(theme)
        missing = sorted(r for r in used if f'QLabel[role="{r}"]' not in sheet)
        assert not missing, f"{theme}: 규칙이 없는 role {missing} (스타일 가이드 §4-2 표와 gen_tokens.py)"


def test_an_error_label_is_drawn_in_the_error_color(app: Any) -> None:
    from PySide6.QtGui import QColor, QPalette  # noqa: PLC0415
    from PySide6.QtWidgets import QLabel  # noqa: PLC0415

    apply_theme(app, choice=THEME_LIGHT)
    plain, error = QLabel("보통"), QLabel("막는 까닭")
    error.setProperty("role", "error")
    for label in (plain, error):
        label.ensurePolished()
    wanted = QColor(tokens.colors(dark=False)["status.failed.fg"])
    assert error.palette().color(QPalette.ColorRole.WindowText) == wanted
    assert plain.palette().color(QPalette.ColorRole.WindowText) != wanted


def test_a_role_given_after_the_label_is_shown_still_colors_it(app: Any) -> None:
    """스타일시트는 처음 보일 때 한 번 입힌다 — `set_role`이 다시 칠해야 늦게 준 뜻도 보인다.

    실행 창의 「학습 안 된 AI 태스크」 줄이 `setVisible` 뒤에 `role`을 받아 검게 남았다.
    """
    from PySide6.QtGui import QColor, QPalette  # noqa: PLC0415
    from PySide6.QtWidgets import QLabel, QWidget  # noqa: PLC0415

    from chaeksas.qt.theme import set_role  # noqa: PLC0415

    apply_theme(app, choice=THEME_LIGHT)
    holder = QWidget()
    late = QLabel("늦게 받은 뜻", holder)
    holder.show()
    set_role(late, "error")
    wanted = QColor(tokens.colors(dark=False)["status.failed.fg"])
    assert late.palette().color(QPalette.ColorRole.WindowText) == wanted
    set_role(late, "")  # 뜻을 거두면 기본 글자로 돌아간다
    assert late.palette().color(QPalette.ColorRole.WindowText) != wanted
    holder.close()


def test_roles_are_given_through_set_role() -> None:
    """`setProperty("role", …)`만 부르면 보인 뒤 준 뜻이 칠해지지 않는다 — `set_role`을 쓴다.

    `chaeksas-qt`를 쓰지 않는 확장은 스스로 다시 칠하므로 여기서 보지 않는다 (스타일 가이드 §4-2).
    """
    from pathlib import Path  # noqa: PLC0415

    root = Path(__file__).resolve().parent.parent
    theme = root / "packages" / "qt" / "src" / "chaeksas" / "qt" / "theme" / "__init__.py"
    raw = [
        f"{path.relative_to(root).as_posix()}"
        for top in ("apps", "packages")
        for path in (root / top).rglob("*.py")
        if path != theme and 'setProperty("role"' in path.read_text(encoding="utf-8")
    ]
    assert not raw, f"set_role 대신 setProperty로 role을 준다: {raw}"


def test_an_icon_is_drawn_in_the_color_given(app: Any) -> None:
    """스타일 가이드 §6 — Lucide SVG의 `currentColor`를 토큰 색으로 칠한다 (20과 고해상도용 40)."""
    from PySide6.QtGui import QColor  # noqa: PLC0415

    from chaeksas.qt.theme import ICON_SIZE, icon  # noqa: PLC0415

    found = icon("square", "#ff0000")
    assert sorted(s.width() for s in found.availableSizes()) == [ICON_SIZE, ICON_SIZE * 2]
    image = found.pixmap(ICON_SIZE * 2).toImage()
    colors = {image.pixelColor(x, y).name() for x in range(image.width()) for y in range(image.height())
              if image.pixelColor(x, y).alpha() == 255}
    assert colors == {QColor("#ff0000").name()}


def test_every_shipped_icon_loads_and_an_unknown_one_is_an_error(app: Any) -> None:
    from importlib.resources import files  # noqa: PLC0415

    from chaeksas.qt.theme import icon  # noqa: PLC0415

    names = [p.name[len("icon-"):-len(".svg")] for p in files("chaeksas.qt.theme").iterdir()
             if p.name.startswith("icon-") and p.name.endswith(".svg")]
    assert "play" in names
    for name in names:
        assert not icon(name, "#000000").isNull(), name
    with pytest.raises(FileNotFoundError):
        icon("없는-아이콘", "#000000")


def test_an_open_menu_has_a_border() -> None:
    """펼친 메뉴는 테두리가 있다 — 없으면 흰 바탕 위에서 메뉴가 어디까지인지 안 보였다."""
    for theme in (THEME_LIGHT, THEME_DARK):
        color = tokens.colors(dark=theme == THEME_DARK)["border.strong"]
        assert f"border: 1px solid {color};" in qss(theme).split("QMenu {", 1)[1].split("}", 1)[0]
