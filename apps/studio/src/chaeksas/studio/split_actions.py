"""STU-06a 「PC BPM 프로세스로 나누기」 (ADR-0071).

서버에서 못 하는 **노드 하나**를 새 PC Bot(시작 → 그 노드 → 끝)으로 옮기고, 원래 자리는 그 노드를
**위임 호출로 바꾼다** (`chk:call.delegate`, ADR-0062).

지키는 것 넷.

- **그림은 둘 다 캔버스가 짓는다** (ADR-0022) — 파이썬은 XML을 만지지 않는다(`appendChain`·
  `delegateNode`). 디스크에 쓰는 것은 캔버스가 내보낸 글 그대로다.
- **이름을 지어내지 않는다** — 미리 채우는 것은 플랫폼이 세는 이름(`read_vars`·`produced_vars`)뿐이고,
  짝은 **같은 이름**이다. 확장 태스크의 `data`는 해석하지 않는다 (C13 §5).
- **PC 쪽을 다 지은 뒤 서버 쪽을 바꾼다** — PC 쪽이 실패하면 서버 그림은 디스크의 것 그대로 돌아오고
  만든 폴더는 지운다.
- **오류 경계·시험 케이스는 지어 넣지 않는다** — 할 일을 말한다.

규칙(무엇을 옮기고 무엇을 적나)은 Qt를 모르는 함수로 두고, 캔버스를 모는 것은 `split()` 하나다.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from chaeksas.contracts.bpmn_ext import (
    BUILTIN_VARS,
    UNKNOWN_VARS,
    BpmnProcess,
    ProcessInfo,
    produced_vars,
    read_vars,
    server_blockers,
)
from chaeksas.studio.canvas import CanvasError
from chaeksas.studio.workspace import ID_PATTERN, BpmProcess, WorkspaceError

if TYPE_CHECKING:
    from chaeksas.studio.main_window import MainWindow

#: PC Bot id의 기본 꼬리 (STU-06a [B]).
PC_SUFFIX = "-pc"

#: 입력 타입의 기본값 (C14 값 타입). 사람이 고친다.
DEFAULT_TYPE = "string"

#: 확장·AI 태스크 — 플랫폼이 읽고 쓰는 변수를 **다 알지 못한다** (ADR-0018, C13 §5).
UNKNOWN_HINT = "이 태스크가 읽고 쓰는 변수는 플랫폼이 다 알지 못합니다 — 입력·출력을 확인해 직접 적으세요."


@dataclass(frozen=True)
class Blocker:
    """서버에서 못 하는 노드 하나 — `server_blockers`(B6과 같은 함수)가 센 것."""

    node_id: str
    name: str
    reason: str

    @property
    def label(self) -> str:
        return f"{self.name or self.node_id} ({self.node_id}) — {self.reason}"


@dataclass
class Plan:
    """사람이 확인한 나누기 하나 (STU-06a)."""

    node_id: str
    pc_id: str
    pc_name: str
    #: `(이름, 타입)` — 위임 호출의 `input`과 PC Bot의 `inputs`(필수)가 된다.
    inputs: list[tuple[str, str]] = field(default_factory=list)
    #: 위임 호출의 `output`과 PC Bot의 `outputs`가 된다.
    outputs: list[str] = field(default_factory=list)


def blockers(process: BpmnProcess, task_type_locations: Any = None) -> list[Blocker]:
    """옮길 수 있는 노드들. **검사와 같은 함수**로 센다 (어긋나면 창과 F6이 다른 것을 말한다)."""
    out: list[Blocker] = []
    for line in server_blockers(process, task_type_locations):
        node_id, _, reason = line.partition(": ")
        node = process.node(node_id)
        out.append(Blocker(node_id=node_id, name=(node.name if node else "") or "", reason=reason))
    return out


def suggested(process: BpmnProcess, node_id: str) -> tuple[list[str], list[str], bool]:
    """미리 채울 입력·출력과 「다 아는가」. **세는 것만** 채운다 — 지어내지 않는다."""
    node = process.node(node_id)
    if node is None:
        return [], [], False
    reads = read_vars(node, process.flows) - BUILTIN_VARS
    made = produced_vars(node)
    known = UNKNOWN_VARS not in reads | made and not ({"task", "aiTask"} & set(node.props))
    return sorted(reads - {UNKNOWN_VARS}), sorted(made - {UNKNOWN_VARS}), known


def default_pc_id(server_id: str) -> str:
    return f"{server_id}{PC_SUFFIX}"


def problems(plan: Plan, *, taken: Any) -> list[str]:
    """「나누기」를 막는 것. `taken(id)`는 그 id의 BPM 프로세스가 이미 있는가."""
    out: list[str] = []
    if not ID_PATTERN.match(plan.pc_id):
        out.append(f"id는 소문자·숫자·`.`·`_`·`-`만 쓰고 소문자나 숫자로 시작합니다: {plan.pc_id or '(비어 있음)'}")
    elif taken(plan.pc_id):
        out.append(f"같은 id의 BPM 프로세스가 있습니다: {plan.pc_id}")
    names = [name for name, _ in plan.inputs] + list(plan.outputs)
    if any(not name.strip() for name in names):
        out.append("이름이 빈 입력·출력이 있습니다.")
    for kind, group in (("입력", [n for n, _ in plan.inputs]), ("출력", plan.outputs)):
        clash = sorted({n for n in group if group.count(n) > 1})
        if clash:
            out.append(f"{kind} 이름이 겹칩니다: {', '.join(clash)}")
    return out


def process_entry_id(pc_id: str) -> str:
    """PC 그림의 BPMN process id — 「만들기」와 같은 규칙이다 (`file_actions.new_process`)."""
    return f"Proc_{pc_id.replace('-', '_')}"


def call_body(plan: Plan) -> str:
    """위임 호출의 `chk:call` (C14) — 짝은 **같은 이름**이다."""
    body: dict[str, Any] = {"delegate": {"bpm_process_id": plan.pc_id}}
    if plan.inputs:
        body["input"] = {name: name for name, _ in plan.inputs}
    if plan.outputs:
        body["output"] = {name: name for name in plan.outputs}
    return json.dumps(body, ensure_ascii=False, indent=2)


def pc_process(plan: Plan, server: ProcessInfo, extension: str | None) -> str:
    """PC Bot의 `chk:process` — 옮긴 노드의 **확장에 해당하는 것만** 서버에서 가져온다 (ADR-0071 4).

    키 참조는 옮기지 않는다 — 키가 없다 (ADR-0102, C14 B7).
    """
    body: dict[str, Any] = {"run_location": "pc"}
    pins = [one.to_json_dict() for one in server.extensions if one.id == extension]
    if pins:
        body["extensions"] = pins
    if plan.inputs:
        body["inputs"] = [{"name": name, "type": kind, "required": True} for name, kind in plan.inputs]
    if plan.outputs:
        body["outputs"] = list(plan.outputs)
    return json.dumps(body, ensure_ascii=False, indent=2)


def extension_of(chk: dict[str, str]) -> str | None:
    """옮길 노드가 확장 태스크면 그 확장 id (`chk:task`의 `extension`)."""
    text = chk.get("task")
    if not text:
        return None
    try:
        found = json.loads(text).get("extension")
    except (ValueError, AttributeError):
        return None
    return str(found) if found else None


def done_message(plan: Plan, node_label: str) -> str:
    """끝난 뒤 할 일 — **경계·케이스를 지어 넣지 않고** 말한다 (ADR-0071 6)."""
    return (
        f"나눴습니다 — {node_label}을(를) PC Bot {plan.pc_id}로 옮겼습니다. 서버 그림은 「저장」(Ctrl+S)으로 쓰세요. "
        "위임이 실패하면 DELEGATION_FAILED가 옵니다 — 오류 경계를 다세요. 시험 케이스에 이 호출의 "
        "delegations를 적어야 시험 실행이 지납니다. PC Bot은 따로 올리고 배포합니다."
    )


# ─────────────────────────── 캔버스를 모는 쪽 ───────────────────────────


def split(window: MainWindow, plan: Plan) -> bool:
    """나눈다 — PC 쪽을 **다 지은 뒤** 서버 쪽을 바꾼다. 실패하면 그 자리에서 말한다."""
    process, definition = window.process, window.definition
    if process is None or definition is None:
        window.say("열린 정의가 없습니다.")
        return False
    # 서버 그림은 **디스크의 것**을 들고 간다 — PC 쪽이 실패하면 이것으로 되돌린다.
    if not window.saved_to_disk():
        return False
    server_xml = definition.read_text(encoding="utf-8")
    canvas = window.canvas
    try:
        node = canvas.call_sync("properties", plan.node_id)
        info = canvas.call_sync("properties", process_id_of(window))
    except CanvasError as e:
        window.say(f"나누지 못했습니다: {e}")
        return False
    if not node.get("found"):
        window.say(f"그 노드가 그림에 없습니다: {plan.node_id}")
        return False
    chk = {str(k): str(v) for k, v in (node.get("chk") or {}).items()}
    server_info = _process_info(str((info.get("chk") or {}).get("process") or ""))

    made = _build_pc(window, plan, node, chk, server_info, server_xml)
    if made is None:
        return False

    # 서버 쪽 — 들고 있던 그림을 다시 띄워 그 노드를 바꾼다 (캔버스에만 적용된다).
    try:
        canvas.call_sync("importXML", server_xml)
        changed = canvas.delegate_node(
            plan.node_id,
            name=f"{node.get('name') or plan.node_id} (PC 위임)",
            called=process_entry_id(plan.pc_id),
            call=call_body(plan),
        )
    except CanvasError as e:
        window.say(f"PC Bot {plan.pc_id}은(는) 만들었지만 서버 그림을 바꾸지 못했습니다: {e}")
        return False
    window.dirty = True
    window.retitle()
    # 새로 만든 PC Bot도 목록에 올린다 (STU-02 — 목록은 연·만든 BPM 프로세스다).
    window.explorer.refresh(opened=definition.as_posix(), adding=(plan.pc_id,))
    canvas.call("select", changed)
    window.say(done_message(plan, str(node.get("name") or plan.node_id)))
    return True


def process_id_of(window: MainWindow) -> str:
    """열린 정의의 BPMN process id — 진입 정의의 그림에서 읽는다."""
    found = window.opened_definition()
    if found is None or found.process is None:
        raise CanvasError("열린 정의의 그림을 읽지 못했다")
    return found.process.id


def _process_info(text: str) -> ProcessInfo:
    try:
        return ProcessInfo.model_validate_json(text) if text else ProcessInfo()
    except ValueError:
        return ProcessInfo()


def _build_pc(
    window: MainWindow,
    plan: Plan,
    node: dict[str, Any],
    chk: dict[str, str],
    server_info: ProcessInfo,
    server_xml: str,
) -> BpmProcess | None:
    """새 작업 폴더에 PC 그림을 짓고 저장한다. 실패하면 **폴더를 지우고 서버 그림을 되돌린다**."""
    process = window.process
    assert process is not None
    canvas = window.canvas
    try:
        made = window.workspace.create(plan.pc_id, name=plan.pc_name, group=process.group)
    except WorkspaceError as e:
        window.say(f"PC Bot을 만들지 못했습니다: {e}")
        return None
    try:
        canvas.create_empty(process_entry_id(plan.pc_id), plan.pc_name)
        canvas.append_chain(
            [
                {"bpmn": f"bpmn:{node.get('type') or 'ServiceTask'}", "name": str(node.get("name") or ""), "chk": chk},
                {"bpmn": "bpmn:EndEvent", "name": "끝", "chk": {}},
            ]
        )
        patch = {"chk": {"process": pc_process(plan, server_info, extension_of(chk))}}
        if not canvas.call_sync("setProperties", process_entry_id(plan.pc_id), patch).get("found"):
            raise CanvasError("PC 그림의 process를 찾지 못했다")
        window.workspace.save_definition(made, made.entry, canvas.save_xml())
    except (CanvasError, OSError) as e:
        shutil.rmtree(made.folder, ignore_errors=True)
        try:
            canvas.call_sync("importXML", server_xml)
        except CanvasError:
            pass
        window.dirty = False  # 디스크의 것 그대로다
        window.retitle()
        window.say(f"PC Bot을 짓지 못했습니다 — 서버 그림은 그대로입니다: {e}")
        return None
    return made


__all__ = [
    "DEFAULT_TYPE",
    "PC_SUFFIX",
    "UNKNOWN_HINT",
    "Blocker",
    "Plan",
    "blockers",
    "call_body",
    "default_pc_id",
    "done_message",
    "extension_of",
    "pc_process",
    "problems",
    "process_entry_id",
    "split",
    "suggested",
]
