"""C14. BPMN 확장 속성 (`chk:*`) — BPM 프로세스 정의 파일 형식.

단일 원본: `docs/03-contracts/C14-bpmn-extensions.md`. Studio(쓰기)·실행기(읽기)·Center(검사)가
**같은 모델**을 쓴다.

세 묶음이다.

| 묶음 | 무엇 |
| --- | --- |
| 속성 모델 | `bpmn:extensionElements` 안 `chk:*` 요소의 JSON (`ProcessInfo`·`AiTask`·`Approval` …) |
| 그래프 | BPMN 파일을 읽어 만든 노드·흐름 (`read_process()` → `BpmnProcess`) |
| 검사 | `validate()` — B1~B14. 오류와 **경고**를 함께 돌려준다 (`Violation.severity`) |

읽기는 표준 라이브러리(`xml.etree`)로만 한다. 의존성을 늘리지 않고, Center가 업로드된 파일을
검사할 때도 같은 코드를 쓴다.

**확장이 더한 태스크(`chk:task`)의 속 내용은 여기서 모른다** (ADR-0018). `type`·`extension`만
보고, JSON 본문은 그 확장의 계약이 검사한다.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar
from xml.etree import ElementTree

from pydantic import Field, ValidationError

from chaeksas.contracts._base import (
    SEVERITY_WARNING,
    ContractModel,
    SchemaVersioned,
    Violation,
)
from chaeksas.contracts.approvals import KNOWN_FIELD_TYPES, FormField
from chaeksas.contracts.manifest import KEY_REF_PATTERN, ExtensionNeed, RunLocation

#: 네임스페이스. 우리 속성은 전부 이 하나에 담는다.
CHK_NS = "urn:chaeksas:bpmn:1"
BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
_CHK = f"{{{CHK_NS}}}"
_BPMN = f"{{{BPMN_NS}}}"

#: 변수 이름 — 한글을 쓸 수 있고, 공백·하이픈은 못 쓰고 숫자로 시작할 수 없다 (식에서 이름이 된다).
VAR_PATTERN = r"^[A-Za-z가-힣_][A-Za-z0-9가-힣_]*$"
_VAR = re.compile(VAR_PATTERN)

#: 생성형 노드 id (bpmn-js 기본값). 읽을 수 없어 경고한다 (B10).
GENERATED_ID_PATTERN = re.compile(r"^(Activity|Gateway|Event|Flow)_[0-9a-z]{7}$")

#: AI 태스크의 대상 환경. `web`·`desktop`은 PC에서만 돈다 (C1 R2).
DOMAINS = frozenset({"llm", "api", "doc", "web", "desktop"})
PC_ONLY_DOMAINS = frozenset({"web", "desktop"})

#: 결과 필드·프로세스 입력의 타입 (B8).
VALUE_TYPES = frozenset({"string", "int", "number", "bool", "list", "dict", "date"})

#: 결재가 어디서 답을 받나.
APPROVAL_LOCATIONS = frozenset({"follow", "center", "field"})

#: 파일 출력 형식.
FILE_FORMATS = frozenset({"md", "xlsx", "json", "txt", "csv"})

#: 이어 쓸 수 있는 형식 (C14 §파일 출력 — `json`·`xlsx`는 이어 붙일 수 없다).
APPENDABLE_FORMATS = frozenset({"md", "txt", "csv"})

#: 파일 목록의 차례 (기본은 이름순 — 디스크가 주는 순서는 실행마다 다르다, ADR-0026).
FILE_SORTS = frozenset({"name", "modified"})

#: 경로 구분자. `pattern`에는 쓸 수 없다 (폴더는 `folder`로만 정한다, ADR-0026).
PATH_SEPARATORS = ("/", "\\")

#: 표준 오류 코드 (오류 경계가 받는다).
ERROR_CODES = frozenset({"TASK_FAILED", "SEND_FAILED", "ESCALATED", "DELEGATION_FAILED"})

#: 웹훅 본문 방식.
WEBHOOK_BODY_ALL = "all"

#: 경계 이벤트를 붙일 수 있는 것 (B12).
BOUNDARY_HOSTS = frozenset(
    {"serviceTask", "userTask", "manualTask", "scriptTask", "businessRuleTask", "sendTask", "receiveTask",
     "callActivity", "subProcess"}
)

#: `location: field` 결재의 시간 제한 경고 기준 (B13) — 하루.
FIELD_APPROVAL_MAX_HOURS = 24

#: **엔진이 늘 주는 변수.** 선언하지 않아도 식·템플릿에서 쓸 수 있다 (예제가 `일일/{오늘}.md`
#: 처럼 파일 이름에 쓴다). 늘어나면 C14 문서의 표와 함께 고친다.
BUILTIN_VARS = frozenset({"오늘", "지금", "run_id"})

#: **확장 태스크가 무엇을 만드는지 플랫폼은 모른다** (ADR-0018 — `chk:task`의 속은 그 확장 것이다).
#: 그 뒤의 변수를 「없다」고 말할 수 없어, 이 표시가 붙은 자리에서는 B11이 입을 닫는다.
#: 확장 호스트가 `extension_task_vars`를 주면 표시 대신 실제 이름이 들어온다.
UNKNOWN_VARS = "*"

#: 번호처럼 보이는 문자열 (B8 경고). 발주번호 `PO-2608-001`을 `int`로 두는 실수를 잡는다.
_LOOKS_LIKE_CODE = re.compile(r"(번호|코드|no$|_no$|id$|_id$)", re.IGNORECASE)


def is_var_name(name: str) -> bool:
    """변수 이름 규칙에 맞나 (C14 기본 규칙 5)."""
    return bool(_VAR.match(name))


# ─────────────────────────── 프로세스 수준 ───────────────────────────


class InputDecl(ContractModel):
    """프로세스 입력 하나. 메시지 본문으로 들어오는 값도 여기 선언한다.

    선언했는데 주지 않았고 기본값도 없으면 `None`이다 (`대상월 = 대상월 or 지난달()`).
    """

    name: str
    type: str  # VALUE_TYPES
    required: bool = False
    description: str | None = None
    default: Any = None

    @property
    def has_default(self) -> bool:
        return self.default is not None


class Limits(ContractModel):
    timeout_s: int | None = None
    max_steps: int | None = None


class WebEnv(ContractModel):
    profile: str | None = None
    session: str | None = None


class DesktopEnv(ContractModel):
    app: str | None = None  # 띄울 앱 이름


class ProcessInfo(ContractModel):
    """`chk:process` — BPM 프로세스 정보 (STU-06). 빌드가 이것을 모아 C1 매니페스트를 만든다."""

    run_location: RunLocation | None = None
    service_keys: dict[str, str] = Field(default_factory=dict)  # {app_id: key_ref}
    extensions: list[ExtensionNeed] = Field(default_factory=list)
    inputs: list[InputDecl] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)

    def input(self, name: str) -> InputDecl | None:
        return next((i for i in self.inputs if i.name == name), None)


class Defaults(ContractModel):
    """`chk:defaults` — 모든 AI·UI 태스크의 기본값. **태스크에 적은 값이 이긴다.**"""

    limits: Limits | None = None
    forbidden_actions: list[str] = Field(default_factory=list)
    confirm_triggers: list[str] = Field(default_factory=list)
    web: WebEnv | None = None
    desktop: DesktopEnv | None = None


# ─────────────────────────── 태스크 속성 ───────────────────────────


class AiTask(ContractModel):
    """`chk:aiTask` — AI = 운전사 (ADR-0008). `goal`은 Markdown이다."""

    goal: str
    domain: str  # DOMAINS
    tools: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)  # 재생 때 `$param`
    results: dict[str, str] = Field(default_factory=dict)  # {이름: 타입}
    limits: Limits | None = None
    forbidden_actions: list[str] = Field(default_factory=list)
    confirm_triggers: list[str] = Field(default_factory=list)
    web: WebEnv | None = None
    desktop: DesktopEnv | None = None


class ExtensionTask(ContractModel):
    """`chk:task` — 확장이 더한 태스크 종류 (C13 `task_types`).

    **속 내용(`data`)은 플랫폼이 해석하지 않는다.** 그 확장의 계약이 검사한다 (ADR-0018).
    """

    type: str  # 태스크 종류 id (예: ui_task)
    extension: str  # 확장 id (예: ui-automation)
    data: dict[str, Any] = Field(default_factory=dict)


class Retry(ContractModel):
    max: int = 0
    on: list[int] = Field(default_factory=list)  # 다시 부를 상태 코드


class ServiceCall(ContractModel):
    """`chk:serviceCall` — 서비스 앱 태스크 (C11). **키 값은 넣지 않는다** (참조 이름만)."""

    app_id: str
    operation: str
    input: dict[str, str] = Field(default_factory=dict)  # {필드: 식}
    output: dict[str, str] = Field(default_factory=dict)  # {변수: 필드}
    key_ref: str | None = None  # 없으면 프로세스의 service_keys를 상속
    timeout_s: int | None = None
    retry: Retry | None = None


class Approval(ContractModel):
    """`chk:approval` — 결재(`userTask`)와 확인(`manualTask`). 폼은 C6과 같은 모양이다."""

    title: str
    description: str | None = None
    #: **변수 이름 배열**이다. 문자열 하나로 쓰면 검사 오류 (B2).
    show: list[str] = Field(default_factory=list)
    fields: list[FormField] = Field(default_factory=list)
    location: str = "follow"  # APPROVAL_LOCATIONS
    expires: str | None = None  # ISO 기간 또는 변수 이름


class Rule(ContractModel):
    """`chk:rule` — 규칙 태스크. DMN은 **한 건**을 판정한다 (목록은 반복으로)."""

    decision: str  # 같은 패키지의 DMN 결정 id
    input: dict[str, str] = Field(default_factory=dict)  # {DMN 입력 이름: 식}
    output: dict[str, str] = Field(default_factory=dict)  # {변수: DMN 출력 이름}


class Email(ContractModel):
    """`chk:email` — 메일 보내기."""

    to: list[str] = Field(default_factory=list)
    cc: list[str] = Field(default_factory=list)
    subject: str = ""
    body: str = ""
    attachments: list[str] = Field(default_factory=list)  # 변수 이름
    store_as: str | None = None


class Webhook(ContractModel):
    """`chk:webhook` — 웹훅 보내기. 주소는 허용 호스트 규칙(C13 §4-3과 같은 해석기)을 따른다."""

    url: str
    method: str = "POST"
    body: str = WEBHOOK_BODY_ALL  # all | fields:[..] | template:"…"
    timeout_s: int | None = None
    store_as: str | None = None


class Receive(ContractModel):
    """`chk:receive` — 메시지 받기·경계·중간 받기의 상관 키와 본문."""

    correlation: str | None = None  # 변수 이름 — 이 값이 같은 메시지만 받는다
    payload: list[str] = Field(default_factory=list)  # 본문에서 변수로 들어오는 이름


class Call(ContractModel):
    """`chk:call` — 다른 BPM 프로세스 호출. **적은 것만 오간다.**"""

    input: dict[str, str] = Field(default_factory=dict)  # {호출 대상 변수: 식}
    output: dict[str, str] = Field(default_factory=dict)  # {내 변수: 호출 대상 변수}


class Loop(ContractModel):
    """`chk:loop` — 반복(다중 인스턴스). `collect_into`가 **필수**다 (빠지면 반복이 멈춘다)."""

    collection: str
    item: str
    result: str | None = None  # 한 번 돈 결과로 쓰는 변수 (그 태스크의 출력 중 하나)
    collect_into: str | None = None  # 모은 목록 (B4가 필수로 본다)


class DataOutput(ContractModel):
    """`chk:dataOutput` — 파일 출력. `store_as`가 **필수**다 (경로를 받는 유일한 길)."""

    path: str
    format: str  # FILE_FORMATS
    template: str | None = None
    variables: list[str] | None = None
    sheet: str | None = None
    append: bool = False
    store_as: str | None = None


class FileList(ContractModel):
    """`chk:fileList` — 파일 목록 태스크 ([ADR-0026](../decisions/0026-file-paths-and-file-list-task.md)).

    디스크를 읽으므로 식의 도우미가 아니라 **태스크**다 (ADR-0025 §식에 두지 않는 것).
    `store_as`가 **필수**다 — 결과를 받을 길이 그것뿐이다.
    """

    folder: str  # 템플릿 (`{변수}`). 상대 경로는 출력 폴더 기준 (C14 §파일 경로)
    pattern: str = "*"  # glob 한 조각 — 경로 구분자는 쓸 수 없다
    recursive: bool = False
    sort: str = "name"  # FILE_SORTS
    limit: int | None = None
    store_as: str | None = None  # 파일 경로 목록이 들어갈 변수 (B5가 필수로 본다)
    count_as: str | None = None  # 개수가 들어갈 변수


#: `chk:*` 요소 이름 → 모델. 모르는 요소는 무시한다 (호환 규칙).
ELEMENT_MODELS: dict[str, type[ContractModel]] = {
    "process": ProcessInfo,
    "defaults": Defaults,
    "aiTask": AiTask,
    "task": ExtensionTask,
    "serviceCall": ServiceCall,
    "approval": Approval,
    "rule": Rule,
    "email": Email,
    "webhook": Webhook,
    "receive": Receive,
    "call": Call,
    "loop": Loop,
    "dataOutput": DataOutput,
    "fileList": FileList,
}


# ─────────────────────────── 그래프 (읽은 결과) ───────────────────────────


@dataclass
class Flow:
    """`bpmn:sequenceFlow` 하나."""

    id: str
    source: str
    target: str
    has_condition: bool = False
    is_default: bool = False
    #: 조건식 본문 (`chk-expr`). 검사는 있는지만 보지만 **엔진은 이것을 평가한다** (M3).
    condition: str | None = None


@dataclass
class Node:
    """노드 하나. `kind`는 BPMN 요소 이름(`serviceTask`·`exclusiveGateway` …)이다."""

    id: str
    kind: str
    name: str | None = None
    #: 이 노드의 `chk:*` 속성. 열쇠는 요소 이름(`aiTask`), 값은 **읽은 모델**이다.
    props: dict[str, Any] = field(default_factory=dict)
    #: 읽히지 않은 `chk:*` (B1이 사유를 남긴다).
    bad_props: dict[str, str] = field(default_factory=dict)
    attached_to: str | None = None  # 경계 이벤트가 붙은 노드
    #: 이벤트 정의 이름 (`timerEventDefinition` 등). 어떤 이벤트인지 가린다.
    event_definitions: tuple[str, ...] = ()
    error_ref: str | None = None
    message_ref: str | None = None
    is_sequential: bool | None = None  # 다중 인스턴스일 때만
    script: str | None = None
    called_element: str | None = None
    data_outputs: tuple[str, ...] = ()  # dataOutputAssociation의 대상 id
    #: 하위 프로세스의 안쪽 (범위가 따로다).
    children: list[Node] = field(default_factory=list)
    child_flows: list[Flow] = field(default_factory=list)

    def prop(self, name: str) -> Any:
        return self.props.get(name)


@dataclass
class BpmnProcess:
    """읽어 들인 BPM 프로세스 하나 (`bpmn:process`)."""

    id: str
    name: str | None = None
    info: ProcessInfo = field(default_factory=ProcessInfo)
    defaults: Defaults | None = None
    nodes: list[Node] = field(default_factory=list)
    flows: list[Flow] = field(default_factory=list)
    #: `bpmn:error errorCode` → id, `bpmn:message name` → id (정의 수준).
    errors: dict[str, str] = field(default_factory=dict)
    messages: dict[str, str] = field(default_factory=dict)
    bad_props: dict[str, str] = field(default_factory=dict)

    def all_nodes(self) -> Iterator[Node]:
        """하위 프로세스 안쪽까지 (범위는 따로지만 노드는 모두 본다)."""

        def walk(nodes: Iterable[Node]) -> Iterator[Node]:
            for n in nodes:
                yield n
                yield from walk(n.children)

        yield from walk(self.nodes)

    def node(self, node_id: str) -> Node | None:
        return next((n for n in self.all_nodes() if n.id == node_id), None)

    def of_kind(self, *kinds: str) -> list[Node]:
        return [n for n in self.all_nodes() if n.kind in kinds]

    def scopes(self) -> Iterator[tuple[str, list[Node], list[Flow]]]:
        """범위마다 `(이름, 노드, 흐름)`. 하위 프로세스는 자기 범위를 가진다."""
        yield "main", self.nodes, self.flows
        for n in self.all_nodes():
            if n.children:
                yield n.id, n.children, n.child_flows

    def outgoing(self, node_id: str, flows: Sequence[Flow] | None = None) -> list[Flow]:
        return [f for f in (flows if flows is not None else self.flows) if f.source == node_id]

    def incoming(self, node_id: str, flows: Sequence[Flow] | None = None) -> list[Flow]:
        return [f for f in (flows if flows is not None else self.flows) if f.target == node_id]


# ─────────────────────────── 읽기 ───────────────────────────


class BpmnReadError(ValueError):
    """BPMN 파일을 읽을 수 없다 (XML이 깨졌거나 `bpmn:process`가 없다)."""


def _text(element: ElementTree.Element) -> str:
    return (element.text or "").strip()


def _read_props(holder: ElementTree.Element | None) -> tuple[dict[str, Any], dict[str, str]]:
    """`extensionElements` 안의 `chk:*`를 모델로 읽는다. `(읽은 것, 못 읽은 것)`."""
    good: dict[str, Any] = {}
    bad: dict[str, str] = {}
    if holder is None:
        return good, bad
    for child in holder:
        if not child.tag.startswith(_CHK):
            continue
        name = child.tag[len(_CHK) :]
        model = ELEMENT_MODELS.get(name)
        if model is None:
            continue  # 모르는 `chk:*`는 무시한다 (호환 규칙)
        raw = _text(child)
        try:
            payload = json.loads(raw) if raw else {}
        except ValueError as e:
            bad[name] = f"JSON이 아니다: {e}"
            continue
        if name == "task":
            # 확장 태스크는 종류·확장만 우리 것이고, 나머지는 그 확장의 몫이다.
            payload = {
                "type": child.get("type", ""),
                "extension": child.get("extension", ""),
                "data": payload if isinstance(payload, dict) else {},
            }
        try:
            good[name] = model.model_validate(payload)
        except ValidationError as e:
            first = e.errors()[0] if e.errors() else {"loc": (), "msg": "?"}
            where = ".".join(str(p) for p in first["loc"])
            bad[name] = f"{where}: {first['msg']}" if where else str(first["msg"])
    return good, bad


def _data_output_refs(el: ElementTree.Element) -> tuple[str, ...]:
    """`dataOutputAssociation`이 가리키는 데이터 객체 id들.

    `find()`의 결과를 `or`로 받으면 안 된다 — `Element`는 **자식이 없으면 거짓**이라
    기본값이 늘 이긴다 (이 함정으로 연결이 통째로 비어 있었다).
    """
    refs = []
    for assoc in el.findall(f"{_BPMN}dataOutputAssociation"):
        target = assoc.find(f"{_BPMN}targetRef")
        if target is not None and _text(target):
            refs.append(_text(target))
    return tuple(refs)


def _read_flows(scope: ElementTree.Element) -> list[Flow]:
    out = []
    for el in scope.findall(f"{_BPMN}sequenceFlow"):
        condition_el = el.find(f"{_BPMN}conditionExpression")
        out.append(
            Flow(
                id=el.get("id", ""),
                source=el.get("sourceRef", ""),
                target=el.get("targetRef", ""),
                has_condition=condition_el is not None,
                is_default=False,
                # 식 본문도 들고 온다 — 엔진이 평가한다. CDATA·줄바꿈으로 들어오므로 깎는다.
                condition=((condition_el.text or "").strip() or None) if condition_el is not None else None,
            )
        )
    return out


#: 노드가 아닌 요소 (흐름·확장·정의).
_NOT_NODES = frozenset(
    {"sequenceFlow", "extensionElements", "dataObject", "documentation", "laneSet", "incoming", "outgoing"}
)


def _read_nodes(scope: ElementTree.Element) -> list[Node]:
    nodes = []
    for el in scope:
        if not el.tag.startswith(_BPMN):
            continue
        kind = el.tag[len(_BPMN) :]
        if kind in _NOT_NODES:
            continue
        props, bad = _read_props(el.find(f"{_BPMN}extensionElements"))
        mi = el.find(f"{_BPMN}multiInstanceLoopCharacteristics")
        definitions = tuple(
            child.tag[len(_BPMN) :]
            for child in el
            if child.tag.startswith(_BPMN) and child.tag.endswith("EventDefinition")
        )
        error_ref = None
        message_ref = None
        for child in el:
            if child.tag == f"{_BPMN}errorEventDefinition":
                error_ref = child.get("errorRef")
            elif child.tag == f"{_BPMN}messageEventDefinition":
                message_ref = child.get("messageRef")
        script_el = el.find(f"{_BPMN}script")
        node = Node(
            id=el.get("id", ""),
            kind=kind,
            name=el.get("name"),
            props=props,
            bad_props=bad,
            attached_to=el.get("attachedToRef"),
            event_definitions=definitions,
            error_ref=error_ref,
            message_ref=message_ref or el.get("messageRef"),
            is_sequential=(mi.get("isSequential") == "true") if mi is not None else None,
            script=_text(script_el) if script_el is not None else None,
            called_element=el.get("calledElement"),
            data_outputs=_data_output_refs(el),
        )
        if kind == "subProcess":
            node.children = _read_nodes(el)
            node.child_flows = _read_flows(el)
            _mark_defaults(el, node.child_flows)
        nodes.append(node)
    return nodes


def _mark_defaults(scope: ElementTree.Element, flows: list[Flow]) -> None:
    """게이트웨이의 `default` 속성을 흐름에 표시한다 (B3)."""
    by_id = {f.id: f for f in flows}
    for el in scope:
        default = el.get("default") if el.tag.startswith(_BPMN) else None
        if default and default in by_id:
            by_id[default].is_default = True


def read_process(xml: str | bytes) -> BpmnProcess:
    """BPMN 파일 하나를 읽는다. `bpmn:process`가 여러 개면 **첫 번째**를 쓴다.

    읽지 못한 `chk:*`는 버리지 않고 `bad_props`에 사유와 함께 남긴다 — B1이 그것을 보고한다.
    """
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as e:
        raise BpmnReadError(f"XML을 읽을 수 없다: {e}") from e

    process_el = root.find(f"{_BPMN}process") if root.tag != f"{_BPMN}process" else root
    if process_el is None:
        raise BpmnReadError("bpmn:process가 없다")

    props, bad = _read_props(process_el.find(f"{_BPMN}extensionElements"))
    flows = _read_flows(process_el)
    _mark_defaults(process_el, flows)

    found = BpmnProcess(
        id=process_el.get("id", ""),
        name=process_el.get("name"),
        info=props.get("process") or ProcessInfo(),
        defaults=props.get("defaults"),
        nodes=_read_nodes(process_el),
        flows=flows,
        errors={
            el.get("errorCode", el.get("name", "")): el.get("id", "")
            for el in root.findall(f"{_BPMN}error")
        },
        messages={el.get("name", ""): el.get("id", "") for el in root.findall(f"{_BPMN}message")},
        bad_props=bad,
    )
    return found


# ─────────────────────────── 시험 케이스 (STU-07) ───────────────────────────

#: 케이스 입력·기대 결과의 연산자. `$`는 변수 이름에 쓰이지 않으므로 예약할 수 있다.
EXPECT_OPERATORS = frozenset({"$gt", "$gte", "$lt", "$lte", "$contains"})
INPUT_OPERATORS = frozenset({"$now_plus", "$test_receiver"})
ANY_VALUE = "*"


class CaseMessage(ContractModel):
    """시작 뒤 `after_s`초에 보내는 메시지 (Center 메시지 API와 같은 모양)."""

    after_s: int = 0
    name: str
    correlation: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class Case(ContractModel):
    """시험 케이스 하나. **패키지에 넣지 않는다** (Studio에서만 쓴다)."""

    name: str
    description: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    expected: dict[str, Any] = Field(default_factory=dict)
    #: 노드 id → 폼 응답. 없는 결재는 **답하지 않고 기다린다** (기한 초과 시험).
    approvals: dict[str, dict[str, Any]] = Field(default_factory=dict)
    messages: list[CaseMessage] = Field(default_factory=list)
    #: 자동 응답을 쓰지 않고 실제 창을 띄운다 (폼을 사람이 보는지 확인).
    manual: bool = False


class CaseFile(SchemaVersioned):
    """케이스 파일 (`cases/*.json`)."""

    SCHEMA: ClassVar[int] = 1

    process: str | None = None  # 비우면 정의 옆에 있는 것으로 본다
    cases: list[Case] = Field(default_factory=list)


def matches(expected: Any, actual: Any) -> bool:
    """기대 결과 비교 (C14 「기대 결과 비교 규칙」).

    AI 결과는 매번 조금씩 달라서 정확히 같음만으로는 시험할 수 없다. 그래서 규칙을 둔다.

    - `"*"`: 있고 비어 있지 않다
    - `{"$gt": n}` 같은 연산자
    - 그 밖의 객체: **부분 일치** (적은 키만)
    - 목록: 길이가 같고 각 원소가 같은 규칙으로 맞는다
    """
    if expected == ANY_VALUE:
        return actual is not None and actual != "" and actual != [] and actual != {}
    if isinstance(expected, Mapping):
        operators = {k for k in expected if isinstance(k, str) and k.startswith("$")}
        if operators:
            return all(_match_operator(op, expected[op], actual) for op in operators)
        if not isinstance(actual, Mapping):
            return False
        return all(key in actual and matches(value, actual[key]) for key, value in expected.items())
    if isinstance(expected, (list, tuple)):
        if not isinstance(actual, (list, tuple)) or len(expected) != len(actual):
            return False
        return all(matches(e, a) for e, a in zip(expected, actual, strict=True))
    # bool은 int보다 먼저 봐야 한다 (True == 1).
    if isinstance(expected, bool) or isinstance(actual, bool):
        return expected is actual
    return bool(expected == actual)


def _match_operator(operator: str, bound: Any, actual: Any) -> bool:
    if operator == "$contains":
        if isinstance(actual, str):
            return isinstance(bound, str) and bound in actual
        if isinstance(actual, (list, tuple)):
            return any(matches(bound, item) for item in actual)
        return False
    if not isinstance(actual, (int, float)) or isinstance(actual, bool):
        return False
    if not isinstance(bound, (int, float)) or isinstance(bound, bool):
        return False
    return {
        "$gt": actual > bound,
        "$gte": actual >= bound,
        "$lt": actual < bound,
        "$lte": actual <= bound,
    }.get(operator, False)


# ─────────────────────────── 식에서 변수 뽑기 ───────────────────────────

#: 식 속의 이름. 뒤에 `(`가 오면 함수, `=`(단 `==` 제외)가 오면 키워드 인자다.
_IDENT = re.compile(r"(?<![.\w가-힣])([A-Za-z가-힣_][A-Za-z0-9가-힣_]*)\s*(\(|=(?!=))?")
#: 문자열 상수. 안의 글은 식이 아니다 (한글 문장이 들어 있다).
_STRING_LITERAL = re.compile(r"[fFrRbB]{0,2}('[^']*'|\"[^\"]*\")")
#: 내포에서 묶이는 이름 (`[x for x in 목록]`).
_COMPREHENSION_TARGET = re.compile(r"\bfor\s+([A-Za-z가-힣_][A-Za-z0-9가-힣_,\s]*?)\s+in\b")
#: 식 언어의 예약어·리터럴. 변수가 아니다.
_RESERVED = frozenset(
    {"True", "False", "None", "and", "or", "not", "in", "if", "else", "for", "is", "len", "sum",
     "min", "max", "round", "zip", "dict", "list", "str", "int", "float", "bool", "abs", "sorted"}
)
#: `{변수}` 모양의 템플릿 자리.
_TEMPLATE_SLOT = re.compile(r"\{([^{}:!]+)")


def expression_vars(expression: str) -> set[str]:
    """식에서 **변수로 보이는 이름**을 뽑는다.

    빼는 것이 넷이다. 하나라도 빠뜨리면 경고가 쓸모없을 만큼 쏟아진다 (실제로 그랬다).

    1. **문자열 상수 안** — 한글 문장이 그대로 이름으로 잡힌다 (`"지급 대상대로 진행"`).
    2. 함수 호출 — 도우미 함수 목록이 아직 확정되지 않아(C14 기본 규칙 6, M3) 뒤에 `(`가
       붙은 이름은 모두 함수로 본다.
    3. 내포에서 묶이는 이름 (`[x for x in 목록]`의 `x`).
    4. 예약어·리터럴.

    그래도 어림이라서, 이것을 쓰는 검사(B11)는 **경고**다.
    """
    text = _STRING_LITERAL.sub(" ", expression or "")
    bound = {
        name.strip()
        for m in _COMPREHENSION_TARGET.finditer(text)
        for name in m.group(1).split(",")
        if name.strip()
    }
    out = set()
    for match in _IDENT.finditer(text):
        name, suffix = match.group(1), match.group(2)
        # `합계(`는 함수, `수량=`은 키워드 인자다 (`dict(품목=p, 수량=q)`).
        if suffix or name in _RESERVED or name in bound:
            continue
        out.add(name)
    return out


def template_vars(text: str) -> set[str]:
    """`{변수}` 자리에 쓰인 이름 (메일 본문·파일 템플릿)."""
    return {
        name.strip()
        for raw in _TEMPLATE_SLOT.findall(text or "")
        for name in [raw.split("[")[0].split(".")[0]]
        if is_var_name(name.strip())
    }


# ─────────────────────────── 변수 흐름 (B11) ───────────────────────────


def _data_objects(process: BpmnProcess, node: Node) -> list[Node]:
    """이 노드가 `dataOutputAssociation`으로 쓰는 데이터 객체들."""
    return [found for ref in node.data_outputs if (found := process.node(ref)) is not None]


def _data_object_reads(process: BpmnProcess, node: Node) -> set[str]:
    """쓰는 태스크 자리에서 읽히는 파일 출력의 변수 (`template`·`variables`·`path`).

    파일은 **그 태스크가 끝날 때** 쓰이므로(C14 「파일 출력」), 태스크가 만든 변수는 이미 있다 —
    결재 폼의 칸을 그 결재의 출력 파일에 넣는 것이 흔하다.
    """
    reads = {v for obj in _data_objects(process, node) for v in read_vars(obj, ())}
    return reads - produced_vars(node)


def _data_object_writes(process: BpmnProcess, node: Node) -> set[str]:
    """파일 출력의 `store_as`. **쓰는 태스크가 끝날 때** 생긴다 (C14 「파일 출력」)."""
    return {v for obj in _data_objects(process, node) for v in produced_vars(obj)}


def produced_vars(node: Node) -> set[str]:
    """이 노드를 지나면 생기는 변수."""
    out: set[str] = set()
    ai: AiTask | None = node.prop("aiTask")
    if ai is not None:
        out |= set(ai.results)
    call: ServiceCall | None = node.prop("serviceCall")
    if call is not None:
        out |= set(call.output)
    rule: Rule | None = node.prop("rule")
    if rule is not None:
        out |= set(rule.output)
    approval: Approval | None = node.prop("approval")
    if approval is not None:
        out |= {f.key for f in approval.fields}
    receive: Receive | None = node.prop("receive")
    if receive is not None:
        out |= set(receive.payload)
    sub_call: Call | None = node.prop("call")
    if sub_call is not None:
        out |= set(sub_call.output)
    for name in ("email", "webhook"):
        sender = node.prop(name)
        if sender is not None and sender.store_as:
            out.add(sender.store_as)
    data: DataOutput | None = node.prop("dataOutput")
    if data is not None and data.store_as:
        out.add(data.store_as)
    files: FileList | None = node.prop("fileList")
    if files is not None:
        out |= {name for name in (files.store_as, files.count_as) if name}
    loop: Loop | None = node.prop("loop")
    if loop is not None:
        out |= {loop.item} | ({loop.collect_into} if loop.collect_into else set())
        if loop.result:
            out.add(loop.result)
    if node.script:
        out |= script_vars(node.script)[1]
    # 오류 경계를 지나면 오류 정보가 생긴다 (C14 「이벤트」).
    if node.kind == "boundaryEvent" and "errorEventDefinition" in node.event_definitions:
        out |= {"error_code", "error_message", "failed_task"}
    return out


def script_vars(script: str) -> tuple[set[str], set[str]]:
    """스크립트의 `(읽는 변수, 만드는 변수)`.

    **줄 순서를 본다** — 앞줄에서 대입한 이름은 뒷줄에서 읽어도 된다. 한 덩어리로 보면
    `보류 = …` 뒤의 `len(보류)`가 「없는 변수를 읽는다」로 잡힌다.
    """
    reads: set[str] = set()
    made: set[str] = set()
    for line in (script or "").splitlines():
        body = line.strip()
        if not body or body.startswith("#"):
            continue
        left, sep, right = body.partition("=")
        # `==`·`>=`는 대입이 아니다.
        if sep and not right.startswith("=") and not left.rstrip().endswith(("!", "<", ">")):
            reads |= expression_vars(right) - made
            target = left.strip()
            if is_var_name(target):
                made.add(target)
        else:
            reads |= expression_vars(body) - made
    return reads, made


def read_vars(node: Node, flows: Sequence[Flow]) -> set[str]:
    """이 노드가 읽는 변수 (어림 — B11이 경고인 이유)."""
    out: set[str] = set()
    approval: Approval | None = node.prop("approval")
    if approval is not None:
        out |= set(approval.show)
        if approval.expires and is_var_name(approval.expires):
            out.add(approval.expires)
    call: ServiceCall | None = node.prop("serviceCall")
    if call is not None:
        out |= {v for expression in call.input.values() for v in expression_vars(expression)}
    rule: Rule | None = node.prop("rule")
    if rule is not None:
        out |= {v for expression in rule.input.values() for v in expression_vars(expression)}
    sub_call: Call | None = node.prop("call")
    if sub_call is not None:
        out |= {v for expression in sub_call.input.values() for v in expression_vars(expression)}
    email: Email | None = node.prop("email")
    if email is not None:
        out |= set(email.attachments)
        out |= template_vars(email.subject) | template_vars(email.body)
    webhook: Webhook | None = node.prop("webhook")
    if webhook is not None:
        out |= template_vars(webhook.url) | template_vars(webhook.body)
    data: DataOutput | None = node.prop("dataOutput")
    if data is not None:
        out |= set(data.variables or ()) | template_vars(data.path) | template_vars(data.template or "")
    files: FileList | None = node.prop("fileList")
    if files is not None:
        out |= template_vars(files.folder)
    loop: Loop | None = node.prop("loop")
    if loop is not None:
        out.add(loop.collection)
    if node.script:
        out |= script_vars(node.script)[0]
    return out


# ─────────────────────────── 검사 규칙 (B1~B14) ───────────────────────────

#: 흐름이 없어도 되는 노드. 시작은 들어오는 흐름이, 끝은 나가는 흐름이 없고,
#: 경계 이벤트는 붙은 노드로 들어오며, 데이터 객체는 `dataOutputAssociation`으로 이어진다.
_NO_INCOMING = frozenset({"startEvent", "boundaryEvent", "dataObjectReference", "dataObject"})
_NO_OUTGOING = frozenset({"endEvent", "dataObjectReference", "dataObject"})

_ISO_DURATION = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)


@dataclass(frozen=True)
class DecisionIo:
    """DMN 결정 하나의 입력·출력 이름 (B14가 규칙 태스크와 대조한다)."""

    inputs: tuple[str, ...]
    outputs: tuple[str, ...]


def duration_hours(value: str) -> float | None:
    """ISO 8601 기간 → 시간. 기간이 아니면(변수 이름 등) `None`."""
    match = _ISO_DURATION.match(value or "")
    if not match or value in ("P", "PT"):
        return None
    parts = {k: int(v) for k, v in match.groupdict(default="0").items()}
    return parts["days"] * 24 + parts["hours"] + parts["minutes"] / 60 + parts["seconds"] / 3600


def _warn(rule: str, message: str, *, code: str | None = None, items: Sequence[str] = ()) -> Violation:
    return Violation(rule=rule, code=code, message=message, items=list(items), severity=SEVERITY_WARNING)


def _error(rule: str, message: str, *, code: str | None = None, items: Sequence[str] = ()) -> Violation:
    return Violation(rule=rule, code=code, message=message, items=list(items))


def available_vars(
    process: BpmnProcess,
    *,
    extension_task_vars: Callable[[ExtensionTask], Iterable[str]] | None = None,
) -> dict[str, set[str]]:
    """노드마다 **어느 경로로 와도** 반드시 있는 변수 (B11의 바탕).

    합류에서 교집합을 잡고 고정점까지 돌린다. 되돌아오는 흐름(반복)이 있어도 끝난다 —
    모든 변수에서 시작해 줄여 가기 때문이다.
    """
    nodes = list(process.all_nodes())

    def made(node: Node) -> set[str]:
        out = produced_vars(node) | _data_object_writes(process, node)
        task: ExtensionTask | None = node.prop("task")
        if task is not None:
            out |= set(extension_task_vars(task)) if extension_task_vars else {UNKNOWN_VARS}
        return out

    produced = {n.id: made(n) for n in nodes}
    declared = {i.name for i in process.info.inputs}
    universe = set(declared)
    for names in produced.values():
        universe |= names

    available = {n.id: set(universe) for n in nodes}
    for scope_name, scope_nodes, scope_flows in process.scopes():
        for node in scope_nodes:
            if not process.incoming(node.id, scope_flows):
                # 시작 자리 — 선언한 입력만 믿는다 (하위 프로세스는 바깥에서 받는다).
                available[node.id] = set(declared) if scope_name == "main" else set(universe)

    changed = True
    while changed:
        changed = False
        for _scope, scope_nodes, scope_flows in process.scopes():
            for node in scope_nodes:
                incoming = process.incoming(node.id, scope_flows)
                if not incoming:
                    continue
                reaching = [available[f.source] | produced[f.source] for f in incoming if f.source in available]
                if not reaching:
                    continue
                # **병렬 합류는 모든 가지를 기다린다** → 가지들이 만든 것이 모두 있다 (합집합).
                # 그 밖의 합류(배타 선택·단순 합류)는 한 가지만 지나므로 교집합이다 — B11이
                # 잡으려는 것이 바로 그 경우다 (「한 가지에서만 생기는 칸을 합류 뒤에 읽음」).
                if node.kind == "parallelGateway" and len(incoming) > 1:
                    merged = set().union(*reaching)
                else:
                    merged = set.intersection(*reaching)
                # 경계 이벤트가 붙은 노드의 변수도 그 뒤로 이어진다.
                if len(merged) != len(available[node.id]) or merged != available[node.id]:
                    available[node.id] = merged
                    changed = True
    # 경계 이벤트는 붙은 노드 자리에서 떠난다.
    for node in nodes:
        if node.attached_to and node.attached_to in available:
            available[node.id] = set(available[node.attached_to])
    return available


def _check_b1_b2(process: BpmnProcess) -> list[Violation]:
    out: list[Violation] = []
    for name, reason in process.bad_props.items():
        out.append(_error("B1", f"chk:{name}이 모델과 맞지 않는다 ({reason})", items=[process.id]))
    for node in process.all_nodes():
        for name, reason in node.bad_props.items():
            out.append(_error("B1", f"{node.id}의 chk:{name}이 모델과 맞지 않는다 ({reason})"))
        approval: Approval | None = node.prop("approval")
        if approval is not None:
            bad = [name for name in approval.show if not is_var_name(name)]
            if bad:
                out.append(_error("B2", f"{node.id}의 show에 변수 이름이 아닌 것이 있다", items=bad))
    return out


def _check_b3(process: BpmnProcess) -> list[Violation]:
    out: list[Violation] = []
    for scope_name, scope_nodes, scope_flows in process.scopes():
        for node in scope_nodes:
            if node.kind not in ("exclusiveGateway", "inclusiveGateway"):
                continue
            outgoing = process.outgoing(node.id, scope_flows)
            if len(outgoing) <= 1:
                continue
            unconditional = [f.id for f in outgoing if not f.has_condition and not f.is_default]
            if unconditional:
                out.append(
                    _error("B3", f"{node.id}의 조건 없는 흐름을 default로 지정하지 않았다", items=unconditional)
                )
        splits = [
            n for n in scope_nodes if n.kind == "inclusiveGateway" and len(process.outgoing(n.id, scope_flows)) > 1
        ]
        joins = [
            n for n in scope_nodes if n.kind == "inclusiveGateway" and len(process.incoming(n.id, scope_flows)) > 1
        ]
        if splits and not joins:
            out.append(
                _error("B3", f"{scope_name}: 포함 분기를 포함 합류로 닫지 않았다", items=[n.id for n in splits])
            )
    return out


def _check_b4_b5(process: BpmnProcess) -> list[Violation]:
    out: list[Violation] = []
    for node in process.all_nodes():
        loop: Loop | None = node.prop("loop")
        if loop is not None and not loop.collect_into:
            out.append(_error("B4", f"{node.id}의 반복에 collect_into가 없다 (반복이 멈춘다)"))
        data: DataOutput | None = node.prop("dataOutput")
        if data is not None:
            if not data.store_as:
                out.append(_error("B5", f"{node.id}의 파일 출력에 store_as가 없다 (경로를 받을 길이 없다)"))
            if not data.template and not data.variables:
                out.append(_error("B5", f"{node.id}의 파일 출력에 template·variables가 모두 없다"))
            if data.format == "xlsx" and data.template:
                out.append(_error("B5", f"{node.id}: xlsx에는 template를 쓸 수 없다 (variables로 시트를 만든다)"))
            if data.format == "csv" and data.variables and len(data.variables) > 1:
                out.append(
                    _error("B5", f"{node.id}: csv의 variables는 이름 하나다", items=list(data.variables))
                )
            if data.append and data.format not in APPENDABLE_FORMATS:
                out.append(
                    _error("B5", f"{node.id}: {data.format}은 이어 쓸 수 없다",
                           items=sorted(APPENDABLE_FORMATS))
                )
        files: FileList | None = node.prop("fileList")
        if files is not None:
            if not files.store_as:
                out.append(_error("B5", f"{node.id}의 파일 목록에 store_as가 없다 (결과를 받을 길이 없다)"))
            if any(sep in files.pattern for sep in PATH_SEPARATORS):
                out.append(
                    _error("B5", f"{node.id}의 pattern에 경로 구분자가 있다 (폴더는 folder로만 정한다)",
                           items=[files.pattern])
                )
    return out


def _check_b6(process: BpmnProcess, task_type_locations: Mapping[str, Sequence[str]] | None) -> list[Violation]:
    """실행 위치가 server면 PC에서만 되는 것이 없어야 한다 (C1 R2와 같은 판정)."""
    if process.info.run_location != "server":
        return []
    items: list[str] = []
    for node in process.all_nodes():
        ai: AiTask | None = node.prop("aiTask")
        if ai is not None and ai.domain in PC_ONLY_DOMAINS:
            items.append(f"{node.id}: AI 태스크 domain={ai.domain}")
        approval: Approval | None = node.prop("approval")
        if approval is not None and approval.location == "field":
            items.append(f"{node.id}: 현장 결재")
        task: ExtensionTask | None = node.prop("task")
        if task is not None and task_type_locations is not None:
            locations = task_type_locations.get(task.type)
            if locations is not None and "server" not in locations:
                items.append(f"{node.id}: 태스크 종류 {task.type} (실행 위치 {list(locations)})")
    if not items:
        return []
    return [
        _error("B6", "실행 위치가 server인데 서버에서 할 수 없는 것이 있다", code="server_incompatible", items=items)
    ]


def _check_b7(process: BpmnProcess) -> list[Violation]:
    out: list[Violation] = []
    for node in process.all_nodes():
        call: ServiceCall | None = node.prop("serviceCall")
        if call is None:
            continue
        key_ref = call.key_ref or process.info.service_keys.get(call.app_id)
        if not key_ref:
            out.append(_error("B7", f"{node.id}: 서비스 앱 {call.app_id}의 키 참조가 없다"))
        elif not re.fullmatch(KEY_REF_PATTERN, key_ref):
            out.append(_error("B7", f"{node.id}: 키 참조 이름이 규칙에 맞지 않는다", items=[key_ref]))
    return out


def _check_b8(process: BpmnProcess) -> list[Violation]:
    out: list[Violation] = []
    for decl in process.info.inputs:
        if decl.type not in VALUE_TYPES:
            out.append(_error("B8", f"입력 {decl.name}의 타입을 모른다: {decl.type}", items=sorted(VALUE_TYPES)))
    for node in process.all_nodes():
        ai: AiTask | None = node.prop("aiTask")
        if ai is None:
            continue
        if ai.domain not in DOMAINS:
            out.append(_error("B8", f"{node.id}의 domain을 모른다: {ai.domain}", items=sorted(DOMAINS)))
        for name, kind in ai.results.items():
            if kind not in VALUE_TYPES:
                out.append(_error("B8", f"{node.id}의 결과 {name} 타입을 모른다: {kind}", items=sorted(VALUE_TYPES)))
            elif kind == "int" and _LOOKS_LIKE_CODE.search(name):
                out.append(
                    _warn("B8", f"{node.id}의 결과 {name}이 번호·코드처럼 보이는데 int다 (문자열이 아닐까)")
                )
    return out


def _check_b9_b10(process: BpmnProcess) -> list[Violation]:
    out: list[Violation] = []
    for _scope, scope_nodes, scope_flows in process.scopes():
        for node in scope_nodes:
            if node.kind not in _NO_INCOMING and not process.incoming(node.id, scope_flows):
                out.append(_error("B9", f"{node.id}에 들어오는 흐름이 없다"))
            if node.kind not in _NO_OUTGOING and not process.outgoing(node.id, scope_flows):
                out.append(_error("B9", f"{node.id}에 나가는 흐름이 없다"))
    for node in process.all_nodes():
        if GENERATED_ID_PATTERN.match(node.id):
            out.append(_warn("B10", f"노드 id가 생성형이다: {node.id} (시험 케이스가 id로 결재에 답한다)"))
    return out


def _check_b11(
    process: BpmnProcess,
    extension_task_vars: Callable[[ExtensionTask], Iterable[str]] | None,
) -> list[Violation]:
    out: list[Violation] = []
    available = available_vars(process, extension_task_vars=extension_task_vars)
    for _scope, scope_nodes, scope_flows in process.scopes():
        for node in scope_nodes:
            # 데이터 객체는 흐름에 없다 — 읽고 쓰는 자리는 이어진 태스크다 (아래에서 함께 본다).
            if node.kind in ("dataObjectReference", "dataObject"):
                continue
            here = available.get(node.id, set())
            if UNKNOWN_VARS in here:
                continue  # 확장 태스크를 지나왔다 — 무엇이 생겼는지 모른다
            # 반복의 한 건(`item`)과 한 번 돈 결과(`result`)는 **그 노드 안에서** 쓸 수 있다.
            loop: Loop | None = node.prop("loop")
            if loop is not None:
                here = here | {loop.item} | ({loop.result} if loop.result else set())
            reads = read_vars(node, scope_flows) | _data_object_reads(process, node)
            missing = sorted(reads - here - BUILTIN_VARS)
            if missing:
                out.append(
                    _warn("B11", f"{node.id}: 어떤 경로로는 만들어지지 않는 변수를 읽는다", items=missing)
                )
    return out


def _check_b12(process: BpmnProcess) -> list[Violation]:
    out: list[Violation] = []
    for node in process.all_nodes():
        approval: Approval | None = node.prop("approval")
        if approval is not None:
            if approval.location not in APPROVAL_LOCATIONS:
                out.append(
                    _error("B12", f"{node.id}의 결재 location을 모른다: {approval.location}",
                           items=sorted(APPROVAL_LOCATIONS))
                )
            for field_ in approval.fields:
                if field_.type not in KNOWN_FIELD_TYPES:
                    out.append(
                        _error("B12", f"{node.id}의 칸 {field_.key} 타입을 모른다: {field_.type}",
                               items=sorted(KNOWN_FIELD_TYPES))
                    )
                elif field_.type == "choice" and not field_.choices:
                    out.append(_error("B12", f"{node.id}의 칸 {field_.key}가 choice인데 choices가 없다"))
        if node.kind == "boundaryEvent":
            host = process.node(node.attached_to or "")
            if host is None:
                out.append(_error("B12", f"{node.id}가 붙은 노드({node.attached_to})가 없다"))
            elif host.kind not in BOUNDARY_HOSTS:
                out.append(
                    _error("B12", f"{node.id}는 {host.kind}에 붙었다 (태스크·하위 프로세스에만 붙인다)")
                )
        data: DataOutput | None = node.prop("dataOutput")
        if data is not None and data.format not in FILE_FORMATS:
            out.append(_error("B12", f"{node.id}의 파일 형식을 모른다: {data.format}", items=sorted(FILE_FORMATS)))
        files: FileList | None = node.prop("fileList")
        if files is not None and files.sort not in FILE_SORTS:
            out.append(_error("B12", f"{node.id}의 파일 목록 sort를 모른다: {files.sort}", items=sorted(FILE_SORTS)))
    return out


def _check_b13(process: BpmnProcess) -> list[Violation]:
    out: list[Violation] = []
    for node in process.all_nodes():
        webhook: Webhook | None = node.prop("webhook")
        if webhook is not None and webhook.body == WEBHOOK_BODY_ALL:
            out.append(_warn("B13", f"{node.id}의 웹훅이 변수를 전부 보낸다 (비밀이 섞일 수 있다)"))
        approval: Approval | None = node.prop("approval")
        if approval is not None and approval.location == "field" and approval.expires:
            hours = duration_hours(approval.expires)
            if hours is not None and hours > FIELD_APPROVAL_MAX_HOURS:
                out.append(
                    _warn("B13", f"{node.id}의 현장 결재 기한이 하루를 넘는다 ({approval.expires}) — "
                                 "현장 PC가 그동안 자리를 쥔다")
                )
    return out


def _check_b14(
    process: BpmnProcess,
    dmn_decisions: Mapping[str, DecisionIo] | None,
    called_processes: Mapping[str, Sequence[str]] | None,
) -> list[Violation]:
    out: list[Violation] = []
    # 병렬 분기·합류의 가지 수 (범위마다).
    for scope_name, scope_nodes, scope_flows in process.scopes():
        splits = [
            n for n in scope_nodes if n.kind == "parallelGateway" and len(process.outgoing(n.id, scope_flows)) > 1
        ]
        joins = [
            n for n in scope_nodes if n.kind == "parallelGateway" and len(process.incoming(n.id, scope_flows)) > 1
        ]
        if len(splits) == 1 and len(joins) == 1:
            branches = len(process.outgoing(splits[0].id, scope_flows))
            waiting = len(process.incoming(joins[0].id, scope_flows))
            if branches != waiting:
                out.append(
                    _error("B14", f"{scope_name}: 병렬 분기는 {branches}갈래인데 합류는 {waiting}개를 기다린다 "
                                  "(합류가 영원히 기다릴 수 있다)")
                )
    # 타이머로 시작하는데 채울 사람이 없는 필수 입력.
    timer_start = any(
        n.kind == "startEvent" and "timerEventDefinition" in n.event_definitions for n in process.all_nodes()
    )
    if timer_start:
        orphans = [i.name for i in process.info.inputs if i.required and not i.has_default]
        if orphans:
            out.append(
                _error("B14", "타이머로 시작하는데 기본값 없는 필수 입력이 있다 (채울 사람이 없다)", items=orphans)
            )
    # 규칙 ↔ DMN, 호출 ↔ 대상.
    for node in process.all_nodes():
        rule: Rule | None = node.prop("rule")
        if rule is not None and dmn_decisions is not None:
            decision = dmn_decisions.get(rule.decision)
            if decision is None:
                out.append(_error("B14", f"{node.id}: DMN 결정 {rule.decision}이 패키지에 없다"))
            else:
                if set(rule.input) != set(decision.inputs):
                    out.append(
                        _error(
                            "B14",
                            f"{node.id}: 입력 {sorted(rule.input)}이 "
                            f"DMN 입력 {sorted(decision.inputs)}과 다르다",
                        )
                    )
                unknown = [v for v in rule.output.values() if v not in decision.outputs]
                if unknown:
                    out.append(_error("B14", f"{node.id}: DMN 출력에 없는 것을 받는다", items=unknown))
        call: Call | None = node.prop("call")
        if call is not None and called_processes is not None and node.called_element:
            target = called_processes.get(node.called_element)
            if target is None:
                out.append(_error("B14", f"{node.id}: 호출 대상 {node.called_element}이 패키지에 없다"))
            else:
                unknown = [v for v in call.output.values() if v not in target]
                if unknown:
                    out.append(
                        _error("B14", f"{node.id}: 호출 대상의 outputs에 없는 것을 받는다", items=unknown)
                    )
    return out


def validate(
    process: BpmnProcess,
    *,
    task_type_locations: Mapping[str, Sequence[str]] | None = None,
    dmn_decisions: Mapping[str, DecisionIo] | None = None,
    called_processes: Mapping[str, Sequence[str]] | None = None,
    extension_task_vars: Callable[[ExtensionTask], Iterable[str]] | None = None,
) -> list[Violation]:
    """C14 검사 규칙 B1~B14. 오류와 경고를 **함께** 돌려준다 (`Violation.severity`).

    Studio 「실행 전 검사」와 Center 업로드가 같은 함수를 쓴다. 인자를 주지 않으면
    **정의 하나만 보고 할 수 있는 검사**만 한다.

    - `task_type_locations`: 확장 태스크 종류 → 실행 위치 (확장 호스트가 C13에서 읽어 준다).
      없으면 B6에서 확장 태스크를 건너뛴다. **플랫폼은 어느 태스크 종류가 PC 전용인지 스스로
      모른다** (ADR-0018).
    - `dmn_decisions`: 결정 id → 입력·출력 이름. 없으면 B14의 DMN 대조를 건너뛴다.
    - `called_processes`: `calledElement` → 그 BPM 프로세스의 `outputs`. 없으면 호출 대조를 건너뛴다.

    여기서 하지 않는 것:
    - **확장 태스크의 속 내용** (`chk:task`의 JSON). 그 확장의 계약이 검사한다 — 예를 들어 UI
      태스크 스텝의 `action`이 C10 동작 목록에 있는지는 UI 자동화 확장이 본다 (ADR-0018).
    - 식 언어의 문법·도우미 함수 이름 (C14 기본 규칙 6 — 목록은 M3에서 정한다).
    """
    return [
        *_check_b1_b2(process),
        *_check_b3(process),
        *_check_b4_b5(process),
        *_check_b6(process, task_type_locations),
        *_check_b7(process),
        *_check_b8(process),
        *_check_b9_b10(process),
        *_check_b11(process, extension_task_vars),
        *_check_b12(process),
        *_check_b13(process),
        *_check_b14(process, dmn_decisions, called_processes),
    ]


def blocking(violations: Iterable[Violation]) -> list[Violation]:
    """막는 것만 (경고는 뺀다). Studio 「실행 전 검사」가 이것으로 실행을 막는다."""
    return [v for v in violations if v.blocks]
