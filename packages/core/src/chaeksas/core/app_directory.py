"""검증된 외부 확장 정의 한 벌 (C13 「전송」).

**주소도 키도 없다** (ADR-0102) — 바깥 앱은 C15 외부 작업으로 부르고(`core.services.CenterServiceCaller`)
외부 앱의 주소·키는 어댑터 일꾼의 설정에만 있다. 여기 남은 일은 **정의를 받아 다시 검증하고
고정한 해시와 대조하는 것**이다 — 실행하는 쪽(시작 전 `unusable`)과 어댑터 일꾼(돌릴 정의)이 같은
코드를 쓴다.

**이 모듈에 두 쪽이 있다.**

- **받아 두는 쪽** (`DirectoryCache`) — Center에서 정의·봉투를 받아 들고 있다가, 그 BPM 프로세스가 쓰는
  것만 골라 준다. PC 실행기는 **파일로** 실행 프로세스에 건네고, **서버 실행기는 제가
  Center를 부르므로** 파일을 거치지 않고 바로 짓는다 (`directory_for`).
- **읽는 쪽** (`AppDirectory`·`build`·`read_directory`) — 받은 것을 **다시 검증한다**.

**둘이 한 자리에 있는 것이 요점이다** — 두 벌이면 「PC는 되는데 서버는 안 된다」가 된다.

지키는 것 둘.

- **봉투를 다시 검증한다** (C13 「전송」, E6). Center가 보관한 정의와 봉투를 그대로 받아
  `verify_external`로 본다 — 관리자 토큰만 새어도 BPM 프로세스의 키가 다른 주소로 새는 일을 막는 관문이
  배포와 같아야 한다. **검증되지 않은 정의는 쓰지 않는다** (사유는 `problems`에 남는다).
- **매니페스트가 고정한 해시와 대조한다** (C1 `requires.extensions[].definition_hash`) — 정의가
  바뀌었으면 그 BPM 프로세스는 승인·배포를 다시 받아야 한다. 몰래 새 정의로 돌리지 않는다.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chaeksas.contracts.extension import ExtensionManifest, definition_hash, verify_external
from chaeksas.contracts.manifest import ExtensionNeed, Manifest
from chaeksas.contracts.signing import AdminKey, Envelope

#: 파일 모양의 판 — 실행하는 쪽과 실행기가 같은 것을 본다.
SCHEMA = 1

#: 들고 있는 명부 (Center가 꺼져 있어도 BPM 프로세스가 돈다).
CACHE_NAME = "app-directory.json"

#: Center가 **모른다고 답한** 것 — 들고 있던 것을 버린다 (철회·삭제는 보안 동작이다).
MISSING_STATUS = 404


@dataclass(frozen=True)
class External:
    """검증을 통과한 외부 확장 하나."""

    manifest: ExtensionManifest
    definition_hash: str


@dataclass(frozen=True)
class AppDirectory:
    """검증을 지난 외부 확장 정의들."""

    externals: Mapping[str, External] = field(default_factory=dict)
    #: 쓰지 못한 정의와 그 사유 (`{확장 id: 사유}`) — 조용히 사라지지 않는다.
    problems: Mapping[str, str] = field(default_factory=dict)

    @property
    def definitions(self) -> dict[str, ExtensionManifest]:
        """`AdapterCaller`에게 줄 **검증된** 정의들."""
        return {app_id: one.manifest for app_id, one in self.externals.items()}

    def unusable(self, needs: Sequence[ExtensionNeed]) -> list[str]:
        """매니페스트가 요구하는 외부 확장 중 **쓸 수 없는 것**과 그 사유 (C1).

        `definition_hash`가 적힌 것만 외부 확장이다 (내장·사내는 설치 파일이 신뢰의 근거다).
        **실행 전에** 본다 — 중간에 알면 이미 한 일을 되돌릴 수 없다.
        """
        out: list[str] = []
        for need in needs:
            if not need.definition_hash:
                continue
            found = self.externals.get(need.id)
            if found is None:
                why = self.problems.get(need.id) or "정의를 받지 못했다 (Center 리소스 목록 확인)"
                out.append(f"{need.id}: {why}")
                continue
            if found.definition_hash != need.definition_hash:
                # 정의가 바뀌었다 — 승인받은 그 정의가 아니다 (C1).
                out.append(
                    f"{need.id}: 패키지가 고정한 정의가 아니다 "
                    f"(요구 {need.definition_hash[:19]}…, 받은 것 {found.definition_hash[:19]}…)"
                )
        return out


def read_directory(path: Path | None) -> AppDirectory:
    """실행하는 쪽이 쓴 파일을 읽어 **검증된 것만** 담는다. 파일이 없으면 빈 명부다."""
    if path is None or not path.is_file():
        return AppDirectory()
    raw = json.loads(path.read_text(encoding="utf-8"))
    return build(raw)


def build(raw: Mapping[str, Any]) -> AppDirectory:
    """파일 내용 하나를 명부로. **봉투를 검증하고 통과한 것만** 싣는다."""
    keys = [AdminKey.model_validate(one) for one in raw.get("keys") or []]
    externals: dict[str, External] = {}
    problems: dict[str, str] = {}

    for entry in raw.get("extensions") or []:
        definition = entry.get("definition")
        app_id = str((definition or {}).get("id") or entry.get("id") or "?")
        if not isinstance(definition, dict):
            problems[app_id] = "정의가 없다"
            continue
        try:
            envelope = Envelope.model_validate(entry.get("envelope") or {})
        except ValueError:
            # **봉투 없는 정의는 쓰지 않는다** — 서명이 유일한 관문이다 (C2).
            problems[app_id] = "서명 봉투가 없다"
            continue
        failed = verify_external(definition, envelope, keys=keys)
        if failed:
            problems[app_id] = "; ".join(str(one) for one in failed)
            continue
        try:
            manifest = ExtensionManifest.model_validate(definition)
        except ValueError as e:
            problems[app_id] = f"정의를 읽지 못했다 ({e.__class__.__name__})"
            continue
        externals[manifest.id] = External(manifest=manifest, definition_hash=definition_hash(definition))

    return AppDirectory(externals=externals, problems=problems)


def to_json_dict(*, keys: Sequence[AdminKey], extensions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """실행하는 쪽이 쓸 파일 내용. **키 값·업무 값은 넣지 않는다** (원칙 6)."""
    return {
        "schema": SCHEMA,
        "keys": [one.to_json_dict() for one in keys],
        "extensions": [dict(one) for one in extensions],
    }


# ─────────────────────────── 받아 두는 쪽 (C7) ───────────────────────────


def external_ids(manifest: Manifest) -> list[str]:
    """매니페스트가 **정의를 고정한** 확장들 (C1 `definition_hash`) — 반드시 외부다.

    `unusable()`이 이것들을 대조한다 — 고정한 정의가 아니면 **시작조차 하지 않는다**.
    """
    return sorted({need.id for need in manifest.requires.extensions if need.definition_hash})


def extension_ids(manifest: Manifest) -> list[str]:
    """매니페스트가 요구하는 확장 **전부** — 정의를 받아 볼 대상이다 (C1 `requires.extensions`).

    **고정한 것만 묻지 않는다.** 지금 내보내기는 `definition_hash`를 적지 않으므로(C1에 칸은
    있지만 채우는 쪽이 없다) 고정된 것만 물으면 **외부 앱을 하나도 부를 수 없다**. 어느 것이
    외부인가는 **Center의 답이 말해 준다** — 내장·사내는 정의 없이 오고(그것은 설치 파일에
    있다, C13) 그런 응답은 담지 않는다. 고정된 것의 대조는 `external_ids`·`unusable()`이
    그대로 한다.
    """
    return sorted({need.id for need in manifest.requires.extensions})


@dataclass
class DirectoryCache:
    """바깥 앱 명부 — 받아 두고, 그 BPM 프로세스가 쓸 것을 만든다.

    **Center를 어떻게 부르는지는 모른다** — `core.deploy`의 `fetch`처럼 **호출 가능한 것**을
    받는다 (`core`는 앱을 import하지 않는다 — `docs/01-architecture.md` §5). 받지 못한 것은
    `problems`에 남고, 「닿지 못했다」와 「없다」는 예외의 `status`로 가른다.
    """

    data_dir: Path
    #: 외부 확장 하나를 주는 쪽 — `(id) -> ExtensionResource` (C7).
    fetch_extension: Any = None
    #: 마지막으로 받지 못한 사유 (화면·기록이 말할 거리).
    problems: list[str] = field(default_factory=list)

    @classmethod
    def using(cls, data_dir: Path, client: Any = None) -> DirectoryCache:
        """`extension(id)`를 가진 것(Center 클라이언트)을 꽂는다. 없으면 들고 있던 것을 쓴다."""
        return cls(data_dir=data_dir, fetch_extension=getattr(client, "extension", None))

    @property
    def cache_path(self) -> Path:
        return self.data_dir / CACHE_NAME

    def cached(self) -> dict[str, Any]:
        """들고 있는 것 — `{extensions: [...]}`."""
        try:
            raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"extensions": []}
        return {"extensions": list(raw.get("extensions") or [])}

    def _save(self, held: dict[str, Any]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(held, ensure_ascii=False), encoding="utf-8")

    def refresh(self, *, externals: Iterable[str] = ()) -> dict[str, Any]:
        """Center에서 받아 들고 있는 것을 고친다.

        **한 가지를 받지 못해도 나머지는 받는다.**
        """
        self.problems = []
        held = self.cached()
        extensions: dict[str, dict[str, Any]] = {
            str((one.get("definition") or {}).get("id") or ""): one for one in held["extensions"]
        }

        for extension_id in externals:
            found, drop = self._definition(extension_id)
            if found is not None:
                extensions[extension_id] = found
            elif drop:
                # Center가 **모른다고 답했다** — 철회·삭제다. 들고 있던 것을 버린다.
                extensions.pop(extension_id, None)

        held = {"extensions": [extensions[key] for key in sorted(extensions) if key]}
        self._save(held)
        return held

    def _definition(self, extension_id: str) -> tuple[dict[str, Any] | None, bool]:
        """외부 확장 하나 → `(정의와 봉투, 버려야 하나)`. 봉투 검증은 **읽는 쪽이** 한다."""
        if self.fetch_extension is None:
            return None, False
        try:
            found = self.fetch_extension(extension_id)
        except Exception as e:  # noqa: BLE001 — 닿지 못할 수 있다
            if getattr(e, "status", None) == MISSING_STATUS:
                # **Center가 모른다고 답했다** — 철회됐다. 들고 있던 것을 버린다.
                self.problems.append(f"{extension_id}은 Center에 없습니다 (철회됐을 수 있습니다)")
                return None, True
            self.problems.append(f"{extension_id} 정의를 받지 못했습니다 — {e}")
            return None, False
        if found.definition is None or found.envelope is None:
            # 내장·사내 확장이다 — 정의는 설치 파일에 있다 (C13). 받을 것이 없다.
            return None, False
        return {"definition": found.definition, "envelope": found.envelope}, False

    # ── 그 BPM 프로세스가 쓸 것만 ──

    def body_for(
        self, manifest: Manifest, *, keys: Sequence[AdminKey], refresh: bool = True
    ) -> dict[str, Any] | None:
        """그 BPM 프로세스가 쓸 명부 하나. 쓸 것이 없으면 `None`.

        **담는 것은 그 BPM 프로세스가 쓰는 것뿐이다** — 다른 BPM 프로세스가 쓰는 정의는 넣지 않는다.
        """
        externals = set(extension_ids(manifest))
        if not externals:
            return None
        held = self.refresh(externals=sorted(externals)) if refresh else self.cached()
        chosen = [
            one for one in held["extensions"] if str((one.get("definition") or {}).get("id") or "") in externals
        ]
        return to_json_dict(keys=list(keys), extensions=chosen)

    def write_for(
        self, manifest: Manifest, *, path: Path, keys: Sequence[AdminKey], refresh: bool = True
    ) -> Path | None:
        """그 BPM 프로세스가 쓸 명부를 **파일로** 쓴다 → 실행기의 `--services`. 쓸 것이 없으면 `None`.

        PC 실행기가 자식 프로세스에 건네는 길이다 (ADR-0031). 서버 실행기는 `directory_for`다.
        """
        body = self.body_for(manifest, keys=keys, refresh=refresh)
        if body is None:
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        return path

    def directory_for(
        self,
        manifest: Manifest,
        *,
        keys: Sequence[AdminKey],
        refresh: bool = True,
    ) -> AppDirectory:
        """그 BPM 프로세스가 쓸 명부를 **그 자리에서** 짓는다 (서버 실행기 — 파일을 거치지 않는다).

        **봉투는 여기서도 검증된다** (`build`) — 파일을 거치지 않는 것이 관문을 비켜 가는
        길이 되면 안 된다 (C13 E6). 부르는 것이 없으면 **빈 명부**다.
        """
        body = self.body_for(manifest, keys=keys, refresh=refresh)
        return build(body or {})


__all__ = [
    "CACHE_NAME",
    "MISSING_STATUS",
    "SCHEMA",
    "AppDirectory",
    "DirectoryCache",
    "External",
    "build",
    "extension_ids",
    "external_ids",
    "read_directory",
    "to_json_dict",
]
