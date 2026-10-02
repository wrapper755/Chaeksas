"""서비스 앱 공통 뼈대 — C11을 지키는 앱을 만든다.

새 서비스 앱은 **작업 함수만** 쓴다. `/healthz`, `/manifest`, 키 검증·권한, 멱등 저장,
오류 형식, 사용 기록은 여기서 계약대로 제공한다 (`docs/03-contracts/C11-service-app-common.md`).

계약 모델 자체는 `chaeksas.contracts.service_app`에 있다 — 부르는 쪽(Bot·Studio·Worker)도
같은 모델을 쓴다.

관리 콘솔 화면(SVC-00~03)은 웹이다 (`web/apps/svc-console`, ADR-0017). 여기서는 그 화면이
부를 관리 API의 재료(키 발급·사용 기록)만 둔다.
"""

from chaeksas.service_kit.app import Handler, OpError, OpResult, create_app
from chaeksas.service_kit.keys import find_key, generate_key, hash_key, issue
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
    "Handler",
    "IdempotencyStore",
    "InMemoryIdempotencyStore",
    "InMemoryKeyStore",
    "InMemoryUsageLog",
    "KeyStore",
    "OpError",
    "OpResult",
    "UsageLog",
    "body_hash",
    "create_app",
    "find_key",
    "generate_key",
    "hash_key",
    "issue",
]
