"""패키지로 내보내기 — 작업 폴더 → C1 패키지 zip (STU-01 파일 메뉴).

매니페스트는 **그림에서 모은다** — `chk:process`·각 태스크의 `chk:*`를 읽어 「무엇이 필요한가」를
적는다. 사람이 두 번 적지 않게 (C14 §프로세스 수준: 「패키지 매니페스트는 빌드 때 이것을 모아
만든다」).

**비밀은 들어가지 않는다** (C1 R5) — 서비스 앱 키는 **참조 이름**만 간다. 그것을 빌드가 보장하고,
여기서도 한 번 더 본다.

**시험 케이스는 넣지 않는다** (C1) — 작업 폴더에는 있지만 패키지에는 없다.
"""

from __future__ import annotations

import json
import zipfile
from collections.abc import Collection, Sequence
from datetime import UTC, datetime
from pathlib import Path

from chaeksas.contracts import Violation
from chaeksas.contracts.bpmn_ext import BpmnProcess
from chaeksas.contracts.hashing import content_hash_from_files
from chaeksas.contracts.manifest import (
    Built,
    ExtensionNeed,
    HumanNeeds,
    Manifest,
    ManifestInput,
    ProvidedProcess,
    Provides,
    Requires,
    ServiceAppNeed,
    TaskTypeNeed,
    Trigger,
    validate,
)
from chaeksas.studio.workspace import BpmProcess, Definition

#: 패키지에 들어가는 폴더 (C1 패키지 구성). 작업 폴더가 같은 이름을 쓴다.
INCLUDED = ("process", "memory", "libs")
MANIFEST_NAME = "manifest.json"
#: 시험 케이스·실행 기록은 넣지 않는다 (C1).
EXCLUDED = ("cases", "runs", "outputs")

SPEC_VERSION = 1


class PackageError(ValueError):
    """패키지를 만들 수 없다 (진입 정의가 없다·검사가 막는다)."""


def _entry(process: BpmProcess) -> Definition:
    found = process.entry_definition
    if found is None or found.process is None:
        raise PackageError("진입 정의를 읽지 못했습니다 — 먼저 저장하세요.")
    return found


def collect_requires(
    process: BpmProcess,
    *,
    definitions: Sequence[Definition] | None = None,
    inside: Collection[str] | None = None,
) -> Requires:
    """그림에서 「무엇이 필요한가」를 모은다 (C1 `requires`).

    `definitions`를 주면 **그 정의들만** 본다 (공유 BPM 프로세스 패키지는 고른 정의만 담는다).
    `inside`는 「이 패키지 안에 있는 정의 id」로, 그 밖을 부르면 `libs`가 된다.
    """
    domains: set[str] = set()
    tools: set[str] = set()
    apps: dict[str, ServiceAppNeed] = {}
    task_types: dict[str, TaskTypeNeed] = {}
    extensions: dict[str, ExtensionNeed] = {}
    libs: set[str] = set()
    within = set(process.processes()) if inside is None else set(inside)

    for definition in process.definitions if definitions is None else definitions:
        found = definition.process
        if found is None:
            continue
        for need in found.info.extensions:
            extensions[need.id] = need
        for node in found.all_nodes():
            ai = node.prop("aiTask")
            if ai is not None:
                domains.add(ai.domain)
                tools.update(ai.tools)
            call = node.prop("serviceCall")
            if call is not None:
                key_ref = call.key_ref or found.info.service_keys.get(call.app_id, "")
                before = apps.get(call.app_id)
                operations = sorted({*(before.operations if before else []), call.operation})
                task_keys = sorted(
                    {*(before.task_key_refs if before else []), *([call.key_ref] if call.key_ref else [])}
                )
                apps[call.app_id] = ServiceAppNeed(
                    app_id=call.app_id,
                    operations=operations,
                    key_ref=(before.key_ref if before else "") or key_ref,
                    task_key_refs=task_keys,
                )
            task = node.prop("task")
            if task is not None:
                # **어느 실행 위치에서 되는지는 확장이 안다** (ADR-0018) — 모르면 비워 둔다.
                task_types[task.type] = TaskTypeNeed(
                    id=task.type, extension=task.extension, run_locations=[]
                )
            if node.called_element and node.called_element not in within:
                libs.add(node.called_element)

    return Requires(
        domains=sorted(domains),
        tools=sorted(tools),
        service_apps=[apps[k] for k in sorted(apps)],
        task_types=[task_types[k] for k in sorted(task_types)],
        extensions=[extensions[k] for k in sorted(extensions)],
        libs=sorted(libs),
    )


