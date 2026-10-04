"""C14 `chk:*` 요소 → bpmn-moddle 설명 (`chk-moddle.js`).

실행: `uv run python scripts/gen_moddle.py`
`--check`: 파일을 쓰지 않고 검사만 하며, 생성물이 모델과 다르면 1로 끝난다 (CI용).

bpmn-js가 우리 확장 요소를 **타입으로** 다루려면 설명이 필요하다 ([ADR-0022](../docs/decisions/0022-studio-canvas.md)).
**손으로 쓰지 않는다** — 원본은 `contracts.bpmn_ext.ELEMENT_MODELS`이고, `chk:*`를 하나 더하면
여기를 다시 돌려야 CI가 통과한다 ([ADR-0029](../docs/decisions/0029-bpmn-js-vendoring.md) §3).

속성 **본문은 JSON 텍스트 하나**다 (C14 기본 규칙 2) — 그래서 요소마다 `isBody` 속성 하나이고,
XML 속성을 따로 쓰는 것은 `chk:task`의 `type`·`extension`뿐이다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from chaeksas.contracts.bpmn_ext import CHK_NS, ELEMENT_MODELS

# Windows 콘솔·파이프의 기본 코드페이지(cp949·cp1252)에서는 한글을 찍다 터진다.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "apps" / "studio" / "src" / "chaeksas" / "studio" / "web" / "chk-moddle.js"

#: XML 속성으로 적는 것 (나머지는 전부 본문 JSON이다). C14 §태스크 종류 표의 `chk:task`.
XML_ATTRIBUTES: dict[str, tuple[str, ...]] = {"task": ("type", "extension")}

BANNER = (
    "// 생성 파일: C14 모델(`contracts.bpmn_ext.ELEMENT_MODELS`)에서 만든다.\n"
    "// 직접 고치지 말고 `uv run python scripts/gen_moddle.py` (ADR-0022·ADR-0029).\n"
)


def descriptor() -> dict[str, object]:
    """bpmn-moddle이 읽는 설명 한 벌."""
    types = []
    for name in sorted(ELEMENT_MODELS):
        properties: list[dict[str, object]] = [{"name": "value", "type": "String", "isBody": True}]
        properties += [
            {"name": attribute, "type": "String", "isAttr": True}
            for attribute in XML_ATTRIBUTES.get(name, ())
        ]
        types.append(
            {
                # moddle 타입 이름은 대문자로 시작한다. `tagAlias: lowerCase`가 `chk:aiTask`로 되돌린다.
                "name": name[0].upper() + name[1:],
                "superClass": ["Element"],
                "properties": properties,
            }
        )
    return {
        "name": "Chaeksas",
        "uri": CHK_NS,
        "prefix": "chk",
        "xml": {"tagAlias": "lowerCase"},
        "types": types,
    }


def rendered() -> str:
    body = json.dumps(descriptor(), ensure_ascii=False, indent=2)
    return f"{BANNER}window.CHK_MODDLE = {body};\n"


def main() -> int:
    text = rendered()
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print("다름:", OUT.relative_to(ROOT))
            return 1
        print(f"chk: 요소 {len(ELEMENT_MODELS)}개 설명이 최신이다.")
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"chk: 요소 {len(ELEMENT_MODELS)}개 → {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
