"""Center 작업 지시를 감싼 앱 — 사내 확장 `center-jobs`의 서버 부분. BX-16이 부른다.

**이 앱만 모의가 아니다.** 진짜 Center의 `POST /jobs`(C5)를 부른다. BX-16이 메우려는
공백이 「서버 BPM 프로세스가 PC BPM 프로세스에 일을 넘기는 요소가 없다」는 것이고
(`docs/08-business-examples/scm.md`, ADR-0016 §3), 그 자리를 **Center 연동용 키를 가진
서비스 앱**으로 메우는 것이 예제의 설계다. 키를 Bot이 아니라 이 앱이 쥔다 (ADR-0013).

설정은 환경변수로만 받는다 (CLAUDE.md §5).

| 환경변수 | 뜻 |
| --- | --- |
| `CHK_SVC_CENTER_JOBS__CENTER__BASE_URL` | Center 주소 |
| `CHK_SVC_CENTER_JOBS__CENTER__TOKEN` | Center 연동용 키 (C5 권한표) |
| `CHK_SVC_CENTER_JOBS__GROUPS` | `{"구매-PC": "<bot_ui_id>"}` — 그룹 이름을 PC로 푼다 |

**그룹은 Center에 없다** — C5의 작업 대상은 `bot_ui`(id 필수) 또는 `server_runner`뿐이다.
BPM 프로세스가 적는 `group:구매-PC`를 어느 PC로 보낼지는 **이 앱이** 안다. 계약을 늘리지
않고 앱 쪽에 둔 것이고, 공백은 `samples/README.md`에 적어 두었다.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Any

from chaeksas.contracts.service_app import OpRequest
from chaeksas.mock_apps.c11 import MockApp, Op, Scenario
from chaeksas.service_kit import OpError

ENV_PREFIX = "CHK_SVC_CENTER_JOBS__"

#: Center API 경로 (C5).
JOBS_PATH = "/api/v1/jobs"

#: 기본 타임아웃 (초).
TIMEOUT_S = 10


def _env(name: str) -> str:
    return os.environ.get(ENV_PREFIX + name, "").strip()


def _groups() -> dict[str, str]:
    raw = _env("GROUPS")
    if not raw:
        return {}
    try:
        found = json.loads(raw)
    except ValueError as e:
        raise OpError("dependency_down", f"{ENV_PREFIX}GROUPS가 JSON이 아니다 (앱 설정)", status=503) from e
    if not isinstance(found, dict):
        raise OpError("dependency_down", f"{ENV_PREFIX}GROUPS는 JSON 객체여야 한다 (앱 설정)", status=503)
    return {str(k): str(v) for k, v in found.items()}


def _target(raw: Any) -> dict[str, Any]:
    """`group:<이름>` · `bot_ui:<id>` · `server_runner`를 C5 `JobTarget`으로 바꾼다."""
    text = str(raw or "").strip()
    if not text:
        raise OpError("input_invalid", "`target`이 필요하다", status=422)
    kind, _, rest = text.partition(":")
    if kind == "server_runner":
        return {"type": "server_runner", "id": rest or None}
    if kind == "bot_ui":
        if not rest:
            raise OpError("input_invalid", "`bot_ui:` 뒤에 Bot UI id가 필요하다", status=422)
        return {"type": "bot_ui", "id": rest}
    if kind == "group":
        found = _groups().get(rest)
        if not found:
            raise OpError(
                "input_invalid",
                f"그룹 「{rest}」을 어느 PC로 보낼지 모른다 ({ENV_PREFIX}GROUPS를 보라)",
                status=422,
            )
        return {"type": "bot_ui", "id": found}
    raise OpError("input_invalid", f"모르는 대상이다: {text}", status=422)


def create_job(req: OpRequest, scenario: Scenario) -> Mapping[str, Any]:
    """Center에 작업 하나를 만든다.

    멱등 키는 **부른 쪽의 자리**(실행·노드·그 노드의 몇 번째)에서 만든다 — 서비스 호출이
    재시도되어도 작업이 둘 생기지 않는다 (C5 멱등은 부른 쪽마다 7일).
    """
    import httpx  # noqa: PLC0415 — 부를 때만 든다

    base = _env("CENTER__BASE_URL")
    token = _env("CENTER__TOKEN")
    if not base or not token:
        raise OpError(
            "dependency_down",
            f"Center 주소·연동용 키가 없다 ({ENV_PREFIX}CENTER__BASE_URL·CENTER__TOKEN)",
            status=503,
        )

    inputs = req.input.get("inputs") or {}
    if not isinstance(inputs, Mapping):
        raise OpError("input_invalid", "`inputs`는 JSON 객체여야 한다", status=422)

    body = {
        "bpm_process_id": str(req.input.get("bpm_process") or ""),
        "target": _target(req.input.get("target")),
        "inputs": dict(inputs),
        # 비우면 Center가 그 대상에 배포된 버전으로 채운다 (C5).
        "version": req.input.get("version") or None,
        "note": req.input.get("note") or None,
        "idempotency_key": f"{req.run_id}:{req.node_id}:{req.node_instance}",
    }
    if not body["bpm_process_id"]:
        raise OpError("input_invalid", "`bpm_process`가 필요하다", status=422)

    try:
        response = httpx.post(
            base.rstrip("/") + JOBS_PATH,
            json=body,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=TIMEOUT_S,
        )
    except httpx.HTTPError as e:
        raise OpError("dependency_down", f"Center에 닿지 못했다 ({type(e).__name__})", status=503) from e

    if response.status_code >= 400:
        detail = _problem(response)
        # Center가 거부한 것(배포 없음·모르는 PC)은 **업무 실패**다 — 다시 보내도 풀리지 않는다.
        # Center가 아픈 것(5xx)은 재시도할 거리다. C11 오류 표의 코드만 쓴다.
        if response.status_code >= 500:
            raise OpError("dependency_down", f"Center가 아프다: {detail}", status=503)
        raise OpError("input_invalid", f"Center가 작업을 만들지 않았다: {detail}", status=422)

    found = response.json()
    return {"job_id": found.get("job_id"), "state": found.get("state")}


def _problem(response: Any) -> str:
    """Center 오류 본문(`{code, message, detail}`)을 한 줄로. **본문 전체를 싣지 않는다.**"""
    try:
        found = response.json()
        return f"{found.get('code')} {found.get('message')}"
    except ValueError:
        return f"HTTP {response.status_code}"


APP = MockApp(
    app_id="center-jobs",
    name="Center 작업 지시 (사내 확장)",
    extension="center-jobs",
    category="system",
    used_by=("BX-16",),
    doc="BPM 프로세스가 다른 BPM 프로세스의 작업 지시를 만든다 (Center 연동용 키는 이 앱이 쥔다)",
    ops=(Op("create_job", "작업 지시 만들기", create_job, server_ok=True),),
)

__all__ = ["APP", "ENV_PREFIX", "JOBS_PATH", "TIMEOUT_S"]
