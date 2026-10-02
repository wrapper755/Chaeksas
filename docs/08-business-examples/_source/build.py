"""예제 정의 → BPMN·DMN·케이스·문서 카드 생성.

실행: `python docs/08-business-examples/_source/build.py` (표준 라이브러리만).
`--check`: 파일을 쓰지 않고 검사만 하며, 생성물이 정의와 다르면 1로 끝난다 (CI용).
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# Windows 콘솔·파이프의 기본 코드페이지(cp949·cp1252)에서는 한글을 찍다 터진다.
# 이 도구들은 한글로 말하므로 stdout을 UTF-8로 고정한다 (CI의 Windows에서 실제로 터졌다).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from exdsl import Example, all_nodes, to_bpmn, to_card, to_cases, to_dmn, validate, var_warnings  # noqa: E402

import spec_fin, spec_fx, spec_hr, spec_ops, spec_scm  # noqa: E402,E401

ROOT = HERE.parent
GROUPS = [
    ("finance.md", "재무·회계", spec_fin.EXAMPLES),
    ("scm.md", "구매·영업·물류", spec_scm.EXAMPLES),
    ("hr.md", "인사·총무", spec_hr.EXAMPLES),
    ("ops.md", "운영·법무·IT·고객", spec_ops.EXAMPLES),
    ("feature-examples.md", "기능 예제", spec_fx.EXAMPLES),
]

BANNER = "<!-- 이 파일은 _source/build.py가 만든다. 직접 고치지 말고 _source/spec_*.py를 고친 뒤 다시 만든다. -->"


def cross_check(examples: list[Example]) -> list[str]:
    errs = []
    files = {e.file for e in examples}
    ids = [e.id for e in examples]
    if len(ids) != len(set(ids)):
        errs.append("예제 id 중복")
    dmn = set()
    for e in examples:
        for d in e.decisions:
            if d.id in dmn:
                errs.append(f"{e.id}: DMN id {d.id} 중복")
            dmn.add(d.id)
    for e in examples:
        for n in all_nodes(e.nodes):
            if n.kind == "call":
                tgt = n.props["called"].removeprefix("Proc_")
                if tgt not in files:
                    errs.append(f"{e.id}: 호출 대상 {tgt} 없음")
                if tgt not in e.called:
                    errs.append(f"{e.id}: called 목록에 {tgt} 없음")
            if n.kind == "rule":
                if not any(d.id == n.props["task"]["decision"] for d in e.decisions) and n.props["task"]["decision"] not in dmn:
                    errs.append(f"{e.id}: DMN {n.props['task']['decision']} 없음")
        errs += deep_check(e, {x.file: x for x in examples}, {d.id: d for x in examples for d in x.decisions})
        if e.run_location not in ("server", "pc"):
            errs.append(f"{e.id}: run_location")
        if not e.cases:
            errs.append(f"{e.id}: 케이스 없음")
    return errs


def deep_check(e: Example, by_file: dict, dmns: dict) -> list[str]:
    """C14 검사 중 정의만 보고 할 수 있는 것 (B3 짝, B11 일부, B12, 케이스·호출·DMN 대조)."""
    from exdsl import defined_vars

    errs = []
    ns = list(all_nodes(e.nodes))
    by_id = {n.id: n for n in ns}
    declared = {i[0] for i in e.inputs}
    defaults = {i[0] for i in e.inputs if len(i) > 4}
    # 타이머 시작인데 필수 입력이 있으면 채울 사람이 없다
    if any(n.kind == "start" and n.props.get("kind") == "timer" for n in e.nodes):
        for i in e.inputs:
            if i[2]:
                errs.append(f"{e.id}: 타이머 시작인데 필수 입력 `{i[0]}`")
    # 규칙 ↔ DMN
    for n in ns:
        if n.kind == "rule":
            t = n.props["task"]
            d = dmns.get(t["decision"])
            if not d:
                continue
            ins = {x[1] for x in d.inputs}
            if set(t["input"]) != ins:
                errs.append(f"{e.id}: {n.id} 입력 {sorted(t['input'])} ≠ DMN 입력 {sorted(ins)}")
            outs = {x[0] for x in d.outputs}
            bad = [v for v in t["output"].values() if v not in outs]
            if bad:
                errs.append(f"{e.id}: {n.id} 출력 {bad}가 DMN 출력 {sorted(outs)}에 없음")
    # 호출 ↔ 대상
    calls = [n for n in ns if n.kind == "call"]
    if sorted({n.props["called"].removeprefix("Proc_") for n in calls}) != sorted(set(e.called)):
        errs.append(f"{e.id}: called 목록과 호출 노드가 다름")
    for n in calls:
        tgt = by_file.get(n.props["called"].removeprefix("Proc_"))
        if not tgt:
            continue
        t = n.props["task"]
        tin = {i[0] for i in tgt.inputs}
        if set(t["input"]) - tin:
            errs.append(f"{e.id}: {n.id} 입력 {sorted(set(t['input']) - tin)}가 {tgt.id} 입력에 없음")
        need = {i[0] for i in tgt.inputs if i[2]} - set(t["input"])
        if need:
            errs.append(f"{e.id}: {n.id}가 {tgt.id}의 필수 입력 {sorted(need)}를 넘기지 않음")
        bad = [v for v in t["output"].values() if v not in tgt.outputs]
        if bad:
            errs.append(f"{e.id}: {n.id} 출력 {bad}가 {tgt.id} outputs에 없음")
    # 병렬 짝, 포함 짝 (범위마다)
    def scope(nodes, flows, where):
        pg = [n for n in nodes if n.kind == "pgw"]
        splits = [n for n in pg if sum(f.src == n.id for f in flows) > 1]
        joins = [n for n in pg if sum(f.dst == n.id for f in flows) > 1]
        if len(splits) == 1 and len(joins) == 1:
            a = sum(f.src == splits[0].id for f in flows)
            b = sum(f.dst == joins[0].id for f in flows)
            if a != b:
                errs.append(f"{e.id}/{where}: 병렬 분기 {a}갈래인데 합류는 {b}개를 기다림")
        ig = [n for n in nodes if n.kind == "igw"]
        if any(sum(f.src == n.id for f in flows) > 1 for n in ig) and not any(sum(f.dst == n.id for f in flows) > 1 for n in ig):
            errs.append(f"{e.id}/{where}: 포함 분기를 포함 합류로 닫지 않음 (B3)")
        for n in nodes:
            if n.kind == "sub":
                scope(n.children, n.flows, n.id)
    scope(e.nodes, e.flows, "main")
    # 케이스
    msgs = {n.props["message"] for n in ns if n.kind == "recv"} | {n.props.get("message") for n in ns if n.kind in ("catch", "start")}
    msgs |= {b.props.get("message") for b in e.boundaries} | {b.props.get("message") for n in ns for b in n.boundaries}
    dv = defined_vars(e)
    for c in e.cases:
        extra = set(c.inputs) - declared
        if extra:
            errs.append(f"{e.id}: 케이스 「{c.name}」 입력 {sorted(extra)}가 선언되지 않음")
        missing = {i[0] for i in e.inputs if i[2]} - set(c.inputs)
        if missing:
            errs.append(f"{e.id}: 케이스 「{c.name}」에 필수 입력 {sorted(missing)} 없음")
        for k in c.expected:
            if k not in dv:
                errs.append(f"{e.id}: 케이스 「{c.name}」 기대 변수 `{k}`를 만드는 곳이 없음")
        for nid, ans in c.approvals.items():
            node = by_id.get(nid)
            if not node or node.kind not in ("appr", "manual"):
                continue
            fields = {f["key"]: f for f in node.props["task"]["fields"]}
            for k, v in ans.items():
                f = fields.get(k)
                if not f:
                    errs.append(f"{e.id}: 케이스 「{c.name}」 {nid}에 칸 `{k}` 없음")
                    continue
                ok = {"bool": isinstance(v, bool), "number": isinstance(v, (int, float)) and not isinstance(v, bool),
                      "text": isinstance(v, str), "choice": v in f.get("choices", [])}[f["type"]]
                if not ok:
                    errs.append(f"{e.id}: 케이스 「{c.name}」 {nid}.{k} 값 {v!r}가 {f['type']}에 맞지 않음")
            req = {k for k, f in fields.items() if f["required"]} - set(ans)
            if req and not c.manual:
                errs.append(f"{e.id}: 케이스 「{c.name}」 {nid} 필수 칸 {sorted(req)} 응답 없음")
        for m in c.messages:
            if m["name"] not in msgs:
                errs.append(f"{e.id}: 케이스 「{c.name}」 메시지 {m['name']}를 받는 곳이 없음")
    return errs


def outputs() -> dict[Path, str]:
    out: dict[Path, str] = {}
    for fname, title, exs in GROUPS:
        cards = [BANNER, "", f"# {title} 예제", "",
                 "[← 예제 목록](README.md) · 작성 규칙: [writing-guide.md](writing-guide.md)", "",
                 "| id | 이름 | 실행 위치 | 시작 |", "| --- | --- | --- | --- |"]
        for e in exs:
            cards.append(f"| [{e.id}](#{slug(e)}) | {e.name} | {'서버' if e.run_location == 'server' else 'PC'} | {e.trigger.split(' — ')[0]} |")
        cards.append("")
        for e in exs:
            bp = f"bpmn/{e.file}.bpmn"
            cs = f"cases/{e.file}.cases.json"
            out[ROOT / bp] = to_bpmn(e)
            out[ROOT / cs] = to_cases(e)
            for d in e.decisions:
                out[ROOT / f"bpmn/{d.id}.dmn"] = to_dmn(d)
            cards += ["---", "", to_card(e, bp, cs)]
        out[ROOT / fname] = "\n".join(cards).rstrip() + "\n"
    out[ROOT / "README.md"] = readme([e for _, _, exs in GROUPS for e in exs])
    return out


def coverage(examples: list[Example]) -> list[str]:
    import re
    from exdsl import KIND_LABEL

    def ids(pred):
        return ", ".join(e.id for e in examples if pred(e)) or "**없음**"

    def nodes(e):
        return list(all_nodes(e.nodes))

    def bnds(e):
        out = list(e.boundaries)
        for n in nodes(e):
            out += n.boundaries
        return out

    def has(nkind, **kw):
        def p(e):
            for n in (e.nodes if nkind in ("start", "end") else nodes(e)):
                if n.kind == nkind and all(n.props.get(k) == v for k, v in kw.items()):
                    return True
            return False
        return p

    def ai_domain(d):
        return lambda e: any(n.kind == "ai" and n.props["task"]["domain"] == d for n in nodes(e))

    def loop(par):
        return lambda e: any(n.props.get("loop") and bool(n.props["loop"].get("parallel")) == par for n in nodes(e))

    def bnd(kind, inter=None):
        return lambda e: any(b.kind == kind and (inter is None or b.interrupting == inter) for b in bnds(e))

    def appr_loc(loc):
        return lambda e: any(n.kind in ("appr", "manual") and n.props["task"]["location"] == loc for n in nodes(e))

    def ext(pred):
        return lambda e: any(pred(x["id"]) for x in e.extensions)

    bpmn_rows = [
        ("시작 — 없음(작업 지시·호출)", has("start", kind="none")), ("시작 — 타이머", has("start", kind="timer")),
        ("시작 — 메시지", has("start", kind="message")),
        ("끝 — 종료(terminate)", has("end", kind="terminate")),
        ("스크립트", has("script")), ("AI 태스크 — llm", ai_domain("llm")), ("AI 태스크 — api", ai_domain("api")),
        ("AI 태스크 — doc", ai_domain("doc")), ("AI 태스크 — web", ai_domain("web")), ("AI 태스크 — desktop", ai_domain("desktop")),
        ("UI 태스크 (UI 자동화 확장)", has("ui")), ("서비스 앱 태스크", has("svc")), ("규칙 (DMN)", has("rule")),
        ("결재 (userTask)", has("appr")), ("수동 확인 (manualTask)", has("manual")),
        ("메일 보내기", has("mail")), ("웹훅 보내기", has("hook")), ("메시지 받기 (receiveTask)", has("recv")),
        ("BPM 프로세스 호출", has("call")), ("하위 프로세스", has("sub")),
        ("배타 게이트웨이", has("xgw")), ("포함 게이트웨이", has("igw")), ("병렬 게이트웨이", has("pgw")),
        ("중간 던지기 — 이정표(없음)", has("throw", kind="none")), ("중간 던지기·받기 — 신호", lambda e: has("throw", kind="signal")(e) or has("catch", kind="signal")(e)),
        ("중간 받기 — 타이머", has("catch", kind="timer")),
        ("반복 — 차례", loop(False)), ("반복 — 병렬", loop(True)),
        ("경계 — 타이머 중단", bnd("timer", True)), ("경계 — 타이머 비중단", bnd("timer", False)),
        ("경계 — 오류", bnd("error")), ("경계 — 메시지", bnd("message")), ("경계 — 신호", bnd("signal")),
        ("파일 출력 — md", lambda e: any(d.props["format"] == "md" for d in e.data)),
        ("파일 출력 — xlsx", lambda e: any(d.props["format"] == "xlsx" for d in e.data)),
        ("파일 출력 — json", lambda e: any(d.props["format"] == "json" for d in e.data)),
    ]
    plat_rows = [
        ("실행 위치 서버", lambda e: e.run_location == "server"), ("실행 위치 PC", lambda e: e.run_location == "pc"),
        ("결재 위치 Center 결재함", appr_loc("center")), ("결재 위치 현장(PC)", appr_loc("field")),
        ("UI 자동화 확장 (내장)", ext(lambda i: i == "ui-automation")),
        ("외부 확장 (HTTP 어댑터)", ext(lambda i: i.startswith("ext-"))),
        ("사내 확장 서비스 앱", ext(lambda i: i not in ("ui-automation",) and not i.startswith("ext-"))),
        ("태스크 단위 키 참조", lambda e: any(n.kind == "svc" and n.props["task"].get("key_ref") for n in nodes(e))),
        ("한 프로세스에 키 참조 여러 개", lambda e: len(e.service_keys) > 1),
        ("프로세스 기본값 (금지 행동·확인 트리거)", lambda e: bool(e.defaults.get("forbidden_actions") or e.defaults.get("confirm_triggers"))),
        ("업무 파라미터", lambda e: any(n.kind == "ai" and n.props["task"]["params"] for n in nodes(e))),
        ("다른 예제를 호출 (공유 BPM 프로세스)", lambda e: bool(e.called)),
        ("수동 케이스 (사람이 폼 확인)", lambda e: any(c.manual for c in e.cases)),
        ("DMN 적중 정책 COLLECT", lambda e: any(d.hit == "COLLECT" for d in e.decisions)),
    ]
    L = ["## BPMN 요소 커버리지", "", "| 요소 | 예제 |", "| --- | --- |"]
    L += [f"| {a} | {ids(p)} |" for a, p in bpmn_rows]
    L += ["", "**없음**인 요소는 C14 schema 1에서 쓰지 않거나(조건 시작) 아직 예제가 없는 것이다.", "",
          "## 플랫폼 기능 커버리지", "", "| 기능 | 예제 |", "| --- | --- |"]
    L += [f"| {a} | {ids(p)} |" for a, p in plat_rows]
    L += ["", "## 마일스톤별 인수 시험 묶음", "",
          "예제가 쓰는 기능으로 자동으로 정한다: 기본 M3(Studio 시험 실행), UI 태스크·데스크톱 → M4, 서비스 앱·확장 → M5. "
          "처음 통과한 뒤에는 회귀로 계속 돈다. M5에서 PC 예제는 Center 배포 → Bot UI 실행으로, M7에서 서버 예제는 서버 실행기에서 다시 통과해야 한다.", "",
          "| 마일스톤 | 처음 통과해야 하는 예제 | 다시 통과 |", "| --- | --- | --- |"]
    by = {}
    for e in examples:
        by.setdefault(first_milestone(e), []).append(e.id)
    again = {"M5": "PC 예제: Center 배포 → Bot UI", "M7": "서버 예제 전부: 서버 실행기"}
    for k in ("M3", "M4", "M5", "M7"):
        L.append(f"| {k} | {', '.join(by.get(k, [])) or '—'} | {again.get(k, '')} |")
    return L


def first_milestone(e: Example) -> str:
    ns = list(all_nodes(e.nodes))
    if any(n.kind == "svc" for n in ns) or e.extensions and any(x["id"] != "ui-automation" for x in e.extensions):
        return "M5"
    if any(n.kind == "ui" or (n.kind == "ai" and n.props["task"]["domain"] in ("web", "desktop")) for n in ns):
        return "M4"
    return "M3"


def set_milestone(e: Example) -> None:
    m = first_milestone(e)
    tail = "M5 Center 배포 → M7 서버 실행기" if e.run_location == "server" else "M5 Center 배포 → Bot UI 실행"
    e.milestone = f"**{m}** Studio 시험 실행에서 처음 통과 → {tail}"


def readme(examples: list[Example]) -> str:
    L = [BANNER, "", (HERE / "readme_intro.txt").read_text(encoding="utf-8").rstrip(), "", "## 목록", ""]
    for fname, title, exs in GROUPS:
        L += [f"### {title} ([{fname}]({fname}))", "", "| id | 이름 | 실행 위치 | 시작 | 확장 | 이 예제로 확인하는 것 |", "| --- | --- | --- | --- | --- | --- |"]
        for e in exs:
            L.append(f"| [{e.id}]({fname}#{slug(e)}) | {e.name} | {'서버' if e.run_location == 'server' else 'PC'} | {e.trigger.split(' — ')[0]} | "
                     f"{', '.join(x['id'] for x in e.extensions) or '—'} | {'; '.join(e.features[:3])} |")
        L.append("")
    L += coverage(examples)
    return "\n".join(L).rstrip() + "\n"


def slug(e: Example) -> str:
    """GitHub 앵커 규칙 근사: 소문자, 공백→-, 구두점 제거."""
    import re
    s = f"{e.id}. {e.name}".lower()
    s = re.sub(r"[^\w\- ]", "", s)
    return s.replace(" ", "-")


def main() -> int:
    check = "--check" in sys.argv
    examples = [e for _, _, exs in GROUPS for e in exs]
    for e in examples:
        set_milestone(e)
    errs = []
    for e in examples:
        errs += [f"{e.id}: {m}" for m in validate(e)]
        errs += [f"{e.id}: {m} (B11)" for m in var_warnings(e)]
    errs += cross_check(examples)
    if errs:
        print("검사 실패:")
        for m in errs:
            print("  -", m)
        return 1
    out = outputs()
    for p, text in out.items():
        if p.suffix in (".bpmn", ".dmn"):
            ET.fromstring(text.encode("utf-8"))
    gen = {p for d in ("bpmn", "cases") for p in (ROOT / d).glob("*") if p.is_file()}
    orphans = sorted(gen - set(out))
    if check:
        stale = [p for p, t in out.items() if not p.exists() or p.read_text(encoding="utf-8") != t] + orphans
        for p in stale:
            print("다름:", p.relative_to(ROOT))
        return 1 if stale else 0
    for p in orphans:
        p.unlink()
        print("지움:", p.relative_to(ROOT))
    for p, text in out.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
    n_b = sum(1 for p in out if p.suffix == ".bpmn")
    n_d = sum(1 for p in out if p.suffix == ".dmn")
    print(f"예제 {len(examples)}개 → BPMN {n_b}, DMN {n_d}, 케이스 {n_b}, 카드 파일 {len(GROUPS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
