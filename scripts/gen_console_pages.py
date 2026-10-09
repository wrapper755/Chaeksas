"""확장이 기여한 콘솔 화면 (C13 `console.pages`) → 서비스 앱 콘솔의 **빌드 시점 레지스트리**.

실행: `uv run python scripts/gen_console_pages.py`
`--check`: 파일을 쓰지 않고 검사만 하며, 생성물이 정의와 다르면 1로 끝난다 (CI용).

**손으로 베끼지 않는다** ([ADR-0042](../docs/decisions/0042-extension-contributed-panels.md) §2).
전에는 콘솔(`Shell.tsx`)에 세 줄이 손으로 적혀 있어서 **확장을 더해도 줄이 생기지 않았다**.

왜 생성물인가: 콘솔은 Next.js 앱이고 화면 모듈이 **번들에 들어가야** 한다 — 브라우저가 바깥
주소로 동적 `import()`를 여는 길을 내지 않는다 (ADR-0017). 그래서 기여 목록을 빌드 시점에
읽어 둔다. 파이썬 쪽에만 확장 정의가 있으니 **읽는 것도 파이썬이** 한다 (`gen_moddle.py`와 같은 결).

모노레포 안 내장·사내 확장만 본다. 외부 확장은 코드를 기여할 수 없고(C13 E1) 자기 콘솔
**링크만** CON-07에 보인다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Windows 콘솔·파이프의 기본 코드페이지(cp949·cp1252)에서는 한글을 찍다 터진다.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
EXTENSIONS = ROOT / "extensions"
OUT = ROOT / "web" / "apps" / "svc-console" / "lib" / "console-pages.generated.ts"

BANNER = (
    "// 생성 파일: 확장 정의(C13 `console.pages`)에서 만든다.\n"
    "// 직접 고치지 말고 `uv run python scripts/gen_console_pages.py` (ADR-0042).\n"
)

NOTE = """
/**
 * 확장이 기여한 앱 고유 화면 — **확장 id로 묶는다.**
 *
 * 콘솔은 접속한 앱의 `/admin/v1/status`가 말하는 `extension.id`로 자기 줄을 고른다 (C11).
 * `module`을 실제 화면으로 잇는 것은 `console-modules.ts`이고, 없는 모듈은 **끄고 이유를
 * 가까이에 적는다** (U3).
 */
""".lstrip()


def manifests() -> list[tuple[str, dict[str, Any]]]:
    """모노레포 안 확장 정의들 — `(파일 경로 글, 정의)`. 경로 순서로 읽는다 (생성물이 흔들리지 않게)."""
    out: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(EXTENSIONS.glob("*/src/chaeksas/ext/*/extension.json")):
        found = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(found, dict):
            out.append((path.relative_to(ROOT).as_posix(), found))
    return out


def pages() -> dict[str, list[dict[str, str]]]:
    """`{확장 id: [{id, label, module}]}`. 기여가 없는 확장은 넣지 않는다."""
    out: dict[str, list[dict[str, str]]] = {}
    for where, definition in manifests():
        extension_id = str(definition.get("id") or "")
        found = (definition.get("contributes") or {}).get("console.pages") or []
        if not extension_id or not found:
            continue
        rows = [
            {"id": str(one["id"]), "label": str(one["label"]), "module": str(one["module"])}
            for one in found
            if isinstance(one, dict) and one.get("id") and one.get("label") and one.get("module")
        ]
        if len(rows) != len(found):
            print(f"경고: {where}의 console.pages에 모양이 맞지 않는 항목이 있다 (건너뛴다)")
        if rows:
            out[extension_id] = rows
    return out


def rendered() -> str:
    body = json.dumps(pages(), ensure_ascii=False, indent=2, sort_keys=True)
    return (
        f"{BANNER}\n"
        "export interface ConsolePage {\n  id: string;\n  label: string;\n  module: string;\n}\n\n"
        f"{NOTE}"
        f"export const CONSOLE_PAGES: Record<string, ConsolePage[]> = {body};\n"
    )


def main() -> int:
    text = rendered()
    count = sum(len(rows) for rows in pages().values())
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print("다름:", OUT.relative_to(ROOT).as_posix())
            return 1
        print(f"콘솔 화면 기여 {count}개가 최신이다.")
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"콘솔 화면 기여 {count}개 → {OUT.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
