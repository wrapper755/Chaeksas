"""HTTP 어댑터 **해석기 규격** (C13 §4). 구현은 하나뿐이고 `core`에 있다.

외부 확장은 코드를 기여하지 않는다 — 정의 안의 선언만 둔다. 그 선언을 읽어 실제로 부르는 것은
플랫폼의 공통 해석기다. 규격을 여기 두는 이유는 두 가지다.

1. 부르는 쪽(Studio 시험 실행·실행기·서버 실행기)이 **같은 모양**으로 부른다.
2. 안전 규칙(https만·리다이렉트 금지·사설망 차단·DNS 고정·크기 상한)을 지킬 책임이 해석기 하나에
   모인다. 확장이 우회할 자리가 없다.

> 상태: 규격만 있다. 해석기(`core.http_adapter`)는 아직 없다 (M5, `docs/05-roadmap.md`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from chaeksas.contracts.extension import AdapterOperation, HttpAdapter

#: 해석기가 돌려주는 실패 코드. `redirect_not_allowed`는 C13 §4-3이 정한 이름이고,
#: 나머지는 같은 규칙을 어긴 자리를 가리키는 해석기의 이름이다.
ERROR_REDIRECT_NOT_ALLOWED = "redirect_not_allowed"
ERROR_HOST_NOT_ALLOWED = "host_not_allowed"
ERROR_INSECURE_SCHEME = "insecure_scheme"
ERROR_PRIVATE_NETWORK_BLOCKED = "private_network_blocked"
ERROR_RESPONSE_TOO_LARGE = "response_too_large"
ERROR_TIMEOUT = "timeout"
ERROR_OUTPUT_MISSING = "output_missing"
ERROR_APP_ERROR = "app_error"  # 응답이 `error_when`에 걸렸다


@dataclass(frozen=True)
class AdapterCall:
    """한 번의 호출. 템플릿에 넣을 값은 모두 여기서 온다 (C13 §4-2).

    **`key`는 템플릿에 넣지 않는다.** 선언한 인증 자리(`adapter.auth`)에만 들어가고, 기록에도
    남지 않는다.
    """

    adapter: HttpAdapter
    operation: AdapterOperation
    #: 쓸 주소 — 리소스 등록(C7)의 `base_url`이 있으면 그것, 없으면 정의의 것 (출처는 하나다).
    base_url: str
    inputs: Mapping[str, Any] = field(default_factory=dict)
    key: str | None = None
    run_id: str = ""
    node_id: str = ""
    #: C11 멱등 키를 문자열로 (`{{idempotency_key}}`로 쓸 수 있다).
    idempotency_key: str = ""


@dataclass(frozen=True)
class AdapterOutcome:
    """호출 결과. 요청·응답 **본문은 담지 않는다** (C13 §4-3 — 기록에 업무 값을 남기지 않는다)."""

    status: int
    outputs: Mapping[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    #: 처리되었는지 **모르는** 실패인가 (시간 초과·연결 끊김). `idempotent=false`면 다시 부르지
    #: 않고 사람에게 넘긴다 (PC는 확인, 서버는 오류 경계).
    unknown_result: bool = False

    @property
    def ok(self) -> bool:
        return self.error_code is None


@runtime_checkable
class AdapterCaller(Protocol):
    """선언된 작업 하나를 실제로 부른다. 안전 규칙은 구현이 지킨다 (C13 §4-3)."""

    def call(self, call: AdapterCall) -> AdapterOutcome: ...
