"""디자인 토큰 생성기 — `design/tokens.json` → 웹 CSS·Qt 테마·미리보기 + 명암비 검사.

실행: `uv run python scripts/gen_tokens.py`
`--check`: 파일을 쓰지 않고 검사만 하며, 생성물이 원본과 다르면 1로 끝난다 (CI용).

생성물 경로는 [ADR-0017](../docs/decisions/0017-web-nextjs-design-system.md) §토큰이 정한다.
**명암비 검사는 항상 돌고, 실패하면 아무것도 쓰지 않고 멈춘다** (`docs/07-style-guide.md` §8-3).

표준 라이브러리만 쓴다 (업무 예제 생성기와 같은 관례).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Windows 콘솔·파이프의 기본 코드페이지(cp949·cp1252)에서는 한글을 찍다 터진다.
# 이 도구들은 한글로 말하므로 stdout을 UTF-8로 고정한다 (CI의 Windows에서 실제로 터졌다).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "design" / "tokens.json"

#: ADR-0017이 정한 생성물.
WEB_SRC = ROOT / "web" / "packages" / "ui" / "src"
WEB_CSS = WEB_SRC / "tokens.css"
WEB_THEME = WEB_SRC / "theme.css"
WEB_STATUS_MAP = WEB_SRC / "status-map.ts"
QT_DIR = ROOT / "packages" / "qt" / "src" / "chaeksas" / "qt" / "theme"
PREVIEW = ROOT / "design" / "preview.html"

BANNER = "생성 파일: design/tokens.json에서 만든다. 직접 고치지 말고 원본을 고친 뒤 scripts/gen_tokens.py"

#: 글자 명암비 기준 (WCAG 2.2 AA, 스타일 가이드 D6).
AA_TEXT = 4.5
AA_UI = 3.0

#: Tailwind는 간격을 **배수 하나**(`--spacing`)로 쓴다. 그 한 걸음에 해당하는 토큰.
SPACING_STEP = "1"

STATUSES = ("neutral", "active", "done", "failed", "waiting", "warning", "replayed")
BACKGROUNDS = ("bg.canvas", "bg.surface", "bg.subtle")
TEXTS = ("text.primary", "text.secondary", "text.muted")


# ───────────────────────── 명암비 ─────────────────────────


def _channel(value: float) -> float:
    return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4


def luminance(color: str) -> float:
    r, g, b = (int(color[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def contrast_rows(colors: dict[str, str]) -> list[tuple[str, str, float, float, bool]]:
    """`(앞, 뒤, 비율, 기준, 통과)` — 스타일 가이드 §2가 **명시한 주장만** 강제한다."""
    rows = []
    for text in TEXTS:
        for bg in BACKGROUNDS:
            rows.append((text, bg, contrast(colors[text], colors[bg]), AA_TEXT, True))
    for status in STATUSES:
        fg = f"status.{status}.fg"
        rows.append((fg, f"status.{status}.bg", contrast(colors[fg], colors[f"status.{status}.bg"]), AA_TEXT, True))
        rows.append((fg, "bg.surface", contrast(colors[fg], colors["bg.surface"]), AA_TEXT, True))
    rows.append(("primary.fg", "primary", contrast(colors["primary.fg"], colors["primary"]), AA_TEXT, True))
    rows.append(
        (
            "danger.fg",
            "status.failed.solid",
            contrast(colors["danger.fg"], colors["status.failed.solid"]),
            AA_TEXT,
            True,
        )
    )
    # UI 요소는 3:1. 테두리는 WCAG 1.4.11의 장식 예외라 **경고만** 한다 (통과=False).
    rows.append(("primary", "bg.surface", contrast(colors["primary"], colors["bg.surface"]), AA_UI, True))
    rows.append(("focus", "bg.surface", contrast(colors["focus"], colors["bg.surface"]), AA_UI, True))
    rows.append(
        ("border.strong", "bg.surface", contrast(colors["border.strong"], colors["bg.surface"]), AA_UI, False)
    )
    return rows


def check_spacing_scale(tokens: dict[str, Any]) -> list[str]:
    """간격 토큰이 **한 걸음의 배수**인가 (Tailwind 테마가 배수 하나로 매핑된다).

    어긋나면 `p-6` 같은 유틸리티가 토큰과 다른 값이 되는데, 화면을 봐도 눈치채기 어렵다.
    그래서 생성 단계에서 막는다.
    """
    space = tokens["space"]
    step = space.get(SPACING_STEP)
    if not step:
        return [f"space.{SPACING_STEP}이 없거나 0이다 — Tailwind 간격의 한 걸음이 필요하다"]
    out = []
    for key, value in space.items():
        try:
            steps = float(key)
        except ValueError:
            continue  # 숫자가 아닌 이름은 유틸리티로 쓰지 않는다
        if value != steps * step:
            out.append(f"space.{key}={value}가 space.{SPACING_STEP}({step})의 {steps}배가 아니다")
    return out


def check_contrast(tokens: dict[str, Any]) -> tuple[list[str], list[str]]:
    """`(막는 것, 경고)`. 막는 것이 있으면 생성기는 아무것도 쓰지 않는다."""
    errors: list[str] = []
    warnings: list[str] = []
    for theme in ("light", "dark"):
        for fg, bg, ratio, floor, blocking in contrast_rows(tokens["color"][theme]):
            if ratio >= floor:
                continue
            line = f"{theme}: {fg} on {bg} = {ratio:.2f}:1 (기준 {floor}:1)"
            (errors if blocking else warnings).append(line)
    return errors, warnings


# ───────────────────────── 이름 바꾸기 ─────────────────────────


def css_var(name: str) -> str:
    """`bg.surface` → `--bg-surface` (스타일 가이드 §1)."""
    return "--" + name.replace(".", "-")


def py_const(name: str) -> str:
    """`bg.surface` → `BG_SURFACE` (스타일 가이드 §1)."""
    return name.replace(".", "_").replace("-", "_").upper()


# ───────────────────────── 웹 CSS ─────────────────────────


def web_css(tokens: dict[str, Any]) -> str:
    lines = [f"/* {BANNER} */", ""]

    def color_block(theme: str, indent: str = "  ") -> list[str]:
        return [f"{indent}{css_var(k)}: {v};" for k, v in tokens["color"][theme].items()]

    lines.append(":root {")
    lines += color_block("light")
    lines.append("")
    lines.append("  /* 글꼴 */")
    for key, value in tokens["font"].items():
        kind = key.split(".")[0]
        suffix = "px" if kind == "size" else ""
        lines.append(f"  {css_var('font.' + key)}: {value}{suffix};")
    lines.append("")
    lines.append("  /* 간격·둥글기·크기 */")
    for group in ("space", "radius", "size"):
        for key, value in tokens[group].items():
            unit = "" if (group == "radius" and key == "full") else "px"
            lines.append(f"  {css_var(group + '.' + str(key))}: {value}{unit};")
    lines.append("")
    lines.append("  /* 그림자·움직임 */")
    for key, value in tokens["shadow"].items():
        lines.append(f"  {css_var('shadow.' + key)}: {value};")
    for key, value in tokens["motion"].items():
        suffix = "ms" if isinstance(value, int) else ""
        lines.append(f"  {css_var('motion.' + key)}: {value}{suffix};")
    lines.append("}")
    lines.append("")
    # 어둡게는 두 가지로 켜진다: 사용자가 고른 값(data-theme)과 OS 설정.
    lines.append('[data-theme="dark"] {')
    lines += color_block("dark")
    lines.append("}")
    lines.append("")
    lines.append("@media (prefers-color-scheme: dark) {")
    lines.append('  :root:not([data-theme="light"]) {')
    lines += color_block("dark", indent="    ")
    lines.append("  }")
    lines.append("}")
    return "\n".join(lines) + "\n"


def web_theme_css(tokens: dict[str, Any]) -> str:
    """Tailwind 테마 (ADR-0017 §3). Tailwind 4는 설정 파일 대신 CSS `@theme`을 읽는다.

    값을 다시 적지 않고 `tokens.css`의 변수를 가리킨다 — 원본은 하나다. 그래서 테마를 바꾸면
    (`data-theme="dark"`) Tailwind 유틸리티의 색도 함께 바뀐다.
    """
    lines = [f"/* {BANNER} */", "", "@theme {"]

    lines.append("  /* 색 — 이름은 토큰 그대로 (`bg.surface` → `bg-surface` 유틸리티) */")
    for key in tokens["color"]["light"]:
        lines.append(f"  --color-{key.replace('.', '-')}: var({css_var(key)});")

    lines.append("")
    lines.append("  /* 글꼴 */")
    lines.append("  --font-sans: var(--font-family-sans);")
    lines.append("  --font-mono: var(--font-family-mono);")
    lines.append("")
    lines.append("  /* 글자 크기 (`text-body`) */")
    for key in tokens["font"]:
        kind, _, name = key.partition(".")
        if kind == "size":
            lines.append(f"  --text-{name}: var({css_var('font.' + key)});")

    lines.append("")
    lines.append("  /* 간격 — 토큰이 4px 단위라 Tailwind의 배수 하나로 맞는다 (`p-4` = 16px = space.4) */")
    lines.append(f"  --spacing: {tokens['space'][SPACING_STEP]}px;")

    lines.append("")
    lines.append("  /* 둥글기·그림자 */")
    for key in tokens["radius"]:
        lines.append(f"  --radius-{key}: var({css_var('radius.' + str(key))});")
    for key in tokens["shadow"]:
        lines.append(f"  --shadow-{key}: var({css_var('shadow.' + key)});")
    lines.append("}")
    return "\n".join(lines) + "\n"


def web_status_map_ts(tokens: dict[str, Any]) -> str:
    """상태 표기 → 상태 색 (스타일 가이드 §2-2). Qt의 `STATUS_MAP`과 같은 내용이다.

    **화면이 표기를 직접 쓰지 않게** 하려고 생성한다. 여기 없는 표기를 쓰면 타입이 막는다.
    """
    statuses = [k.split(".")[1] for k in tokens["color"]["light"] if k.startswith("status.") and k.endswith(".fg")]
    lines = [
        f"// {BANNER}",
        "",
        "/** 상태 색 7가지 (스타일 가이드 §2-2). */",
        "export const STATUS_TOKENS = [" + ", ".join(f'"{s}"' for s in statuses) + "] as const;",
        "",
        "export type StatusToken = (typeof STATUS_TOKENS)[number];",
        "",
        "/** 상태 표기 → 상태 색. 열쇠는 화면 설계서(`docs/06-screens`)의 묶음 이름이다. */",
        "export const STATUS_MAP = {",
    ]
    for group, mapping in tokens["status_map"].items():
        lines.append(f'  "{group}": {{')
        lines += [f'    "{label}": "{token}",' for label, token in mapping.items()]
        lines.append("  },")
    lines += [
        "} as const satisfies Record<string, Record<string, StatusToken>>;",
        "",
        "export type StatusGroup = keyof typeof STATUS_MAP;",
        "",
        "/** 그 묶음의 표기에 맞는 상태 색. 모르는 표기는 `undefined` — 화면은 회색으로 보이고,",
        " *  계약의 상태 값이 열린 문자열이라(계약 원칙 10) 모르는 값 하나로 화면이 깨지지 않는다. */",
        "export function statusToken(group: StatusGroup, label: string): StatusToken | undefined {",
        "  return (STATUS_MAP[group] as Record<string, StatusToken>)[label];",
        "}",
    ]
    return "\n".join(lines) + "\n"


# ───────────────────────── Qt ─────────────────────────


def _fit(line: str) -> str:
    """ruff의 줄 길이(120)를 넘는 생성 줄에는 noqa를 붙인다 (글꼴 목록이 길다)."""
    return f"{line}  # noqa: E501" if len(line) > 120 else line


def qt_tokens_py(tokens: dict[str, Any]) -> str:
    """Qt용 상수. 색은 테마마다 다르므로 `colors()`로 고르고, 색 상수는 밝게 값이다."""
    lines = [
        f'"""{BANNER}."""',
        "",
        "from typing import Final",
        "",
        "LIGHT: Final[dict[str, str]] = {",
    ]
    lines += [f'    "{k}": "{v}",' for k, v in tokens["color"]["light"].items()]
    lines += ["}", "", "DARK: Final[dict[str, str]] = {"]
    lines += [f'    "{k}": "{v}",' for k, v in tokens["color"]["dark"].items()]
    lines += ["}", ""]

    lines.append("# 색 상수는 **밝게** 값이다. 테마를 따라야 하면 colors()를 쓴다.")
    for key, value in tokens["color"]["light"].items():
        lines.append(f'{py_const(key)}: Final = "{value}"')
    lines.append("")

    for group in ("space", "radius", "size"):
        for key, value in tokens[group].items():
            lines.append(f"{py_const(group + '.' + str(key))}: Final = {value}")
    lines.append("")
    for key, value in tokens["font"].items():
        rendered = json.dumps(value, ensure_ascii=False) if isinstance(value, str) else value
        lines.append(_fit(f"{py_const('font.' + key)}: Final = {rendered}"))
    lines.append("")
    for group in ("shadow", "motion"):
        for key, value in tokens[group].items():
            rendered = json.dumps(value, ensure_ascii=False) if isinstance(value, str) else value
            lines.append(f"{py_const(group + '.' + key)}: Final = {rendered}")
    lines.append("")
    lines.append("#: 상태 표기 → 상태 색 이름 (`docs/07-style-guide.md` §2). 표기는 이 표에 있는 것만 쓴다.")
    lines.append("STATUS_MAP: Final[dict[str, dict[str, str]]] = {")
    for group, mapping in tokens["status_map"].items():
        lines.append(f'    "{group}": {{')
        lines += [f'        "{k}": "{v}",' for k, v in mapping.items()]
        lines.append("    },")
    lines.append("}")
    lines.append("")
    lines.append("")
    lines.append("def colors(*, dark: bool) -> dict[str, str]:")
    lines.append('    """테마에 맞는 색 표."""')
    lines.append("    return DARK if dark else LIGHT")
    return "\n".join(lines) + "\n"


def qt_arrow_svg(tokens: dict[str, Any], theme: str, direction: str) -> str:
    """QSpinBox ▲▼ 화살표. 색은 토큰 `text.secondary`, 크기는 간격 토큰 (가로 space.2 × 세로 space.1)."""
    w, h = tokens["space"]["2"], tokens["space"]["1"]
    color = tokens["color"][theme]["text.secondary"]
    points = f"0,{h} {w // 2},0 {w},{h}" if direction == "up" else f"0,0 {w // 2},{h} {w},0"
    return (
        f"<!-- {BANNER} ({theme}) -->\n"
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
        f'<polygon points="{points}" fill="{color}"/></svg>\n'
    )


def qt_check_svg(tokens: dict[str, Any], theme: str) -> str:
    """체크박스의 ✓. 색은 `primary.fg`(채운 상자 위에 올라간다), 크기는 간격 토큰 space.3."""
    size = tokens["space"]["3"]
    color = tokens["color"][theme]["primary.fg"]
    # 선 세 점: 왼쪽에서 아래로 내려가 오른쪽 위로 올라간다.
    corner = (size * 0.42, size * 0.78)
    points = f"{size * 0.2:.1f},{size * 0.55:.1f} {corner[0]:.1f},{corner[1]:.1f} {size * 0.8:.1f},{size * 0.25:.1f}"
    return (
        f"<!-- {BANNER} ({theme}) -->\n"
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}">'
        f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round"/></svg>\n'
    )


def qt_qss(tokens: dict[str, Any], theme: str) -> str:
    """QSS에는 변수가 없어 테마마다 파일 하나씩 만든다."""
    c = tokens["color"][theme]
    f, s, r, z = tokens["font"], tokens["space"], tokens["radius"], tokens["size"]
    return f"""/* {BANNER} ({theme}) */

