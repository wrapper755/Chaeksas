"""바깥 앱 명부를 Center에서 받아 들고 있는다 (C7·C13 「전송」).

Bot을 띄우기 전에 그 Bot이 부르는 **서비스 앱의 주소**(C7 리소스 등록)와, **외부 확장의 정의와
봉투**를 받아 실행기에 파일로 넘긴다. 실행기는 Center를 부르지 않는다 (ADR-0031).

주소의 출처가 둘인 것이 아니다 (C13 「주소 출처는 하나다」).

- **서비스 앱**(C11)은 운영자가 Center에 주소를 넣은 것뿐이다 — 등록되지 않으면 부를 수 없다.
- **외부 앱**은 C11이 아니라 `/manifest`가 없어 Center에 등록되지 않는다. 주소는 **정의의
  `base_url`**이고, 어댑터가 그것으로 떨어진다 (`core.http_adapter`).

지키는 것 넷.

- **닿지 못하면 들고 있던 것을 쓴다** — Center가 꺼졌다고 업무가 멈추지 않는다 (ADR-0007).
  캐시가 낡았을 수는 있지만, 정의가 바뀌었으면 **해시가 달라** 실행기가 거절한다 (C1).
- **404는 들고 있던 것을 버린다** — 철회·삭제된 확장은 Center가 모른다고 분명히 답한 것이다.
  철회된 정의로 돌리는 것이 모르고 멈추는 것보다 나쁘다 (C13 — 철회는 보안 동작이다).
- **그 Bot이 쓰는 것만 담는다** — 매니페스트가 적은 앱·확장만 (필요한 것만 준다).
- **키 값은 담지 않는다** (ADR-0013). Admin 공개키는 하트비트로 온 것을 그대로 싣는다 (C4).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chaeksas.bot_ui.center_client import CenterProblem, Unreachable
from chaeksas.contracts.manifest import Manifest
from chaeksas.contracts.signing import AdminKey
from chaeksas.core.app_directory import to_json_dict

log = logging.getLogger(__name__)

#: 들고 있는 명부 (Center가 꺼져 있어도 Bot이 돈다).
CACHE_NAME = "app-directory.json"


def external_ids(manifest: Manifest) -> list[str]:
    """매니페스트가 요구하는 **외부** 확장들 (C1 — `definition_hash`가 적힌 것).

    내장·사내 확장은 정의가 설치 파일에 있어 받을 것이 없다 (C13).
    """
    return sorted({need.id for need in manifest.requires.extensions if need.definition_hash})


def app_ids(manifest: Manifest) -> list[str]:
    """부르는 **서비스 앱**들 (C11). 외부 앱은 주소가 정의에 있어 여기 없다."""
    return sorted({need.app_id for need in manifest.requires.service_apps})


@dataclass
class Services:
    """바깥 앱 명부 — 받아 두고, 실행기에 줄 내용을 만든다."""

    data_dir: Path
    #: `CenterClient` (없으면 Center를 부르지 않고 들고 있던 것만 쓴다).
    client: Any = None
    #: 마지막으로 받지 못한 사유 (화면이 말할 거리).
    problems: list[str] = field(default_factory=list)

    @property
    def cache_path(self) -> Path:
        return self.data_dir / CACHE_NAME

    def cached(self) -> dict[str, Any]:
        """들고 있는 것 — `{apps: {app_id: {base_url, extension_id}}, extensions: [...]}`."""
        try:
            raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"apps": {}, "extensions": []}
        return {"apps": dict(raw.get("apps") or {}), "extensions": list(raw.get("extensions") or [])}

    def _save(self, held: dict[str, Any]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(held, ensure_ascii=False), encoding="utf-8")

    def base_url_of(self, *, app_id: str | None = None, extension_id: str | None = None) -> str | None:
        """들고 있는 주소 하나. **Center를 부르지 않는다** (화면을 그릴 때마다 묻지 않게)."""
        apps = self.cached()["apps"]
        if app_id and apps.get(app_id, {}).get("base_url"):
            return str(apps[app_id]["base_url"])
        if extension_id:
            for one in apps.values():
                if one.get("extension_id") == extension_id and one.get("base_url"):
                    return str(one["base_url"])
        return None

    def refresh(self, *, externals: Iterable[str] = ()) -> dict[str, Any]:
        """Center에서 받아 들고 있는 것을 고친다.

        **한 가지를 받지 못해도 나머지는 받는다** — 주소를 못 읽었다고 정의까지 버리지 않는다.
        """
        self.problems = []
        held = self.cached()
        apps: dict[str, Any] = dict(held["apps"])
        extensions: dict[str, dict[str, Any]] = {
            str((one.get("definition") or {}).get("id") or ""): one for one in held["extensions"]
        }

        got = self._service_apps()
        if got is not None:
            # 목록 전체를 받았다 — **해제된 앱은 사라져야 한다** (낡은 주소로 부르지 않게).
            apps = got
        for extension_id in externals:
            found, drop = self._definition(extension_id)
            if found is not None:
                extensions[extension_id] = found
            elif drop:
                # Center가 **모른다고 답했다** — 철회·삭제다. 들고 있던 것을 버린다.
                extensions.pop(extension_id, None)

        held = {"apps": apps, "extensions": [extensions[key] for key in sorted(extensions) if key]}
        self._save(held)
        return held

    def _service_apps(self) -> dict[str, Any] | None:
        """C7 리소스 등록의 주소들. 받지 못하면 `None` (들고 있던 것을 그대로 둔다)."""
        if self.client is None:
            return None
        try:
            found = self.client.service_apps()
        except (Unreachable, CenterProblem) as e:
            self.problems.append(f"서비스 앱 주소를 받지 못했습니다 — {e}")
            return None
        return {
            one.app_id: {"base_url": one.base_url, "extension_id": one.extension_id}
            for one in found
            if one.base_url
        }

    def _definition(self, extension_id: str) -> tuple[dict[str, Any] | None, bool]:
        """외부 확장 하나 → `(정의와 봉투, 버려야 하나)`. 봉투 검증은 **실행기가** 한다."""
        if self.client is None:
            return None, False
        try:
            found = self.client.extension(extension_id)
        except Unreachable as e:
            self.problems.append(f"{extension_id} 정의를 받지 못했습니다 — {e}")
            return None, False
        except CenterProblem as e:
            if e.status == 404:
                self.problems.append(f"{extension_id}은 Center에 없습니다 (철회됐을 수 있습니다)")
                return None, True
            self.problems.append(f"{extension_id} 정의를 받지 못했습니다 — {e}")
            return None, False
        if found.definition is None or found.envelope is None:
            # 내장·사내 확장이다 — 정의는 설치 파일에 있다 (C13). 받을 것이 없다.
            return None, False
        return {"definition": found.definition, "envelope": found.envelope}, False

    def write_for(
        self, manifest: Manifest, *, path: Path, keys: Sequence[AdminKey], refresh: bool = True
    ) -> Path | None:
        """그 Bot이 쓸 명부를 파일로 쓴다 → 실행기의 `--services`. 쓸 것이 없으면 `None`.

        **담는 것은 그 Bot이 쓰는 것뿐이다** — 다른 Bot이 부르는 앱의 주소·정의는 넣지 않는다.
        """
        wanted, externals = set(app_ids(manifest)), set(external_ids(manifest))
        if not wanted and not externals:
            return None
        held = self.refresh(externals=sorted(externals)) if refresh else self.cached()
        body = to_json_dict(
            addresses={
                app_id: str(one["base_url"])
                for app_id, one in held["apps"].items()
                if app_id in wanted and one.get("base_url")
            },
            keys=list(keys),
            extensions=[
                one
                for one in held["extensions"]
                if str((one.get("definition") or {}).get("id") or "") in externals
            ],
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        return path


__all__ = ["CACHE_NAME", "Services", "app_ids", "external_ids"]