def human_of(found: BpmnProcess) -> HumanNeeds:
    """정의 하나의 사람 개입 종류. 공유 정의마다도 적는다 (C1 `provides.processes[].human`)."""
    center = field = confirmation = False
    for node in found.all_nodes():
        approval = node.prop("approval")
        if approval is None:
            continue
        if node.kind == "manualTask":
            confirmation = True
        elif approval.location == "field":
            field = True
        else:
            center = True
    return HumanNeeds(approval_center=center, approval_field=field, confirmation=confirmation)


def collect_human(process: BpmProcess, *, definitions: Sequence[Definition] | None = None) -> HumanNeeds:
    """사람 개입 종류 (C1 `human`) — 서버 검사가 쓴다. 정의마다 합친다."""
    out = HumanNeeds()
    for definition in process.definitions if definitions is None else definitions:
        if definition.process is None:
            continue
        here = human_of(definition.process)
        out = HumanNeeds(
            approval_center=out.approval_center or here.approval_center,
            approval_field=out.approval_field or here.approval_field,
            confirmation=out.confirmation or here.confirmation,
        )
    return out


def collect_provides(definitions: Sequence[Definition]) -> Provides:
    """공유 BPM 프로세스 패키지가 제공하는 정의들 (C1 `provides.processes`). CON-06이 읽는다.

    **`reads`·`writes`는 선언한 것이다** — `chk:process.inputs`·`outputs`를 그대로 옮긴다.
    그림에서 어림하지 않는다: 확장 태스크가 만드는 변수는 플랫폼이 모르고(ADR-0018) 어림한 값을
    「부르는 쪽이 줘야 하는 것」으로 보이면 거짓말이 된다. 호출(`chk:call`)의 받는 값을 검사하는
    B14도 **선언한 `outputs`**와 맞춰 보니 약속은 거기에 있다.

    `description`은 비운다 — 정의에 설명 칸이 없다 (C14 `chk:process`).
    """
    out = []
    for definition in definitions:
        found = definition.process
        if found is None:
            continue
        out.append(
            ProvidedProcess(
                process_id=found.id,
                file=f"process/{definition.path.name}",
                name=found.name or found.id,
                reads=[one.name for one in found.info.inputs],
                writes=list(found.info.outputs),
                run_location=found.info.run_location,
                ai_tasks=sum(1 for node in found.all_nodes() if node.prop("aiTask") is not None),
                human=human_of(found),
            )
        )
    return Provides(processes=out)


def collect_triggers(entry: Definition) -> list[Trigger]:
    """시작 방법 (C1 `triggers`) — 시작 이벤트의 정의에서 읽는다."""
    if entry.process is None:
        return []
    out = []
    for node in entry.process.nodes:
        if node.kind != "startEvent":
            continue
        if "timerEventDefinition" in node.event_definitions:
            out.append(Trigger(kind="schedule", name=node.timer.value if node.timer else None))
        elif "messageEventDefinition" in node.event_definitions:
            out.append(Trigger(kind="message", name=node.message_ref))
        else:
            out.append(Trigger(kind="manual"))
    return out


