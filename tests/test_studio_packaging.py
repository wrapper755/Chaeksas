"""Studio 패키지 내보내기 (M3 조각 3e-4) — 작업 폴더 → C1 패키지 zip.

거듭 보는 것 넷.

1. **매니페스트는 그림에서 모은다** — 사람이 도구·서비스 앱·결재 종류를 두 번 적지 않는다.
2. **`content_hash`는 받는 쪽이 다시 계산해 맞아야 한다** (C2) — `content_hash_zip`으로 본다.
3. **시험 케이스는 들어가지 않는다** (C1) — 작업 폴더에만 있다.
4. **실행 위치는 처음부터 들어간다** (C1 R1·ADR-0016 — 생략하면 서버).
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from chaeksas.contracts.bpmn_ext import read_process
from chaeksas.contracts.hashing import content_hash_zip
from chaeksas.contracts.manifest import KNOWN_TRIGGER_KINDS, Manifest, validate
from chaeksas.studio.packaging import (
    EXCLUDED,
    MANIFEST_NAME,
    PackageError,
    build_lib_manifest,
    build_manifest,
    check,
    collect_human,
    collect_requires,
    collect_triggers,
    default_lib_name,
    default_name,
    export,
    export_lib,
    gather,
    gather_lib,
)
from chaeksas.studio.workspace import BpmProcess, Definition, Workspace

EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples" / "bpmn"

#: 도구·서비스 앱·결재·DMN이 골고루 들어 있는 예제들.
RECONCILIATION = "bx01_invoice_reconciliation"
CREDIT = "bx06_bulk_credit_check"
EXPENSE = "bx03_expense_approval"
#: **확장 태스크**(UI 태스크)가 있는 예제 — 실행 위치는 확장 정의만 안다 (C13).
EXTENSION = "bx04_tax_invoice_issue"
#: 확장 호스트가 주는 표 (`ExtensionHost.task_type_locations()`).
UI_TASK_ON_PC = {"ui_task": ["pc"]}

#: 시작 이벤트 다섯을 한 그림에 — C1 `triggers[].kind`가 BPMN 이벤트 정의와 1:1인지 본다.
#: 메시지·신호는 **id가 아니라 `name`**이 나가야 한다 (C12).
FIVE_START_EVENTS = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Defs">
  <bpmn:message id="Msg_order" name="order_arrived" />
  <bpmn:signal id="Sig_branch" name="branch_done" />
  <bpmn:process id="starts" name="시작 이벤트 다섯">
    <bpmn:startEvent id="S_plain" />
    <bpmn:startEvent id="S_message">
      <bpmn:messageEventDefinition messageRef="Msg_order" />
    </bpmn:startEvent>
    <bpmn:startEvent id="S_timer">
      <bpmn:timerEventDefinition><bpmn:timeCycle>0 9 * * 1-5</bpmn:timeCycle></bpmn:timerEventDefinition>
    </bpmn:startEvent>
    <bpmn:startEvent id="S_conditional">
      <bpmn:conditionalEventDefinition />
    </bpmn:startEvent>
    <bpmn:startEvent id="S_signal">
      <bpmn:signalEventDefinition signalRef="Sig_branch" />
    </bpmn:startEvent>
  </bpmn:process>
</bpmn:definitions>
"""


def imported(tmp_path: Path, example: str) -> BpmProcess:
    return Workspace(tmp_path / "작업").ensure().import_example(EXAMPLES, example)


# ─────────────────────────── 그림에서 모으기 ───────────────────────────


def test_the_manifest_is_collected_from_the_drawing(tmp_path: Path) -> None:
    """AI 태스크의 영역·도구가 `requires`로 간다 — 사람이 다시 적지 않는다."""
    found = collect_requires(imported(tmp_path, RECONCILIATION))
    assert found.domains == ["doc"]
    assert "pdf_text_tool" in found.tools and "excel_parser_tool" in found.tools