QWidget {{
  background-color: {c["bg.canvas"]};
  color: {c["text.primary"]};
  font-family: {f["family.sans"]};
  font-size: {f["size.body"]}px;
}}

QFrame#Surface, QGroupBox, QDialog {{
  background-color: {c["bg.surface"]};
  border: 1px solid {c["border.default"]};
  border-radius: {r["lg"]}px;
}}

/* QGroupBox에 테두리를 입히면 Qt가 제목 자리를 비워 주지 않는다 — 여백과 ::title을 직접 정한다.
   없으면 제목이 첫 줄과 겹친다 (이슈 #3). */
QGroupBox {{
  margin-top: {s["4"]}px;
  padding: {s["3"]}px {s["2"]}px {s["2"]}px {s["2"]}px;
}}
QGroupBox::title {{
  subcontrol-origin: margin;
  subcontrol-position: top left;
  left: {s["3"]}px;
  padding: 0 {s["1"]}px;
  color: {c["text.secondary"]};
  font-weight: {f["weight.semibold"]};
}}

/* QWidget 배경이 글자 위젯에도 칠해져 흰 상자 안에 회색 칸이 생긴다 — 글자는 놓인 곳의 배경을 따른다. */
QLabel, QCheckBox, QRadioButton {{ background-color: transparent; }}

