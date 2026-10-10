"""내려받기 관문 — 누가 어느 패키지 **파일**을 받을 수 있나 (C5 권한표).

| 부르는 쪽 | 내려받을 수 있는 것 |
| --- | --- |
| 관리자 토큰 | 전부 |
| 읽기 토큰 | **없다** — 콘솔 「보기 전용」은 목록·정보까지다 (파일은 받지 않는다) |
| Studio 키 | 전부 — 올린 쪽이고, 공유 BPM 프로세스·툴팩을 가져다 쓴다 |
| Bot UI·서버 실행기 키 | **자기에게 배포된 것과 그 패키지가 요구하는 툴팩만** |
| 연동용 키 | 없다 — 작업만 만든다 |

세 모듈 위에 앉으므로 **따로 둔다**. `api.packages`는 `api.deployments`가 이미 import하고
있어(상태 상수) 거기에 배포 조회를 넣으면 순환 import다. 여기는 아무도 import하지 않는
끝자리라 `auth`·`bot_ui`·`deployments`를 한자리에서 볼 수 있다.

**「없다」와 「자기 것이 아니다」를 같은 코드로 답한다** (403 `forbidden`, C5 오류표). 어느
패키지가 Center에 있는지를 권한 없는 키에게 알려 주지 않는다 — 404로 가르면 그것이 곧
목록이 된다.
"""

from __future__ import annotations

from typing import Any

from chaeksas.center.api import bot_ui, deployments
from chaeksas.center.auth import PACKAGE_KEY_TYPE, Caller
from chaeksas.center.errors import ApiError
from chaeksas.center.storage import Store

#: 자기에게 배포된 것만 받는 키 종류 → 배포 대상 종류 (C2 §배포 대상 규칙).
TARGET_OF = {"bot_ui": "bot_ui", "server_runner": "server_runner"}


def _target(store: Store, key: Any) -> tuple[str | None, str]:
    """그 키가 **어느 대상인가** (C4 — 키가 신원이다). `(대상 id, 없는 까닭)`.

    서버 실행기는 등록받는 자리가 **아직 없다** (C12·M7) — 그래서 배포를 가질 수 없고, 키
    이름을 대상 id로 흉내 내지 않는다. 그 자리가 생기면 여기 한 줄이 늘어난다.
    """
    if key.type == "bot_ui":
        found = bot_ui.id_for_key(store, key)
        return found, "이 키로 등록된 Bot UI가 없다 — 먼저 register를 부르세요"
    return None, "서버 실행기 등록은 M7부터다 (C12) — 배포될 수 있는 대상이 아직 없다"


def guard_download(store: Store, found: Caller, *, package_id: str, version: str) -> None:
    """`GET /packages/{id}/{version}`의 관문. 받을 수 없으면 403 `forbidden`이다."""
    if found.is_admin:
        return

    key = found.key
    if key is None:
        # 읽기 토큰 — 콘솔은 패키지 **파일**을 받지 않는다 (C5 권한표의 「—」).
        raise ApiError(403, "forbidden", "읽기 토큰으로는 패키지 파일을 내려받을 수 없다")
    if key.type == PACKAGE_KEY_TYPE:
        return
    if key.type not in TARGET_OF:
        raise ApiError(
            403, "forbidden", f"{key.type} 종류의 키로는 패키지를 내려받을 수 없다"
        )

    target_id, why = _target(store, key)
    if target_id is None:
        raise ApiError(403, "forbidden", why)
    allowed = deployments.downloadable_by(
        store, target_type=TARGET_OF[key.type], target_id=target_id
    )
    if (package_id, version) not in allowed:
        raise ApiError(
            403,
            "forbidden",
            f"{package_id}@{version}은 이 {TARGET_OF[key.type]}에 배포되지 않았다",
        )


__all__ = ["TARGET_OF", "guard_download"]
