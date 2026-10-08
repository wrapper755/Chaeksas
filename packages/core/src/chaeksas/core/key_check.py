"""서비스 앱 키 하나의 상태를 앱에 물어본다 — C11 `GET /v1/keys/self`.

**설정 화면이 쓰는 길이다** (BUI-10 「확인」·STU-10 「연결 테스트」). 사전 점검은 이것을 부르지
않는다 — 점검은 서버를 부르지 않기로 했다 (`core.preflight`). 그래서 점검은 「값이 있나」까지만
보고, 「맞는 키인가」는 사람이 이 단추를 누를 때 본다.

- **결과는 사람이 읽는 한 줄**이다. 화면이 글을 다시 짓지 않는다 (Bot UI와 Studio가 같은 말을 쓴다).
- **키 값은 결과 글에 들어가지 않는다.**
- `client`는 시험이 끼운다 (httpx와 같은 모양).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

TIMEOUT_S = 5.0

#: 수행 모드를 사람 말로 (C11 `allowed_modes`).
MODE_WORDS = {"autonomous": "자율", "deterministic": "결정"}

#: 「상태」 열의 값들. 화면이 글자를 직접 쓰지 않게 이름을 둔다.
NO_VALUE = "없음"
NO_ADDRESS = "주소를 모름"
UNREACHABLE = "앱에 닿지 못함"


def _get(url: str, *, headers: Mapping[str, str] | None = None, client: Any = None) -> Any:
    import httpx  # noqa: PLC0415 — 누를 때만 든다

    if client is not None:
        return client.get(url, headers=dict(headers or {}))
    with httpx.Client(timeout=TIMEOUT_S) as made:
        return made.get(url, headers=dict(headers or {}))


def _reachable(error: Exception) -> bool:
    """닿기는 했는데 다른 이유로 터진 것인가 — 그런 것은 숨기지 않고 올린다."""
    import httpx  # noqa: PLC0415

    return not isinstance(error, httpx.HTTPError)


def key_status(base_url: str | None, key: str | None, *, client: Any = None) -> str:
    """키가 살아 있고 무엇을 허용하는지 (C11 §키 확인)."""
    if not key:
        return NO_VALUE
    if not base_url:
        return NO_ADDRESS
    try:
        answer = _get(
            f"{base_url.rstrip('/')}/v1/keys/self", headers={"Authorization": f"Bearer {key}"}, client=client
        )
    except Exception as e:  # noqa: BLE001 — 닿지 못한 모든 경우
        if _reachable(e):
            raise
        return UNREACHABLE
    if answer.status_code == 401:
        return "키가 틀림"
    if answer.status_code == 403:
        try:
            code = str(answer.json().get("code") or "")
        except ValueError:
            code = ""
        return "만료됨" if code == "key_expired" else "폐기됨"
    if answer.status_code >= 400:
        return f"앱이 {answer.status_code}로 답했습니다"
    body = answer.json()
    modes = "·".join(MODE_WORDS.get(str(m), str(m)) for m in body.get("allowed_modes") or []) or "없음"
    expires = body.get("expires_at")
    return f"정상 — 허용: {modes}" + (f", 만료 {str(expires)[:10]}" if expires else "")


__all__ = ["MODE_WORDS", "NO_ADDRESS", "NO_VALUE", "UNREACHABLE", "key_status"]
