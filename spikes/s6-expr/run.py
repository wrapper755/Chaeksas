"""스파이크 S6 — 식 언어 후보를 **예제가 실제로 쓰는 식**으로 재어 본다.

재는 것:
1. **문법 받아들임** — 예제 50개의 식 자리 201곳(`corpus.json`)을 그 후보가 파싱하는가.
2. **값 내기** — 손으로 쓴 평가 시험 (사전 점 접근·내포·조건식·도우미·막아야 할 것).
3. **막아야 할 것** — 파일 읽기·import·던더 접근이 막히는가.

후보:
- `walker` — 직접 만든 AST 검사기 (이 폴더)
- `simpleeval` — 널리 쓰이는 작은 평가기 (`uv run --with simpleeval`)
- `asteval` — numpy 쪽에서 많이 쓰는 평가기 (`uv run --with asteval`)

실행: `uv run python spikes/s6-expr/run.py`  (라이브러리까지 보려면
`uv run --with simpleeval --with asteval python spikes/s6-expr/run.py`)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from walker import ExprError, Walker  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CORPUS = json.loads((Path(__file__).with_name("corpus.json")).read_text(encoding="utf-8"))

#: 업무 예제가 쓰는 도우미 (이름만 맞춘 가짜 — 스파이크는 문법·안전을 본다).
HELPERS: dict[str, Any] = {
    "len": len,
    "sum": sum,
    "min": min,
    "max": max,
    "round": round,
    "zip": lambda *a: list(zip(*a, strict=False)),
    "dict": dict,
    "list": list,
    "지난달": lambda: "2026-09",
    "이번달": lambda: "2026-10",
    "오늘날짜": lambda: "2026-10-04",
    "지금시각": lambda: "2026-10-04T09:00:00+09:00",
    "어제": lambda: "2026-10-03",
    "기간": lambda a, b: {"from": a, "to": b},
    "날짜더하기": lambda d, n: d,
    "지난주표기": lambda: "2026-W40",
    "파일목록": lambda pattern: ["a.pdf", "b.pdf"],
    "합계": lambda rows, key: sum(r[key] for r in rows),
    "소계": lambda rows, key: sum(r[key] for r in rows),
    "세기": lambda rows: len(rows),
    "비율": lambda a, b: (a / b) if b else 0,
    "나누기": lambda a, b: (a / b) if b else 0,
    "펼치기": lambda rows: [x for r in rows for x in r],
    "빈칸없음": lambda row, keys: all(row.get(k) for k in keys),
    "범위벗어남": lambda v, lo, hi: not (lo <= v <= hi),
    "표를사전": lambda rows, key: {r[key]: r for r in rows},
    "총무게": lambda rows: sum(r.get("무게", 0) for r in rows),
    "설정": lambda name, default=None: default,
    "전표자료": lambda *a, **k: [],
    "대사규칙": lambda *a: {"지급": [], "보류": [], "미청구": []},
    # 「양식」류는 예제가 만든 서식 함수다 — 목록에 넣을지가 ADR의 물음이다.
    "대사표양식": lambda *a: "표",
    "아침보고양식": lambda *a: "표",
    "지출기록양식": lambda *a: "표",
    "발행보고양식": lambda *a: "표",
}

#: 평가 시험 — (식, 변수, 기대값). 예제에서 본 모양을 줄여 담았다.
EVAL_CASES: list[tuple[str, dict[str, Any], Any]] = [
    ("보류건수 > 0", {"보류건수": 2}, True),
    ("경로 == '결재'", {"경로": "결재"}, True),
    ("len(이관대상) > 0", {"이관대상": [1, 2]}, True),
    ("대상월 or 지난달()", {"대상월": None}, "2026-09"),
    ("결과.지급", {"결과": {"지급": [1]}}, [1]),  # **사전을 점으로** — 예제가 이렇게 쓴다
    ("결과.지급[0]", {"결과": {"지급": [7]}}, 7),
    ("[r['합계'] for r in 목록 if r['합계'] > 1]", {"목록": [{"합계": 1}, {"합계": 5}]}, [5]),
    ("{r['id']: r for r in 목록}", {"목록": [{"id": "a"}]}, {"a": {"id": "a"}}),
    ("[] if 진행 == '보류' else 지급대상", {"진행": "보류", "지급대상": [1]}, []),
    ("합계(지급대상, '합계')", {"지급대상": [{"합계": 3}, {"합계": 4}]}, 7),
    ("'일일/' + 오늘 + '.md'", {"오늘": "2026-10-04"}, "일일/2026-10-04.md"),
    ("미입력", {"미입력": None}, None),  # 선언했지만 값이 없으면 None (C14)
    ("[a + b for a, b in zip(목록1, 목록2)]", {"목록1": [1], "목록2": [2]}, [3]),
    ("round(비율(3, 4) * 100, 1)", {}, 75.0),
]

#: 막아야 할 것 — 하나라도 통과하면 그 후보는 쓸 수 없다.
MUST_REFUSE = [
    "__import__('os').listdir('.')",
    "open('/etc/passwd').read()",
    "().__class__.__bases__[0].__subclasses__()",
    "오늘.__class__",
    "exec('x=1')",
    "eval('1')",
    "globals()",
]


def try_walker() -> dict[str, Any]:
    parsed, failed = 0, []
    for row in CORPUS:
        try:
            tree_ok = Walker({}, HELPERS)
            source = row["text"]
            if row["site"] == "script":
                import ast  # noqa: PLC0415

                from walker import check  # noqa: PLC0415

                check(ast.parse(source.strip(), mode="exec"))
            else:
                import ast  # noqa: PLC0415

                from walker import check  # noqa: PLC0415

                check(ast.parse(source.strip(), mode="eval"))
            del tree_ok
            parsed += 1
        except (ExprError, SyntaxError) as e:
            failed.append((row["file"], row["site"], str(e)[:60]))

    good, wrong = 0, []
    for source, variables, expected in EVAL_CASES:
        try:
            found = Walker(variables, HELPERS).eval(source)
        except Exception as e:  # noqa: BLE001
            wrong.append((source, f"오류: {e}"))
            continue
        if found == expected:
            good += 1
        else:
            wrong.append((source, f"{found!r} ≠ {expected!r}"))

    refused = 0
    leaked = []
    for source in MUST_REFUSE:
        try:
            Walker({"오늘": "2026-10-04"}, HELPERS).eval(source)
        except Exception:  # noqa: BLE001
            refused += 1
        else:
            leaked.append(source)
    return {"parsed": parsed, "parse_failures": failed, "eval_ok": good, "eval_bad": wrong,
            "refused": refused, "leaked": leaked}


def try_simpleeval() -> dict[str, Any] | None:
    try:
        from simpleeval import EvalWithCompoundTypes  # type: ignore[import-not-found]
    except ImportError:
        return None

    def make(variables: dict[str, Any]) -> Any:
        return EvalWithCompoundTypes(names=dict(variables), functions=dict(HELPERS))

    parsed, failed = 0, []
    for row in CORPUS:
        if row["site"] == "script":
            continue  # simpleeval은 식만 본다 (대입문 없음)
        try:
            make({}).parse(row["text"].strip())
            parsed += 1
        except Exception as e:  # noqa: BLE001
            failed.append((row["file"], row["site"], str(e)[:60]))

    good, wrong = 0, []
    for source, variables, expected in EVAL_CASES:
        try:
            found = make(variables).eval(source)
        except Exception as e:  # noqa: BLE001
            wrong.append((source, f"오류: {type(e).__name__} {e}"[:70]))
            continue
        if found == expected:
            good += 1
        else:
            wrong.append((source, f"{found!r} ≠ {expected!r}"))

    refused, leaked = 0, []
    for source in MUST_REFUSE:
        try:
            make({"오늘": "2026-10-04"}).eval(source)
        except Exception:  # noqa: BLE001
            refused += 1
        else:
            leaked.append(source)
    return {"parsed": parsed, "parse_failures": failed, "eval_ok": good, "eval_bad": wrong,
            "refused": refused, "leaked": leaked, "note": "스크립트(대입문)는 다루지 않는다"}


def try_asteval() -> dict[str, Any] | None:
    try:
        from asteval import Interpreter  # type: ignore[import-not-found]
    except ImportError:
        return None

    def make(variables: dict[str, Any]) -> Any:
        found = Interpreter(usersyms={**HELPERS, **variables}, minimal=True, no_print=True)
        return found

    good, wrong = 0, []
    for source, variables, expected in EVAL_CASES:
        engine = make(variables)
        try:
            found = engine(source, raise_errors=True)
        except Exception as e:  # noqa: BLE001
            wrong.append((source, f"오류: {type(e).__name__} {e}"[:70]))
            continue
        if found == expected:
            good += 1
        else:
            wrong.append((source, f"{found!r} ≠ {expected!r}"))

    refused, leaked = 0, []
    for source in MUST_REFUSE:
        engine = make({"오늘": "2026-10-04"})
        try:
            engine(source, raise_errors=True)
        except Exception:  # noqa: BLE001
            refused += 1
        else:
            leaked.append(source)
    return {"eval_ok": good, "eval_bad": wrong, "refused": refused, "leaked": leaked,
            "note": "문법 받아들임은 재지 않았다 (라이브러리가 파싱만 떼어 주지 않는다)"}


def report(name: str, found: dict[str, Any] | None) -> None:
    print(f"\n── {name} ──")
    if found is None:
        print("  설치되지 않았다 (`uv run --with …`로 다시 돌리면 잰다)")
        return
    if "parsed" in found:
        total = len([r for r in CORPUS if name != "simpleeval" or r["site"] != "script"])
        print(f"  문법 받아들임: {found['parsed']}/{total}")
        for row in found["parse_failures"][:5]:
            print(f"    못 읽음: {row[0]} {row[1]} — {row[2]}")
    print(f"  값 내기: {found['eval_ok']}/{len(EVAL_CASES)}")
    for row in found["eval_bad"][:8]:
        print(f"    틀림: {row[0]}  →  {row[1]}")
    print(f"  막아야 할 것 막음: {found['refused']}/{len(MUST_REFUSE)}")
    for row in found["leaked"]:
        print(f"    **새어 나감**: {row}")
    if "note" in found:
        print(f"  («{found['note']}»)")


if __name__ == "__main__":
    print(f"시험대: 예제 식 자리 {len(CORPUS)}곳, 평가 시험 {len(EVAL_CASES)}개, 막을 것 {len(MUST_REFUSE)}개")
    report("walker (직접)", try_walker())
    report("simpleeval", try_simpleeval())
    report("asteval", try_asteval())
