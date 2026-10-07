"""Center에 등록·하트비트 (C4). **연결은 늘 Bot UI → Center다** (ADR-0007).

이 모듈이 Center와 말하는 유일한 곳이다. 화면은 여기를 직접 부르지 않는다 (`agent.py`가 부른다).

오류를 **갈라서** 올린다 — 트레이 상태 글이 다르기 때문이다 (BUI-01):

| 예외 | 트레이 |
| --- | --- |
| `Unreachable` | 「연결 끊김」 (실행은 계속한다) |
| `KeyRejected` | 「키 폐기됨」·「키 만료」·「등록 전」 |
| `MachineMismatch` | 「등록 전」 + 「다른 PC에 묶인 키」 안내 (BUI-03) |
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from chaeksas.contracts.approvals import ApprovalInfo
from chaeksas.contracts.bot_ui import (
    HeartbeatRequest,
    HeartbeatResponse,
    RegisterRequest,
    RegisterResponse,
)

log = logging.getLogger(__name__)

API = "/api/v1/bot-ui"
#: 결재는 Bot UI 경로가 아니라 C6 경로다 (올린 쪽 키로).
APPROVALS = "/api/v1/approvals"
#: 요청 크기 한도 (C4 — 256 KB). 넘으면 보내기 전에 막는다.
MAX_REQUEST_KB = 256
#: 한 번의 요청을 기다리는 시간. 하트비트 주기(30초)보다 넉넉히 짧게.
DEFAULT_TIMEOUT_S = 10.0

#: 키가 거부되는 코드 (C4·C5). 이 코드가 오면 **다시 시도해도 똑같다** — 사람이 고쳐야 한다.
KEY_REJECTED_CODES = frozenset({"key_invalid", "key_revoked", "key_expired", "wrong_key_type", "token_missing"})
#: 키 묶기가 어긋난 코드 (C4 409 — 키 → PC, PC → 키). 운영자가 콘솔에서 묶음을 풀어야 한다.
BINDING_CODES = frozenset({"machine_mismatch", "machine_already_registered"})


class CenterProblem(RuntimeError):
    """Center와 말하다 생긴 문제. 사람에게 보일 한 줄을 `str()`로 준다."""

    def __init__(self, message: str, *, code: str | None = None, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class Unreachable(CenterProblem):
    """닿지 못했다 (주소·네트워크·Center가 꺼짐). **실행은 계속한다** (ADR-0007)."""


class KeyRejected(CenterProblem):
    """키가 거부됐다 (없음·폐기·만료·종류 틀림). 사람이 고쳐야 한다."""


class MachineMismatch(CenterProblem):
    """키 묶기가 어긋났다 (C4 409 — 두 방향 모두). 콘솔에서 「PC 묶음 풀기」.

    `machine_mismatch`는 이 키가 다른 PC에 묶인 것이고, `machine_already_registered`는 이 PC가
    이미 다른 키로 등록된 것이다. **둘 다 다시 시도해도 같다** — 운영자가 고쳐야 한다.
    """


def _problem(response: httpx.Response) -> CenterProblem:
    """Center의 오류 본문(C5 `ErrorBody`)을 예외로 바꾼다."""
    code, message = None, None
    try:
        body = response.json()
        code = body.get("code")
        message = body.get("message")
    except ValueError:
        pass
    shown = message or f"Center가 {response.status_code}를 돌려줬습니다"
    if response.status_code == 409 and code in BINDING_CODES:
        return MachineMismatch(shown, code=code, status=response.status_code)
    if code in KEY_REJECTED_CODES:
        return KeyRejected(shown, code=code, status=response.status_code)
    return CenterProblem(shown, code=code, status=response.status_code)


@dataclass
class CenterClient:
    """Center API 하나. `client`를 넣으면 그것을 쓴다 (시험에서 ASGI로 바로 붙인다)."""

    base_url: str
    api_key: str
    timeout_s: float = DEFAULT_TIMEOUT_S
    client: httpx.Client | None = None

    def _send(
        self,
        path: str,
        payload: dict[str, Any] | None,
        *,
        method: str = "POST",
        api: str = API,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        body = httpx.Request("POST", "http://x", json=payload).content if payload is not None else b""
        if len(body) > MAX_REQUEST_KB * 1024:
            # 보내 봐야 413이다. 무엇이 큰지 말해 준다 (대개 대기열·준비 상태가 늘어난 경우).
            raise CenterProblem(
                f"보낼 내용이 {MAX_REQUEST_KB} KB를 넘습니다 ({len(body) // 1024} KB) — 대기열·준비 상태를 줄이세요"
            )

        own = self.client is None
        client = self.client or httpx.Client(timeout=self.timeout_s)
        try:
            response = client.request(
                method,
                f"{self.base_url.rstrip('/')}{api}{path}",
                params=params,
                content=body,
                headers={
                    # 토큰·키는 ASCII만 (CLAUDE.md §5 — 헤더에 한글을 넣지 않는다).
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        except httpx.HTTPError as e:
            raise Unreachable(f"Center에 닿지 못했습니다 ({self.base_url}) — {type(e).__name__}") from e
        finally:
            if own:
                client.close()

        if response.status_code >= 400:
            raise _problem(response)
        try:
            return dict(response.json())
        except ValueError as e:
            raise CenterProblem("Center 응답이 JSON이 아닙니다") from e

    def register(self, request: RegisterRequest) -> RegisterResponse:
        """처음 한 번, 그리고 이름·버전이 바뀔 때. **멱등** — 같은 키·PC면 같은 `bot_ui_id`."""
        return RegisterResponse.model_validate(self._send("/register", request.to_json_dict()))

    def heartbeat(self, request: HeartbeatRequest) -> HeartbeatResponse:
        """30초마다. 응답의 `next_heartbeat_s`를 따른다."""
        return HeartbeatResponse.model_validate(self._send("/heartbeat", request.to_json_dict()))

    def create_approval(self, body: dict[str, Any]) -> ApprovalInfo:
        """결재를 Center 결재함에 올린다 (C6 `POST /approvals`). **본문은 실행기가 쓴 그대로**다.

        멱등 — 같은 `request_id`·같은 본문이면 기존 결재를 돌려준다 (200).
        """
        return ApprovalInfo.model_validate(self._send("", body, api=APPROVALS))

    def withdraw_approval(self, request_id: str, *, reason: str) -> ApprovalInfo:
        """올린 결재를 거둔다 (C6 `DELETE /approvals/{id}?reason=`) — 현장에서 먼저 답했을 때."""
        return ApprovalInfo.model_validate(
            self._send(f"/{request_id}", None, method="DELETE", api=APPROVALS, params={"reason": reason})
        )

    def download_package(self, package_id: str, version: str) -> bytes:
        """패키지 zip (C5 `GET /packages/{id}/{v}`). 승인된 것이면 `SIGNATURE`가 들어 있다.

        **Bot UI 경로가 아니라 C5 경로**다 — 자기 배포분만 받을 수 있다 (C5 권한표).
        """
        import httpx  # noqa: PLC0415 — 부를 때만 든다

        own = self.client is None
        client = self.client or httpx.Client(timeout=self.timeout_s)
        try:
            response = client.get(
                f"{self.base_url.rstrip('/')}/api/v1/packages/{package_id}/{version}",
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
        except httpx.HTTPError as e:
            raise Unreachable(f"패키지를 받지 못했습니다 ({type(e).__name__})") from e
        finally:
            if own:
                client.close()
        if response.status_code >= 400:
            raise _problem(response)
        return bytes(response.content)


__all__ = [
    "API",
    "DEFAULT_TIMEOUT_S",
    "KEY_REJECTED_CODES",
    "MAX_REQUEST_KB",
    "CenterClient",
    "CenterProblem",
    "KeyRejected",
    "MachineMismatch",
    "Unreachable",
]
