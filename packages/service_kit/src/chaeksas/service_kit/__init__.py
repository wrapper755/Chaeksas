"""서비스 앱 공통 뼈대 — C11을 지키는 앱을 만든다. **앱은 일꾼이다** (ADR-0102).

새 서비스 앱은 **작업 함수만** 쓴다. 멱등 저장, 수행 모드·폴백, 오류 형식, 사용 기록, `/healthz`,
관리 API는 `create_app`이, Center에서 일감을 가져와 끝내는 일은 `Consumer`가 한다
(`docs/03-contracts/C11-service-app-common.md`, C15).

관리 콘솔 화면(SVC-00·01·03)은 웹이다 (`web/apps/svc-console`, ADR-0017). 그 화면이 부르는
**관리 API(`/admin/v1/status`·`usage`)는 여기서 제공한다** — `create_app(admin_token=…)`을 주면
열리고, 주지 않으면 503이다 (빈 토큰으로 열리지 않는다).

모델이 필요한 작업은 `ServiceLlm`(C11 §모델 연결, ADR-0034)으로 부른다.
"""

from chaeksas.service_kit.admin import DependencyProbe, admin_guard
from chaeksas.service_kit.app import (
    CatalogSource,
    Handler,
    OpError,
    OpResult,
    Outcome,
    Service,
    TopicService,
    create_app,
)
from chaeksas.service_kit.consumer import Consumer, TokenFile, start_in_thread
from chaeksas.service_kit.llm import LLM_UNAVAILABLE, LlmSettings, ServiceLlm, usage_of
from chaeksas.service_kit.stores import (
    IdempotencyStore,
    InMemoryIdempotencyStore,
    InMemoryUsageLog,
    UsageLog,
    body_hash,
)

__all__ = [
    "LLM_UNAVAILABLE",
    "CatalogSource",
    "Consumer",
    "DependencyProbe",
    "Handler",
    "IdempotencyStore",
    "InMemoryIdempotencyStore",
    "InMemoryUsageLog",
    "LlmSettings",
    "OpError",
    "OpResult",
    "Outcome",
    "Service",
    "ServiceLlm",
    "TokenFile",
    "TopicService",
    "UsageLog",
    "admin_guard",
    "body_hash",
    "create_app",
    "start_in_thread",
    "usage_of",
]
