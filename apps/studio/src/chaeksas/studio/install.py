"""공유 BPM 프로세스를 받아 작업 폴더의 `libs/`에 푼다 (STU-11 「설치」, ADR-0048).

**「설치돼 있나」를 답하는 자리도 여기다** (`installed_of`) — STU-11의 「설치본」 열과 STU-03의
셋(부르기·보기·복사)이 **그 하나**를 쓴다
([ADR-0051](../../../../../docs/decisions/0051-shared-process-conveniences.md)). 베끼면 한
화면은 「설치됨」이라 하고 다른 화면은 「—」라 하는 날이 온다.

지키는 것 다섯.

- **자리는 작업 폴더의 `libs/`다.** PC 공용 저장소를 두지 않는다 — 패키지와 같은 자리라
  내보내기(`packaging.INCLUDED`)와 실행기(`bot_ui/runner_main.py`)가 **이미 그것을 안다**.
  그래서 시험 실행과 현장이 **같은 파일**을 본다.
- **설치는 BPM 프로세스 하나에 하는 일이다.** 판을 BPM 프로세스마다 쥐어야 다른 BPM 프로세스를 건드리지 않고
  올릴 수 있다.
- **Center를 읽기만 한다** (C5 `GET /packages/{id}/{version}`). 쓰는 길은 `upload.py` 하나다.
- **아무 패키지나 풀지 않는다** — `kind=process_lib`이고 id·버전이 받으려던 것과 같아야 한다
  (`bpm_process` 패키지를 lib으로 풀면 진입 정의가 남의 `libs/`에서 돌게 된다).
- **정의와 결정표를 함께 푼다** (`process/*.bpmn`·`process/*.dmn`) — 규칙 태스크를 쓰는 공유
  BPM 프로세스가 돌아야 한다. 읽는 쪽은 **Studio와 실행기 둘 다** `libs/`를 보고(C1), 한쪽만
  읽으면 「Studio에서는 되는데 현장에서 안 된다」가 된다.
"""

from __future__ import annotations

import io
import logging
import zipfile
from dataclasses import dataclass
from pathlib import Path

from chaeksas.contracts.bpmn_ext import BpmnReadError, read_process
from chaeksas.contracts.manifest import Manifest
from chaeksas.studio.services import CenterReader, CenterUnreachable
from chaeksas.studio.workspace import (
    LIBS_DIR,
    BpmProcess,
    InstalledLib,
    Workspace,
    WorkspaceError,
)

log = logging.getLogger(__name__)

#: 받을 수 있는 갈래 (C1). 「설치」는 공유 BPM 프로세스만 한다.
KIND_LIB = "process_lib"

#: 패키지 안에서 정의·결정표가 사는 곳 (C1 §패키지 구성).
PROCESS_DIR = "process/"
#: 푸는 것 — 정의와 그것이 쓰는 결정표 (ADR-0048). 그 밖(케이스·기록)은 lib에 없다.
SUFFIXES = (".bpmn", ".dmn")

NO_PROCESS = "열린 BPM 프로세스가 없습니다 — 설치는 BPM 프로세스 하나에 하는 일입니다."
NO_CENTER = "Center에 아직 들어오지 않았습니다 — 설정 → 「Center」에서 「연결 테스트」 (STU-16)."
#: 받아 둔 판이 그 정의를 주지 않는다 (읽지 못한 정의일 수 있다 — B14가 그 말을 한다).
NOT_PROVIDED = "설치된 판이 이 정의를 주지 않습니다 (읽지 못한 정의일 수 있습니다)."


class InstallFailed(RuntimeError):
    """설치하지 못했다 — 화면이 그대로 보여 줄 한 줄."""


@dataclass(frozen=True)
class Installed:
    """설치한 결과."""

    lib: InstalledLib
    #: 함께 푼 결정표 수 (C1 `libs/`) — 0이면 그 말을 하지 않는다.
    decisions: int = 0

    @property
    def message(self) -> str:
        head = f"{self.lib.ref}을 설치했습니다 (정의 {len(self.lib.processes)}개"
        return f"{head}, 결정표 {self.decisions}개)." if self.decisions else f"{head})."


