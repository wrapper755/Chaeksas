"""파일을 읽고 쓰는 자리 — C14 §파일 경로·파일 목록·파일 출력.

결정은 [ADR-0026](../../../../docs/decisions/0026-file-paths-and-file-list-task.md)이다.

실행 하나가 닿을 수 있는 곳은 **출력 폴더**(쓰기·상대 경로의 기준)와 **읽기 허용 폴더**(읽기)
뿐이다. 그 밖을 가리키면 `PathDenied`이고, 엔진은 그것을 오류 경계로 **받지 않는다** — 그림이나
설정이 잘못된 것이라 고쳐야 한다. 폴더가 없거나 읽을 수 없는 것은 `FileTaskError`(업무 실패)다.

경로는 `pathlib`만 쓰고, 파일은 늘 `encoding="utf-8"`로 연다 (CLAUDE.md §5 — Windows 기본
인코딩은 cp949다). BPM 프로세스가 적는 경로의 구분자는 `/`이고, 여기서 그 OS의 것으로 바뀐다.

**변수에 들어가는 경로는 BPM 프로세스가 적은 그대로**다 (`folder`·`path`에 이어 붙인 것).
실행한 PC의 절대 경로를 엔진이 새로 만들어 업무 값에 섞지 않는다.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from chaeksas.contracts.bpmn_ext import APPENDABLE_FORMATS, DataOutput, FileList
from chaeksas.core.expr import Scope, fill

#: Excel이 UTF-8 CSV를 바로 열게 하는 표시 (없으면 한글이 깨져 보인다).
CSV_BOM = "﻿"


class PathDenied(ValueError):
    """실행 폴더 밖을 가리켰다. **오류 경계로 받지 않는다** (그림·설정이 잘못된 것이다)."""


class FileTaskError(RuntimeError):
    """폴더가 없다·읽을 수 없다·형식이 맞지 않는다 — **업무 실패**다 (경계가 받는다)."""


def _has_anchor(raw: str) -> bool:
    """절대 경로인가. Windows에서 `/share/x`는 `is_absolute()`가 거짓이라 anchor를 본다."""
    return bool(Path(raw).anchor)


@dataclass(frozen=True)
class Workspace:
    """실행 하나가 파일에 닿을 수 있는 범위 (C14 §파일 경로).

    실행하는 쪽(Bot UI·Studio 시험 실행·서버 실행기)이 정해서 준다. 주지 않으면 아무것도
    읽고 쓸 수 없다 — **조용히 아무 데나 쓰지 않는다.**
    """

    #: 실행 하나가 파일을 쓰는 곳이자 상대 경로의 기준.
    output_dir: Path | None = None
    #: 파일 목록이 들여다볼 수 있는 폴더 (출력 폴더는 늘 포함된다).
    readable: tuple[Path, ...] = ()
    #: 출력 폴더 **밖에 쓸 수 있는** 폴더 (ADR-0032). **기본은 비어 있다** — 비면 지금까지와
    #: 똑같이 출력 폴더 안만 쓸 수 있다. 쓸 수 있는 곳은 **읽기도 된다** (덧붙이려면 읽어야 한다).
    writable: tuple[Path, ...] = ()

    def _roots(self) -> list[Path]:
        found = [*self.readable, *self.writable]
        if self.output_dir is not None:
            found.append(self.output_dir)
        return [p.resolve() for p in found]

    def _write_roots(self) -> list[Path]:
        found = [*self.writable]
        if self.output_dir is not None:
            found.append(self.output_dir)
        return [p.resolve() for p in found]

    def for_write(self, raw: str) -> Path:
        """쓸 자리. 출력 폴더와 **쓰기 허용 폴더** 안만 된다 (ADR-0032).

        **상대 경로의 기준은 늘 출력 폴더**다 — 쓰기 허용 폴더는 절대 경로로만 가리킨다.
        """
        roots = self._write_roots()
        if not roots:
            raise PathDenied("출력 폴더가 없다 — 실행하는 쪽이 정해 주어야 파일을 쓸 수 있다")
        if _has_anchor(raw):
            found = Path(raw).resolve()
        elif self.output_dir is None:
            raise PathDenied(f"상대 경로의 기준(출력 폴더)이 없다: {raw}")
        else:
            found = (self.output_dir.resolve() / Path(raw)).resolve()
        if not any(found.is_relative_to(root) for root in roots):
            allowed = ", ".join(root.as_posix() for root in roots)
            raise PathDenied(f"쓰기 허용 폴더 밖이다: {raw} (허용: {allowed})")
        return found

    def for_read(self, raw: str) -> Path:
        """읽을 자리. 출력 폴더·**읽기 허용 폴더**·쓰기 허용 폴더 안만 된다."""
        roots = self._roots()
        if not roots:
            raise PathDenied("읽기 허용 폴더가 없다 — 실행하는 쪽이 정해 주어야 파일을 읽을 수 있다")
        if _has_anchor(raw):
            found = Path(raw).resolve()
        elif self.output_dir is None:
            raise PathDenied(f"상대 경로의 기준(출력 폴더)이 없다: {raw}")
        else:
            found = (self.output_dir.resolve() / Path(raw)).resolve()
        if not any(found.is_relative_to(root) for root in roots):
            allowed = ", ".join(root.as_posix() for root in roots)
            raise PathDenied(f"읽기 허용 폴더 밖이다: {raw} (허용: {allowed})")
        return found


# ─────────────────────────── 파일 목록 (chk:fileList) ───────────────────────────


@dataclass(frozen=True)
class Listing:
    """파일 목록 한 번의 결과. `paths`는 **BPM 프로세스가 적은 `folder` 기준**이다."""

    paths: list[str]
    folder: str

    @property
    def count(self) -> int:
        return len(self.paths)


def list_files(workspace: Workspace, spec: FileList, scope: Scope) -> Listing:
    """폴더를 훑어 파일 경로 목록을 만든다 (C14 §파일 목록).

    차례는 `sort`가 정한다 — 디스크가 주는 순서를 그대로 쓰면 같은 폴더에서도 실행마다 결과가
    달라진다 (ADR-0026). 맞는 파일이 없으면 빈 목록이고 실패가 아니다.
    """
    folder = fill(spec.folder, scope).strip().rstrip("/")
    base = workspace.for_read(folder)
    if not base.is_dir():
        raise FileTaskError(f"폴더가 없다: {folder}")

    try:
        found = base.rglob(spec.pattern) if spec.recursive else base.glob(spec.pattern)
        files = [p for p in found if p.is_file()]
    except OSError as e:
        raise FileTaskError(f"폴더를 읽을 수 없다: {folder} ({e})") from e

    if spec.sort == "modified":
        files.sort(key=lambda p: (p.stat().st_mtime, p.name))
    else:
        files.sort(key=lambda p: p.relative_to(base).as_posix())
    if spec.limit is not None:
        files = files[: spec.limit]

    prefix = PurePosixPath(folder) if folder else None
    paths = [
        (prefix / p.relative_to(base).as_posix()).as_posix() if prefix else p.relative_to(base).as_posix()
        for p in files
    ]
    return Listing(paths=paths, folder=folder)


# ─────────────────────────── 파일 출력 (chk:dataOutput) ───────────────────────────


@dataclass(frozen=True)
class Written:
    """쓴 파일 하나. `path`는 **BPM 프로세스가 적은 경로 그대로**다 (`store_as`에 들어간다)."""

    path: str
    size: int


def write_output(workspace: Workspace, spec: DataOutput, scope: Scope) -> Written:
    """파일 하나를 쓴다 (C14 §파일 출력)."""
    path = fill(spec.path, scope)
    target = workspace.for_write(path)
    if spec.append and spec.format not in APPENDABLE_FORMATS:
        raise FileTaskError(f"{spec.format}은 이어 쓸 수 없다 (B5)")

    target.parent.mkdir(parents=True, exist_ok=True)
    if spec.format == "xlsx":
        _write_xlsx(target, spec, scope)
    else:
        text = _render(spec, scope, appending=spec.append and target.exists())
        with target.open("a" if spec.append else "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    return Written(path=path, size=target.stat().st_size)


def _values(spec: DataOutput, scope: Scope) -> list[tuple[str, Any]]:
    """`variables`의 (이름, 값). 없는 변수는 실행 오류다 (템플릿과 같은 태도)."""
    out = []
    for name in spec.variables or ():
        if name not in scope.variables:
            raise FileTaskError(f"파일 출력이 모르는 변수를 쓴다: {name}")
        out.append((name, scope.variables[name]))
    return out


def _is_table(value: Any) -> bool:
    """사전 목록이면 표로 본다 (C14 §파일 출력)."""
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and bool(value) and all(
        isinstance(row, Mapping) for row in value
    )


def _columns(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """열 이름 — 사전 열쇠의 합집합, **처음 나온 순서**다 (정렬하면 사람이 적은 차례가 깨진다)."""
    out: list[str] = []
    for row in rows:
        for key in row:
            if key not in out:
                out.append(str(key))
    return out


def _cell(value: Any) -> str:
    return "" if value is None else str(value)


def _render(spec: DataOutput, scope: Scope, *, appending: bool) -> str:
    if spec.template:
        text = fill(spec.template, scope)
        if spec.format == "json":
            try:
                json.loads(text)
            except ValueError as e:
                raise FileTaskError(f"json 파일 출력의 template가 JSON이 아니다: {e}") from e
        return text if text.endswith("\n") else text + "\n"

    pairs = _values(spec, scope)
    if spec.format == "json":
        return json.dumps(dict(pairs), ensure_ascii=False, indent=2) + "\n"
    if spec.format == "csv":
        return _render_csv(pairs, appending=appending)
    return _render_text(pairs, markdown=spec.format == "md")


def _render_text(pairs: Sequence[tuple[str, Any]], *, markdown: bool) -> str:
    chunks: list[str] = []
    for name, value in pairs:
        if not _is_table(value):
            chunks.append(f"{name}: {_cell(value)}")
            continue
        rows: Sequence[Mapping[str, Any]] = value
        columns = _columns(rows)
        if markdown:
            head = "| " + " | ".join(columns) + " |"
            rule = "| " + " | ".join("---" for _ in columns) + " |"
            body = ["| " + " | ".join(_cell(row.get(c)) for c in columns) + " |" for row in rows]
            chunks.append("\n".join([f"## {name}", "", head, rule, *body]))
        else:
            lines = [name]
            for row in rows:
                lines += [f"{c}: {_cell(row.get(c))}" for c in columns] + [""]
            chunks.append("\n".join(lines).rstrip())
    return "\n\n".join(chunks) + "\n"


def _render_csv(pairs: Sequence[tuple[str, Any]], *, appending: bool) -> str:
    if len(pairs) != 1:
        raise FileTaskError(f"csv의 variables는 이름 하나다 ({len(pairs)}개를 받았다)")
    name, value = pairs[0]
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    if _is_table(value):
        rows: Sequence[Mapping[str, Any]] = value
        columns = _columns(rows)
        if not appending:  # 이어 쓸 때는 열 이름 줄을 다시 쓰지 않는다 (C14)
            writer.writerow(columns)
        for row in rows:
            writer.writerow([_cell(row.get(c)) for c in columns])
    else:
        if not appending:
            writer.writerow(["이름", "값"])
        writer.writerow([name, _cell(value)])
    return ("" if appending else CSV_BOM) + buffer.getvalue()


def _write_xlsx(target: Path, spec: DataOutput, scope: Scope) -> None:
    """`variables`의 **이름마다 시트 하나** (C14 §파일 출력)."""
    from openpyxl import Workbook  # noqa: PLC0415 — 엑셀을 쓰는 실행에서만 든다

    pairs = _values(spec, scope)
    if not pairs:
        raise FileTaskError("xlsx 파일 출력에 variables가 없다")
    book = Workbook()
    book.remove(book.active)
    for index, (name, value) in enumerate(pairs):
        title = spec.sheet if (spec.sheet and len(pairs) == 1) else name
        sheet = book.create_sheet(title=_sheet_title(title, index))
        if _is_table(value):
            rows: Sequence[Mapping[str, Any]] = value
            columns = _columns(rows)
            sheet.append(columns)
            for row in rows:
                sheet.append([_excel(row.get(c)) for c in columns])
        else:
            sheet.append([name, _excel(value)])
    book.save(target)


def _excel(value: Any) -> Any:
    """엑셀 칸에 넣을 값. 수·글자·참거짓은 그대로, 목록·사전은 글자로 (openpyxl이 거부한다)."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (Sequence, Mapping)) and not value:
        return ""
    return str(value)


#: 엑셀 시트 이름에 쓸 수 없는 글자와 길이 한도.
_SHEET_BAD = set(r"[]:*?/\\")
_SHEET_MAX = 31


def _sheet_title(name: str, index: int) -> str:
    cleaned = "".join("_" if c in _SHEET_BAD else c for c in name).strip()[:_SHEET_MAX]
    return cleaned or f"시트{index + 1}"


__all__ = [
    "CSV_BOM",
    "FileTaskError",
    "Listing",
    "PathDenied",
    "Workspace",
    "Written",
    "list_files",
    "write_output",
]
