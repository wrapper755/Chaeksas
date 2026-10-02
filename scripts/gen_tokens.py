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

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "design" / "tokens.json"

#: ADR-0017이 정한 생성물.
WEB_CSS = ROOT / "web" / "packages" / "ui" / "src" / "tokens.css"
QT_DIR = ROOT / "packages" / "qt" / "src" / "chaeksas" / "qt" / "theme"
PREVIEW = ROOT / "design" / "preview.html"

BANNER = "생성 파일: design/tokens.json에서 만든다. 직접 고치지 말고 원본을 고친 뒤 scripts/gen_tokens.py"

#: 글자 명암비 기준 (WCAG 2.2 AA, 스타일 가이드 D6).
AA_TEXT = 4.5
AA_UI = 3.0

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
        QT_DIR / "tokens.py": qt_tokens_py(tokens),
        QT_DIR / "theme-light.qss": qt_qss(tokens, "light"),
        QT_DIR / "theme-dark.qss": qt_qss(tokens, "dark"),
        QT_DIR / "__init__.py": f'"""Qt 테마 — {BANNER}."""\n',
        PREVIEW: preview_html(tokens, contrast_rows(tokens["color"]["light"])),
    }


def main() -> int:
    check = "--check" in sys.argv
    tokens = json.loads(SOURCE.read_text(encoding="utf-8"))

    errors, warnings = check_contrast(tokens)
    for line in warnings:
        print("경고:", line)
    if errors:
        print("명암비 검사 실패 — 아무것도 쓰지 않는다:")
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