def test_a_mail_task_asks_for_smtp(tmp_path: Path) -> None:
    """`chk:email`이 있으면 `requires.settings`에 `smtp`가 간다 (C1, ADR-0059 §4).

    적어 두지 않으면 **사전 점검이 「SMTP가 없다」를 미리 말할 수 없다** — 현장은 메일을
    보내려는 순간에야 안다. 09-gaps §3-11이 이 자리였다.
    """
    assert collect_requires(imported(tmp_path, "fx07_email")).settings == ["smtp"]
    # BX-01도 메일로 끝난다 — 그래서 함께 묻는다.
    assert collect_requires(imported(tmp_path, RECONCILIATION)).settings == ["smtp"]
    # 보내지 않는 그림은 **묻지 않는다** (갖추지 않은 설정으로 막히면 안 된다).
    assert collect_requires(imported(tmp_path, "fx03b_amount_branch")).settings == []


def test_a_service_app_call_becomes_a_requirement_without_a_key_reference(tmp_path: Path) -> None:
    """줄은 C15 토픽과 작업뿐이다 — **키도 키 참조도 없다** (ADR-0102)."""
    found = collect_requires(imported(tmp_path, CREDIT))
    (app,) = found.service_apps
    assert app.app_id == "ext-credit"
    assert app.operations == ["lookup"]
    assert app.to_json_dict() == {"app_id": "ext-credit", "operations": ["lookup"]}


def test_a_task_types_run_locations_come_from_the_extension_table(tmp_path: Path) -> None:
    """실행 위치는 **확장 정의만** 안다 (C13 `task_types[].run_locations`, ADR-0018).

    표에 없으면 **넣지 않는다** — 빈 목록을 적으면 C1 R2가 「서버에서 안 된다」로 읽는다
    (C3 `queued_s`·C4 `key_expires_at`과 같은 결: 아는 쪽이 주고, 모르면 넣지 않는다).
    """
    made = imported(tmp_path, EXTENSION)
    (need,) = collect_requires(made).task_types
    assert (need.id, need.extension) == ("ui_task", "ui-automation")
    assert need.run_locations is None, "모르는 것을 빈 목록으로 적었다"

    (told,) = collect_requires(made, task_type_locations=UI_TASK_ON_PC).task_types
    assert told.run_locations == ["pc"]


def test_a_server_process_with_an_extension_task_is_not_falsely_rejected(tmp_path: Path) -> None:
    """**올리기가 막히던 버그** (C1 R2) — 「확장 태스크가 있다」만으로 422를 받으면 안 된다.

    빈 목록은 `"server" not in []`이라 참이어서, 실행 위치가 server인 Bot에 확장 태스크가
    하나라도 있으면 **그 확장이 서버를 지원하든 말든** Center 업로드가 거부했다. 설계자가
    보는 것은 `manifest_invalid` + 태스크 종류 이름뿐이라 고칠 데를 알 수 없다.
    """
    made = imported(tmp_path, EXTENSION)
    entry = made.entry_definition
    assert entry is not None
    entry.path.write_text(
        entry.path.read_text(encoding="utf-8").replace(
            '"run_location": "pc"', '"run_location": "server"'
        ),
        encoding="utf-8",
    )
    server = Workspace(tmp_path / "작업").read(made.folder, made.group)
    assert build_manifest(server).run_location == "server"

    # 모를 때: 막지 않는다 (확장을 깔지 않은 PC에서도 패키지를 만들 수 있다).
    unknown = build_manifest(server)
    assert [v.code for v in validate(unknown)] == []
    # 서버를 지원한다고 선언했을 때: 막지 않는다.
    ok = build_manifest(server, task_type_locations={"ui_task": ["pc", "server"]})
    assert [v.code for v in validate(ok)] == []
    # PC 전용이라고 선언했을 때: **막는다.** 그래야 설계자가 Studio에서 안다.
    caught = validate(build_manifest(server, task_type_locations=UI_TASK_ON_PC))
    assert [v.code for v in caught] == ["server_incompatible"]
    assert "task_types:ui_task" in caught[0].items


