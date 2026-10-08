"""모의 외부 확장 정의 둘 (C13) — 어댑터가 남의 API를 우리 말로 옮기는 자리.

정의는 **주소를 담고 있어** 그대로 커밋할 수 없다 (모의 앱의 포트는 띄울 때 정해진다).
그래서 파일이 아니라 함수로 두고, `chk-mock-apps definition <id> --base-url …`이 파일로 쓴다.
그 파일을 `chk-admin sign-extension`으로 서명해 Center에 등록한다 (C13 E6).

여기서 눈여겨볼 것 — 모의 외부 앱이 **우리 모양으로 답하지 않기 때문에** 어댑터가 일을 한다.

| 외부 앱이 말하는 것 | 정의가 옮기는 것 |
| --- | --- |
| `bizNo` (낙타 표기) | `{{input.biz_no}}` |
| `{"status": "ok", "result": {…}}` | `output.result = "$.result"`, `error_when`이 `status != "ok"`를 업무 실패로 |
| `{"ok": true, "tickets": […]}` | `output.items = "$.tickets"` |
| 경로에 문의 번호 | `path: "/api/tickets/{{input.ticket_id}}/replies"` (조각 하나로 퍼센트 인코딩된다) |

입력 이름은 **ASCII만** 쓴다 — 템플릿 변수 규칙이 `input.<ASCII 식별자>`다 (C13 §4-2).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from chaeksas.contracts.service_app import MODE_AUTONOMOUS, MODE_DETERMINISTIC

#: 두 모드 다 받는다 — Bot은 결정 수행, Studio 시험 실행은 자율 수행이다.
BOTH = [MODE_DETERMINISTIC, MODE_AUTONOMOUS]

#: 외부 앱이 「받았지만 처리하지 못했다」고 알리는 상태 코드 — 같은 요청을 다시 보내도 된다.
RETRY_ON = [429, 503]


def _host_of(base_url: str) -> str:
    host = urlsplit(base_url).hostname
    if not host:
        raise ValueError(f"base_url에 호스트가 없다: {base_url!r}")
    return host


def _private(base_url: str) -> bool:
    """사설·루프백 주소를 열어야 하는가 (C13 §4-3 4번).

    모의 앱은 127.0.0.1에 뜨므로 개발·시험에서는 열어야 한다. 진짜 외부 앱 정의에는
    이 칸이 없어야 한다.
    """
    return _host_of(base_url) in ("127.0.0.1", "localhost", "::1")


def credit(base_url: str, *, version: str = "1.0.0") -> dict[str, Any]:
    """`ext-credit` — 사업자번호로 신용점수·연체를 본다. BX-06·BX-10·FX-20이 쓴다."""
    return {
        "schema": 2,
        "id": "ext-credit",
        "version": version,
        "name": "외부 신용 조회 (모의)",
        "description": "업무 예제 시험용. 사업자번호로 신용점수와 연체 여부를 돌려준다.",
        "publisher": "Chaeksas 예제",
        "tier": "external",
        "service": {
            "protocol": "http-adapter",
            "base_url": base_url,
            "adapter": {
                "allowed_hosts": [_host_of(base_url)],
                "allow_private_network": _private(base_url),
                "auth": {"type": "bearer"},
                "limits": {"timeout_s": 10, "max_response_kb": 64},
                "health": {"path": "/health", "expect_status": 200},
                "operations": [
                    {
                        "name": "lookup",
                        "description": "신용 조회",
                        "modes": BOTH,
                        "idempotent": True,
                        "retry_on": RETRY_ON,
                        "request": {
                            "method": "POST",
                            "path": "/v1/credit/lookup",
                            "body": {"bizNo": "{{input.biz_no}}", "ref": "{{run_id}}"},
                        },
                        "response": {
                            "output": {"result": "$.result"},
                            # 모르는 사업자번호는 200에 `status: "not_found"`로 온다.
                            "error_when": {"path": "$.status", "not_equals": "ok"},
                        },
                    }
                ],
            },
        },
        "requires_keys": [{"purpose": "run"}],
        "contributes": {},
    }


def helpdesk(base_url: str, *, version: str = "1.0.0") -> dict[str, Any]:
    """`ext-helpdesk` — 문의 내려받기·답변 등록. BX-32·BX-35가 쓴다."""
    return {
        "schema": 2,
        "id": "ext-helpdesk",
        "version": version,
        "name": "외부 헬프데스크 (모의)",
        "description": "업무 예제 시험용. 문의를 내려받고 답변을 등록한다.",
        "publisher": "Chaeksas 예제",
        "tier": "external",
        "service": {
            "protocol": "http-adapter",
            "base_url": base_url,
            "adapter": {
                "allowed_hosts": [_host_of(base_url)],
                "allow_private_network": _private(base_url),
                "auth": {"type": "bearer"},
                "limits": {"timeout_s": 15, "max_response_kb": 512},
                "health": {"path": "/health", "expect_status": 200},
                "operations": [
                    {
                        "name": "export_tickets",
                        "description": "기간 안의 문의 내려받기",
                        "modes": BOTH,
                        "idempotent": True,
                        "retry_on": RETRY_ON,
                        "request": {
                            "method": "POST",
                            "path": "/api/tickets/export",
                            "body": {"since": "{{input.since}}"},
                        },
                        "response": {
                            "output": {"items": "$.tickets"},
                            "error_when": {"path": "$.ok", "equals": False},
                        },
                    },
                    {
                        "name": "post_reply",
                        "description": "문의에 답변 등록",
                        # **멱등이 아니다** — 답변은 다시 보내면 두 번 달린다. BX-32가 등록
                        # 응답을 못 받았을 때 자동으로 다시 보내지 않고 **사람에게 확인**을
                        # 묻는 것이 그래서다.
                        "modes": BOTH,
                        "idempotent": False,
                        "retry_on": [],
                        "request": {
                            "method": "POST",
                            "path": "/api/tickets/{{input.ticket_id}}/replies",
                            "body": {"message": "{{input.body}}"},
                        },
                        "response": {
                            "output": {"result": "$"},
                            "error_when": {"path": "$.ok", "equals": False},
                        },
                    },
                ],
            },
        },
        "requires_keys": [{"purpose": "run"}],
        "contributes": {},
    }


#: app_id → 정의를 만드는 함수.
BUILDERS = {"ext-credit": credit, "ext-helpdesk": helpdesk}

__all__ = ["BOTH", "BUILDERS", "RETRY_ON", "credit", "helpdesk"]