def build_manifest(process: BpmProcess, *, by: str = "studio", core: str = "0.1.0") -> Manifest:
    """C1 매니페스트 (`content_hash`는 아직 비어 있다 — 파일을 모은 뒤 채운다)."""
    entry = _entry(process)
    assert entry.process is not None
    return Manifest(
        schema=1,
        kind="bpm_process",
        id=process.id,
        version=process.version,
        name=process.name or process.id,
        # 실행 위치는 **처음부터** 들어간다. 생략하면 서버다 (C1 R1·ADR-0016).
        run_location=entry.process.info.run_location or "server",
        entry=f"process/{entry.path.name}",
        process_id=entry.process.id,
        triggers=collect_triggers(entry),
        requires=collect_requires(process),
        human=collect_human(process),
        # 작업 지시 화면(CON-05)이 입력 칸을 그린다 — 사람이 두 번 적지 않게 그림에서 옮긴다.
        inputs=[
            ManifestInput(
                name=one.name,
                type=one.type,
                required=one.required,
                description=one.description,
                default=one.default,
            )
            for one in entry.process.info.inputs
        ],
        outputs=list(entry.process.info.outputs),
        built=Built(
            by=by, at=datetime.now(UTC).isoformat(timespec="seconds"), core=core, spec_version=SPEC_VERSION
        ),
        content_hash="sha256:" + "0" * 64,
    )


def build_lib_manifest(
    process: BpmProcess,
    definitions: Sequence[Definition],
    *,
    by: str = "studio",
    core: str = "0.1.0",
) -> Manifest:
    """공유 BPM 프로세스 패키지의 매니페스트 (C1 `kind=process_lib`, STU-12).

    **`entry`·`process_id`·`run_location`·`inputs`가 없다** — 이 패키지는 스스로 돌지 않고 남이
    부르는 정의를 담는다 (R1은 `bpm_process`에만 묻는다). 실행 위치는 정의마다 `provides`에 있다.
    """
    chosen = [d for d in definitions if d.process is not None]
    if not chosen:
        raise PackageError("공유할 정의를 하나 이상 고르세요 — 읽지 못한 정의는 담을 수 없습니다.")
    within = {d.process.id for d in chosen if d.process is not None}
    return Manifest(
        schema=1,
        kind="process_lib",
        id=process.id,
        version=process.version,
        name=process.name or process.id,
        requires=collect_requires(process, definitions=chosen, inside=within),
        human=collect_human(process, definitions=chosen),
        provides=collect_provides(chosen),
        built=Built(
            by=by, at=datetime.now(UTC).isoformat(timespec="seconds"), core=core, spec_version=SPEC_VERSION
        ),
        content_hash="sha256:" + "0" * 64,
    )


def gather_lib(process: BpmProcess, definitions: Sequence[Definition]) -> dict[str, bytes]:
    """공유 BPM 프로세스 패키지에 들어갈 파일 — **고른 BPMN**과 `memory`·`libs`, 그리고 DMN 전부.

    결정(DMN)은 가려내지 않고 모두 담는다. 어느 결정을 쓰는지 골라내다 하나를 빠뜨리면 **부르는
    쪽이 실행 때** 깨지는데, 결정 파일은 작아서 함께 담는 값이 더 싸다.
    """
    keep = {d.path.name for d in definitions}
    out: dict[str, bytes] = {}
    for name, body in gather(process).items():
        path = Path(name)
        if path.parts[0] == "process" and path.suffix == ".bpmn" and path.name not in keep:
            continue
        out[name] = body
    return out


def check_lib(process: BpmProcess, manifest: Manifest, files: dict[str, bytes]) -> list[Violation]:
    """C1 검사 + **담은 정의가 패키지 안에 있는지**와 **고르지 않은 형제를 부르지 않는지**.

    형제를 부르면 `requires.libs`에 그 id가 들어가 「바깥 패키지」로 적히는데, 실은 같은 작업
    폴더의 정의다. 그대로 올리면 받는 쪽이 없는 패키지를 찾는다 — 여기서 말해 주는 쪽이 낫다.
    """
    out = list(validate(manifest))
    for one in manifest.provides.processes if manifest.provides else []:
        if one.file not in files:
            out.append(
                Violation(rule="R1", message=f"공유할 정의가 패키지에 없다: {one.file}", items=[one.file])
            )
    siblings = set(process.processes())
    outside = sorted(set(manifest.requires.libs) & siblings)
    if outside:
        out.append(
            Violation(
                rule="R1",
                message="고르지 않은 정의를 부른다 — 함께 공유할 정의로 고르세요",
                items=outside,
            )
        )
    return out


