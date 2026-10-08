"""바깥 앱 한 벌 — **주소와 검증된 외부 확장 정의** (C13 「전송」, C7).

실행하는 쪽(Bot UI·서버 실행기)이 Center에서 받아 **파일로** 건네고, 실행기가 이것을 읽어
`RunEnv.services`를 짓는다. 실행기는 Center를 부르지 않는다 (ADR-0031 — 올라오는 것은 실행
기록, 내려가는 것은 제어 파일뿐이다).

지키는 것 넷.

- **봉투를 다시 검증한다** (C13 「전송」, E6). Center가 보관한 정의와 봉투를 그대로 받아
  `verify_external`로 본다 — 관리자 토큰만 새어도 Bot의 키가 다른 주소로 새는 일을 막는 관문이
  배포와 같아야 한다. **검증되지 않은 정의는 쓰지 않는다** (사유는 `problems`에 남는다).
- **주소의 출처는 하나다** (C13) — Center 리소스 등록이 이기고, 없으면 정의의 `base_url`이다
  (그 폴백은 `AdapterCaller`가 한다). C11 서비스 앱은 등록된 주소밖에 없다.
- **키 값은 여기 없다.** 참조 이름만 오고, 값은 실행하는 쪽이 준 `secrets`가 푼다 (ADR-0013).
- **매니페스트가 고정한 해시와 대조한다** (C1 `requires.extensions[].definition_hash`) — 정의가
  바뀌었으면 그 Bot은 승인·배포를 다시 받아야 한다. 몰래 새 정의로 돌리지 않는다.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chaeksas.contracts.extension import ExtensionManifest, definition_hash, verify_external
from chaeksas.contracts.manifest import ExtensionNeed
from chaeksas.contracts.signing import AdminKey, Envelope
from chaeksas.core.services import ServiceCaller

#: 파일 모양의 판 — 실행하는 쪽과 실행기가 같은 것을 본다.
SCHEMA = 1


@dataclass(frozen=True)
class External:
    """검증을 통과한 외부 확장 하나."""

    manifest: ExtensionManifest
    definition_hash: str


@dataclass(frozen=True)
class AppDirectory:
    """부를 수 있는 바깥 앱들. `core.services.Addresses`로 그대로 쓰인다.

    `secrets`는 `key_ref` → 키 값이다 (없으면 키를 풀지 못한다 — 부르는 일이 분명히 실패한다).
    """

    addresses: Mapping[str, str] = field(default_factory=dict)
    externals: Mapping[str, External] = field(default_factory=dict)
    #: 쓰지 못한 정의와 그 사유 (`{확장 id: 사유}`) — 조용히 사라지지 않는다.
    problems: Mapping[str, str] = field(default_factory=dict)
    secrets: Callable[[str], str | None] | None = None

    # ── `Addresses` ──

    def base_url(self, app_id: str) -> str | None:
        """**Center 리소스 등록만** 돌려준다 — 정의의 값으로 떨어지는 것은 어댑터가 한다."""
        return self.addresses.get(app_id)

    def key(self, key_ref: str) -> str | None:
        return self.secrets(key_ref) if self.secrets is not None else None

    # ── 쓰는 쪽 ──

    @property
    def definitions(self) -> dict[str, ExtensionManifest]:
        """`AdapterCaller`에게 줄 **검증된** 정의들."""
        return {app_id: one.manifest for app_id, one in self.externals.items()}

    def caller(self, *, caller_type: str = "bot_ui", client: Any = None) -> ServiceCaller:
        """`RunEnv.services` 하나 — 외부 확장은 어댑터로, 나머지는 C11로 간다."""
        from chaeksas.core.http_adapter import AdapterCaller, RoutedCaller  # noqa: PLC0415 - 순환 피함
        from chaeksas.core.services import HttpServiceCaller  # noqa: PLC0415

        return RoutedCaller(
            adapter=AdapterCaller(definitions=self.definitions, addresses=self, client=client),
            others=HttpServiceCaller(addresses=self, caller_type=caller_type, client=client),
        )

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


def read_directory(
    path: Path | None,
    *,
    secrets: Callable[[str], str | None] | None = None,
) -> AppDirectory:
    """실행하는 쪽이 쓴 파일을 읽어 **검증된 것만** 담는다. 파일이 없으면 빈 명부다."""
    if path is None or not path.is_file():
        return AppDirectory(secrets=secrets)
    raw = json.loads(path.read_text(encoding="utf-8"))
    return build(raw, secrets=secrets)


def build(raw: Mapping[str, Any], *, secrets: Callable[[str], str | None] | None = None) -> AppDirectory:
    """파일 내용 하나를 명부로. **봉투를 검증하고 통과한 것만** 싣는다."""
    keys = [AdminKey.model_validate(one) for one in raw.get("keys") or []]
    addresses = {
        str(app_id): str(base) for app_id, base in (raw.get("addresses") or {}).items() if base
    }
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

    return AppDirectory(addresses=addresses, externals=externals, problems=problems, secrets=secrets)


def to_json_dict(
    *,
    addresses: Mapping[str, str],
    keys: Sequence[AdminKey],
    extensions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """실행하는 쪽이 쓸 파일 내용. **키 값·업무 값은 넣지 않는다** (ADR-0013, 원칙 6)."""
    return {
        "schema": SCHEMA,
        "addresses": {str(app_id): str(base) for app_id, base in addresses.items() if base},
        "keys": [one.to_json_dict() for one in keys],
        "extensions": [dict(one) for one in extensions],
    }


__all__ = [
    "SCHEMA",
    "AppDirectory",
    "External",
    "build",
    "read_directory",
    "to_json_dict",
]
