"""예제 50개에서 **식이 쓰이는 자리**를 전부 모은다 (스파이크 S6의 시험대).

정규식이 아니라 제품 reader(`chaeksas.contracts.bpmn_ext`)로 읽는다 — 식이 JSON 속에도 있다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from chaeksas.contracts.bpmn_ext import read_process

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
BPMN_DIR = ROOT / "docs" / "08-business-examples" / "bpmn"


def rows() -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    for path in sorted(BPMN_DIR.glob("*.bpmn")):
        process = read_process(path.read_text(encoding="utf-8"))
        for node in process.all_nodes():
            if node.script:
                found.append({"file": path.name, "node": node.id, "site": "script", "text": node.script})
            for name in ("serviceCall", "rule", "call"):
                holder = node.prop(name)
                if holder is None:
                    continue
                for field, expr in (holder.input or {}).items():
                    found.append({"file": path.name, "node": node.id, "site": f"{name}.input.{field}", "text": expr})
            loop = node.prop("loop")
            if loop is not None and getattr(loop, "over", None):
                found.append({"file": path.name, "node": node.id, "site": "loop.over", "text": loop.over})
            data_output = node.prop("dataOutput")
            if data_output is not None:
                for field in ("value", "rows", "content", "path"):
                    value = getattr(data_output, field, None)
                    if isinstance(value, str) and value:
                        found.append(
                            {"file": path.name, "node": node.id, "site": f"dataOutput.{field}", "text": value}
                        )
        for flow in process.flows + [f for n in process.all_nodes() for f in n.child_flows]:
            if flow.condition:
                found.append({"file": path.name, "node": flow.id, "site": "condition", "text": flow.condition})
    return found


if __name__ == "__main__":
    found = rows()
    out = Path(__file__).with_name("corpus.json")
    out.write_text(json.dumps(found, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    kinds: dict[str, int] = {}
    for row in found:
        kinds[row["site"].split(".")[0]] = kinds.get(row["site"].split(".")[0], 0) + 1
    print(f"식 자리 {len(found)}곳 → {out.relative_to(ROOT)}")
    print("자리별:", kinds)
