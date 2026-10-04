"""작업 폴더 — BPM 프로세스가 디스크에 사는 모양 (STU-02 탐색기가 읽는 것).

**패키지(C1)와 같은 폴더 이름을 쓴다** — 「패키지로 내보내기」가 거의 복사가 되게.

```
<작업 폴더>/
└─ <그룹>/                     「기본」은 항상 있고 지울 수 없다 (STU-02)
   └─ <BPM 프로세스 id>/
      ├─ process.json          이름·버전·진입 정의 (Studio 안에서만 쓴다)
      ├─ process/*.bpmn        정의들 (C1 `process/`와 같은 이름)
      ├─ process/*.dmn         규칙 태스크가 쓰는 결정표
      ├─ cases/*.cases.json    시험 케이스 (패키지에는 넣지 않는다, C1)
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


class WorkspaceError(ValueError):
    """작업 폴더에서 할 수 없는 일 (이름이 겹친다·규칙에 맞지 않는다)."""


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
    definitions: list[Definition] = field(default_factory=list)

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
        """호출(`callActivity`)이 찾을 다른 정의 — `RunEnv.processes`."""
        return {d.process.id: d.process for d in self.definitions if d.process is not None}

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

    def import_example(self, source: Path, process_id: str, *, group: str = DEFAULT_GROUP) -> BpmProcess:
        """예제 BPM 프로세스 가져오기 (STU-01 파일 메뉴).

        `source`는 업무 예제의 `bpmn/` 폴더이고, `<id>.bpmn`과 그것이 쓰는 `.dmn`·케이스를
        함께 가져온다. **예제 폴더는 생성물이라 건드리지 않는다** (CLAUDE.md §2).
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
        for node in definition.all_nodes():
            rule = node.prop("rule")
            if rule is None:
                continue
            decision = source / f"{rule.decision}.dmn"
            if decision.is_file():
                (made.folder / "process" / decision.name).write_text(
                    decision.read_text(encoding="utf-8"), encoding="utf-8", newline="\n"
                )
        cases = source.parent / "cases" / f"{process_id}.cases.json"
        if cases.is_file():
            (made.folder / "cases" / cases.name).write_text(
                cases.read_text(encoding="utf-8"), encoding="utf-8", newline="\n"
            )
        return self.read(made.folder, group)


__all__ = [
    "DEFAULT_GROUP",
    "ID_PATTERN",
    "RECORD_NAME",
    "BpmProcess",
    "Definition",
    "Group",
    "Workspace",
    "WorkspaceError",
    "read_record",
    "write_record",
]
