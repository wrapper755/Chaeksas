"""서비스 앱 키 하나의 상태를 앱에 물어본다 — C11 `GET /v1/keys/self`.

**설정 화면이 쓰는 길이다** (BUI-10 「확인」·STU-10 「연결 테스트」). 사전 점검은 이것을 부르지
않는다 — 점검은 서버를 부르지 않기로 했다 (`core.preflight`). 그래서 점검은 「값이 있나」까지만
보고, 「맞는 키인가」는 사람이 이 단추를 누를 때 본다.

- **결과는 사람이 읽는 한 줄**이다. 화면이 글을 다시 짓지 않는다 (Bot UI와 Studio가 같은 말을 쓴다).
- **키 값은 결과 글에 들어가지 않는다.**
- `client`는 시험이 끼운다 (httpx와 같은 모양).

**판단할 거리가 필요한 쪽은 `key_facts()`로 값을 받는다** (ADR-0052) — BUI-05의 「만료 임박」
알림은 한 줄짜리 글로는 재지 못한다 (만료일이 글 안에 있다). `key_status()`는 그 위에서 글을
만드는 얇은 겹이라 **말은 여전히 한 곳**에 있다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

TIMEOUT_S = 5.0

#: 수행 모드를 사람 말로 (C11 `allowed_modes`).
MODE_WORDS = {"autonomous": "자율", "deterministic": "결정"}

#: 「상태」 열의 값들. 화면이 글자를 직접 쓰지 않게 이름을 둔다.
NO_VALUE = "없음"
NO_ADDRESS = "주소를 모름"
UNREACHABLE = "앱에 닿지 못함"


def _get(
    url: str, *, headers: Mapping[str, str] | None = None, client: Any = None, timeout_s: float = TIMEOUT_S
) -> Any:
    import httpx  # noqa: PLC0415 — 누를 때만 든다

    if client is not None:
        return client.get(url, headers=dict(headers or {}))
    with httpx.Client(timeout=timeout_s) as made:
        return made.get(url, headers=dict(headers or {}))


def _reachable(error: Exception) -> bool:
    """닿기는 했는데 다른 이유로 터진 것인가 — 그런 것은 숨기지 않고 올린다."""
    import httpx  # noqa: PLC0415

    return not isinstance(error, httpx.HTTPError)


@dataclass(frozen=True)
class KeyFacts:
    """앱이 말해 준 것 — **글이 아니라 값**이다 (ADR-0052).

    `line`은 사람이 읽는 한 줄이고(화면이 쓰는 것), 나머지는 알림이 판단에 쓰는 값이다.
    **키 값은 어디에도 들어가지 않는다.**
    """

    #: 사람이 읽는 한 줄 (BUI-10 「상태」 열·STU-10 「연결 테스트」).
    line: str
    #: 앱과 말이 통했나 — **닿지 못한 것·물을 거리가 없는 것은 `False`**다.
    answered: bool = False
    #: 앱이 **분명히 거부했나** (401·403). 값이 없는 것은 거부가 아니다.
    refused: bool = False
    #: C11 `expires_at` — 없으면 **만료 없는 키**다 (「모른다」가 아니다).
    expires_at: str | None = None


def key_facts(
    base_url: str | None, key: str | None, *, client: Any = None, timeout_s: float = TIMEOUT_S
) -> KeyFacts:
    """키가 살아 있고 무엇을 허용하는지 (C11 §키 확인). **값으로** 돌려준다.

    `timeout_s`는 **사람이 기다리지 않는 쪽이 줄인다** — 주기에서 부르면 그만큼 창이 멈춘다
    (ADR-0052).
    """
    if not key:
        return KeyFacts(line=NO_VALUE)
    if not base_url:
        return KeyFacts(line=NO_ADDRESS)
    try:
        answer = _get(
            f"{base_url.rstrip('/')}/v1/keys/self",
            headers={"Authorization": f"Bearer {key}"},
            client=client,
            timeout_s=timeout_s,
        )
    except Exception as e:  # noqa: BLE001 — 닿지 못한 모든 경우
        if _reachable(e):
            raise
        return KeyFacts(line=UNREACHABLE)
    if answer.status_code == 401:
        return KeyFacts(line="키가 틀림", answered=True, refused=True)
    if answer.status_code == 403:
        try:
            code = str(answer.json().get("code") or "")
        except ValueError:
            code = ""
        expired = code == "key_expired"
        return KeyFacts(line="만료됨" if expired else "폐기됨", answered=True, refused=True)
    if answer.status_code >= 400:
        # 앱이 답은 했지만 키에 대한 답이 아니다 (5xx·429…) — 거부로 읽지 않는다.
        return KeyFacts(line=f"앱이 {answer.status_code}로 답했습니다", answered=True)
    body = answer.json()
    modes = "·".join(MODE_WORDS.get(str(m), str(m)) for m in body.get("allowed_modes") or []) or "없음"
    expires = body.get("expires_at")
    return KeyFacts(
        line=f"정상 — 허용: {modes}" + (f", 만료 {str(expires)[:10]}" if expires else ""),
        answered=True,
        expires_at=str(expires) if expires else None,
    )


def key_status(base_url: str | None, key: str | None, *, client: Any = None) -> str:
    """같은 것을 **한 줄로** (화면이 글을 다시 짓지 않는다)."""
    return key_facts(base_url, key, client=client).line


__all__ = [
    "MODE_WORDS",
    "NO_ADDRESS",
    "NO_VALUE",
    "UNREACHABLE",
    "KeyFacts",
    "key_facts",
    "key_status",
]