def definitions_in(raw: bytes, *, package_id: str, version: str) -> dict[str, str]:
    """패키지 zip에서 **정의와 결정표**를 꺼낸다 (`process/*.bpmn`·`process/*.dmn`).

    매니페스트를 먼저 보고 **갈래·id·버전이 맞는지** 확인한다 — 받으려던 것과 다른 것이 오면
    풀지 않는다. 폴더 구조는 C1이 정한 그대로를 믿지 않고 **이름으로** 고른다.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as e:
        raise InstallFailed(f"{package_id} {version}: 패키지가 zip이 아닙니다") from e
    with archive:
        try:
            manifest = Manifest.model_validate_json(archive.read("manifest.json"))
        except (KeyError, ValueError) as e:
            raise InstallFailed(f"{package_id} {version}: 매니페스트를 읽지 못했습니다") from e
        if manifest.kind != KIND_LIB:
            raise InstallFailed(
                f"{package_id} {version}: 공유 BPM 프로세스 패키지가 아닙니다 ({manifest.kind})"
            )
        if (manifest.id, manifest.version) != (package_id, version):
            raise InstallFailed(
                f"{package_id} {version}: 받은 패키지가 {manifest.id} {manifest.version}입니다"
            )
        found = {
            Path(name).name: archive.read(name).decode("utf-8")
            for name in sorted(archive.namelist())
            if name.startswith(PROCESS_DIR) and name.endswith(SUFFIXES)
        }
    if not any(name.endswith(".bpmn") for name in found):
        raise InstallFailed(f"{package_id} {version}: 패키지에 정의가 없습니다")
    return found


def install(
    workspace: Workspace,
    process: BpmProcess | None,
    reader: CenterReader | None,
    *,
    package_id: str,
    version: str,
) -> Installed:
    """받아서 푼다 (STU-11 「설치」·「갱신」).

    **같은 패키지가 이미 있으면 갈아 치운다** — 그것이 「갱신」이다 (`Workspace.install_lib`).
    """
    if process is None:
        raise InstallFailed(NO_PROCESS)
    if reader is None:
        raise InstallFailed(NO_CENTER)
    try:
        raw = reader.package_zip(package_id, version)
    except CenterUnreachable as e:
        raise InstallFailed(f"{package_id} {version}: {e}") from e
    definitions = definitions_in(raw, package_id=package_id, version=version)
    try:
        made = workspace.install_lib(
            process, package_id=package_id, version=version, definitions=definitions
        )
    except WorkspaceError as e:
        raise InstallFailed(f"{package_id} {version}: {e}") from e
    log.info("공유 BPM 프로세스를 설치했다: %s → %s", made.ref, process.id)
    return Installed(lib=made, decisions=sum(1 for name in definitions if name.endswith(".dmn")))


def remove(workspace: Workspace, process: BpmProcess | None, *, package_id: str) -> str:
    """지운다 (STU-11 「제거」). 돌려주는 것은 화면이 보일 한 줄이다."""
    if process is None:
        raise InstallFailed(NO_PROCESS)
    found = next((one for one in process.libs if one.package_id == package_id), None)
    if found is None or not workspace.remove_lib(process, package_id):
        raise InstallFailed(f"{package_id}은 이 BPM 프로세스에 설치되어 있지 않습니다")
    log.info("공유 BPM 프로세스를 제거했다: %s ← %s", found.ref, process.id)
    return f"{found.ref}을 제거했습니다."


def installed_of(process: BpmProcess | None) -> dict[str, InstalledLib]:
    """열린 BPM 프로세스에 받아 둔 판들 `{패키지 id: 받아 둔 것}` (ADR-0048 — 설치는 BPM 프로세스마다다).

    **「설치돼 있나」를 묻는 자리는 이 함수 하나다** (ADR-0051) — STU-11의 「설치본」 열과
    STU-03의 부르기·보기·복사가 같은 것을 본다.
    """
    if process is None:
        return {}
    return {one.package_id: one for one in process.libs}


def definition_file(process: BpmProcess, lib: InstalledLib, process_id: str) -> Path | None:
    """그 BPMN 프로세스 id를 담은 `libs/` 파일 — 「열기 (읽기 전용)」·「복사」가 읽는 자리.

    **기록이 적어 둔 파일만** 본다 — `libs/`가 평평해서 다른 판이 같은 이름을 들고 있을 수
    있다 (설치가 파일 이름에 패키지 id를 붙이는 까닭이다). 읽지 못한 정의는 `None`이다.
    """
    folder = process.folder / LIBS_DIR
    for name in lib.files:
        if not name.endswith(".bpmn"):
            continue  # 결정표는 호출 대상이 아니다
        path = folder / name
        try:
            found = read_process(path.read_text(encoding="utf-8"))
        except (BpmnReadError, OSError):
            continue  # 읽지 못한 정의는 보여 줄 수도 복사할 수도 없다 (B14가 말한다)
        if found.id == process_id:
            return path
    return None


@dataclass(frozen=True)
class Copy:
    """「내 BPM 프로세스로 복사」가 할 일 — **묻기 전에** 셈한다 (STU-03).

    창이 `file_name`을 적어 보이므로 사람이 **무엇이 생기는지 알고** 고른다 (U9의 결).
    """

    source: Path
    #: `process/` 안에 만들 이름. **겹치면 새 이름이고 덮어쓰지 않는다** (ADR-0051).
    file_name: str
    xml: str


def plan_copy(process: BpmProcess, lib: InstalledLib, process_id: str) -> Copy:
    """복사할 것을 셈한다. 할 수 없으면 `InstallFailed`로 **까닭 한 줄**이다.

    **같은 BPMN 프로세스 id의 정의가 이미 있으면 복사하지 않는다** — 한 패키지에 같은 id가
    둘이면 `BpmProcess.processes()`가 조용히 하나를 가린다.
    """
    found = definition_file(process, lib, process_id)
    if found is None:
        raise InstallFailed(f"{lib.ref}: {NOT_PROVIDED}")
    if any(one.id == process_id for one in process.definitions):
        raise InstallFailed(f"같은 id의 정의가 이미 있습니다: {process_id}")
    return Copy(
        source=found,
        file_name=_free_name(process, lib, found.name),
        xml=found.read_text(encoding="utf-8"),
    )


def _free_name(process: BpmProcess, lib: InstalledLib, file_name: str) -> str:
    """`process/`에 쓸 이름 — 설치가 붙인 패키지 id를 떼고, **겹치면 비낀다**."""
    head = f"{lib.package_id}__"
    bare = file_name[len(head) :] if file_name.startswith(head) else file_name
    stem = Path(bare).stem or lib.package_id
    folder = process.folder / "process"
    name = f"{stem}.bpmn"
    for number in range(2, 100):
        if not (folder / name).exists():
            return name
        name = f"{stem}-{number}.bpmn"
    return name


def copy_into(workspace: Workspace, process: BpmProcess, plan: Copy) -> Path:
    """셈한 것을 **내 정의로** 쓴다 (STU-03 「내 BPM 프로세스로 복사」).

    그때부터 **내 것이 이기고**(`processes()`) 내보낼 때 `requires.libs`에서 저절로 빠진다
    (`packaging.collect_requires`가 「내 정의만 패키지 안」이라고 적어 둔 그대로다).
    """
    try:
        path = workspace.save_definition(process, plan.file_name, plan.xml)
    except WorkspaceError as e:
        raise InstallFailed(f"복사하지 못했습니다: {e}") from e
    log.info("공유 BPM 프로세스 정의를 복사했다: %s → %s", plan.source.name, path.name)
    return path


def callers_of(process: BpmProcess, lib: InstalledLib) -> list[str]:
    """그 공유 BPM 프로세스를 **부르는 노드** — 제거하기 전에 묻는 데 쓴다 (STU-11).

    지우고 나면 C14 B14가 그 그림을 막으므로 사람이 모르고 지나가지는 않는다. 그래도 **먼저**
    말해 주는 쪽이 낫다 (되돌릴 수 없는 일은 묻는다, U9).
    """
    out = []
    for definition in process.definitions:
        if definition.process is None:
            continue
        for node in definition.process.all_nodes():
            if node.called_element and node.called_element in lib.processes:
                out.append(f"{definition.name}: {node.id}")
    return out


__all__ = [
    "KIND_LIB",
    "NOT_PROVIDED",
    "NO_CENTER",
    "NO_PROCESS",
    "SUFFIXES",
    "Copy",
    "InstallFailed",
    "Installed",
    "callers_of",
    "copy_into",
    "definition_file",
    "definitions_in",
    "install",
    "installed_of",
    "plan_copy",
    "remove",
]
