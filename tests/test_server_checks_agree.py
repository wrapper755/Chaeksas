"""「서버에서 할 수 없다」는 두 자리가 **같은 답**을 낸다 — 그림 검사 C14 B6 ↔ 패키지 검사 C1 R2.

둘은 같은 규칙(ADR-0015)을 **따로 적는다**: B6는 노드를 보고(`server_blockers`), R2는 Studio가
그림에서 모은 매니페스트를 본다(`requires.domains`·`task_types`·`human`). 한쪽에만 항목이 더해지면
「시험 실행은 되는데 올리기만 막힌다」가 된다 — 확인(manualTask)이 그렇게 B6에서 빠져 있었다.

업무 예제 전부와 **노드 하나짜리 그림들**(막히는 종류마다 하나 — 예제가 늘 밟지는 않는다: 확인은
예제에서 늘 `location: field`를 적어 「현장 결재」 규칙이 대신 잡았다)을 **서버로 친 채** 견준다.
`server_blockers`는 실행 위치를 보지 않고, 매니페스트는 실행 위치만 `server`로 바꿔 R2에 넣는다
(나머지 칸은 그림에서 모은 그대로다).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chaeksas.contracts.bpmn_ext import server_blockers
from chaeksas.contracts.manifest import validate
from chaeksas.core.extensions import ExtensionHost
from chaeksas.studio.dialogs import example_ids
from chaeksas.studio.packaging import build_manifest
from chaeksas.studio.workspace import BpmProcess, Workspace

EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples" / "bpmn"


@pytest.fixture(scope="module")
def locations() -> dict[str, list[str]]:
    """깔린 확장이 말하는 태스크 종류별 실행 위치 — B6·R2에 **같은 표**를 준다 (Studio처럼)."""
    return ExtensionHost().task_type_locations()


@pytest.fixture(scope="module")
def imported(tmp_path_factory: pytest.TempPathFactory) -> dict[str, BpmProcess]:
    space = Workspace(tmp_path_factory.mktemp("examples")).ensure()
    return {example: space.import_example(EXAMPLES, example) for example in example_ids(EXAMPLES)}


def _probe(node: str) -> str:
    """노드 하나를 시작·끝 사이에 둔 그림 (실행 위치는 적지 않는다 — 서버로 친다)."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
  xmlns:bpm="urn:chaeksas:bpmn:1" id="Defs_p" targetNamespace="urn:chaeksas:test">
  <bpmn:process id="Proc_p" name="probe" isExecutable="true">
    <bpmn:startEvent id="Start" />{node}<bpmn:endEvent id="End" />
    <bpmn:sequenceFlow id="F0" sourceRef="Start" targetRef="N" />
    <bpmn:sequenceFlow id="F1" sourceRef="N" targetRef="End" />
  </bpmn:process>
</bpmn:definitions>"""


def _task(kind: str, ext: str) -> str:
    return f'<bpmn:{kind} id="N"><bpmn:extensionElements>{ext}</bpmn:extensionElements></bpmn:{kind}>'


def probes(locations: dict[str, list[str]]) -> dict[str, str]:
    """막히는 종류마다 하나, 막히지 않는 것도 섞는다."""
    found = {
        "확인-위치없음": _task("manualTask", '<bpm:approval>{"title": "확인"}</bpm:approval>'),
        "확인-현장": _task("manualTask", '<bpm:approval>{"title": "확인", "location": "field"}</bpm:approval>'),
        "결재-현장": _task("userTask", '<bpm:approval>{"title": "결재", "location": "field"}</bpm:approval>'),
        "결재-Center": _task("userTask", '<bpm:approval>{"title": "결재", "location": "center"}</bpm:approval>'),
        "결재-위치없음": _task("userTask", '<bpm:approval>{"title": "결재"}</bpm:approval>'),
        "AI-web": _task("serviceTask", '<bpm:aiTask>{"goal": "x", "domain": "web"}</bpm:aiTask>'),
        "AI-desktop": _task("serviceTask", '<bpm:aiTask>{"goal": "x", "domain": "desktop"}</bpm:aiTask>'),
        "AI-도메인없음": _task("serviceTask", '<bpm:aiTask>{"goal": "x"}</bpm:aiTask>'),
    }
    for task_type, where in sorted(locations.items()):
        extension = task_type.split(".")[0]
        body = f'<bpm:task type="{task_type}" extension="{extension}">{{}}</bpm:task>'
        found[f"확장-{task_type}-{'/'.join(where)}"] = _task("serviceTask", body)
    return found


@pytest.fixture(scope="module")
def probed(
    tmp_path_factory: pytest.TempPathFactory, locations: dict[str, list[str]]
) -> dict[str, BpmProcess]:
    root = tmp_path_factory.mktemp("probes")
    space = Workspace(root / "space").ensure()
    made = {}
    for index, (name, node) in enumerate(probes(locations).items()):
        drawing = root / f"probe{index}.bpmn"
        drawing.write_text(_probe(node), encoding="utf-8")
        made[name] = space.create(f"probe-{index}", first=drawing)
    return made


def b6_says_no(process: BpmProcess, locations: dict[str, list[str]]) -> bool:
    """패키지에 들어가는 정의 어느 하나라도 서버에서 못 하는 것이 있나 (실행 위치는 보지 않는다)."""
    return any(
        server_blockers(found.process, locations)
        for found in process.definitions
        if found.process is not None
    )


def r2_says_no(process: BpmProcess, locations: dict[str, list[str]]) -> bool:
    manifest = build_manifest(process, task_type_locations=locations)
    on_server = manifest.model_copy(update={"run_location": "server"})
    return any(v.rule == "R2" for v in validate(on_server))


def answers(processes: dict[str, BpmProcess], locations: dict[str, list[str]]) -> dict[str, dict[str, bool]]:
    return {
        name: {"B6": b6_says_no(process, locations), "R2": r2_says_no(process, locations)}
        for name, process in processes.items()
    }


def test_every_example_gets_the_same_answer_from_b6_and_r2(
    imported: dict[str, BpmProcess], locations: dict[str, list[str]]
) -> None:
    assert len(imported) >= 45, "예제를 찾지 못했다"
    apart = answers(imported, locations)
    disagree = {example: both for example, both in apart.items() if both["B6"] != both["R2"]}
    assert not disagree, f"B6와 R2가 다르게 답한다: {disagree}"
    # 견준 것이 「둘 다 통과」뿐이면 이 시험은 아무것도 지키지 않는다 — 막히는 쪽도 있어야 한다.
    assert any(both["B6"] for both in apart.values()), "서버에서 막히는 예제가 하나도 없다"


def test_each_kind_of_server_blocker_gets_the_same_answer(
    probed: dict[str, BpmProcess], locations: dict[str, list[str]]
) -> None:
    apart = answers(probed, locations)
    disagree = {name: both for name, both in apart.items() if both["B6"] != both["R2"]}
    assert not disagree, f"B6와 R2가 다르게 답한다: {disagree}"
    # 그림이 뜻대로 지어졌나 — 막혀야 할 것은 막히고 아닌 것은 지난다.
    for name in ("확인-위치없음", "확인-현장", "결재-현장", "AI-web", "AI-desktop"):
        assert apart[name]["B6"], name
    for name in ("결재-Center", "결재-위치없음", "AI-도메인없음"):
        assert not apart[name]["B6"], name
