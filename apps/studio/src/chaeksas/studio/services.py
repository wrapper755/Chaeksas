"""Studio가 Center를 **읽는** 길과, 시험 실행이 서비스 태스크를 올리는 길 (C7·C15).

- **서비스 태스크는 Center에 외부 작업으로 올린다** (`CenterServiceCaller`, ADR-0102) — Studio의
  Center API 키로, `run_id`가 `test_…`이고 일감은 `origin: test`다. 바깥 앱의 주소도 키도 모른다
  (시험용 키라는 것이 없다 — 시험 쪽으로 보낼지는 일꾼이 정한다).
- 외부 확장은 **정의만** 받아 검증한다 (`core.app_directory` — PC 실행기와 같은 코드). 들고 있지 않는다
  — 닿지 못하면 **그 자리에서 말한다** (Studio는 현장이 아니라 개발 도구다).

이 모듈이 Center를 부르는 것은 **읽기만**이다 (올리기는 C15 호출기, 패키지 올리기는 `upload.py`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from chaeksas.contracts.center_api import PackageInfo
from chaeksas.contracts.extension import TIER_EXTERNAL
from chaeksas.contracts.resources import (
    ContributedResource,
    ExtensionResource,
    ServiceAppResource,
)
from chaeksas.contracts.signing import AdminKey
from chaeksas.core.app_directory import AppDirectory, build, to_json_dict
from chaeksas.core.services import CenterServiceCaller

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

    PC 실행기의 `CenterClient`를 쓰지 않는다 — 앱끼리 import하지 않는다 (01-architecture §5).
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
        같은 것을 읽는다).
        """
        found = self._get(f"{PACKAGES}?kind={quote(kind)}") or []
        return [PackageInfo.model_validate(one) for one in found]

    def package_zip(self, package_id: str, version: str) -> bytes:
        """패키지 파일 하나 (C5 `GET /packages/{id}/{version}`) — STU-11 「설치」가 받는 것.

        **읽기다** — 내려받기는 C5 권한표에서 Studio 키에 열려 있다(쓰는 길은 `upload.py`
        하나다). 철회된 패키지는 Center가 410으로 막는다.
        """
        import httpx  # noqa: PLC0415 — 부를 때만 든다

        url = f"{self.base_url.rstrip('/')}{PACKAGES}/{quote(package_id)}/{quote(version)}"
        own = self.client is None
        # 패키지는 최대 50 MB라 목록 읽기(10초)보다 넉넉히 둔다 (`upload.py`와 같은 결).
        client = self.client or httpx.Client(timeout=60)
        try:
            response = client.get(url, headers={"Authorization": f"Bearer {self.api_key}"})
        except httpx.HTTPError as e:
            raise CenterUnreachable(f"Center에 닿지 못했습니다 ({type(e).__name__})") from e
        finally:
            if own:
                client.close()
        if response.status_code >= 400:
            raise CenterUnreachable(
                f"Center가 {response.status_code}로 답했습니다 ({package_id} {version})"
            )
        return bytes(response.content)

    def admin_keys(self) -> list[AdminKey]:
        """봉투를 검증할 Admin **공개**키 (C2). 비밀이 아니라 읽기 토큰으로 읽는다."""
        return [AdminKey.model_validate(one) for one in self._get(ADMIN_KEYS) or []]


@dataclass
class Services:
    """시험 실행에 줄 것 — 서비스 태스크를 올리는 호출기와 검증된 외부 확장 정의."""

    reader: CenterReader | None = None
    #: 마지막으로 못 받은 사유들 (STU-09 「로그」가 그대로 찍는다).
    problems: list[str] = field(default_factory=list)

    def caller(self) -> CenterServiceCaller | None:
        """서비스 태스크가 부르는 자리 — Studio의 Center API 키로 Center에 올린다 (C15)."""
        if self.reader is None:
            return None
        return CenterServiceCaller(
            base_url=self.reader.base_url, token=self.reader.api_key, caller_type="studio", client=self.reader.client
        )

    def directory(self) -> AppDirectory:
        """검증된 외부 확장 정의 (고정한 해시와 대조할 때 쓴다). 못 받은 것은 `problems`에 남는다."""
        self.problems = []
        if self.reader is None:
            self.problems.append("Center 주소·Studio 키가 설정되지 않았습니다 (STU-10)")
            return AppDirectory()

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

        made = build(to_json_dict(keys=keys, extensions=entries))
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

    키는 **환경변수가 먼저**다 (`BPM_STUDIO__CENTER_API_KEY`) — `credentials.py`와 같은 규칙.
    """
    from chaeksas.studio.credentials import StudioCredentials  # noqa: PLC0415 — 순환 피함

    return Services(reader=reader_for(settings, StudioCredentials().center_api_key()))


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
