"""서비스 앱 공통 뼈대 — C11을 지키는 앱을 만든다.

새 서비스 앱은 **작업 함수만** 쓴다. `/healthz`, `/manifest`, 키 검증·권한, 멱등 저장,
오류 형식, 사용 기록은 여기서 계약대로 제공한다 (`docs/03-contracts/C11-service-app-common.md`).

계약 모델 자체는 `chaeksas.contracts.service_app`에 있다 — 부르는 쪽(Bot·Studio·Worker)도
같은 모델을 쓴다.

관리 콘솔 화면(SVC-00~03)은 웹이다 (`web/apps/svc-console`, ADR-0017). 그 화면이 부르는
**관리 API(`/admin/v1/status`·`keys`·`usage`)는 여기서 제공한다** — `create_app(admin_token=…)`을
주면 열리고, 주지 않으면 503이다 (빈 토큰으로 열리지 않는다).

모델이 필요한 작업은 `ServiceLlm`(C11 §모델 연결, ADR-0034)으로 부른다 — 클라이언트는 엔진과 같은
`chaeksas.llm`이고, 설정이 없으면 503 `llm_unavailable`이다.
"""

from chaeksas.service_kit.admin import DependencyProbe, admin_guard
from chaeksas.service_kit.app import Handler, OpError, OpResult, create_app
from chaeksas.service_kit.keys import find_key, generate_key, hash_key, issue
from chaeksas.service_kit.llm import LLM_UNAVAILABLE, LlmSettings, ServiceLlm, usage_of
from chaeksas.service_kit.stores import (
    IdempotencyStore,
    InMemoryIdempotencyStore,
    InMemoryKeyStore,
    InMemoryUsageLog,
    KeyStore,
    UsageLog,
    body_hash,
)

__all__ = [
    "DependencyProbe",
    "Handler",
    "IdempotencyStore",
    "InMemoryIdempotencyStore",
    "InMemoryKeyStore",
    "InMemoryUsageLog",
    "KeyStore",
    "LLM_UNAVAILABLE",
    "LlmSettings",
    "OpError",
    "OpResult",
    "ServiceLlm",
    "UsageLog",
    "admin_guard",
    "body_hash",
    "create_app",
    "find_key",
    "generate_key",
    "hash_key",
    "issue",
    "usage_of",
]
