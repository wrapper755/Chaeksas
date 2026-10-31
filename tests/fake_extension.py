"""시험용 내장 확장 하나의 코드 — 태스크 수행기·편집기·사전 점검 (ADR-0018).

저장소에는 **확장이 하나도 없다** (ADR-0114 — UI 자동화 확장을 걷었다). 그래서 「호스트가 정의를
읽고 `entry`를 풀어 모양을 본다」를 보려면 가짜 하나가 필요하다. 확장 호스트는 `root` 밖을
가리키지 못하게 하므로 이 모듈이 **그 확장의 패키지 자리**를 맡는다 (`root="fake_extension"`).

**Qt를 쓰지 않는다** — 편집기의 위젯은 아무 객체다 (호스트는 모양만 본다).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from chaeksas.extension_api import ExtensionContext, Finding, PreflightTarget, TaskContext, TaskOutcome

#: 확장 id와 그 「패키지」 — 호스트에 넣을 때 쓴다.
EXTENSION_ID = "fake-builtin"
ROOT = "fake_extension"

#: 이 확장의 정의 (C13). 태스크 종류 하나·편집기·사전 점검·리소스 갈래·콘솔 화면.
DEFINITION: dict[str, Any] = {
    "schema": 2,
    "id": EXTENSION_ID,
    "version": "0.1.0",
    "name": "시험용 확장",
    "publisher": "Chaeksas",
    "tier": "builtin",
    "api": ">=2,<3",
    "contributes": {
        "task_types": [
            {
                "id": "fake_task",
                "label": "시험 태스크",
                "editor": {"kind": "builtin", "entry": "fake_extension:FakeTaskEditor"},
                "executor": {"entry": "fake_extension:FakeTaskExecutor"},
                "run_locations": ["pc"],
            }
        ],
        "preflight": [{"id": "always-ok", "entry": "fake_extension:FakePreflight"}],
        "studio.resource_views": [{"id": "forms", "label": "서식", "resource_type": "fake_form"}],
        "console.pages": [{"id": "overview", "label": "개요", "module": "fake-builtin/overview"}],
    },
}


def definition_bytes() -> bytes:
    return json.dumps(DEFINITION).encode("utf-8")


class FakeTaskExecutor:
    """`extension_api.TaskExecutor` — 받은 속성을 그대로 돌려준다."""

    def execute(self, ctx: TaskContext) -> TaskOutcome:
        return TaskOutcome(outputs=dict(ctx.properties))


class FakeTaskEditor:
    """`extension_api.TaskEditor` — 위젯 대신 아무 객체."""

    def __init__(self) -> None:
        self._values: dict[str, Any] = {}

    def widget(self, ctx: ExtensionContext) -> object:
        return object()

    def load(self, properties: Mapping[str, Any]) -> None:
        self._values = dict(properties)

    def dump(self) -> Mapping[str, Any]:
        return dict(self._values)


class FakePreflight:
    """`extension_api.PreflightCheck` — 아무것도 찾지 않는다."""

    def check(self, target: PreflightTarget) -> Sequence[Finding]:
        return ()


#: 업무 예제의 그림 폴더 (생성물이다 — 읽기만 한다).
EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples" / "bpmn"
#: 이 확장의 태스크를 쓰는 그림 하나의 예제 id (`drawing()`이 만든다).
DRAWING = "fake_task_pc"
_MANUAL = """<bpmn:manualTask id="Manual_Paper" name="용지 넣기">"""


def drawing(source: Path) -> Path:
    """**이 확장의 태스크를 쓰는 PC 그림**을 `source/<DRAWING>.bpmn`에 쓴다 — 예제 폴더 모양이다.

    업무 예제에는 확장 태스크를 쓰는 것이 지금 없다 (ADR-0114) — FX-19의 확인 자리를 `fake_task`로
    바꾼다. 요소 id는 그대로 둔다(그림 좌표가 따라온다). `Workspace.import_example(source, DRAWING)`.
    """
    text = (EXAMPLES / "fx19_manual_task_pc.bpmn").read_text(encoding="utf-8")
    head, rest = text.split(_MANUAL, 1)
    body, tail = rest.split("</bpmn:manualTask>", 1)
    flows = body[body.index("<bpmn:incoming>"):]
    task = (
        f'<bpmn:serviceTask id="Manual_Paper" name="시험 태스크">'
        f'<bpmn:extensionElements><chk:task type="fake_task" extension="{EXTENSION_ID}">{{}}</chk:task>'
        f"</bpmn:extensionElements>{flows}</bpmn:serviceTask>"
    )
    made = head.replace("Proc_fx19_manual_task_pc", f"Proc_{DRAWING}") + task + tail
    source.mkdir(parents=True, exist_ok=True)
    (source / f"{DRAWING}.bpmn").write_text(made, encoding="utf-8")
    return source
