"""업무 예제 50개의 AI 태스크를 **제품 reader로** 읽어 센다 (NOTES.md §1의 표).

돌리기: `uv run python spikes/s7-llm/collect.py`
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from chaeksas.contracts.bpmn_ext import read_process  # noqa: E402

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "08-business-examples" / "bpmn"


def main() -> int:
    total = 0
    domains: Counter[str] = Counter()
    tools: Counter[str] = Counter()
    types: Counter[str] = Counter()
    counts: Counter[int] = Counter()
    loops = 0
    lengths = []

    for path in sorted(EXAMPLES.glob("*.bpmn")):
        for node in read_process(path.read_text(encoding="utf-8")).all_nodes():
            ai = node.prop("aiTask")
            if ai is None:
                continue
            total += 1
            domains[ai.domain] += 1
            lengths.append(len(ai.goal))
            counts[len(ai.results)] += 1
            tools.update(ai.tools)
            types.update(ai.results.values())
            loops += node.prop("loop") is not None

    print(f"AI 태스크 {total}곳")
    print(f"  domain        {dict(domains.most_common())}")
    print(f"  도구          {len(tools)}종, {sum(tools.values())}곳 — {dict(tools.most_common())}")
    print(f"  results 개수  {dict(sorted(counts.items()))}")
    print(f"  결과 타입     {dict(types.most_common())}")
    print(f"  반복이 붙은 것 {loops}곳")
    print(f"  goal 길이     {min(lengths)}~{max(lengths)}자 (중앙 {sorted(lengths)[len(lengths) // 2]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