QLabel#Secondary {{ color: {c["text.secondary"]}; }}
QLabel#Muted {{ color: {c["text.muted"]}; }}

QPushButton {{
  background-color: {c["primary"]};
  color: {c["primary.fg"]};
  border: none;
  border-radius: {r["md"]}px;
  min-height: {z["control.md"]}px;
  padding: 0 {s["3"]}px;
  font-weight: {f["weight.medium"]};
}}
QPushButton:hover {{ background-color: {c["primary.hover"]}; }}
QPushButton:focus {{ border: 2px solid {c["focus"]}; }}
QPushButton:disabled {{ background-color: {c["bg.subtle"]}; color: {c["text.muted"]}; }}

QPushButton#Secondary {{
  background-color: {c["bg.surface"]};
  color: {c["text.primary"]};
  border: 1px solid {c["border.strong"]};
}}

QPushButton#Danger {{
  background-color: {c["status.failed.solid"]};
  color: {c["danger.fg"]};
}}

QLineEdit, QComboBox, QPlainTextEdit, QTextEdit, QSpinBox {{
  background-color: {c["bg.surface"]};
  color: {c["text.primary"]};
  border: 1px solid {c["border.strong"]};
  border-radius: {r["md"]}px;
  min-height: {z["control.md"]}px;
  padding: 0 {s["2"]}px;
}}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus {{
  border: 2px solid {c["focus"]};
}}

