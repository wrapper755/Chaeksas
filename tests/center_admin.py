"""시험이 Center에 **관리자로** 승인·배포·외부 확장 등록을 시키는 길 — 자리가 하나다 (ADR-0090).

**이것은 제품 코드가 아니다.** 사람은 Center 콘솔에서 누르고, 시험은 관리자 토큰으로 같은
API를 부른다(외부 확장은 일꾼이 올린다 — ADR-0121). 봉투는 **Center가 짓고 서명한다** — 시험이 Admin
키를 만들거나 봉투에 서명하지 않는다. 현장(PC 실행기·서버 실행기)은 하트비트의 `admin_keys`에 든
Center 공개키로 다시 검증한다.

`client`는 `TestClient`(in-process)든 진짜 소켓의 `httpx.Client`든 된다 — 둘 다 같은 메서드를 쓴다.
`expect`는 바라는 상태 코드이고 다르면 본문을 붙여 그 자리에서 멈춘다(거부를 보려는 시험은 그
코드를 적는다). `None`이면 보지 않고 응답을 그대로 돌려준다.

거부 사유를 `pytest.raises`로 받아 보는 시험은 `AdminCenter`를 쓴다 — 거절이면 `CenterProblem`
(`status`·`code`)을 던지고, 받아들이면 본문을 돌려준다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from chaeksas.contracts.resources import ExtensionResource
from chaeksas.contracts.signing import AdminKey

API = "/api/v1"
#: 시험의 Center가 받는 관리자 토큰 (`CenterSettings(admin_token="t-admin")`).
ADMIN = {"Authorization": "Bearer t-admin"}


def _check(answer: httpx.Response, expect: int | tuple[int, ...] | None) -> httpx.Response:
    if expect is None:
        return answer
    wanted = (expect,) if isinstance(expect, int) else expect
    assert answer.status_code in wanted, f"{answer.status_code} {answer.text}"
    return answer


def approve(
    client: Any,
    package_id: str,
    version: str,
    *,
    headers: dict[str, str] = ADMIN,
    expect: int | tuple[int, ...] | None = 200,
) -> httpx.Response:
    """패키지 승인 (C5 `PUT …/signature`) — 본문이 없다."""
    return _check(client.put(f"{API}/packages/{package_id}/{version}/signature", headers=headers), expect)


def revoke_approval(
    client: Any,
    package_id: str,
    version: str,
    *,
    reason: str = "시험 철회",
    headers: dict[str, str] = ADMIN,
    expect: int | tuple[int, ...] | None = 200,
) -> httpx.Response:
    """패키지 승인 철회 (C5 `POST …/revoke`) — 그 패키지의 배포가 모두 무효가 된다."""
    return _check(
        client.post(f"{API}/packages/{package_id}/{version}/revoke", json={"reason": reason}, headers=headers),
        expect,
    )


def deploy(
    client: Any,
    *,
    target: dict[str, str],
    bpm_process_id: str,
    version: str,
    not_before: str | None = None,
    expires_at: str | None = None,
    max_concurrency: int | None = None,
    headers: dict[str, str] = ADMIN,
    expect: int | tuple[int, ...] | None = (200, 201),
) -> httpx.Response:
    """배포 (C5 `POST /deployments`). `deployment_id`는 **Center가 짓는다** — 응답에서 읽는다."""
    body: dict[str, Any] = {"target": target, "bpm_process_id": bpm_process_id, "version": version}
    for name, value in (
        ("not_before", not_before),
        ("expires_at", expires_at),
        ("max_concurrency", max_concurrency),
    ):
        if value is not None:
            body[name] = value
    return _check(client.post(f"{API}/deployments", json=body, headers=headers), expect)


def deploy_id(client: Any, **wanted: Any) -> str:
    """배포하고 Center가 지은 `deployment_id`를 돌려준다."""
    return str(deploy(client, **wanted).json()["deployment_id"])


def revoke_deployment(
    client: Any,
    deployment_id: str,
    *,
    reason: str = "시험 철회",
    headers: dict[str, str] = ADMIN,
    expect: int | tuple[int, ...] | None = 200,
) -> httpx.Response:
    """배포 철회 (C5 `DELETE /deployments`). **되살릴 수 없다.**"""
    return _check(
        client.request(
            "DELETE",
            f"{API}/deployments",
            json={"deployment_id": deployment_id, "reason": reason},
            headers=headers,
        ),
        expect,
    )


def register_extension(
    client: Any,
    definition: dict[str, Any],
    *,
    headers: dict[str, str] = ADMIN,  # noqa: ARG001 — 옛 부르는 꼴을 받는다
    expect: int | tuple[int, ...] | None = (200, 201),
) -> httpx.Response:
    """외부 확장 등록 — **그 토픽을 맡은 일꾼이 제 정의를 올린다** (C15 `PUT …/self/extension`, ADR-0121).

    시험은 그 확장 id를 토픽으로 맡은 일꾼을 들이고(일꾼 폴더와 같은 함수) 그 토큰으로 올린다.
    """
    from consumers import enroll  # noqa: PLC0415 — 시험 도우미끼리 순환을 피한다

    ext_id = str(definition.get("id"))
    tokens = enroll(client, topics=[ext_id], name=f"{ext_id} 일꾼", machine=f"ext-{ext_id}")
    answer = client.put(
        f"{API}/consumers/self/extension",
        json={"definition": definition},
        headers={"Authorization": f"Bearer {tokens.token()}"},
    )
    return _check(answer, expect)


def revoke_extension(client: Any, extension_id: str, version: str, *, reason: str = "시험 철회") -> dict[str, Any]:
    """외부 확장 등록 해제 — 콘솔·API 길은 없다 (ADR-0121). 일꾼 폴더가 거둘 때 쓰는 함수를 그대로 부른다."""
    from consumers import store_of  # noqa: PLC0415

    from chaeksas.center.api import resources  # noqa: PLC0415

    return resources.revoke_extension(
        store_of(client), extension_id, version, reason=reason, by="시험"
    ).to_json_dict()


class CenterProblem(RuntimeError):
    """Center가 거절했다. `code`는 계약의 사유다."""

    def __init__(self, message: str, *, code: str = "", status: int = 0) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass
class AdminCenter:
    """관리자 토큰으로 Center를 부른다 — 콘솔(BFF)이 하는 일을 시험이 한다 (ADR-0090)."""

    client: Any
    token: str = "t-admin"
    last_status: int = 0  # 마지막 응답 코드 — 201(새로)과 200(이미 있음)을 가른다

    def call(self, method: str, path: str, *, body: Any = None) -> Any:
        response = self.client.request(
            method, f"{API}{path}", json=body, headers={"Authorization": f"Bearer {self.token}"}
        )
        self.last_status = response.status_code
        if response.status_code >= 400:
            found: dict[str, Any] = {}
            try:
                found = dict(response.json())
            except ValueError:
                pass
            raise CenterProblem(
                str(found.get("message") or response.status_code),
                code=str(found.get("code") or ""),
                status=response.status_code,
            )
        return response.json() if response.content else {}

    # ── 패키지·배포 (C5) ──

    def package(self, package_id: str, version: str) -> dict[str, Any]:
        return dict(self.call("GET", f"/packages/{package_id}/{version}/info"))

    def approve(self, package_id: str, version: str) -> dict[str, Any]:
        return dict(self.call("PUT", f"/packages/{package_id}/{version}/signature"))

    def revoke_package(self, package_id: str, version: str, *, reason: str = "시험 철회") -> dict[str, Any]:
        return dict(self.call("POST", f"/packages/{package_id}/{version}/revoke", body={"reason": reason}))

    def deprecate(self, package_id: str, version: str) -> dict[str, Any]:
        """지원 종료 표시 (C5 — **서명이 없다**, 막는 쪽이라서 관리자 권한으로 한다)."""
        return dict(self.call("PUT", f"/packages/{package_id}/{version}/status", body={"status": "deprecated"}))

    def deploy(
        self, *, target: dict[str, str], bpm_process_id: str, version: str, **extra: Any
    ) -> dict[str, Any]:
        """배포한다. `deployment_id`는 Center가 짓는다 — 돌려받는 `DeploymentInfo`에서 읽는다."""
        body = {"target": target, "bpm_process_id": bpm_process_id, "version": version}
        body |= {name: value for name, value in extra.items() if value is not None}
        return dict(self.call("POST", "/deployments", body=body))

    def revoke_deployment(self, deployment_id: str, *, reason: str = "시험 철회") -> dict[str, Any]:
        return dict(self.call("DELETE", "/deployments", body={"deployment_id": deployment_id, "reason": reason}))

    def deployments(self, *, bot_ui: str | None = None, active: bool = True) -> list[dict[str, Any]]:
        query = f"?active={'true' if active else 'false'}" + (f"&bot_ui={bot_ui}" if bot_ui else "")
        found = self.call("GET", f"/deployments{query}")
        return list(found) if isinstance(found, list) else []

    # ── 작업 (C5 — 봉투가 없다) ──

    def create_job(self, body: dict[str, Any]) -> dict[str, Any]:
        return dict(self.call("POST", "/jobs", body=body))

    def jobs(
        self, *, state: str | None = None, bot_ui: str | None = None, bpm_process_id: str | None = None
    ) -> list[dict[str, Any]]:
        asked = {"state": state, "target_id": bot_ui, "bpm_process_id": bpm_process_id}
        query = "&".join(f"{k}={v}" for k, v in asked.items() if v)
        found = self.call("GET", f"/jobs{'?' + query if query else ''}")
        return list(found) if isinstance(found, list) else []

    def job(self, job_id: str) -> dict[str, Any]:
        return dict(self.call("GET", f"/jobs/{job_id}"))

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        return dict(self.call("DELETE", f"/jobs/{job_id}"))

    def extensions(self) -> list[ExtensionResource]:
        found = self.call("GET", "/resources?type=extension")
        items = found.get("items", []) if isinstance(found, dict) else []
        return [ExtensionResource.model_validate(one) for one in items]

    def admin_keys(self) -> list[AdminKey]:
        """믿는 공개키 — Center 키(와 옛 Admin 키)다. 하트비트가 현장에 내려 주는 그것이다."""
        found = self.call("GET", "/admin-keys")
        return [AdminKey.model_validate(one) for one in found] if isinstance(found, list) else []
