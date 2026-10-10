"""Studio가 바깥 앱을 부르는 길 — Center 리소스 목록에서 주소를, 등록된 정의에서 외부 앱을.

Bot UI 쪽과 **같은 것을 본다** (`core.app_directory`) — 주소는 C7 리소스 등록, 외부 확장은
C13으로 등록된 정의와 봉투다. 그래서 Studio 시험 실행과 배포된 Bot이 같은 앱을 같은 규칙으로
부르고, 봉투도 같은 `verify_external`로 검증된다. 다른 것은 셋뿐이다.

- **파일로 넘기지 않는다.** Bot UI는 실행기(자식 프로세스)에 파일로 주지만 (ADR-0031),
  Studio는 엔진을 제 안에서 돌리므로 명부를 그대로 들고 쓴다.
- **들고 있지 않는다.** Center에 닿지 못하면 **그 자리에서 말한다** — Studio는 현장이 아니라
  개발 도구다. 낡은 주소로 조용히 부르는 것보다 「Center에 닿지 못했습니다」가 낫다
  (ADR-0007의 「들고 있던 것을 쓴다」는 현장 쪽 규칙이다).
- **키는 Studio의 비밀 저장소에서** 푼다 (`StudioCredentials.service_key`, STU-10 「서비스 앱 키」).

이 모듈이 Center를 부르는 것은 **읽기만**이다 (명부는 세 번, STU-03 리소스 탐색기가 뿌리마다
한 번 더). 외부 확장의 정의·봉투는 리소스 목록이 이미 싣고 오므로 확장마다 따로 묻지 않는다
(C7 `ExtensionResource`). **쓰는 쪽은 `upload.py` 하나다** — 그래서 「Center로 올리기」를
붙여도 이 길이 쓰는 길로 바뀌지 않는다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from chaeksas.contracts.center_api import PackageInfo
from chaeksas.contracts.extension import TIER_EXTERNAL
from chaeksas.contracts.resources import (
    ContributedResource,
    ExtensionResource,
    ServiceAppResource,
    ToolpackResource,
)
from chaeksas.contracts.signing import AdminKey
from chaeksas.core.app_directory import AppDirectory, build, to_json_dict

log = logging.getLogger(__name__)

#: Center API 경로 (C5·C7).
RESOURCES = "/api/v1/resources"
ADMIN_KEYS = "/api/v1/admin-keys"
PACKAGES = "/api/v1/packages"

#: 읽기 타임아웃 (초). 사람이 「시험 실행」을 누른 뒤 기다리는 자리다.
TIMEOUT_S = 10


class CenterUnreachable(RuntimeError):
    """Center에서 읽지 못했다 — 화면이 그대로 보여 줄 한 줄."""


@dataclass
class CenterReader:
    """Center를 **읽기만** 하는 작은 클라이언트.

    Bot UI의 `CenterClient`를 쓰지 않는다 — 앱끼리 import하지 않는다 (01-architecture §5).
    여기서 필요한 것은 몇 경로뿐이라 따로 두는 쪽이 싸다.
    """

    base_url: str
    api_key: str
    #: `httpx.Client` 또는 `TestClient` (시험이 끼운다).
    client: Any = None

    def _get(self, path: str) -> Any:
        import httpx  # noqa: PLC0415 — 부를 때만 든다

        url = self.base_url.rstrip("/") + path
        own = self.client is None
        client = self.client or httpx.Client(timeout=TIMEOUT_S)
        try:
            response = client.get(url, headers={"Authorization": f"Bearer {self.api_key}"})
        except httpx.HTTPError as e:
            raise CenterUnreachable(f"Center에 닿지 못했습니다 ({type(e).__name__})") from e
        finally:
            if own:
                client.close()
        if response.status_code >= 400:
            raise CenterUnreachable(f"Center가 {response.status_code}로 답했습니다 ({path})")
        found: Any = response.json()
        return found

    def service_apps(self) -> list[ServiceAppResource]:
        found = self._get(f"{RESOURCES}?type=service_app") or {}
        return [ServiceAppResource.model_validate(one) for one in found.get("items") or []]

    def extensions(self) -> list[ExtensionResource]:
        """등록된 확장들. 외부 확장은 **정의와 봉투를 싣고 온다** (C7)."""
        found = self._get(f"{RESOURCES}?type=extension") or {}
        return [ExtensionResource.model_validate(one) for one in found.get("items") or []]

    def contributed(self, resource_type: str) -> list[ContributedResource]:
        """확장이 기여한 자원들 (C7, STU-03 뿌리 하나). **`data`는 해석하지 않는다** (C13 §5)."""
        found = self._get(f"{RESOURCES}?type=contributed&resource_type={quote(resource_type)}") or {}
        return [ContributedResource.model_validate(one) for one in found.get("items") or []]

    def packages(self, kind: str) -> list[PackageInfo]:
        """그 갈래의 패키지들 (C5 `GET /packages?kind=`). STU-11과 STU-03의 공유 뿌리.

        **C7이 아니라 C5를 읽는다** — C7 리소스 목록에는 `process_lib` 갈래가 없고, STU-11이
        보여야 하는 「상태」(후보·승인됨·지원 종료·철회)는 **패키지 상태**라서다 (CON-06이
        같은 것을 읽는다). 툴팩은 두 길이 다 있는데, **STU-03의 뿌리는 C7을 쓴다**(도구 목록이
        거기 있다) — 쓰는 데가 다르면 읽는 길도 다르다.
        """
        found = self._get(f"{PACKAGES}?kind={quote(kind)}") or []
        return [PackageInfo.model_validate(one) for one in found]

    def toolpacks(self) -> list[ToolpackResource]:
        """툴팩들 (C7 — Center가 `kind=toolpack` 패키지에서 모은다). STU-03 「툴팩」 뿌리."""
        found = self._get(f"{RESOURCES}?type=toolpack") or {}
        return [ToolpackResource.model_validate(one) for one in found.get("items") or []]

    def admin_keys(self) -> list[AdminKey]:
        """봉투를 검증할 Admin **공개**키 (C2). 비밀이 아니라 읽기 토큰으로 읽는다."""
        return [AdminKey.model_validate(one) for one in self._get(ADMIN_KEYS) or []]


@dataclass
class Services:
    """시험 실행에 줄 바깥 앱 명부를 짓는다."""

    reader: CenterReader | None = None
    #: `key_ref` → 키 값 (`StudioCredentials.service_key`). 없으면 키를 풀지 못한다.
    secrets: Callable[[str], str | None] | None = None
    #: 마지막으로 못 받은 사유들 (STU-09 「로그」가 그대로 찍는다).
    problems: list[str] = field(default_factory=list)

    def directory(self) -> AppDirectory:
        """Center가 아는 바깥 앱 한 벌.

        **한 가지를 못 받아도 나머지는 담는다** — 외부 정의를 못 읽었다고 주소까지 버리지
        않는다. 담지 못한 것은 `problems`에 남고, 그 앱을 부르는 순간 분명히 실패한다
        (조용히 지나가지 않는다).
        """
        self.problems = []
        if self.reader is None:
            self.problems.append("Center 주소·Studio 키가 설정되지 않았습니다 (STU-10)")
            return self._build({}, [], [])

        addresses: dict[str, str] = {}
        try:
            addresses = {one.app_id: one.base_url for one in self.reader.service_apps() if one.base_url}
        except CenterUnreachable as e:
            self.problems.append(f"서비스 앱 주소를 받지 못했습니다 — {e}")

        entries: list[dict[str, Any]] = []
        try:
            for one in self.reader.extensions():
                if one.tier != TIER_EXTERNAL:
                    continue  # 내장·사내는 정의가 설치 파일에 있다 (C13 E2)
                if one.definition is None or one.envelope is None:
                    self.problems.append(f"{one.id}: 정의·봉투가 함께 오지 않았습니다")
                    continue
                entries.append({"definition": one.definition, "envelope": one.envelope})
        except CenterUnreachable as e:
            self.problems.append(f"외부 확장 정의를 받지 못했습니다 — {e}")

        keys: list[AdminKey] = []
        if entries:
            try:
                keys = self.reader.admin_keys()
            except CenterUnreachable as e:
                # 공개키가 없으면 **어느 봉투도 검증되지 않는다** — 정의를 받아도 못 쓴다.
                self.problems.append(f"Admin 공개키를 받지 못했습니다 — {e}")

        return self._build(addresses, keys, entries)

    def _build(
        self, addresses: dict[str, str], keys: list[AdminKey], entries: list[dict[str, Any]]
    ) -> AppDirectory:
        made = build(to_json_dict(addresses=addresses, keys=keys, extensions=entries), secrets=self.secrets)
        # 봉투 검증에서 떨어진 것도 사람이 봐야 한다 (`AppDirectory.problems`).
        self.problems += [f"{app_id}: {why}" for app_id, why in sorted(made.problems.items())]
        return made


def reader_for(settings: Any, api_key: str | None) -> CenterReader | None:
    """설정과 키가 **둘 다** 있을 때만 읽는 쪽을 만든다. 없으면 `None`이다."""
    base = str(getattr(settings, "center_url", "") or "").strip()
    if not base or not api_key:
        return None
    return CenterReader(base_url=base, api_key=api_key)


def from_settings(settings: Any) -> Services:
    """STU-10 설정과 비밀 저장소에서 한 벌 (`main_window`가 실행마다 한 번 짓는다).

    키는 **환경변수가 먼저**다 (`CHK_STUDIO__CENTER_API_KEY`·`CHK_STUDIO__SVC__<참조>`) —
    개발·CI에서 덮어쓰기 쉬우라고 (`credentials.py`와 같은 규칙).
    """
    from chaeksas.studio.credentials import StudioCredentials  # noqa: PLC0415 — 순환 피함

    store = StudioCredentials()
    return Services(reader=reader_for(settings, store.center_api_key()), secrets=store.service_key)


__all__ = [
    "ADMIN_KEYS",
    "PACKAGES",
    "RESOURCES",
    "TIMEOUT_S",
    "CenterReader",
    "CenterUnreachable",
    "Services",
    "reader_for",
]