/* QSpinBox에 테두리·둥근 모서리를 입히면 기본 ▲▼ 단추가 그 테두리 위에 그대로 겹쳐 잘린다 (이슈 #3, 150%).
   단추를 테두리 안쪽에 세로로 놓고, 칸 오른쪽에 그 자리를 비운다. */
QSpinBox {{ padding-right: {s["6"]}px; }}
QSpinBox::up-button, QSpinBox::down-button {{
  subcontrol-origin: border;
  width: {s["5"]}px;
  border: none;
  border-left: 1px solid {c["border.default"]};
  background-color: transparent;
}}
QSpinBox::up-button {{
  subcontrol-position: top right;
  margin: 1px 1px 0 0;
  border-top-right-radius: {r["md"]}px;
}}
QSpinBox::down-button {{
  subcontrol-position: bottom right;
  margin: 0 1px 1px 0;
  border-bottom-right-radius: {r["md"]}px;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background-color: {c["bg.subtle"]}; }}
/* 단추를 꾸미면 Qt가 기본 화살표를 그리지 않는다 — 생성한 SVG를 쓴다. `@THEME_DIR@`는 테마를 읽을 때
   그 패키지 폴더의 실제 경로로 바뀐다 (chaeksas.qt.theme.qss). */
QSpinBox::up-arrow {{
  image: url(@THEME_DIR@/arrow-up-{theme}.svg);
  width: {s["2"]}px;
  height: {s["1"]}px;
}}
QSpinBox::down-arrow {{
  image: url(@THEME_DIR@/arrow-down-{theme}.svg);
  width: {s["2"]}px;
  height: {s["1"]}px;
}}

