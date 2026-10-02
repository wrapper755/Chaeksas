"""공통 계약 — 주고받는 데이터 모델, 스키마 버전, 해시·서명 규칙 (C1~C14).

**원본은 하나다** (`docs/03-contracts/README.md` 원칙 1). 다른 앱은 이 패키지를 import하고,
복사본을 두지 않는다. 문서는 뜻·규칙·예시를 설명하고, 코드는 이 패키지가 전부다.

지금 구현된 것:

| 계약 | 모듈 | 내용 |
| --- | --- | --- |
| C1 | `manifest` | 패키지 매니페스트 + 검사 규칙 `validate()` |
| C3 | `events` | 실행 이벤트 (`kind`는 열린 문자열) |
| C4 | `bot_ui` | Bot UI 등록·하트비트 |

자세히: docs/01-architecture.md §2, docs/03-contracts/.
"""

from chaeksas.contracts._base import ContractModel, SchemaVersioned, Sha256, Timestamp
from chaeksas.contracts.bot_ui import (
    AdminKey,
    ApprovalAck,
    ApprovalDispatch,
    CurrentRun,
    DeploymentResult,
    ExtensionState,
    HeartbeatRequest,
    HeartbeatResponse,
    JobAck,
    JobDispatch,
    Queue,
    QueueItem,
    Readiness,
    RegisterRequest,
    RegisterResponse,
    Runtimes,
    Versions,
    WorkerState,
)
from chaeksas.contracts.events import (
    EventBatchResponse,
    RejectedLine,
    RunEvent,
    missing_data_keys,
)
from chaeksas.contracts.manifest import (
    Built,
    ExtensionNeed,
    HumanNeeds,
    Manifest,
    Provides,
    Requires,
    ResourceRef,
    ServiceAppNeed,
    TaskTypeNeed,
    ToolpackRef,
    Trigger,
    Violation,
    validate,
)

__all__ = [
    # 바탕
    "ContractModel",
    "SchemaVersioned",
    "Sha256",
    "Timestamp",
    # C1
    "Built",
    "ExtensionNeed",
    "HumanNeeds",
    "Manifest",
    "Provides",
    "Requires",
    "ResourceRef",
    "ServiceAppNeed",
    "TaskTypeNeed",
    "ToolpackRef",
    "Trigger",
    "Violation",
    "validate",
    # C3
    "EventBatchResponse",
    "RejectedLine",
    "RunEvent",
    "missing_data_keys",
    # C4
    "AdminKey",
    "ApprovalAck",
    "ApprovalDispatch",
    "CurrentRun",
    "DeploymentResult",
    "ExtensionState",
    "HeartbeatRequest",
    "HeartbeatResponse",
    "JobAck",
    "JobDispatch",
    "Queue",
    "QueueItem",
    "Readiness",
    "RegisterRequest",
    "RegisterResponse",
    "Runtimes",
    "Versions",
    "WorkerState",
]
