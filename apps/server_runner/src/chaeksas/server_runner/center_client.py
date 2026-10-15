"""Center에 등록·하트비트 (C12). **연결은 늘 실행기 → Center다** (ADR-0007).

이 모듈이 Center와 말하는 유일한 곳이다. 오류를 **갈라서** 올리는 것도 C4(Bot UI)와 같다 —
로그 한 줄이 달라야 운영자가 무엇을 고칠지 안다.

| 예외 | 뜻 | 어떻게 |
| --- | --- | --- |
| `Unreachable` | 주소·네트워크·Center가 꺼짐 | **기다렸다 다시 건다** (ADR-0007) |
| `KeyRejected` | 키가 없음·폐기·만료·종류 틀림 | 사람이 고쳐야 한다 — 다시 걸어도 같다 |
| `MachineMismatch` | 키 묶기가 어긋남 (C12 409) | 운영자가 콘솔에서 묶음을 풀어야 한다 |
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from chaeksas.contracts.resources import ExtensionResource, ServiceAppResource
from chaeksas.contracts.server_runner import (
    DelegationRequest,
    DelegationResponse,
    ServerRunnerHeartbeatRequest,
    ServerRunnerHeartbeatResponse,
    ServerRunnerRegisterRequest,
    ServerRunnerRegisterResponse,
)

log = logging.getLogger(__name__)

API = "/api/v1/server-runner"
#: 결재는 실행기 경로가 아니라 **C6 경로**다 (올린 쪽 키로 — 답은 올린 키에게만 내려간다).
APPROVALS = "/api/v1/approvals"
#: 리소스 목록도 **C7 경로**다 — 주소와 외부 확장 정의를 읽는다 (실행기 키로, C5 권한표).
RESOURCES = "/api/v1/resources"
#: 요청 크기 한도 (C4와 같다 — 256 KB). 넘으면 보내기 전에 막는다.
MAX_REQUEST_KB = 256
#: 한 번의 요청을 기다리는 시간. 주기(10초)보다 넉넉히 짧게.
DEFAULT_TIMEOUT_S = 5.0

#: 키가 거부되는 코드 (C12·C5). 이 코드가 오면 **다시 시도해도 똑같다**.
KEY_REJECTED_CODES = frozenset(
    {"key_invalid", "key_revoked", "key_expired", "wrong_key_type", "token_missing"}
)
#: 키 묶기가 어긋난 코드 (C12 409 — 양방향). 운영자가 콘솔에서 풀어야 한다.
BINDING_CODES = frozenset({"machine_mismatch", "machine_already_registered"})


class CenterProblem(RuntimeError):
    """Center와 말하다 생긴 문제. 사람에게 보일 한 줄을 `str()`로 준다."""

    def __init__(self, message: str, *, code: str | None = None, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class Unreachable(CenterProblem):
    """닿지 못했다. **기다리는 실행은 그대로 둔다** (ADR-0007)."""


class KeyRejected(CenterProblem):
    """키가 거부됐다. 사람이 고쳐야 한다."""


class MachineMismatch(CenterProblem):
    """키 묶기가 어긋났다 (C12 409). 콘솔에서 묶음 풀기.

    `machine_mismatch`는 이 키가 다른 서버에 묶인 것이고, `machine_already_registered`는 이
    서버가 이미 다른 키로 등록된 것이다. **둘 다 다시 걸어도 같다.**
    """


class NotRegistered(CenterProblem):
    """아직 등록되지 않았다 (409 `not_registered`) — `register`를 먼저 부른다.

    Center의 DB가 새로 선 경우에도 이것이 온다. 그래서 **다시 등록하면 이어진다** (멱등).
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
    if response.status_code == 409 and code == "not_registered":
        return NotRegistered(shown, code=code, status=response.status_code)
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
        api: str | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        body = httpx.Request("POST", "http://x", json=payload).content if payload is not None else b""
        if len(body) > MAX_REQUEST_KB * 1024:
            # 보내 봐야 413이다. 무엇이 큰지 말해 준다 (대개 `waiting[]`이 늘어난 경우).
            raise CenterProblem(
                f"보낼 내용이 {MAX_REQUEST_KB} KB를 넘습니다 ({len(body) // 1024} KB) — "
                "기다리는 실행이 너무 많습니다"
            )

        own = self.client is None
        client = self.client or httpx.Client(timeout=self.timeout_s)
        try:
            response = client.request(
                method,
                f"{self.base_url.rstrip('/')}{api or API}{path}",
                params=params,
                content=body,
                headers={
                    # 토큰·키는 ASCII만 (CLAUDE.md §5 — 헤더에 한글을 넣지 않는다).
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        except httpx.HTTPError as e:
            raise Unreachable(
                f"Center에 닿지 못했습니다 ({self.base_url}) — {type(e).__name__}"
            ) from e
        finally:
            if own:
                client.close()

        if response.status_code >= 400:
            raise _problem(response)
        try:
            return dict(response.json())
        except ValueError as e:
            raise CenterProblem("Center 응답이 JSON이 아닙니다") from e

    def register(self, request: ServerRunnerRegisterRequest) -> ServerRunnerRegisterResponse:
        """처음 한 번, 그리고 이름·버전·상한이 바뀔 때. **멱등** — 같은 키·서버면 같은 id."""
        return ServerRunnerRegisterResponse.model_validate(
            self._send("/register", request.to_json_dict())
        )

    def heartbeat(self, request: ServerRunnerHeartbeatRequest) -> ServerRunnerHeartbeatResponse:
        """기본 10초마다. 응답의 `next_heartbeat_s`를 따른다 (C12)."""
        return ServerRunnerHeartbeatResponse.model_validate(
            self._send("/heartbeat", request.to_json_dict())
        )

    def create_approval(self, body: dict[str, Any]) -> dict[str, Any]:
        """결재를 Center 결재함에 올린다 (C6 `POST /approvals`). **서버의 창구는 Center만**이다.

        멱등 — 같은 `request_id`·같은 본문이면 기존 결재를 돌려준다 (200). **4xx는 다시 보내지
        않는다** (부르는 쪽이 그렇게 다룬다 — 한 번 거부된 것이 큐를 영원히 막는다).
        """
        return self._send("", body, api=APPROVALS)

    def create_delegation(self, request: DelegationRequest) -> DelegationResponse:
        """PC 위임을 맡긴다 (C12 §PC 위임, ADR-0062). 돌려주는 것은 **그 작업**이다.

        **멱등 키와 `requested_by`는 본문에 없다** — Center가 `run_id`·`node_id`·
        `node_instance`로 짓는다. 그래서 되살린 실행이 같은 자리에서 다시 맡겨도 **같은
        작업이 돌아온다**(200). 이쪽은 201·200을 가리지 않는다 — 어느 쪽이든 그 작업을
        기다리면 된다.
        """
        return DelegationResponse.model_validate(
            self._send("/delegations", request.to_json_dict())
        )

    def cancel_delegation(self, job_id: str) -> dict[str, Any]:
        """맡긴 위임을 거둔다 (`POST …/delegations/{job_id}/cancel`, ADR-0062 §5).

        **이미 시작된 PC 실행은 거절된다** (C5 — 작업은 `accepted`로 남는다). 그것도 답이므로
        부르는 쪽은 다시 걸지 않는다.
        """
        return self._send(f"/delegations/{job_id}/cancel", {})

    def service_apps(self) -> list[ServiceAppResource]:
        """서비스 앱 리소스 목록 (C7 `GET /resources?type=service_app`) — **주소의 유일한 출처**다.

        **실행기가 제 손으로 읽는다** — Bot UI는 자식 프로세스에 파일로 건네지만(ADR-0031의
        「실행기는 Center를 부르지 않는다」는 그 자식 이야기다) 여기서는 이 프로세스가 엔진을
        돌린다. **앱을 깨우지 않는다** — Center가 들고 있는 것을 준다.
        """
        found = self._send("", None, method="GET", api=RESOURCES, params={"type": "service_app"})
        return [ServiceAppResource.model_validate(one) for one in found.get("items") or []]

    def extension(self, extension_id: str) -> ExtensionResource:
        """확장 하나 (C7 `GET /resources/extensions/{id}`). 외부면 **정의와 봉투**가 함께 온다.

        철회된 확장은 404다 — 받지 못한 것은 쓰지 않는다 (C13).
        """
        return ExtensionResource.model_validate(
            self._send(f"/extensions/{extension_id}", None, method="GET", api=RESOURCES)
        )

    def download_package(self, package_id: str, version: str) -> bytes:
        """패키지 zip (C5 `GET /packages/{id}/{v}`). 승인된 것이면 `SIGNATURE`가 들어 있다.

        **실행기 경로가 아니라 C5 경로**다 — 자기에게 배포된 것만 받을 수 있다 (C5 권한표의
        `guard_download`가 배포 표까지 대조한다).
        """
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
    "APPROVALS",
    "DEFAULT_TIMEOUT_S",
    "KEY_REJECTED_CODES",
    "MAX_REQUEST_KB",
    "RESOURCES",
    "CenterClient",
    "CenterProblem",
    "KeyRejected",
    "MachineMismatch",
    "NotRegistered",
    "Unreachable",
]