/* QCheckBox·QRadioButton에 **무엇이든** 스타일을 주면 Qt가 기본 표시기를 그리지 않는다 — 체크된 칸이
   상자 없이 ✓만 보였다 (이슈 #3). 표시기를 직접 그린다. ✓는 생성한 SVG다. */
QCheckBox::indicator, QRadioButton::indicator {{
  width: {s["4"]}px;
  height: {s["4"]}px;
  border: 1px solid {c["border.strong"]};
  background-color: {c["bg.surface"]};
}}
QCheckBox::indicator {{ border-radius: {r["sm"]}px; }}
QRadioButton::indicator {{ border-radius: {s["2"]}px; }}  /* 지름의 절반 = 동그라미 */
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {c["primary"]}; }}
QCheckBox::indicator:checked {{
  background-color: {c["primary"]};
  border-color: {c["primary"]};
  image: url(@THEME_DIR@/check-{theme}.svg);
}}
QRadioButton::indicator:checked {{
  background-color: {c["bg.surface"]};
  border: {s["1"]}px solid {c["primary"]};
}}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{
  background-color: {c["bg.subtle"]};
  border-color: {c["border.default"]};
}}

QHeaderView::section {{
  background-color: {c["bg.subtle"]};
  color: {c["text.secondary"]};
  border: none;
  border-bottom: 1px solid {c["border.default"]};
  height: {z["row.compact"]}px;
  padding: 0 {s["2"]}px;
}}
QTableView, QTreeView, QListView {{
  background-color: {c["bg.surface"]};
  alternate-background-color: {c["bg.canvas"]};
  border: 1px solid {c["border.default"]};
  border-radius: {r["lg"]}px;
}}
QTableView::item:selected, QTreeView::item:selected, QListView::item:selected {{
  background-color: {c["primary.subtle"]};
  color: {c["text.primary"]};
}}

