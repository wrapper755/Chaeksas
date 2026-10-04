"""예제 정의용 작은 DSL과 생성기.

예제 하나(정의) → BPMN(배치 포함, C14 형식) + 문서 카드(Markdown) + 시험 케이스(JSON) + DMN.
실행: `uv run python docs/08-business-examples/_source/build.py` (또는 `python build.py`).
표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from xml.sax.saxutils import escape

NS_CHK = "urn:chaeksas:bpmn:1"


# ───────────────────────── 노드 ─────────────────────────


@dataclass
class Node:
    id: str
    kind: str  # start end script ai ui svc appr manual rule mail hook recv call xgw igw pgw sub throw catch
    name: str = ""
    props: dict[str, Any] = field(default_factory=dict)
    children: list["Node"] = field(default_factory=list)  # sub
    flows: list["Flow"] = field(default_factory=list)  # sub
    boundaries: list["Boundary"] = field(default_factory=list)  # sub 안의 경계


@dataclass
class Flow:
    src: str
    dst: str
    cond: str | None = None
    name: str = ""
    default: bool = False
    id: str = ""


@dataclass
class Boundary:
    id: str
    attached: str
    kind: str  # timer error signal message
    name: str = ""
    interrupting: bool = True
    props: dict[str, Any] = field(default_factory=dict)


@dataclass
class DataOut:
    id: str
    name: str
    writer: str  # 이 태스크가 끝날 때 쓴다
    props: dict[str, Any] = field(default_factory=dict)


@dataclass
class Decision:
    id: str
    name: str
    inputs: list[tuple[str, str, str]]  # (label, expr, typeRef)
    outputs: list[tuple[str, str]]  # (name, typeRef)
    rules: list[tuple[list[str], list[str], str]]  # (input entries, output entries, 설명)
    hit: str = "FIRST"


@dataclass
class Case:
    name: str
    inputs: dict[str, Any]
    expected: dict[str, Any]
    approvals: dict[str, dict[str, Any]] = field(default_factory=dict)
    description: str = ""
    manual: bool = False
    messages: list[dict[str, Any]] = field(default_factory=list)  # [{after_s, name, correlation?, payload}]


@dataclass
class Example:
    id: str  # BX-01 / FX-01
    file: str  # 파일 이름(영문)
    name: str
    dept: str
    origin: str
    run_location: str  # server | pc
    trigger: str
    background: str
    why_location: str
    nodes: list[Node]
    flows: list[Flow]
    boundaries: list[Boundary] = field(default_factory=list)
    data: list[DataOut] = field(default_factory=list)
    variables: list[tuple[str, str, str, str]] = field(default_factory=list)  # 이름, 타입, 출처, 뜻
    inputs: list[tuple[str, str, bool, str]] = field(default_factory=list)  # 이름, 타입, 필수, 뜻
    service_keys: dict[str, str] = field(default_factory=dict)
    extensions: list[dict[str, str]] = field(default_factory=list)
    defaults: dict[str, Any] = field(default_factory=dict)
    decisions: list[Decision] = field(default_factory=list)
    cases: list[Case] = field(default_factory=list)
    features: list[str] = field(default_factory=list)
    lessons: list[str] = field(default_factory=list)
    samples: str = ""
    kind: str = "business"  # business | feature
    called: list[str] = field(default_factory=list)  # 호출하는 다른 예제 file
    milestone: str = ""  # build.py가 쓰는 기능으로 정한다
    outputs: list[str] = field(default_factory=list)  # chk:process.outputs (호출 대상이면 필수)


# ───────── 만들기 도우미 ─────────

def start(id, name="시작", kind="none", **p):
    return Node(id, "start", name, dict(kind=kind, **p))


def end(id, name="끝", kind="none", **p):
    return Node(id, "end", name, dict(kind=kind, **p))


def script(id, name, code):
    return Node(id, "script", name, dict(code=code))


def ai(id, name, goal, domain, results, tools=None, params=None, loop=None, **p):
    d = dict(goal=goal, domain=domain, results=results, tools=tools or [], params=params or {})
    d.update(p)
    return Node(id, "ai", name, dict(task=d, loop=loop))


def ui(id, name, page_id, steps, loop=None, **p):
    d = dict(page_id=page_id, steps=steps, heal=True)
    d.update(p)
    return Node(id, "ui", name, dict(task=d, loop=loop))


def svc(id, name, app_id, operation, input, output, loop=None, **p):
    d = dict(app_id=app_id, operation=operation, input=input, output=output)
    d.update(p)
    return Node(id, "svc", name, dict(task=d, loop=loop))


def appr(id, name, title, show, fields, location="follow", description="", manual=False, **p):
    d = dict(title=title, description=description, show=show, fields=fields, location=location)
    d.update(p)
    return Node(id, "manual" if manual else "appr", name, dict(task=d))


def fld(key, label, type="text", required=False, choices=None, default=None):
    f = dict(key=key, label=label, type=type, required=required)
    if choices:
        f["choices"] = choices
    if default is not None:
        f["default"] = default
    return f


def rule(id, name, decision, input, output, loop=None):
    return Node(id, "rule", name, dict(task=dict(decision=decision, input=input, output=output), loop=loop))


def flist(id, name, folder, store_as, pattern="*", recursive=False, sort="name", limit=None, count_as=None):
    """파일 목록 태스크 (`chk:fileList`). 디스크를 읽으므로 식이 아니라 태스크다 (ADR-0026)."""
    return Node(id, "flist", name, dict(task=dict(
        folder=folder, pattern=pattern, recursive=recursive, sort=sort,
        **({"limit": limit} if limit is not None else {}),
        store_as=store_as, **({"count_as": count_as} if count_as else {}))))


def mail(id, name, to, subject, body, attachments=None, store_as=None):
    return Node(id, "mail", name, dict(task=dict(to=to, subject=subject, body=body,
                                                  attachments=attachments or [], store_as=store_as)))


def hook(id, name, url, body="all", method="POST", store_as=None, timeout_s=10):
    return Node(id, "hook", name, dict(task=dict(url=url, method=method, body=body,
                                                  timeout_s=timeout_s, store_as=store_as)))


def recv(id, name, message, correlation, payload=None):
    return Node(id, "recv", name, dict(message=message, correlation=correlation, payload=payload or []))


def call(id, name, called, input, output):
    return Node(id, "call", name, dict(called=called, task=dict(input=input, output=output)))


def xgw(id, name="", default=None):
    return Node(id, "xgw", name, dict(default=default))


def igw(id, name="", default=None):
    return Node(id, "igw", name, dict(default=default))


def pgw(id, name=""):
    return Node(id, "pgw", name)


def sub(id, name, children, flows, boundaries=None):
    return Node(id, "sub", name, {}, children, flows, boundaries or [])


def throw(id, name, kind="none", ref=None):
    return Node(id, "throw", name, dict(kind=kind, ref=ref))


def catch(id, name, kind, **p):
    return Node(id, "catch", name, dict(kind=kind, **p))


def f(src, dst, cond=None, name="", default=False):
    return Flow(src, dst, cond, name, default)


def bnd(id, attached, kind, name="", interrupting=True, **p):
    return Boundary(id, attached, kind, name, interrupting, p)


def out(id, name, writer, path, format="md", template=None, variables=None, store_as=None, **p):
    d = dict(path=path, format=format, store_as=store_as)
    if template is not None:
        d["template"] = template
    if variables is not None:
        d["variables"] = variables
    d.update(p)
    return DataOut(id, name, writer, d)


def goal(상황, 할일, 판단하지않음=None, 반환=None):
    s = f"## 상황\n{상황}\n\n## 할 일\n{할일}"
    if 판단하지않음:
        s += f"\n\n## 판단하지 않는 것\n{판단하지않음}"
    if 반환:
        s += f"\n\n## 반환\n{반환}"
    return s


# ───────────────────────── 검사 ─────────────────────────

KIND_LABEL = {
    "start": "시작 이벤트", "end": "끝 이벤트", "script": "스크립트", "ai": "AI 태스크",
    "ui": "UI 태스크", "svc": "서비스 앱 태스크", "appr": "결재", "manual": "수동 확인",
    "rule": "규칙(DMN)", "flist": "파일 목록", "mail": "메일 보내기", "hook": "웹훅 보내기", "recv": "메시지 받기",
    "call": "BPM 프로세스 호출", "xgw": "배타 게이트웨이", "igw": "포함 게이트웨이",
    "pgw": "병렬 게이트웨이", "sub": "하위 프로세스", "throw": "중간 던지기", "catch": "중간 받기",
}


def all_nodes(nodes):
    for n in nodes:
        yield n
        if n.kind == "sub":
            yield from all_nodes(n.children)


def validate(ex: Example) -> list[str]:
    errs = []
    ids = [n.id for n in all_nodes(ex.nodes)] + [b.id for b in ex.boundaries]
    for n in all_nodes(ex.nodes):
        ids += [b.id for b in n.boundaries]
    ids += [d.id for d in ex.data]
    if len(ids) != len(set(ids)):
        dup = {i for i in ids if ids.count(i) > 1}
        errs.append(f"중복 id {dup}")

    def chk_scope(nodes, flows, bnds, where):
        nid = {n.id for n in nodes} | {b.id for b in bnds}
        for fl in flows:
            if fl.src not in nid or fl.dst not in nid:
                errs.append(f"{where}: 흐름 {fl.src}->{fl.dst} 끝점 없음")
        for n in nodes:
            ins = [x for x in flows if x.dst == n.id]
            outs = [x for x in flows if x.src == n.id]
            if n.kind != "start" and not ins:
                errs.append(f"{where}: {n.id} 들어오는 흐름 없음")
            if n.kind != "end" and not outs:
                errs.append(f"{where}: {n.id} 나가는 흐름 없음")
            if n.kind in ("xgw", "igw") and len(outs) > 1:
                no_cond = [x for x in outs if not x.cond]
                if any(not x.default for x in no_cond):
                    errs.append(f"{where}: {n.id} 조건 없는 흐름이 default가 아님")
            if n.kind == "sub":
                chk_scope(n.children, n.flows, n.boundaries, n.id)
            if n.kind in ("ai", "ui", "svc", "rule") and n.props.get("loop") and "collect_into" not in n.props["loop"]:
                errs.append(f"{n.id} 반복에 collect_into 없음")
            if n.kind in ("appr", "manual"):
                for fd in n.props["task"]["fields"]:
                    if fd["type"] not in ("bool", "number", "text", "choice"):
                        errs.append(f"{n.id} 결재 칸 타입 {fd['type']} (C6)")
                    if fd["type"] == "choice" and not fd.get("choices"):
                        errs.append(f"{n.id} choice 칸에 choices 없음")
                if not isinstance(n.props["task"]["show"], list):
                    errs.append(f"{n.id} show가 배열이 아님")
                if ex.run_location == "server" and n.props["task"]["location"] == "field":
                    errs.append(f"{n.id} 서버인데 현장 결재")
            if ex.run_location == "server" and n.kind == "ui":
                errs.append(f"{n.id} 서버 BPM 프로세스에 UI 태스크")
            if ex.run_location == "server" and n.kind == "ai" and n.props["task"]["domain"] in ("web", "desktop"):
                errs.append(f"{n.id} 서버 BPM 프로세스에 web/desktop AI 태스크")
            if n.kind == "ui":
                for st in n.props["task"]["steps"]:
                    if st["action"] not in ("fill", "click", "press", "select", "read", "read_table", "read_options", "read_selection"):
                        errs.append(f"{n.id} UI 동작 {st['action']} (C10에 없음)")
                    if "$secret" in str(st.get("value", "")):
                        errs.append(f"{n.id} UI 스텝 값에 비밀 참조")
            if n.kind == "ai":
                for t in n.props["task"]["results"].values():
                    if t not in ("string", "int", "number", "bool", "list", "dict", "date"):
                        errs.append(f"{n.id} 결과 타입 {t} (C14 B8)")
            if n.kind == "svc":
                app = n.props["task"]["app_id"]
                if app not in ex.service_keys and not n.props["task"].get("key_ref"):
                    errs.append(f"{n.id} 서비스 앱 {app} 키 참조 없음")
        kinds = {n.id: n.kind for n in nodes}
        for b in bnds:
            if kinds.get(b.attached) in ("start", "end", "throw", "catch", "xgw", "igw", "pgw", None):
                errs.append(f"{where}: 경계 {b.id}가 태스크가 아닌 {b.attached}에 붙음")
            if not any(x.src == b.id for x in flows):
                errs.append(f"{where}: 경계 {b.id} 나가는 흐름 없음")

    chk_scope(ex.nodes, ex.flows, ex.boundaries, ex.id)
    for d in ex.data:
        if not d.props.get("store_as"):
            errs.append(f"{d.id} store_as 없음")
        if "template" not in d.props and "variables" not in d.props:
            errs.append(f"{d.id} template/variables 없음")
    node_ids = {n.id for n in all_nodes(ex.nodes)}
    for c in ex.cases:
        for k in c.approvals:
            if k not in node_ids:
                errs.append(f"케이스 {c.name}: 결재 노드 {k} 없음")
    return errs


# ───────────────────────── 배치 ─────────────────────────

SIZE = {"task": (100, 80), "event": (36, 36), "gw": (50, 50)}


def shape_kind(n: Node):
    if n.kind in ("start", "end", "throw", "catch"):
        return "event"
    if n.kind in ("xgw", "igw", "pgw"):
        return "gw"
    return "task"


def back_edges(nodes, flows, bnds):
    """DFS로 되돌아가는 흐름(루프백)을 찾는다. 배치에서 순위 계산에 쓰지 않는다."""
    by_id = {n.id for n in nodes} | {b.id for b in bnds}
    succ: dict[str, list[Flow]] = {}
    for fl in flows:
        succ.setdefault(fl.src, []).append(fl)
    for b in bnds:  # 경계는 붙은 노드의 자식처럼
        succ.setdefault(b.attached, [])
    att = {}
    for b in bnds:
        att.setdefault(b.attached, []).append(b.id)
    color: dict[str, int] = {}
    back = set()

    def dfs(u):
        color[u] = 1
        nxt = [fl.dst for fl in succ.get(u, [])] + att.get(u, [])
        for fl in succ.get(u, []):
            v = fl.dst
            if color.get(v) == 1:
                back.add(id(fl))
            elif v not in color and v in by_id:
                dfs(v)
        for v in att.get(u, []):
            if v not in color:
                dfs(v)
        color[u] = 2

    roots = [n.id for n in nodes if n.kind == "start"] + [n.id for n in nodes]
    for r in roots:
        if r not in color:
            dfs(r)
    return back


def layout(nodes, flows, bnds, x0, y0):
    """간단한 계층 배치: 순위(가장 긴 경로, 루프백 제외) → 열, 같은 순위에서 줄.

    게이트웨이의 기본 흐름(없으면 첫 흐름)은 같은 줄에, 나머지 가지는 아래 줄에 둔다.
    """
    pos = {}
    by_id = {n.id: n for n in nodes}
    b_by_id = {b.id: b for b in bnds}
    back = back_edges(nodes, flows, bnds)
    fwd = [fl for fl in flows if id(fl) not in back]
    succ: dict[str, list[str]] = {}
    for fl in fwd:
        succ.setdefault(fl.src, []).append(fl.dst)
    rank: dict[str, int] = {}
    order: list[str] = []
    from collections import deque

    indeg = {n.id: 0 for n in nodes}
    for fl in fwd:
        if fl.dst in indeg and (fl.src in by_id or fl.src in b_by_id):
            indeg[fl.dst] += 1
    q = deque(n.id for n in nodes if indeg[n.id] == 0)
    for s0 in q:
        rank[s0] = 0
    remaining = dict(indeg)
    processed = set()
    while q:
        u = q.popleft()
        if u in processed:
            continue
        processed.add(u)
        order.append(u)
        srcs = [u] + [b.id for b in bnds if b.attached == u]
        for s_ in srcs:
            if s_ != u:
                rank[s_] = rank[u]
            for v in succ.get(s_, []):
                if v in by_id:
                    rank[v] = max(rank.get(v, 0), rank[u] + 1)
                    remaining[v] -= 1
                    if remaining[v] <= 0:
                        q.append(v)
    for n in nodes:
        if n.id not in processed:
            rank.setdefault(n.id, max(rank.values(), default=0) + 1)
            order.append(n.id)
    # 줄 배정
    row: dict[str, int] = {}
    used: dict[int, set[int]] = {}
    for u in order:
        r = rank[u]
        want = None
        for fl in fwd:
            if fl.dst != u:
                continue
            p = fl.src
            if p in b_by_id:
                cand = row.get(b_by_id[p].attached, 0) + 1
            elif p in row:
                cand = row[p]
                pn = by_id[p]
                if pn.kind in ("xgw", "igw", "pgw"):
                    outs = [x for x in fwd if x.src == p]
                    main = next((x for x in outs if x.default), outs[0])
                    if fl is not main:
                        cand = row[p] + 1 + [x for x in outs if x is not main].index(fl)
            else:
                continue
            want = cand if want is None else min(want, cand)
        want = want or 0
        taken = used.setdefault(r, set())
        avoid = set(taken)
        for fl in fwd:  # 경계에서 나온 가지는 붙은 태스크 열의 줄도 피한다 (흐름이 가로지르지 않게)
            if fl.dst == u and fl.src in b_by_id:
                ar = rank.get(b_by_id[fl.src].attached)
                for rr in range(ar, r):
                    avoid |= used.get(rr, set())
        while want in avoid:
            want += 1
        row[u] = want
        taken.add(want)
    # 열 너비·줄 높이 (하위 프로세스 크기 반영)
    sub_layout = {}
    for n in nodes:
        if n.kind == "sub":
            inner, w, h = layout(n.children, n.flows, n.boundaries, 0, 0)
            sub_layout[n.id] = (inner, w + 60, h + 60)
    col_w: dict[int, int] = {}
    row_h: dict[int, int] = {}
    for n in nodes:
        w, h = sub_layout[n.id][1:] if n.kind == "sub" else SIZE[shape_kind(n)]
        col_w[rank[n.id]] = max(col_w.get(rank[n.id], 0), w)
        row_h[row[n.id]] = max(row_h.get(row[n.id], 0), h)
    xs, x = {}, x0
    for r in range(0, max(col_w) + 1 if col_w else 0):
        xs[r] = x
        x += col_w.get(r, 100) + 70
    ys, y = {}, y0
    for rr in range(0, max(row_h) + 1 if row_h else 0):
        ys[rr] = y
        y += row_h.get(rr, 80) + 70
    for n in nodes:
        if n.kind == "sub":
            inner, w, h = sub_layout[n.id]
        else:
            w, h = SIZE[shape_kind(n)]
        cw = col_w[rank[n.id]]
        rh = row_h[row[n.id]]
        bx = xs[rank[n.id]] + (cw - w) // 2
        by = ys[row[n.id]] + (rh - h) // 2
        pos[n.id] = (bx, by, w, h)
        if n.kind == "sub":
            for k, (ix, iy, iw, ih) in inner.items():
                pos[k] = (bx + 30 + ix, by + 30 + iy, iw, ih)
    for b in bnds:
        ax, ay, aw, ah = pos[b.attached]
        k = sum(1 for bb in bnds if bb.attached == b.attached and bnds.index(bb) < bnds.index(b))
        pos[b.id] = (ax + aw - 40 - k * 45, ay + ah - 18, 36, 36)
    total_w = (x - x0 - 70) if col_w else 0
    total_h = (y - y0 - 70) if row_h else 0
    return pos, total_w, total_h


# ───────────────────────── BPMN 쓰기 ─────────────────────────

def jtext(d):
    return escape(json.dumps(d, ensure_ascii=False, indent=2))


def node_xml(n: Node, ex: Example, flows_all, data_by_writer, ind="    "):
    inc = [fl for fl in flows_all if fl.dst == n.id]
    outg = [fl for fl in flows_all if fl.src == n.id]
    io = "".join(f"{ind}  <bpmn:incoming>{fl.id}</bpmn:incoming>\n" for fl in inc)
    io += "".join(f"{ind}  <bpmn:outgoing>{fl.id}</bpmn:outgoing>\n" for fl in outg)
    nm = escape(n.name, {'"': "&quot;"})
    p = n.props
    ext = ""
    loop = ""

    def ext_el(tag, d, attrs=""):
        return f"{ind}  <bpmn:extensionElements>\n{ind}    <chk:{tag}{attrs}>{jtext(d)}</chk:{tag}>\n{ind}  </bpmn:extensionElements>\n"

    if p.get("loop"):
        lp = p["loop"]
        seq = "false" if lp.get("parallel") else "true"
        loop = f'{ind}  <bpmn:multiInstanceLoopCharacteristics isSequential="{seq}" />\n'
        lp2 = {k: v for k, v in lp.items() if k != "parallel"}
    dassoc = ""
    for d in data_by_writer.get(n.id, []):
        dassoc += f'{ind}  <bpmn:dataOutputAssociation id="DOA_{d.id}">\n{ind}    <bpmn:targetRef>{d.id}</bpmn:targetRef>\n{ind}  </bpmn:dataOutputAssociation>\n'

    k = n.kind
    if k == "start" or k == "end" or k == "throw" or k == "catch":
        tag = {"start": "startEvent", "end": "endEvent", "throw": "intermediateThrowEvent", "catch": "intermediateCatchEvent"}[k]
        ev = event_def({k: v for k, v in p.items() if k not in ("correlation", "payload")}, ex, ind + "  ")
        if p.get("correlation"):
            io = (f"{ind}  <bpmn:extensionElements>\n{ind}    <chk:receive>{jtext({'correlation': p['correlation'], 'payload': p.get('payload', [])})}</chk:receive>\n"
                  f"{ind}  </bpmn:extensionElements>\n") + io
        return f'{ind}<bpmn:{tag} id="{n.id}" name="{nm}">\n{io}{ev}{ind}</bpmn:{tag}>\n'
    if k in ("xgw", "igw", "pgw"):
        tag = {"xgw": "exclusiveGateway", "igw": "inclusiveGateway", "pgw": "parallelGateway"}[k]
        dflt = ""
        dfl = [fl for fl in outg if fl.default]
        if dfl:
            dflt = f' default="{dfl[0].id}"'
        return f'{ind}<bpmn:{tag} id="{n.id}" name="{nm}"{dflt}>\n{io}{ind}</bpmn:{tag}>\n'
    if k == "script":
        code = escape(p["code"])
        return (f'{ind}<bpmn:scriptTask id="{n.id}" name="{nm}" scriptFormat="chk-expr">\n{io}{dassoc}'
                f'{ind}  <bpmn:script>{code}</bpmn:script>\n{ind}</bpmn:scriptTask>\n')
    if k in ("ai", "ui", "svc"):
        t = dict(p["task"])
        if k == "ai":
            body = ext_el("aiTask", t)
        elif k == "ui":
            body = ext_el("task", t, ' type="ui_task" extension="ui-automation"')
        else:
            body = ext_el("serviceCall", t)
        if p.get("loop"):
            body = body.replace(f"{ind}  </bpmn:extensionElements>\n",
                                f"{ind}    <chk:loop>{jtext(lp2)}</chk:loop>\n{ind}  </bpmn:extensionElements>\n")
        return f'{ind}<bpmn:serviceTask id="{n.id}" name="{nm}">\n{body}{io}{dassoc}{loop}{ind}</bpmn:serviceTask>\n'
    if k in ("appr", "manual"):
        tag = "userTask" if k == "appr" else "manualTask"
        return f'{ind}<bpmn:{tag} id="{n.id}" name="{nm}">\n{ext_el("approval", p["task"])}{io}{dassoc}{ind}</bpmn:{tag}>\n'
    if k == "rule":
        body = ext_el("rule", p["task"])
        if p.get("loop"):
            body = body.replace(f"{ind}  </bpmn:extensionElements>\n",
                                f"{ind}    <chk:loop>{jtext(lp2)}</chk:loop>\n{ind}  </bpmn:extensionElements>\n")
        return f'{ind}<bpmn:businessRuleTask id="{n.id}" name="{nm}">\n{body}{io}{dassoc}{loop}{ind}</bpmn:businessRuleTask>\n'
    if k == "flist":
        return f'{ind}<bpmn:serviceTask id="{n.id}" name="{nm}">\n{ext_el("fileList", p["task"])}{io}{dassoc}{ind}</bpmn:serviceTask>\n'
    if k in ("mail", "hook"):
        return f'{ind}<bpmn:sendTask id="{n.id}" name="{nm}">\n{ext_el("email" if k == "mail" else "webhook", p["task"])}{io}{dassoc}{ind}</bpmn:sendTask>\n'
    if k == "recv":
        mref = f"Msg_{p['message']}"
        return (f'{ind}<bpmn:receiveTask id="{n.id}" name="{nm}" messageRef="{mref}">\n'
                f'{ext_el("receive", {"correlation": p["correlation"], "payload": p["payload"]})}{io}{ind}</bpmn:receiveTask>\n')
    if k == "call":
        return (f'{ind}<bpmn:callActivity id="{n.id}" name="{nm}" calledElement="{p["called"]}">\n'
                f'{ext_el("call", p["task"])}{io}{dassoc}{ind}</bpmn:callActivity>\n')
    if k == "sub":
        inner = ""
        for c in n.children:
            inner += node_xml(c, ex, n.flows, data_by_writer, ind + "  ")
        for b in n.boundaries:
            inner += boundary_xml(b, ex, n.flows, ind + "  ")
        for fl in n.flows:
            inner += flow_xml(fl, ind + "  ")
        return f'{ind}<bpmn:subProcess id="{n.id}" name="{nm}">\n{io}{inner}{ind}</bpmn:subProcess>\n'
    raise ValueError(k)


def event_def(p, ex, ind):
    kind = p.get("kind", "none")
    if kind == "none":
        return ""
    if kind == "timer":
        if "cycle" in p:
            return f'{ind}<bpmn:timerEventDefinition>\n{ind}  <bpmn:timeCycle xsi:type="bpmn:tFormalExpression">{escape(p["cycle"])}</bpmn:timeCycle>\n{ind}</bpmn:timerEventDefinition>\n'
        return f'{ind}<bpmn:timerEventDefinition>\n{ind}  <bpmn:timeDuration xsi:type="bpmn:tFormalExpression">{escape(p["duration"])}</bpmn:timeDuration>\n{ind}</bpmn:timerEventDefinition>\n'
    if kind == "message":
        return f'{ind}<bpmn:messageEventDefinition messageRef="Msg_{p["message"]}" />\n'
    if kind == "signal":
        return f'{ind}<bpmn:signalEventDefinition signalRef="Sig_{p["signal"]}" />\n'
    if kind == "error":
        return f'{ind}<bpmn:errorEventDefinition errorRef="Err_{p["error"]}" />\n'
    if kind == "terminate":
        return f"{ind}<bpmn:terminateEventDefinition />\n"
    raise ValueError(kind)


def boundary_xml(b: Boundary, ex, flows, ind):
    outg = [fl for fl in flows if fl.src == b.id]
    io = "".join(f"{ind}  <bpmn:outgoing>{fl.id}</bpmn:outgoing>\n" for fl in outg)
    if b.props.get("correlation"):
        io = (f"{ind}  <bpmn:extensionElements>\n{ind}    <chk:receive>{jtext({'correlation': b.props['correlation']})}</chk:receive>\n"
              f"{ind}  </bpmn:extensionElements>\n") + io
    ci = "" if b.interrupting else ' cancelActivity="false"'
    ev = event_def(dict(kind=b.kind, **{k: v for k, v in b.props.items() if k != "correlation"}), ex, ind + "  ")
    nm = escape(b.name, {'"': "&quot;"})
    return f'{ind}<bpmn:boundaryEvent id="{b.id}" name="{nm}" attachedToRef="{b.attached}"{ci}>\n{io}{ev}{ind}</bpmn:boundaryEvent>\n'


def flow_xml(fl: Flow, ind):
    nm = f' name="{escape(fl.name, {chr(34): "&quot;"})}"' if fl.name else ""
    if fl.cond:
        return (f'{ind}<bpmn:sequenceFlow id="{fl.id}"{nm} sourceRef="{fl.src}" targetRef="{fl.dst}">\n'
                f'{ind}  <bpmn:conditionExpression xsi:type="bpmn:tFormalExpression">{escape(fl.cond)}</bpmn:conditionExpression>\n'
                f"{ind}</bpmn:sequenceFlow>\n")
    return f'{ind}<bpmn:sequenceFlow id="{fl.id}"{nm} sourceRef="{fl.src}" targetRef="{fl.dst}" />\n'


def name_flows(flows, prefix):
    for i, fl in enumerate(flows, 1):
        if not fl.id:
            fl.id = f"{prefix}{i:02d}"


def collect_refs(ex):
    msgs, sigs, errs = set(), set(), set()

    def visit(n_or_b):
        p = n_or_b.props
        kind = p.get("kind") if isinstance(n_or_b, Node) else n_or_b.kind
        if isinstance(n_or_b, Boundary):
            kind = n_or_b.kind
        if kind == "message" and "message" in p:
            msgs.add(p["message"])
        if kind == "signal" and "signal" in p:
            sigs.add(p["signal"])
        if kind == "error" and "error" in p:
            errs.add(p["error"])
        if isinstance(n_or_b, Node) and n_or_b.kind == "recv":
            msgs.add(p["message"])
        if isinstance(n_or_b, Node) and n_or_b.kind == "throw" and p.get("kind") == "signal":
            sigs.add(p["ref"])

    for n in all_nodes(ex.nodes):
        visit(n)
        for b in n.boundaries:
            visit(b)
    for b in ex.boundaries:
        visit(b)
    return msgs, sigs, errs


def to_bpmn(ex: Example) -> str:
    name_flows(ex.flows, "Flow_")
    for n in all_nodes(ex.nodes):
        if n.kind == "sub":
            name_flows(n.flows, f"Flow_{n.id}_")
    # throw signal: props ref → signal
    for n in all_nodes(ex.nodes):
        if n.kind == "throw" and n.props.get("kind") == "signal":
            n.props["signal"] = n.props["ref"]
    data_by_writer: dict[str, list[DataOut]] = {}
    for d in ex.data:
        data_by_writer.setdefault(d.writer, []).append(d)
    msgs, sigs, errs = collect_refs(ex)
    pid = "Proc_" + ex.file
    proc_meta = dict(run_location=ex.run_location, service_keys=ex.service_keys,
                     extensions=ex.extensions, outputs=ex.outputs,
                     inputs=[dict(name=i[0], type=i[1], required=i[2], description=i[3], **({'default': i[4]} if len(i) > 4 else {})) for i in ex.inputs])
    s = ['<?xml version="1.0" encoding="UTF-8"?>',
         '<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"',
         '  xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"',
         '  xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"',
         '  xmlns:di="http://www.omg.org/spec/DD/20100524/DI"',
         '  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"',
         f'  xmlns:chk="{NS_CHK}"',
         f'  id="Defs_{ex.file}" targetNamespace="urn:chaeksas:examples" exporter="chaeksas-examples" exporterVersion="1">']
    for m in sorted(msgs):
        s.append(f'  <bpmn:message id="Msg_{m}" name="{m}" />')
    for g in sorted(sigs):
        s.append(f'  <bpmn:signal id="Sig_{g}" name="{g}" />')
    for e in sorted(errs):
        s.append(f'  <bpmn:error id="Err_{e}" name="{e}" errorCode="{e}" />')
    s.append(f'  <bpmn:process id="{pid}" name="{escape(ex.name)}" isExecutable="true">')
    s.append("    <bpmn:extensionElements>")
    s.append(f"      <chk:process>{jtext(proc_meta)}</chk:process>")
    if ex.defaults:
        s.append(f"      <chk:defaults>{jtext(ex.defaults)}</chk:defaults>")
    s.append("    </bpmn:extensionElements>")
    body = ""
    for n in ex.nodes:
        body += node_xml(n, ex, ex.flows, data_by_writer)
    for b in ex.boundaries:
        body += boundary_xml(b, ex, ex.flows, "    ")
    for fl in ex.flows:
        body += flow_xml(fl, "    ")
    for d in ex.data:
        body += (f'    <bpmn:dataObject id="DO_{d.id}" />\n'
                 f'    <bpmn:dataObjectReference id="{d.id}" name="{escape(d.name)}" dataObjectRef="DO_{d.id}">\n'
                 f'      <bpmn:extensionElements>\n        <chk:dataOutput>{jtext(d.props)}</chk:dataOutput>\n      </bpmn:extensionElements>\n'
                 f"    </bpmn:dataObjectReference>\n")
    s.append(body.rstrip("\n"))
    s.append("  </bpmn:process>")
    # DI
    allb = list(ex.boundaries)
    pos, W, H = layout(ex.nodes, ex.flows, ex.boundaries, 160, 80)
    # 데이터 객체: 쓰는 태스크 위
    def overlaps(r):
        x, y, w, h = r
        return any(not (x + w + 10 < a or a + c + 10 < x or y + h + 10 < b or b + e + 10 < y) for a, b, c, e in pos.values())

    for d in ex.data:
        wx, wy, ww, wh = pos[d.writer]
        cand = [(wx + ww // 2 - 18, wy - 100, 36, 50), (wx + ww // 2 - 18, wy + wh + 50, 36, 50), (wx + ww + 10, wy - 100, 36, 50)]
        pos[d.id] = next((c for c in cand if not overlaps(c)), cand[0])
    # 데이터가 위로 나가면 전체를 아래로 밀기
    miny = min(v[1] for v in pos.values())
    if miny < 20:
        dy = 20 - miny
        pos = {k: (x, y + dy, w, h) for k, (x, y, w, h) in pos.items()}
    s.append('  <bpmndi:BPMNDiagram id="Diagram_1">')
    s.append(f'    <bpmndi:BPMNPlane id="Plane_1" bpmnElement="{pid}">')

    def shapes(nodes, bnds):
        out = []
        for n in nodes:
            x, y, w, h = pos[n.id]
            extra = ""
            if n.kind == "xgw":
                extra = ' isMarkerVisible="true"'
            if n.kind == "sub":
                extra = ' isExpanded="true"'
            lbl = ""
            if shape_kind(n) in ("event", "gw") and n.name:
                lbl = f'<bpmndi:BPMNLabel><dc:Bounds x="{x - 20}" y="{y + h + 4}" width="{w + 40}" height="27" /></bpmndi:BPMNLabel>'
            out.append(f'      <bpmndi:BPMNShape id="{n.id}_di" bpmnElement="{n.id}"{extra}><dc:Bounds x="{x}" y="{y}" width="{w}" height="{h}" />{lbl}</bpmndi:BPMNShape>')
            if n.kind == "sub":
                out += shapes(n.children, n.boundaries)
        for b in bnds:
            x, y, w, h = pos[b.id]
            lb = f'<bpmndi:BPMNLabel><dc:Bounds x="{x - 4}" y="{y + h + 2}" width="44" height="27" /></bpmndi:BPMNLabel>' if b.name else ""
            out.append(f'      <bpmndi:BPMNShape id="{b.id}_di" bpmnElement="{b.id}"><dc:Bounds x="{x}" y="{y}" width="{w}" height="{h}" />{lb}</bpmndi:BPMNShape>')
        return out

    s += shapes(ex.nodes, ex.boundaries)
    for d in ex.data:
        x, y, w, h = pos[d.id]
        s.append(f'      <bpmndi:BPMNShape id="{d.id}_di" bpmnElement="{d.id}"><dc:Bounds x="{x}" y="{y}" width="{w}" height="{h}" /><bpmndi:BPMNLabel><dc:Bounds x="{x + w + 6}" y="{y + 16}" width="{12 * len(d.name) + 10}" height="14" /></bpmndi:BPMNLabel></bpmndi:BPMNShape>')

    def blocked(x, y1, y2, skip):
        lo, hi = min(y1, y2), max(y1, y2)
        for k, (bx_, by_, bw_, bh_) in pos.items():
            if k in skip or k in sub_ids:
                continue
            if bx_ - 4 <= x <= bx_ + bw_ + 4 and by_ < hi and by_ + bh_ > lo:
                return True
        return False

    sub_ids = {n.id for n in all_nodes(ex.nodes) if n.kind == "sub"}
    bnd_att = {b.id: b.attached for b in ex.boundaries}
    for n in all_nodes(ex.nodes):
        bnd_att.update({b.id: b.attached for b in n.boundaries})

    def edges(flows, bnd_ids):
        out = []
        for fl in flows:
            sx, sy, sw, sh = pos[fl.src]
            tx, ty, tw, th = pos[fl.dst]
            if fl.src not in bnd_ids and tx + tw <= sx:
                # 루프백: 위로 돌아간다
                top = min(sy, ty) - 25
                pts = [(sx + sw // 2, sy), (sx + sw // 2, top), (tx + tw // 2, top), (tx + tw // 2, ty)]
            elif fl.src in bnd_ids:
                p1 = (sx + sw // 2, sy + sh)
                pts = [p1, (p1[0], ty + th // 2), (tx, ty + th // 2)]
                if ty + th // 2 > p1[1] and blocked(p1[0], p1[1] + 2, ty + th // 2, {fl.src, fl.dst}):
                    ax_, _, aw_, _ = pos[bnd_att[fl.src]]
                    gx = ax_ + aw_ + 25
                    pts = [p1, (p1[0], p1[1] + 12), (gx, p1[1] + 12), (gx, ty + th // 2), (tx, ty + th // 2)]
                if ty + th // 2 <= p1[1]:
                    pts = [p1, (p1[0], p1[1] + 20), (tx - 20, p1[1] + 20), (tx - 20, ty + th // 2), (tx, ty + th // 2)]
            else:
                p1 = (sx + sw, sy + sh // 2)
                p2 = (tx, ty + th // 2)
                if p1[1] == p2[1]:
                    pts = [p1, p2]
                elif tx > sx + sw:
                    mx = tx - 25
                    pts = [p1, (mx, p1[1]), (mx, p2[1]), p2]
                else:
                    pts = [p1, (p1[0] + 20, p1[1]), (p1[0] + 20, max(sy + sh, ty + th) + 30), (tx - 20, max(sy + sh, ty + th) + 30), (tx - 20, p2[1]), p2]
                if shape_kind_by_id(fl.src) == "gw" and p1[1] != p2[1] and tx > sx:
                    # 게이트웨이에서 위/아래로 나감 (그 열에 다른 도형이 없을 때)
                    gx = sx + sw // 2
                    gy = sy + sh if p2[1] > p1[1] else sy
                    if not blocked(gx, gy, p2[1], {fl.src, fl.dst}):
                        pts = [(gx, gy), (gx, p2[1]), p2]
                    else:
                        mx = p1[0] + 25
                        pts = [p1, (mx, p1[1]), (mx, p2[1]), p2]
            wps = "".join(f'<di:waypoint x="{x}" y="{y}" />' for x, y in pts)
            lbl = ""
            if fl.name:
                (ax, ay), (bx2, by2) = pts[-2], pts[-1]
                lx = min(ax, bx2) + 4 if ay == by2 else ax + 6
                ly = ay - 18 if ay == by2 else (ay + by2) // 2 - 7
                lbl = f'<bpmndi:BPMNLabel><dc:Bounds x="{lx}" y="{ly}" width="{max(24, 12 * len(fl.name))}" height="14" /></bpmndi:BPMNLabel>'
            out.append(f'      <bpmndi:BPMNEdge id="{fl.id}_di" bpmnElement="{fl.id}">{wps}{lbl}</bpmndi:BPMNEdge>')
        return out

    kinds = {n.id: shape_kind(n) for n in all_nodes(ex.nodes)}

    def shape_kind_by_id(i):
        return kinds.get(i, "event")

    s += edges(ex.flows, {b.id for b in ex.boundaries})
    for n in all_nodes(ex.nodes):
        if n.kind == "sub":
            s += edges(n.flows, {b.id for b in n.boundaries})
    for d in ex.data:
        wx, wy, ww, wh = pos[d.writer]
        x, y, w, h = pos[d.id]
        if y > wy:
            pts = f'<di:waypoint x="{wx + ww // 2}" y="{wy + wh}" /><di:waypoint x="{x + w // 2}" y="{y}" />'
        else:
            pts = f'<di:waypoint x="{wx + ww // 2}" y="{wy}" /><di:waypoint x="{x + w // 2}" y="{y + h}" />'
        s.append(f'      <bpmndi:BPMNEdge id="DOA_{d.id}_di" bpmnElement="DOA_{d.id}">{pts}</bpmndi:BPMNEdge>')
    s.append("    </bpmndi:BPMNPlane>")
    s.append("  </bpmndi:BPMNDiagram>")
    s.append("</bpmn:definitions>")
    return "\n".join(s) + "\n"


def to_dmn(d: Decision) -> str:
    rows = []
    ins = "".join(
        f'      <dmn:input id="In_{i}" label="{escape(lab)}">\n        <dmn:inputExpression id="InE_{i}" typeRef="{t}"><dmn:text>{escape(expr)}</dmn:text></dmn:inputExpression>\n      </dmn:input>\n'
        for i, (lab, expr, t) in enumerate(d.inputs))
    outs = "".join(f'      <dmn:output id="Out_{i}" name="{escape(n)}" typeRef="{t}" />\n' for i, (n, t) in enumerate(d.outputs))
    for r, (ie, oe, desc) in enumerate(d.rules):
        cells = "".join(f'        <dmn:inputEntry id="R{r}_I{i}"><dmn:text>{escape(v)}</dmn:text></dmn:inputEntry>\n' for i, v in enumerate(ie))
        cells += "".join(f'        <dmn:outputEntry id="R{r}_O{i}"><dmn:text>{escape(v)}</dmn:text></dmn:outputEntry>\n' for i, v in enumerate(oe))
        rows.append(f'      <dmn:rule id="Rule_{r}">\n        <dmn:description>{escape(desc)}</dmn:description>\n{cells}      </dmn:rule>\n')
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<dmn:definitions xmlns:dmn="https://www.omg.org/spec/DMN/20191111/MODEL/" '
            f'id="Defs_{d.id}" name="{escape(d.name)}" namespace="urn:chaeksas:examples">\n'
            f'  <dmn:decision id="{d.id}" name="{escape(d.name)}">\n'
            f'    <dmn:decisionTable id="DT_{d.id}" hitPolicy="{d.hit}">\n{ins}{outs}{"".join(rows)}'
            '    </dmn:decisionTable>\n  </dmn:decision>\n</dmn:definitions>\n')


def to_cases(ex: Example) -> str:
    return json.dumps({"schema": 1, "process": "Proc_" + ex.file, "cases": [
        dict(name=c.name, description=c.description, inputs=c.inputs, expected=c.expected,
             approvals=c.approvals, **({"messages": c.messages} if c.messages else {}), manual=c.manual) for c in ex.cases]}, ensure_ascii=False, indent=2) + "\n"


# ───────────────────────── 문서 카드 ─────────────────────────

def md_cell(v):
    return str(v).replace("|", "\\|").replace("\n", "<br>")


def node_summary(n: Node) -> str:
    p = n.props
    k = n.kind
    if k == "start" or k == "end" or k in ("throw", "catch"):
        kd = p.get("kind", "none")
        if kd == "timer":
            return f"타이머 `{p.get('cycle') or p.get('duration')}`"
        if kd == "message":
            return f"메시지 `{p['message']}`"
        if kd == "signal":
            return f"신호 `{p.get('signal') or p.get('ref')}`"
        if kd == "error":
            return f"오류 `{p['error']}`"
        if kd == "terminate":
            return "종료(전체)"
        return "—"
    if k == "script":
        return f"`{p['code'].splitlines()[0][:70]}`" + (" …" if len(p["code"].splitlines()) > 1 or len(p["code"]) > 70 else "")
    if k == "ai":
        t = p["task"]
        s = f"{t['domain']} · 결과 {', '.join(f'`{a}`:{b}' for a, b in t['results'].items())}"
        if t["tools"]:
            s += f" · 도구 {', '.join(t['tools'])}"
        if t["params"]:
            s += f" · 파라미터 {', '.join(t['params'])}"
        if p.get("loop"):
            lp = p["loop"]
            s += f" · 반복({'병렬' if lp.get('parallel') else '차례'}) `{lp['collection']}`→`{lp['collect_into']}`"
        return s
    if k == "ui":
        t = p["task"]
        st = ", ".join(f"{x['action']} `{x['key']}`" for x in t["steps"])
        s = f"화면 `{t['page_id']}` · {st}"
        if p.get("loop"):
            s += f" · 반복 `{p['loop']['collection']}`"
        return s
    if k == "svc":
        t = p["task"]
        s = f"`{t['app_id']}`.`{t['operation']}` · 입력 {', '.join(t['input'])} → {', '.join(t['output'])}"
        if t.get("key_ref"):
            s += f" · 키 참조 `{t['key_ref']}`(태스크 지정)"
        if p.get("loop"):
            s += f" · 반복({'병렬' if p['loop'].get('parallel') else '차례'}) `{p['loop']['collection']}`"
        return s
    if k in ("appr", "manual"):
        t = p["task"]
        fl = ", ".join(f"`{x['key']}`({x['type']}{'*' if x['required'] else ''})" for x in t["fields"])
        loc = {"follow": "Bot UI 설정을 따름", "center": "Center 결재함", "field": "현장 PC"}[t["location"]]
        return f"「{t['title']}」 · 보임 {', '.join(t['show'])} · 칸 {fl} · {loc}"
    if k == "rule":
        t = p["task"]
        return f"DMN `{t['decision']}` → {', '.join(t['output'])}"
    if k == "flist":
        t = p["task"]
        s = f"`{t['folder']}` · 무늬 `{t['pattern']}` → `{t['store_as']}`"
        if t.get("count_as"):
            s += f" · 개수 `{t['count_as']}`"
        return s
    if k == "mail":
        t = p["task"]
        return f"받는 사람 {', '.join(t['to'])} · 제목 「{t['subject']}」" + (f" · 첨부 {', '.join(t['attachments'])}" if t["attachments"] else "")
    if k == "hook":
        t = p["task"]
        return f"{t['method']} `{t['url']}`"
    if k == "recv":
        return f"메시지 `{p['message']}` · 상관 `{p['correlation']}`" + (f" · 받는 값 {', '.join(p['payload'])}" if p["payload"] else "")
    if k == "call":
        t = p["task"]
        return f"`{p['called']}` · 입력 {', '.join(t['input'])} · 출력 {', '.join(t['output'])}"
    if k in ("xgw", "igw", "pgw"):
        return "—"
    if k == "sub":
        return f"안에 {len(n.children)}개 노드"
    return ""


def to_card(ex: Example, bpmn_rel: str, cases_rel: str) -> str:
    loc = "서버 (서버 Bot)" if ex.run_location == "server" else "PC (Bot)"
    keys = [f"`{a}` → `{b}`" for a, b in ex.service_keys.items()]
    keys += [f"`{n.props['task']['app_id']}` → `{n.props['task']['key_ref']}` (태스크 지정)"
             for n in all_nodes(ex.nodes) if n.kind == "svc" and n.props["task"].get("key_ref")]
    keys_txt = ", ".join(keys) or "없음"
    L = [f"## {ex.id}. {ex.name}", ""]
    L += ["| 항목 | 값 |", "| --- | --- |",
          f"| 분야 | {ex.dept} |", f"| 출처 | {ex.origin} |", f"| 실행 위치 | **{loc}** |",
          f"| 시작 | {md_cell(ex.trigger)} |",
          f"| 서비스 앱·키 참조 | {keys_txt} |",
          f"| 확장 | {', '.join(e['id'] for e in ex.extensions) or '없음 (플랫폼 기본 태스크만)'} |",
          f"| 마일스톤 | {ex.milestone} |",
          f"| 파일 | [BPMN]({bpmn_rel}) · [시험 케이스]({cases_rel})" + "".join(f" · [DMN](bpmn/{d.id}.dmn)" for d in ex.decisions) + " |", ""]
    L += ["**업무 배경과 목표**", "", ex.background.strip(), "",
          f"**왜 {'서버' if ex.run_location == 'server' else 'PC'}에서 도는가**", "", ex.why_location.strip(), ""]
    if ex.inputs:
        L += ["**입력** (`chk:process.inputs` — 작업 지시·메시지 본문·케이스가 채운다)", "", "| 이름 | 타입 | 필수 | 기본값 | 뜻 |", "| --- | --- | --- | --- | --- |"]
        L += [f"| `{i[0]}` | {i[1]} | {'✓' if i[2] else ''} | {md_cell(json.dumps(i[4], ensure_ascii=False)) if len(i) > 4 else ''} | {md_cell(i[3])} |" for i in ex.inputs]
        L.append("")
    L += ["**흐름 (노드)**", "", "| id | 이름 | 종류 | 핵심 속성 | 다음 |", "| --- | --- | --- | --- | --- |"]

    def rows(nodes, flows, bnds, prefix=""):
        out = []
        for n in nodes:
            nxt = []
            for fl in flows:
                if fl.src == n.id:
                    t = fl.dst
                    if fl.cond:
                        t += f" (`{fl.cond}`)"
                    elif fl.default:
                        t += " (기본)"
                    nxt.append(t)
            out.append(f"| `{prefix}{n.id}` | {md_cell(n.name)} | {KIND_LABEL[n.kind]} | {md_cell(node_summary(n))} | {md_cell(', '.join(nxt))} |")
            if n.kind == "sub":
                out += rows(n.children, n.flows, n.boundaries, prefix="↳ ")
        for b in bnds:
            nxt = ", ".join(fl.dst for fl in flows if fl.src == b.id)
            kind = {"timer": "타이머", "error": "오류", "signal": "신호", "message": "메시지"}[b.kind]
            det = b.props.get("duration") or b.props.get("error") or b.props.get("signal") or b.props.get("message") or ""
            out.append(f"| `{prefix}{b.id}` | {md_cell(b.name)} | 경계({kind}{', 비중단' if not b.interrupting else ''}) | `{b.attached}`에 붙음 · `{det}` | {nxt} |")
        return out

    L += rows(ex.nodes, ex.flows, ex.boundaries)
    for d in ex.data:
        L.append(f"| `{d.id}` | {md_cell(d.name)} | 파일 출력 | `{d.props['path']}` ({d.props['format']}) → `{d.props['store_as']}` · `{d.writer}`가 끝날 때 | — |")
    L.append("")
    if ex.variables:
        L += ["**주요 변수**", "", "| 이름 | 타입 | 만드는 곳 | 뜻 |", "| --- | --- | --- | --- |"]
        L += [f"| `{a}` | {b} | {md_cell(c)} | {md_cell(d)} |" for a, b, c, d in ex.variables]
        L.append("")
    goals = [n for n in all_nodes(ex.nodes) if n.kind == "ai"]
    if goals:
        L += ["<details><summary>AI 태스크 목표 전문</summary>", ""]
        for n in goals:
            L += [f"**`{n.id}` {n.name}**", "", "```markdown", n.props["task"]["goal"], "```", ""]
        L += ["</details>", ""]
    for dcs in ex.decisions:
        L += [f"**규칙 `{dcs.id}` ({dcs.name}, 적중 정책 {dcs.hit})**", "",
              "| " + " | ".join(i[0] for i in dcs.inputs) + " | → " + " | ".join(o[0] for o in dcs.outputs) + " | 설명 |",
              "| " + " | ".join("---" for _ in dcs.inputs) + " | " + " | ".join("---" for _ in dcs.outputs) + " | --- |"]
        for ie, oe, desc in dcs.rules:
            L.append("| " + " | ".join(md_cell(v) for v in ie) + " | " + " | ".join(md_cell(v) for v in oe) + f" | {md_cell(desc)} |")
        L.append("")
    if ex.cases:
        L += ["**시험 케이스**", "", "| 케이스 | 입력 | 기대 결과 | 결재 자동 응답 · 보내는 메시지 |", "| --- | --- | --- | --- |"]
        for c in ex.cases:
            ap = "; ".join(f"`{k}`: {json.dumps(v, ensure_ascii=False)}" for k, v in c.approvals.items()) or ("— (사람이 직접 답함)" if c.manual else "—")
            if c.messages:
                ap += "<br>" + "; ".join(f"{m['after_s']}초 뒤 `{m['name']}` {json.dumps(m.get('payload', {}), ensure_ascii=False)}" for m in c.messages)
            desc = f"<br><small>{md_cell(c.description)}</small>" if c.description else ""
            L.append(f"| {md_cell(c.name)}{' (수동)' if c.manual else ''}{desc} | {md_cell(json.dumps(c.inputs, ensure_ascii=False))} | {md_cell(json.dumps(c.expected, ensure_ascii=False))} | {md_cell(ap)} |")
        L.append("")
    if ex.features:
        L += ["**이 예제로 확인하는 것**", ""] + [f"- {x}" for x in ex.features] + [""]
    if ex.lessons:
        L += ["**주의**", ""] + [f"- {x}" for x in ex.lessons] + [""]
    if ex.samples:
        L += ["**샘플 데이터**", "", ex.samples.strip(), ""]
    return "\n".join(L)


# ───────────────────────── 변수 출처 점검 (B11 근사) ─────────────────────────

import re as _re

_BUILTIN = {"오늘", "error_message", "error_code", "failed_task"}
_NAME = r"[A-Za-z가-힣_][A-Za-z0-9가-힣_]*"


def defined_vars(ex: Example) -> set[str]:
    d = set(_BUILTIN) | {i[0] for i in ex.inputs}
    for n in all_nodes(ex.nodes):
        p = n.props
        t = p.get("task") or {}
        if n.kind == "script":
            d |= set(_re.findall(rf"^\s*({_NAME})\s*=", p["code"], _re.M))
        if n.kind == "ai":
            d |= set(t["results"])
        if n.kind in ("svc", "rule", "call"):
            d |= set(t["output"])
        if n.kind == "ui":
            d |= {s["result"] for s in t["steps"] if s.get("result")}
        if n.kind in ("appr", "manual"):
            d |= {f["key"] for f in t["fields"]}
        if n.kind == "recv":
            d |= set(p["payload"])
        if n.kind in ("mail", "hook") and t.get("store_as"):
            d.add(t["store_as"])
        if n.kind == "flist":
            d.add(t["store_as"])
            if t.get("count_as"):
                d.add(t["count_as"])
        if p.get("loop"):
            d |= {p["loop"]["item"], p["loop"]["collect_into"]}
    d |= {x.props["store_as"] for x in ex.data}
    return d


def used_template_vars(ex: Example) -> set[tuple[str, str]]:
    u = set()
    for n in all_nodes(ex.nodes):
        t = n.props.get("task") or {}
        if n.kind == "mail":
            for s in t["to"] + [t["subject"], t["body"]]:
                u |= {(n.id, m.split(".")[0]) for m in _re.findall(r"\{([^{}\"]+)\}", s)}
            u |= {(n.id, a) for a in t["attachments"]}
        if n.kind == "hook":
            u |= {(n.id, m.split(".")[0]) for m in _re.findall(r"\{([^{}\"]+)\}", t["url"])}
            m = _re.match(r"fields:\[(.*)\]", t["body"])
            if m:
                u |= {(n.id, x.strip()) for x in m.group(1).split(",")}
        if n.kind in ("appr", "manual"):
            u |= {(n.id, x) for x in t["show"]}
    return u


def var_warnings(ex: Example) -> list[str]:
    d = defined_vars(ex)
    return sorted(f"{nid}: `{v}` 출처 없음" for nid, v in used_template_vars(ex) if v not in d)