#: PC 위임 하나만 든 서버 그림 (ADR-0062). 예제 묶음에는 아직 위임이 없어 여기서 만든다.
#: `calledElement`는 **읽는 사람을 위한 것**이라 패키지에 그 정의가 없어도 된다.
DELEGATING = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
  xmlns:chk="urn:chaeksas:bpmn:1" id="Defs_d" targetNamespace="urn:chaeksas:test">
  <bpmn:process id="Proc_fx03b_amount_branch" name="위임" isExecutable="true">
    <bpmn:extensionElements><chk:process>{"run_location": "server"}</chk:process></bpmn:extensionElements>
    <bpmn:startEvent id="Start" />
    <bpmn:callActivity id="Call_Erp" calledElement="Proc_erp_input">
      <bpmn:extensionElements><chk:call>{"delegate":
        {"bpm_process_id": "fin.erp-input", "version": "1.2.0"}, "output": {"결과": "결과코드"}}</chk:call>
      </bpmn:extensionElements>
    </bpmn:callActivity>
    <bpmn:endEvent id="End" />
    <bpmn:sequenceFlow id="F1" sourceRef="Start" targetRef="Call_Erp" />
    <bpmn:sequenceFlow id="F2" sourceRef="Call_Erp" targetRef="End" />
  </bpmn:process>