QToolTip {{
  background-color: {c["bg.inverse"]};
  color: {c["text.inverse"]};
  border: none;
  padding: {s["1"]}px {s["2"]}px;
}}

QProgressBar {{
  background-color: {c["bg.subtle"]};
  border: none;
  border-radius: {r["full"]}px;
  height: {s["2"]}px;
  text-align: center;
}}
QProgressBar::chunk {{ background-color: {c["status.active.solid"]}; border-radius: {r["full"]}px; }}
"""


# ───────────────────────── 미리보기 ─────────────────────────


def preview_html(tokens: dict[str, Any], rows_light: list[tuple[str, str, float, float, bool]]) -> str:
    def swatches(theme: str) -> str:
        return "\n".join(
            f'<div class="sw"><span style="background:{v}"></span><code>{k}</code><small>{v}</small></div>'
            for k, v in tokens["color"][theme].items()
        )

    badges = "\n".join(
        f'<div class="grp"><h4>{group}</h4>'
        + "".join(f'<span class="badge {tone}">{label}</span>' for label, tone in mapping.items())
        + "</div>"
        for group, mapping in tokens["status_map"].items()
    )
    sizes = "\n".join(
        f'<p style="font-size:{v}px">{k} — {v}px · 다람쥐 헌 쳇바퀴에 타고파 ABC 123</p>'
        for k, v in tokens["font"].items()
        if k.startswith("size.")
    )
    spaces = "\n".join(
        f'<div class="sp"><span style="width:{v}px"></span><code>space.{k}</code><small>{v}px</small></div>'
        for k, v in tokens["space"].items()
    )
    radii = "\n".join(
        f'<div class="rd"><span style="border-radius:{v}px"></span><code>radius.{k}</code></div>'
        for k, v in tokens["radius"].items()
    )
    contrast_table = "\n".join(
        f"<tr><td><code>{fg}</code></td><td><code>{bg}</code></td>"
        f'<td class="{"ok" if ratio >= floor else ("warn" if not blocking else "bad")}">{ratio:.2f}:1</td>'
        f"<td>{floor}:1{'' if blocking else ' (경고)'}</td></tr>"
        for fg, bg, ratio, floor, blocking in rows_light
    )
    # 글꼴은 **외부 CDN에서 받지 않는다** (스타일 가이드 §4 — 사내망). 설치된 글꼴로 떨어진다.
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Chaeksas 스타일 미리보기</title>
<!-- {BANNER} -->
<link rel="stylesheet" href="../web/packages/ui/src/tokens.css">
<style>
body {{ margin:0; padding:var(--space-6); background:var(--bg-canvas); color:var(--text-primary);
  font-family:var(--font-family-sans); font-size:var(--font-size-body); line-height:var(--font-line-body); }}
h1 {{ font-size:var(--font-size-display); }} h2 {{ font-size:var(--font-size-h2); margin-top:var(--space-10); }}
h4 {{ font-size:var(--font-size-body-sm); color:var(--text-muted); margin:var(--space-3) 0 var(--space-1); }}
section {{ background:var(--bg-surface); border:1px solid var(--border-default);
  border-radius:var(--radius-lg); padding:var(--space-5); margin-bottom:var(--space-5); }}
.grid {{ display:flex; flex-wrap:wrap; gap:var(--space-2); }}
.sw {{ width:180px; display:flex; align-items:center; gap:var(--space-2); }}
.sw span {{ width:28px; height:28px; border-radius:var(--radius-sm); border:1px solid var(--border-default); }}
.sw code {{ font-size:var(--font-size-caption); }} .sw small {{ color:var(--text-muted); }}
.badge {{ display:inline-block; padding:2px var(--space-2); border-radius:var(--radius-full);
  font-size:var(--font-size-caption); font-weight:var(--font-weight-medium); margin:2px; }}
.neutral {{ color:var(--status-neutral-fg); background:var(--status-neutral-bg); }}
.active {{ color:var(--status-active-fg); background:var(--status-active-bg); }}
.done {{ color:var(--status-done-fg); background:var(--status-done-bg); }}
.failed {{ color:var(--status-failed-fg); background:var(--status-failed-bg); }}
.waiting {{ color:var(--status-waiting-fg); background:var(--status-waiting-bg); }}
.warning {{ color:var(--status-warning-fg); background:var(--status-warning-bg); }}
.replayed {{ color:var(--status-replayed-fg); background:var(--status-replayed-bg); }}
.sp, .rd {{ display:flex; align-items:center; gap:var(--space-2); width:220px; }}
.sp span {{ height:12px; background:var(--primary); border-radius:var(--radius-sm); }}
.rd span {{ width:48px; height:32px; background:var(--primary-subtle); border:1px solid var(--primary); }}
button {{ font:inherit; height:var(--size-control-md); padding:0 var(--space-3); border:none;
  border-radius:var(--radius-md); background:var(--primary); color:var(--primary-fg);
  font-weight:var(--font-weight-medium); }}
button.secondary {{ background:var(--bg-surface); color:var(--text-primary); border:1px solid var(--border-strong); }}
input {{ font:inherit; height:var(--size-control-md); padding:0 var(--space-2); color:var(--text-primary);
  background:var(--bg-surface); border:1px solid var(--border-strong); border-radius:var(--radius-md); }}
table {{ border-collapse:collapse; font-size:var(--font-size-body-sm); }}
th, td {{ text-align:left; padding:var(--space-1) var(--space-3); border-bottom:1px solid var(--border-default); }}
th {{ color:var(--text-secondary); background:var(--bg-subtle); }}
.ok {{ color:var(--status-done-fg); }} .warn {{ color:var(--status-warning-fg); }}
.bad {{ color:var(--status-failed-fg); font-weight:var(--font-weight-bold); }}
#toggle {{ position:fixed; top:var(--space-4); right:var(--space-4); }}
</style></head>
<body>
<button id="toggle" class="secondary" onclick="
  const r=document.documentElement;
  r.dataset.theme = r.dataset.theme==='dark' ? 'light' : 'dark';">밝게 / 어둡게</button>

<h1>Chaeksas 스타일 미리보기</h1>
<p style="color:var(--text-muted)">원본은 <code>design/tokens.json</code>. 이 파일은 생성물이다.</p>

<h2>색 (밝게)</h2>
<section><div class="grid">{swatches("light")}</div></section>
<h2>색 (어둡게)</h2>
<section><div class="grid">{swatches("dark")}</div></section>

<h2>상태 표기 → 색</h2>
<section>{badges}</section>

<h2>글자</h2>
<section>{sizes}</section>

<h2>간격</h2>
<section><div class="grid">{spaces}</div></section>

<h2>둥글기</h2>
<section><div class="grid">{radii}</div></section>

<h2>구성요소</h2>
<section>
  <button>기본 단추</button>
  <button class="secondary">보조 단추</button>
  <input placeholder="입력칸">
</section>

<h2>명암비 (밝게 기준, 생성기가 검사한 값)</h2>
<section><table><tr><th>앞</th><th>뒤</th><th>비율</th><th>기준</th></tr>
{contrast_table}
</table></section>
</body></html>
"""


