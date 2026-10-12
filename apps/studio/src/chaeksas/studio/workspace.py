"""작업 폴더 — BPM 프로세스가 디스크에 사는 모양 (STU-02 탐색기가 읽는 것).

**패키지(C1)와 같은 폴더 이름을 쓴다** — 「패키지로 내보내기」가 거의 복사가 되게.

```
<작업 폴더>/
└─ <그룹>/                     「기본」은 항상 있고 지울 수 없다 (STU-02)
   └─ <BPM 프로세스 id>/
      ├─ process.json          이름·버전·진입 정의·설명·담당자·태그 (Studio 안에서만 쓴다)
      ├─ process/*.bpmn        정의들 (C1 `process/`와 같은 이름)
      ├─ process/*.dmn         규칙 태스크가 쓰는 결정표
      ├─ cases/*.cases.json    시험 케이스 (패키지에는 넣지 않는다, C1)
      ├─ libs/*.bpmn           받아 둔 공유 BPM 프로세스 (ADR-0048 — 편집 대상이 아니다)
      └─ memory/specs.json     재생 명세 (ADR-0028)
```

`process.json`은 **Studio 안에서만 쓰는 기록**이라 계약이 아니다 (구성요소 사이를 오가지 않는다).
패키지 매니페스트(C1)는 내보낼 때 이것과 `chk:process`를 모아 만든다.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from chaeksas.contracts.bpmn_ext import BpmnProcess, BpmnReadError, read_process
from chaeksas.contracts.dmn import Decision, DmnReadError, read_decisions
from chaeksas.contracts.replay import ReplayMemory
from chaeksas.core.replay import read_memory

#: 지울 수 없는 기본 그룹 (STU-02 — 항상 맨 위).
DEFAULT_GROUP = "기본"

#: BPM 프로세스 id — C1과 같은 규칙 (소문자·숫자·`.`·`_`·`-`, 첫 글자는 소문자·숫자).
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,99}$")

RECORD_NAME = "process.json"
SCHEMA = 1

#: 받아 둔 공유 BPM 프로세스가 사는 폴더 (ADR-0048).
#:
#: **패키지와 같은 이름이고 실행기가 이미 읽는 자리다** (`bot_ui/runner_main.py`가
#: `libs/*.bpmn`을 글롭한다) — 그래서 내보내기도 실행기도 바뀌지 않는다.
LIBS_DIR = "libs"


class WorkspaceError(ValueError):
    """작업 폴더에서 할 수 없는 일 (이름이 겹친다·규칙에 맞지 않는다)."""


@dataclass(frozen=True)
class InstalledLib:
    """받아 둔 공유 BPM 프로세스 하나 (ADR-0048).

    파일은 `libs/` 안에 **평평하게** 둔다 — 실행기가 `libs/*.bpmn`만 글롭하므로 하위 폴더를
    쓰면 현장에서 못 찾는다. 그래서 **어느 파일이 어느 판의 것인지는 기록이 안다**(제거가 그것만
    지운다). `processes`는 내보내기가 `requires.libs`에 **판을 붙이는 데** 쓴다 (C1).
    """

    package_id: str
    version: str
    #: `libs/` 안 파일 이름들.
    files: tuple[str, ...] = ()
    #: 그 파일들이 주는 BPMN 프로세스 id (`calledElement`가 가리키는 것).
    processes: tuple[str, ...] = ()

    @property
    def ref(self) -> str:
        """C1 `requires.libs`의 한 줄 — `<id>@<version>`."""
        return f"{self.package_id}@{self.version}"

    def to_json(self) -> dict[str, object]:
        return {
            "id": self.package_id,
            "version": self.version,
            "files": list(self.files),
            "processes": list(self.processes),
        }


@dataclass
class Definition:
    """정의 하나 (BPMN 파일 하나)."""

    path: Path
    #: 읽은 결과. 읽지 못했으면 `None`이고 `problem`에 사유가 있다.
    process: BpmnProcess | None = None
    problem: str | None = None

    @property
    def name(self) -> str:
        return self.path.stem

    @property
    def id(self) -> str:
        return self.process.id if self.process else ""


@dataclass
class BpmProcess:
    """BPM 프로세스 하나 (폴더 하나). 운영 화면에서는 「Bot」이다."""

    id: str
    folder: Path
    group: str
    name: str = ""
    version: str = "0.1.0"
    #: 진입 정의의 **파일 이름** (`main.bpmn`). 비면 첫 정의를 진입으로 본다.
    entry: str = ""
    #: 사람이 적는 것 (STU-06). **설명만 패키지로 간다** (C1 `description`) — 담당자·태그는
    #: 매니페스트에 칸이 없어 작업 폴더 기록에만 남는다 (설계자가 보는 메모다).
    description: str = ""
    owner: str = ""
    tags: tuple[str, ...] = ()
    definitions: list[Definition] = field(default_factory=list)
    #: 받아 둔 공유 BPM 프로세스 (ADR-0048). **편집 대상이 아니라** `definitions`에 없다.
    libs: tuple[InstalledLib, ...] = ()

    @property
    def display(self) -> str:
        return self.name or self.id

    @property
    def entry_definition(self) -> Definition | None:
        found = next((d for d in self.definitions if d.path.name == self.entry), None)
        return found or (self.definitions[0] if self.definitions else None)

    def decisions(self) -> dict[str, Decision]:
        """같은 패키지의 DMN 결정 — 규칙 태스크가 찾는 것 (`RunEnv.decisions`)."""
        found: dict[str, Decision] = {}
        for path in sorted((self.folder / "process").glob("*.dmn")):
            try:
                found.update(read_decisions(path.read_text(encoding="utf-8")))
            except DmnReadError:
                continue  # 읽기 오류는 실행 전 검사가 말한다 (여기서 터뜨리지 않는다)
        return found

    def processes(self) -> dict[str, BpmnProcess]:
        """호출(`callActivity`)이 찾을 다른 정의 — `RunEnv.processes`.

        **`process/`와 `libs/`를 함께 본다** (ADR-0048) — 실행기(`bot_ui/runner_main.py`)와 같은
        규칙이라 시험 실행과 현장이 같은 것을 부른다. 같은 사전이 C14 B14의 `called_processes`로
        가므로 **설치한 뒤에는 검사도 그 호출을 받아들인다**.

        **내 정의가 이긴다** — 받은 것과 id가 겹치면 내 `process/`의 것을 쓴다(남의 판이 내
        정의를 조용히 가리면 안 된다). 깨진 lib 하나가 시험 실행을 막지는 않는다 — 읽지 못한
        것은 호출할 수 없고, 그 말은 실행 전 검사가 한다 (B14).
        """
        out = {d.process.id: d.process for d in self.definitions if d.process is not None}
        for path in sorted((self.folder / LIBS_DIR).glob("*.bpmn")):
            try:
                found = read_process(path.read_text(encoding="utf-8"))
            except (BpmnReadError, OSError):
                continue
            out.setdefault(found.id, found)
        return out

    def lib_of(self, process_id: str) -> InstalledLib | None:
        """그 `calledElement`를 주는 공유 BPM 프로세스 — 내보내기가 판을 붙이는 데 쓴다."""
        return next((one for one in self.libs if process_id in one.processes), None)

    def memory(self) -> ReplayMemory:
        """재생 명세 (ADR-0028). 없으면 빈 기억이다."""
        return read_memory(self.folder)

    def case_file(self, definition: Definition) -> Path:
        return self.folder / "cases" / f"{definition.path.stem}.cases.json"


@dataclass
class Group:
    """그룹 하나 (폴더 하나). 「기본」은 늘 맨 위에 있다."""

    name: str
    processes: list[BpmProcess] = field(default_factory=list)


def _record_path(folder: Path) -> Path:
    return folder / RECORD_NAME


def _tags(raw: object) -> tuple[str, ...]:
    """태그 목록. **모양이 틀리면 버린다** — 기록 하나 때문에 탐색기가 뜨지 않으면 안 된다."""
    if not isinstance(raw, list):
        return ()
    return tuple(str(one).strip() for one in raw if str(one).strip())


def _libs(raw: object) -> tuple[InstalledLib, ...]:
    """설치 기록. **모양이 틀린 줄은 버린다** — 기록 하나 때문에 탐색기가 뜨지 않으면 안 된다.

    id·버전이 없는 줄은 쓸 수 없다(제거도 내보내기도 그 둘로 말한다).
    """
    if not isinstance(raw, list):
        return ()
    out = []
    for one in raw:
        if not isinstance(one, dict):
            continue
        package_id, version = str(one.get("id") or ""), str(one.get("version") or "")
        if not package_id or not version:
            continue
        out.append(
            InstalledLib(
                package_id=package_id,
                version=version,
                files=tuple(str(f) for f in one.get("files") or [] if str(f)),
                processes=tuple(str(p) for p in one.get("processes") or [] if str(p)),
            )
        )
    return tuple(out)


def read_record(folder: Path) -> dict[str, object]:
    found = _record_path(folder)
    if not found.is_file():
        return {}
    try:
        raw = json.loads(found.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    return raw if isinstance(raw, dict) else {}


def write_record(process: BpmProcess) -> Path:
    found = _record_path(process.folder)
    found.parent.mkdir(parents=True, exist_ok=True)
    found.write_text(
        json.dumps(
            {
                "schema": SCHEMA,
                "id": process.id,
                "name": process.name,
                "version": process.version,
                "entry": process.entry,
                # **빈 값은 적지 않는다** — 기록이 「아직 안 적었다」와 「비웠다」로 갈리지 않게.
                **({"description": process.description} if process.description else {}),
                **({"owner": process.owner} if process.owner else {}),
                **({"tags": list(process.tags)} if process.tags else {}),
                # 받아 둔 공유 BPM 프로세스 (ADR-0048). **패키지로 가지 않는다** — 계약이
                # 아니라 Studio 기록이다 (패키지에는 `libs/` 파일과 `requires.libs`가 간다).
                **({"libs": [one.to_json() for one in process.libs]} if process.libs else {}),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return found


@dataclass
class Workspace:
    """작업 폴더 한 벌. **디스크가 원본이다** — 화면은 `scan()`한 결과를 그린다."""

    root: Path

    def ensure(self) -> Workspace:
        (self.root / DEFAULT_GROUP).mkdir(parents=True, exist_ok=True)
        return self

    # ── 읽기 ──

    def groups(self) -> list[Group]:
        """그룹 → BPM 프로세스 → 정의. 「기본」이 맨 위, 나머지는 이름순 (STU-02)."""
        self.ensure()
        found = [
            Group(name=folder.name, processes=self._processes(folder))
            for folder in sorted(self.root.iterdir())
            if folder.is_dir()
        ]
        found.sort(key=lambda g: (g.name != DEFAULT_GROUP, g.name))
        return found

    def _processes(self, group: Path) -> list[BpmProcess]:
        out = []
        for folder in sorted(group.iterdir()):
            if folder.is_dir() and _record_path(folder).is_file():
                out.append(self.read(folder, group.name))
        return out

    def read(self, folder: Path, group: str) -> BpmProcess:
        record = read_record(folder)
        process = BpmProcess(
            id=str(record.get("id") or folder.name),
            folder=folder,
            group=group,
            name=str(record.get("name") or ""),
            version=str(record.get("version") or "0.1.0"),
            entry=str(record.get("entry") or ""),
            description=str(record.get("description") or ""),
            owner=str(record.get("owner") or ""),
            tags=_tags(record.get("tags")),
            libs=_libs(record.get("libs")),
        )
        process.definitions = list(self._definitions(folder))
        return process

    def _definitions(self, folder: Path) -> Iterator[Definition]:
        for path in sorted((folder / "process").glob("*.bpmn")):
            try:
                yield Definition(path=path, process=read_process(path.read_text(encoding="utf-8")))
            except (BpmnReadError, OSError) as e:
                yield Definition(path=path, problem=str(e))

    def find(self, process_id: str) -> BpmProcess | None:
        return next(
            (p for group in self.groups() for p in group.processes if p.id == process_id), None
        )

    # ── 쓰기 ──

    def create_group(self, name: str) -> Path:
        cleaned = name.strip()
        if not cleaned or "/" in cleaned or "\\" in cleaned:
            raise WorkspaceError(f"그룹 이름으로 쓸 수 없다: {name}")
        folder = self.root / cleaned
        if folder.exists():
            raise WorkspaceError(f"같은 이름의 그룹이 있다: {cleaned}")
        folder.mkdir(parents=True)
        return folder

    def create(
        self,
        process_id: str,
        *,
        name: str = "",
        version: str = "0.1.0",
        group: str = DEFAULT_GROUP,
        entry: str = "main.bpmn",
    ) -> BpmProcess:
        """새 BPM 프로세스 (STU-05). 정의 파일은 캔버스가 저장할 때 생긴다."""
        if not ID_PATTERN.match(process_id):
            raise WorkspaceError(
                f"id는 소문자·숫자·`.`·`_`·`-`만 쓸 수 있고 소문자나 숫자로 시작한다: {process_id}"
            )
        if self.find(process_id) is not None:
            raise WorkspaceError(f"같은 id의 BPM 프로세스가 있다: {process_id}")
        folder = self.root / group / process_id
        if folder.exists():
            raise WorkspaceError(f"같은 폴더가 있다: {folder.name}")
        (folder / "process").mkdir(parents=True)
        (folder / "cases").mkdir()
        found = BpmProcess(
            id=process_id, folder=folder, group=group, name=name or process_id,
            version=version, entry=entry,
        )
        write_record(found)
        return found

    def save_definition(self, process: BpmProcess, file_name: str, xml: str) -> Path:
        """정의 하나를 쓴다. 파일은 늘 UTF-8이다 (Windows 기본 인코딩은 cp949)."""
        if not file_name.endswith(".bpmn"):
            raise WorkspaceError(f"정의 파일 이름은 `.bpmn`으로 끝나야 한다: {file_name}")
        path = process.folder / "process" / file_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(xml, encoding="utf-8", newline="\n")
        return path

    # ── 받아 둔 공유 BPM 프로세스 (ADR-0048) ──

    def install_lib(
        self,
        process: BpmProcess,
        *,
        package_id: str,
        version: str,
        definitions: dict[str, str],
    ) -> InstalledLib:
        """공유 BPM 프로세스 하나를 그 BPM 프로세스의 `libs/`에 푼다 (STU-11 「설치」).

        **같은 패키지가 이미 있으면 갈아 치운다** — 「갱신」이 그 길이다(옛 판의 파일을 먼저
        지운다. 남겨 두면 `libs/*.bpmn`을 글롭하는 쪽이 **두 판을 함께** 읽는다).

        파일 이름에 **패키지 id를 붙인다** — `libs/`가 평평해서 서로 다른 패키지가 같은
        `main.bpmn`을 들고 올 수 있다. 읽는 쪽은 파일 이름이 아니라 **BPMN 프로세스 id**로
        찾으므로(`processes()`) 이름을 바꿔도 호출은 그대로다.
        """
        if not definitions:
            raise WorkspaceError(f"{package_id}에 정의가 없다 (풀 것이 없다)")
        self.remove_lib(process, package_id)
        folder = process.folder / LIBS_DIR
        folder.mkdir(parents=True, exist_ok=True)
        files, provided = [], []
        for name, xml in sorted(definitions.items()):
            file_name = f"{package_id}__{Path(name).name}"
            (folder / file_name).write_text(xml, encoding="utf-8", newline="\n")
            files.append(file_name)
            try:
                provided.append(read_process(xml).id)
            except BpmnReadError:
                continue  # 읽지 못한 정의는 호출할 수 없다 — 파일은 그대로 둔다 (B14가 말한다)
        made = InstalledLib(
            package_id=package_id,
            version=version,
            files=tuple(files),
            processes=tuple(sorted(set(provided))),
        )
        process.libs = (*process.libs, made)
        write_record(process)
        return made

    def remove_lib(self, process: BpmProcess, package_id: str) -> bool:
        """그 공유 BPM 프로세스를 지운다 (STU-11 「제거」). 있었으면 `True`.

        **기록이 적어 둔 파일만** 지운다 — `libs/`를 통째로 비우면 다른 판까지 날아간다.
        """
        found = next((one for one in process.libs if one.package_id == package_id), None)
        if found is None:
            return False
        for name in found.files:
            (process.folder / LIBS_DIR / name).unlink(missing_ok=True)
        process.libs = tuple(one for one in process.libs if one.package_id != package_id)
        write_record(process)
        return True

    def import_example(self, source: Path, process_id: str, *, group: str = DEFAULT_GROUP) -> BpmProcess:
        """예제 BPM 프로세스 가져오기 (STU-01 파일 메뉴).

        `source`는 업무 예제의 `bpmn/` 폴더이고, `<id>.bpmn`과 그것이 쓰는 `.dmn`·**호출 대상**·
        케이스를 함께 가져온다. **예제 폴더는 생성물이라 건드리지 않는다** (CLAUDE.md §2).

        호출 대상을 빼놓으면 돌려 보고야 안다 (「호출 대상이 패키지에 없다」) — 인수 시험에서
        FX-03이 실제로 그렇게 걸렸다. 호출은 겹칠 수 있으므로 **따라가며** 모은다.
        """
        found = source / f"{process_id}.bpmn"
        if not found.is_file():
            raise WorkspaceError(f"예제를 찾지 못했다: {found.name}")
        definition = read_process(found.read_text(encoding="utf-8"))
        made = self.create(
            process_id.replace("_", "-"),
            name=definition.name or process_id,
            group=group,
            entry=f"{process_id}.bpmn",
        )
        self.save_definition(made, found.name, found.read_text(encoding="utf-8"))
        self._bring_along(source, definition, made)
        cases = source.parent / "cases" / f"{process_id}.cases.json"
        if cases.is_file():
            (made.folder / "cases" / cases.name).write_text(
                cases.read_text(encoding="utf-8"), encoding="utf-8", newline="\n"
            )
        return self.read(made.folder, group)

    def _bring_along(self, source: Path, definition: BpmnProcess, made: BpmProcess) -> None:
        """그 정의가 쓰는 DMN과 **호출 대상 BPM 프로세스**를 따라가며 가져온다."""
        seen = {definition.id}
        pending = [definition]
        while pending:
            current = pending.pop()
            for node in current.all_nodes():
                rule = node.prop("rule")
                if rule is not None:
                    self._copy_next_to(source / f"{rule.decision}.dmn", made)
                called = node.called_element
                if not called or called in seen:
                    continue
                seen.add(called)
                # 예제의 호출 대상 id는 `Proc_<파일이름>`이다 (생성기가 그렇게 짓는다).
                target = source / f"{called.removeprefix('Proc_')}.bpmn"
                if not target.is_file():
                    continue
                self._copy_next_to(target, made)
                pending.append(read_process(target.read_text(encoding="utf-8")))

    def _copy_next_to(self, path: Path, made: BpmProcess) -> None:
        if path.is_file():
            (made.folder / "process" / path.name).write_text(
                path.read_text(encoding="utf-8"), encoding="utf-8", newline="\n"
            )


__all__ = [
    "DEFAULT_GROUP",
    "ID_PATTERN",
    "LIBS_DIR",
    "RECORD_NAME",
    "BpmProcess",
    "Definition",
    "Group",
    "InstalledLib",
    "Workspace",
    "WorkspaceError",
    "read_record",
    "write_record",
]
