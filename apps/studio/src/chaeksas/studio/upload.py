"""Studio가 Center에 패키지를 올리는 길 (C5 `POST /packages`, STU-01·STU-12 「올리기」).

지키는 것 넷.

- **올리는 것은 만들어 둔 zip이다.** `packaging.export`·`export_lib`이 만든 파일을 그대로
  보낸다 — 여기서 새로 짓지 않으므로 「내보내기」와 「올리기」가 서로 다른 것을 낼 일이 없다.
- **올린 것은 후보다.** 승인·배포는 **서명이 유일한 관문**이고(C2) Admin의 일이다. Studio
  키로는 승인할 수 없으니 결과 한 줄이 **그렇게 말한다** — 「올렸는데 왜 안 도나」를 남기지
  않는다.
- **「이미 있다」와 「다른 내용으로 있다」를 가른다.** 같은 id·버전·해시면 Center가 200으로
  받고(재시도), 내용이 다르면 409 `version_conflict`다. 둘을 뭉개면 사람이 버전을 올려야
  할 때를 모른다.
- **키 값은 결과 글에 들어가지 않는다** (`checks.py`·STU-10과 같은 규칙).

읽기는 `services.CenterReader`가 한다 — 그쪽은 **읽기만** 하고 이쪽만 쓴다. 주소·키가 오는
곳은 같다 (`Settings.center_url`, `StudioCredentials.center_api_key()`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: Center API 경로 (C5).
PACKAGES = "/api/v1/packages"

#: 올리기 제한 시간 (초). 패키지는 최대 50 MB라 읽기(10초)보다 넉넉히 둔다.
TIMEOUT_S = 60

#: 승인 뒤에야 배포된다는 말 — 창과 로그가 **같은 글**을 쓴다.
CANDIDATE_NOTE = "후보로 올렸습니다. 관리자 승인 뒤에 배포됩니다."


class UploadFailed(RuntimeError):
    """올리지 못했다 — 화면이 그대로 보여 줄 한 줄."""


@dataclass(frozen=True)
class Uploaded:
    """올린 결과."""

    package_id: str
    version: str
    status: str
    #: 새로 올라갔나 (201). 같은 내용을 다시 올리면 `False`다 (200 — C5 재시도).
    created: bool

    @property
    def message(self) -> str:
        """사람에게 할 말 한 줄. **무엇이 다음인지**까지 말한다."""
        what = f"{self.package_id} {self.version}"
        if not self.created:
            return f"{what}: 이미 올라가 있습니다 (같은 내용). 상태는 「{self.status}」입니다."
        return f"{what}: {CANDIDATE_NOTE}"


#: Center가 돌려주는 `code` → 사람이 읽을 한 줄 (C5 오류표). 없는 코드는 그대로 보인다.
WHY = {
    "version_conflict": (
        "같은 버전이 다른 내용으로 Center에 있습니다 — 버전을 올려서 다시 올리세요."
    ),
    "forbidden": "Center가 거부했습니다 — Studio용 Center API 키인지 확인하세요 (설정 → Center).",
    "key_invalid": "Center API 키가 거부되었습니다 (설정 → Center).",
    "too_large": "패키지가 너무 큽니다 (Center 제한 50 MB).",
}


@dataclass
class CenterUploader:
    """Center에 **쓰는** 작은 클라이언트. 하는 일은 하나다."""

    base_url: str
    api_key: str
    #: `httpx.Client` 또는 `TestClient` (시험이 끼운다).
    client: Any = None

    def upload(self, path: Path) -> Uploaded:
        """패키지 zip 하나를 올린다 (multipart 칸 이름은 `file`이다 — C5).

        닿지 못하거나 거부되면 `UploadFailed`다. **무엇을 올렸는지는 돌아온 본문에서** 읽는다
        (파일 이름으로 어림하지 않는다 — Center가 매니페스트를 보고 답한다).
        """
        import httpx  # noqa: PLC0415 — 부를 때만 든다

        url = self.base_url.rstrip("/") + PACKAGES
        own = self.client is None
        client = self.client or httpx.Client(timeout=TIMEOUT_S)
        try:
            response = client.post(
                url,
                files={"file": (path.name, path.read_bytes(), "application/zip")},
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
        except httpx.HTTPError as e:
            raise UploadFailed(f"Center에 닿지 못했습니다 ({type(e).__name__})") from e
        finally:
            if own:
                client.close()

        if response.status_code >= 400:
            raise UploadFailed(_refused(response))
        body = response.json() or {}
        return Uploaded(
            package_id=str(body.get("id") or path.stem),
            version=str(body.get("version") or ""),
            status=str(body.get("status") or ""),
            created=response.status_code == 201,
        )


def _refused(response: Any) -> str:
    """거부된 까닭 한 줄 — Center의 `code`·`message`를 **그대로 싣는다** (C5 오류 본문).

    모르는 코드를 「알 수 없는 오류」로 덮지 않는다. 운영자가 Center 로그에서 찾을 글이다.
    """
    code, message = "", ""
    try:
        body = response.json() or {}
        code, message = str(body.get("code") or ""), str(body.get("message") or "")
    except ValueError:
        pass
    if not code:
        return f"Center가 {response.status_code}로 답했습니다."
    known = WHY.get(code)
    if known:
        return known if not message else f"{known} (Center: {code} — {message})"
    return f"Center가 거부했습니다: {code} — {message or response.status_code}"


def uploader_for(settings: Any, api_key: str | None) -> CenterUploader | None:
    """설정과 키가 **둘 다** 있을 때만 만든다 (`services.reader_for`와 같은 규칙)."""
    base = str(getattr(settings, "center_url", "") or "").strip()
    if not base or not api_key:
        return None
    return CenterUploader(base_url=base, api_key=api_key)


def from_settings(settings: Any) -> CenterUploader | None:
    """STU-10 설정과 비밀 저장소에서. 키는 **환경변수가 먼저**다."""
    from chaeksas.studio.credentials import StudioCredentials  # noqa: PLC0415 — 순환 피함

    return uploader_for(settings, StudioCredentials().center_api_key())


__all__ = [
    "CANDIDATE_NOTE",
    "PACKAGES",
    "TIMEOUT_S",
    "WHY",
    "CenterUploader",
    "UploadFailed",
    "Uploaded",
    "from_settings",
    "uploader_for",
]