# ───────────────────────── 실행 ─────────────────────────


def outputs(tokens: dict[str, Any]) -> dict[Path, str]:
    return {
        WEB_CSS: web_css(tokens),
        WEB_THEME: web_theme_css(tokens),
        WEB_STATUS_MAP: web_status_map_ts(tokens),
        QT_DIR / "tokens.py": qt_tokens_py(tokens),
        QT_DIR / "theme-light.qss": qt_qss(tokens, "light"),
        QT_DIR / "theme-dark.qss": qt_qss(tokens, "dark"),
        **{
            QT_DIR / f"arrow-{d}-{t}.svg": qt_arrow_svg(tokens, t, d)
            for t in ("light", "dark")
            for d in ("up", "down")
        },
        **{QT_DIR / f"check-{t}.svg": qt_check_svg(tokens, t) for t in ("light", "dark")},
        # `theme/__init__.py`는 손으로 쓴다 (테마를 **적용하는** 코드가 거기 있다).
        PREVIEW: preview_html(tokens, contrast_rows(tokens["color"]["light"])),
    }


def main() -> int:
    check = "--check" in sys.argv
    tokens = json.loads(SOURCE.read_text(encoding="utf-8"))

    errors, warnings = check_contrast(tokens)
    errors += check_spacing_scale(tokens)
    for line in warnings:
        print("경고:", line)
    if errors:
        print("검사 실패 — 아무것도 쓰지 않는다:")
        for line in errors:
            print("  -", line)
        return 1

    out = outputs(tokens)
    if check:
        stale = [p for p, text in out.items() if not p.exists() or p.read_text(encoding="utf-8") != text]
        for p in stale:
            print("다름:", p.relative_to(ROOT).as_posix())
        return 1 if stale else 0

    for p, text in out.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
    print(f"토큰 → 생성물 {len(out)}개 (명암비 검사 통과, 경고 {len(warnings)}개)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