def export_lib(
    process: BpmProcess, definitions: Sequence[Definition], target: Path, *, by: str = "studio"
) -> Path:
    """공유 BPM 프로세스 패키지 zip 하나 (STU-12 「내보내기」)."""
    manifest = build_lib_manifest(process, definitions, by=by)
    files = gather_lib(process, definitions)
    blocking = [v for v in check_lib(process, manifest, files) if v.blocks]
    if blocking:
        raise PackageError("패키지 검사가 막습니다: " + "; ".join(v.message for v in blocking))
    return _write(manifest, files, target)


def gather(process: BpmProcess) -> dict[str, bytes]:
    """패키지에 들어갈 파일 (`경로 → 내용`). **케이스·실행 기록은 뺀다** (C1)."""
    out: dict[str, bytes] = {}
    for name in INCLUDED:
        folder = process.folder / name
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                out[path.relative_to(process.folder).as_posix()] = path.read_bytes()
    return out


def check(process: BpmProcess, manifest: Manifest, files: dict[str, bytes] | None = None) -> list[Violation]:
    """C1 검사 (R1~R7) + **매니페스트와 파일이 맞는지**.

    매니페스트만 보는 `validate()`는 「`entry`가 실제로 들어 있는가」를 모른다. 패키지를 만드는
    쪽에서만 아는 것이니 여기서 본다 — 받는 쪽(Center)이 거부하기 전에.
    """
    out = list(validate(manifest))
    inside = gather(process) if files is None else files
    if manifest.entry and manifest.entry not in inside:
        out.append(
            Violation(rule="R1", message=f"진입 정의가 패키지에 없다: {manifest.entry}", items=[manifest.entry])
        )
    return out


def export(process: BpmProcess, target: Path, *, by: str = "studio") -> Path:
    """패키지 zip 하나를 만든다. `content_hash`는 **파일에서 계산한다** (C2·R6)."""
    manifest = build_manifest(process, by=by)
    files = gather(process)
    blocking = [v for v in check(process, manifest, files) if v.blocks]
    if blocking:
        raise PackageError("패키지 검사가 막습니다: " + "; ".join(v.message for v in blocking))

    return _write(manifest, files, target)


def _write(manifest: Manifest, files: dict[str, bytes], target: Path) -> Path:
    files[MANIFEST_NAME] = _as_bytes(manifest)
    # 해시는 **파일에서** 계산한다 (C2·R6). `manifest.json` 자신의 `content_hash`는 빠진다.
    manifest = manifest.model_copy(update={"content_hash": content_hash_from_files(files)})
    files[MANIFEST_NAME] = _as_bytes(manifest)

    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(files):
            zf.writestr(name, files[name])
    return target


def _as_bytes(manifest: Manifest) -> bytes:
    body = json.dumps(manifest.to_json_dict(), ensure_ascii=False, indent=2) + "\n"
    return body.encode("utf-8")


def default_name(process: BpmProcess) -> str:
    return f"{process.id}-{process.version}.zip"


def default_lib_name(process: BpmProcess) -> str:
    """공유 BPM 프로세스 패키지의 기본 파일 이름 — Bot 패키지와 **한 폴더에서 구별되게**."""
    return f"{process.id}-lib-{process.version}.zip"


__all__ = [
    "EXCLUDED",
    "INCLUDED",
    "MANIFEST_NAME",
    "SPEC_VERSION",
    "PackageError",
    "build_lib_manifest",
    "build_manifest",
    "check",
    "check_lib",
    "collect_human",
    "collect_provides",
    "collect_requires",
    "collect_triggers",
    "default_lib_name",
    "default_name",
    "export",
    "export_lib",
    "gather",
    "gather_lib",
    "human_of",
]