</bpmn:definitions>
"""


def delegating(tmp_path: Path) -> BpmProcess:
    """위임 그림을 작업 폴더에 넣어 읽는다 (진입 정의를 통째로 바꿔 쓴다)."""
    made = imported(tmp_path, "fx03b_amount_branch")
    entry = made.entry_definition
    assert entry is not None
    entry.path.write_text(DELEGATING, encoding="utf-8")
    return Workspace(tmp_path / "작업").read(made.folder, made.group)


def test_a_delegated_call_is_not_a_lib(tmp_path: Path) -> None:
    """**PC 위임은 `libs`가 아니다** ([ADR-0062](../docs/decisions/0062-pc-delegation.md)).

    복사해 넣는 것이 아니라 **따로 배포된 Bot**이다. `libs`에 넣으면 없는 공유 BPM 프로세스를
    요구하는 패키지가 되어 설치가 막히고, R3이 「PC 정의를 부른다」고 읽는다.
    """
    found = collect_requires(delegating(tmp_path))
    assert found.delegations == ["fin.erp-input@1.2.0"]
    assert found.libs == [], "위임을 공유 BPM 프로세스로 셌다"


def test_a_delegating_package_passes_the_manifest_rules(tmp_path: Path) -> None:
    """서버 Bot이면 R10이 입을 닫는다 — 올리는 길이 막히지 않는다 (C1)."""
    made = build_manifest(delegating(tmp_path))
    assert made.run_location == "server"
    assert made.requires.delegations == ["fin.erp-input@1.2.0"]
    assert validate(made) == []


def test_an_open_version_delegation_keeps_the_id_alone(tmp_path: Path) -> None:
    """판을 비우면 **배포된 판**이라는 뜻이라 여기서 지어내지 않는다 (C14)."""
    made = imported(tmp_path, "fx03b_amount_branch")
    entry = made.entry_definition
    assert entry is not None
    entry.path.write_text(DELEGATING.replace(', "version": "1.2.0"', ""), encoding="utf-8")
    opened = Workspace(tmp_path / "작업").read(made.folder, made.group)
    assert collect_requires(opened).delegations == ["fin.erp-input"]


def test_approvals_say_what_kind_of_human_is_needed(tmp_path: Path) -> None:
    found = collect_human(imported(tmp_path, EXPENSE))
    assert found.approval_center is True


def test_the_run_location_is_in_the_manifest_from_the_start(tmp_path: Path) -> None:
    """생략하면 서버다 (C1 R1·ADR-0016). 「나중에 정한다」가 없다."""
    manifest = build_manifest(imported(tmp_path, EXPENSE))
    assert manifest.run_location in ("pc", "server")
    assert manifest.entry and manifest.process_id


def test_a_timer_start_event_is_a_timer_trigger(tmp_path: Path) -> None:
    """`schedule`이 아니라 **C1에 적힌 `timer`**다 — 읽는 쪽이 `timer`를 기다린다.

    타이머 식은 `name`이 아니라 `expression`에 있다 (`name`은 메시지 이름 자리 — C12).
    """
    manifest = build_manifest(imported(tmp_path, RECONCILIATION))
    assert [t.kind for t in manifest.triggers] == ["timer"]
    assert manifest.triggers[0].expression == "0 9 1 * *"
    assert manifest.triggers[0].name is None
    assert validate(manifest) == []


def test_a_message_start_event_carries_the_name_the_sender_uses(tmp_path: Path) -> None:
    """**id가 아니라 이름이다** — 외부 시스템은 `bpmn:message name`으로 보낸다 (C12).

    그림에는 `messageRef="Msg_expense_request"`로 적혀 있지만, 그 id를 매니페스트에 싣고
    있던 동안에는 그것을 보고 보낸 메시지가 **기다리는 실행을 깨우지 못했다**.
    """
    manifest = build_manifest(imported(tmp_path, EXPENSE))
    assert [(t.kind, t.name) for t in manifest.triggers] == [("message", "expense_request")]
    assert manifest.triggers[0].expression is None


def test_every_start_event_maps_to_a_kind_the_contract_lists() -> None:
    """다섯을 한 그림에 두고 본다 — **옮기는 쪽이 지어낸 이름을 쓰지 않는다** (C1 R9).

    조건·신호 시작은 schema 1의 범위 밖이지만(C14) `none`으로 뭉개지 않는다 — 「작업 지시로
    시작한다」고 적어 주면 왜 안 도는지 아무도 모른다.
    """
    read = Definition(path=Path("starts.bpmn"), process=read_process(FIVE_START_EVENTS))
    found = collect_triggers(read)
    assert [(t.kind, t.name, t.expression) for t in found] == [
        ("none", None, None),
        ("message", "order_arrived", None),
        ("timer", None, "0 9 * * 1-5"),
        ("conditional", None, None),
        ("signal", "branch_done", None),
    ]
    assert {t.kind for t in found} <= KNOWN_TRIGGER_KINDS


def test_no_example_produces_a_trigger_kind_outside_the_contract() -> None:
    """예제 50개를 옮겨 본다 — 갈라지면 여기가 먼저 깨진다 (올라간 뒤에 알면 늦다)."""
    seen = set()
    for bpmn in sorted(EXAMPLES.glob("*.bpmn")):
        read = Definition(path=bpmn, process=read_process(bpmn.read_text(encoding="utf-8")))
        seen |= {t.kind for t in collect_triggers(read)}
    assert seen, "예제를 하나도 읽지 못했다"
    assert seen <= KNOWN_TRIGGER_KINDS


# ─────────────────────────── 무엇이 들어가는가 ───────────────────────────


def test_the_dmn_next_to_the_drawing_goes_in(tmp_path: Path) -> None:
    files = gather(imported(tmp_path, CREDIT))
    assert "process/credit_grade.dmn" in files
    assert f"process/{CREDIT}.bpmn" in files


def test_test_cases_do_not_go_in(tmp_path: Path) -> None:
    """케이스는 작업 폴더에만 있다 (C1) — 배포된 Bot이 시험 입력을 들고 다니지 않는다."""
    made = imported(tmp_path, EXPENSE)
    case_file = made.folder / "cases" / f"{EXPENSE}.cases.json"
    case_file.parent.mkdir(parents=True, exist_ok=True)
    case_file.write_text('{"schema": 1, "cases": []}', encoding="utf-8")

    files = gather(made)
    assert case_file.is_file()
    assert not [name for name in files if name.split("/")[0] in EXCLUDED]


# ─────────────────────────── zip과 해시 ───────────────────────────


def test_the_package_hash_is_what_the_receiving_side_computes(tmp_path: Path) -> None:
    """Center가 `content_hash_zip`으로 다시 계산한다 (C2) — 여기서 맞춰 둔다."""
    made = imported(tmp_path, CREDIT)
    written = export(made, tmp_path / default_name(made))

    with zipfile.ZipFile(written) as zf:
        manifest = Manifest.model_validate_json(zf.read(MANIFEST_NAME))
    assert manifest.content_hash == content_hash_zip(written)


def test_the_manifest_is_readable_utf8_json(tmp_path: Path) -> None:
    """한글 이름이 `\\uXXXX`로 깨져 나가지 않는다 (사람이 읽는 파일이다)."""
    made = imported(tmp_path, EXPENSE)
    written = export(made, tmp_path / default_name(made))
    with zipfile.ZipFile(written) as zf:
        raw = zf.read(MANIFEST_NAME).decode("utf-8")
    assert json.loads(raw)["name"]
    assert "\\u" not in raw


def test_the_name_is_id_and_version(tmp_path: Path) -> None:
    made = imported(tmp_path, EXPENSE)
    assert default_name(made) == f"{made.id}-{made.version}.zip"


def test_export_makes_the_parent_folder(tmp_path: Path) -> None:
    made = imported(tmp_path, EXPENSE)
    written = export(made, tmp_path / "없던" / "폴더" / default_name(made))
    assert written.is_file()


# ─────────────────────────── 막는 것 ───────────────────────────


def test_a_process_without_a_definition_cannot_be_packaged(tmp_path: Path) -> None:
    made = Workspace(tmp_path / "작업").ensure().create("empty-one", name="빈 것")
    with pytest.raises(PackageError, match="진입 정의"):
        export(made, tmp_path / "empty-one.zip")


def test_a_missing_entry_file_blocks_the_export(tmp_path: Path) -> None:
    """매니페스트만 보는 `validate()`는 모르는 것 — 만드는 쪽에서 잡는다."""
    made = imported(tmp_path, EXPENSE)
    manifest = build_manifest(made)
    blocking = [v for v in check(made, manifest, {}) if v.blocks]
    assert blocking and "진입 정의가 패키지에 없다" in blocking[0].message


def test_the_inputs_go_into_the_manifest(tmp_path: Path) -> None:
    """작업 지시 화면(CON-05)이 입력 칸을 그린다 — `chk:process.inputs`를 그대로 옮긴다 (C1)."""
    made = build_manifest(imported(tmp_path, RECONCILIATION))
    names = [one.name for one in made.inputs]
    assert names[:2] == ["대상월", "청구서폴더"]
    first = made.inputs[0]
    assert (first.type, first.required) == ("string", False)
    assert first.description and "지난달" in first.description


# ─────────── 공유 BPM 프로세스 패키지 (STU-12·C1 `provides`) ───────────

#: 호출(`callActivity`)이 있는 예제 — 가져오면 호출 대상까지 두 정의가 된다.
CALLER = "fx03_call_mapping"
CALLER_FILE = f"{CALLER}.bpmn"
CALLEE_FILE = "fx03b_amount_branch.bpmn"


def picked(made: BpmProcess, *names: str) -> list[Definition]:
    return [d for d in made.definitions if d.path.name in names]


def test_a_shared_package_is_not_a_bot(tmp_path: Path) -> None:
    """`process_lib`에는 진입이 없다 — 스스로 돌지 않고 남이 부르는 정의를 담는다 (C1 R1)."""
    made = imported(tmp_path, CALLER)
    manifest = build_lib_manifest(made, picked(made, CALLEE_FILE))
    assert manifest.kind == "process_lib"
    assert (manifest.entry, manifest.process_id, manifest.run_location) == (None, None, None)
    assert not [v for v in validate(manifest) if v.blocks], "C1이 막는다"


def test_a_shared_package_says_what_it_provides(tmp_path: Path) -> None:
    """CON-06 「제공 정의」가 읽는 칸을 **그림에서** 채운다 — 사람이 두 번 적지 않는다."""
    made = imported(tmp_path, CALLER)
    manifest = build_lib_manifest(made, picked(made, CALLEE_FILE))
    assert manifest.provides is not None
    (one,) = manifest.provides.processes
    assert one.process_id == "Proc_fx03b_amount_branch"
    assert one.file == f"process/{CALLEE_FILE}"
    assert one.ai_tasks == 0 and one.human is not None


def test_reads_and_writes_are_what_the_definition_declared(tmp_path: Path) -> None:
    """**선언한 것**을 옮긴다 (`chk:process.inputs`·`outputs`) — 그림에서 어림하지 않는다.

    호출(`chk:call`)의 받는 값을 보는 B14도 선언한 `outputs`와 맞춰 보니 약속은 거기에 있다.
    확장 태스크가 만드는 변수는 플랫폼이 모르므로(ADR-0018) 어림한 값을 「부르는 쪽이 줘야
    하는 것」으로 보이면 거짓말이 된다.
    """
    made = imported(tmp_path, CALLER)
    callee = picked(made, CALLEE_FILE)[0]
    assert callee.process is not None
    manifest = build_lib_manifest(made, [callee])
    assert manifest.provides is not None
    (one,) = manifest.provides.processes
    assert one.reads == [decl.name for decl in callee.process.info.inputs]
    assert one.writes == list(callee.process.info.outputs)
    assert one.reads, "이 예제는 입력을 선언한다 (시험이 빈 목록을 통과시키지 않게)"


def test_only_the_picked_definitions_go_in(tmp_path: Path) -> None:
    """고르지 않은 BPMN은 빠지고, 결정(DMN)은 **가려내지 않고 모두** 담는다."""
    made = imported(tmp_path, CALLER)
    files = gather_lib(made, picked(made, CALLEE_FILE))
    assert f"process/{CALLEE_FILE}" in files
    assert f"process/{CALLER_FILE}" not in files
    assert [name for name in gather(made) if name.endswith(".dmn")] == [
        name for name in files if name.endswith(".dmn")
    ]


def test_calling_a_definition_you_did_not_pick_is_blocked(tmp_path: Path) -> None:
    """그대로 두면 같은 작업 폴더의 id가 `requires.libs`에 「바깥 패키지」로 적힌다 — 받는 쪽이 없는 것을 찾는다."""
    made = imported(tmp_path, CALLER)
    with pytest.raises(PackageError, match="고르지 않은 정의를 부른다"):
        export_lib(made, picked(made, CALLER_FILE), tmp_path / "lib.zip")


def test_picking_the_caller_and_the_callee_together_works(tmp_path: Path) -> None:
    made = imported(tmp_path, CALLER)
    both = picked(made, CALLER_FILE, CALLEE_FILE)
    written = export_lib(made, both, tmp_path / "밖" / default_lib_name(made))
    assert written.is_file()
    manifest = Manifest.model_validate_json(
        zipfile.ZipFile(written).read(MANIFEST_NAME).decode("utf-8")
    )
    assert manifest.provides is not None
    assert len(manifest.provides.processes) == 2
    assert manifest.requires.libs == [], "안에 있는 것을 바깥 패키지로 적지 않는다"
    # 받는 쪽이 다시 계산해 맞아야 한다 (C2·R6).
    assert manifest.content_hash == content_hash_zip(written)


def test_a_shared_package_needs_at_least_one_definition(tmp_path: Path) -> None:
    made = imported(tmp_path, CALLER)
    with pytest.raises(PackageError, match="하나 이상"):
        build_lib_manifest(made, [])
