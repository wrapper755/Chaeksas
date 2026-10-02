"""공통 계약 — 주고받는 데이터 모델, 스키마 버전, 해시·서명 규칙 (C1~C14).

**원본은 하나다** (`docs/03-contracts/README.md` 원칙 1). 다른 앱은 이 패키지를 import하고,
복사본을 두지 않는다. 문서는 뜻·규칙·예시를 설명하고, 코드는 이 패키지가 전부다.

지금 구현된 것:

| 계약 | 모듈 | 내용 |
| --- | --- | --- |
| C1 | `manifest` | 패키지 매니페스트 + 검사 규칙 `validate()` |
| C2 | `hashing`, `signing` | `canonical_json`·`content_hash`, 서명 봉투 + 검증 규칙 V1~V8 |
| C3 | `events` | 실행 이벤트 (`kind`는 열린 문자열) |
| C4 | `bot_ui` | Bot UI 등록·하트비트 |
| C5 | `center_api` | 패키지·배포·작업 + 배포·작업 검사 |
| C6 | `approvals` | 결재 요청·답 + 폼으로 답 검증 |
| C7 | `resources`, `center_keys` | 리소스 목록 + 누락 검사, Center API 키 |

검사 함수가 계약마다 있어서, 이름이 겹치는 것은 루트에서 계약을 붙여 다시 내보낸다
(`validate_approval_create`, `validate_center_key_create`). 모듈 안의 이름은 계약 문서 그대로다.

자세히: docs/01-architecture.md §2, docs/03-contracts/.
"""

from chaeksas.contracts._base import ContractModel, SchemaVersioned, Sha256, Timestamp, Violation
from chaeksas.contracts.approvals import (
    AnswerRequest,
    ApprovalCreateRequest,
    ApprovalHost,
    ApprovalInfo,
    Form,
    FormField,
    apply_defaults,
    request_id_for,
    validate_answer,
)
from chaeksas.contracts.approvals import validate_create as validate_approval_create
from chaeksas.contracts.bot_ui import (
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
from chaeksas.contracts.center_api import (
    DeploymentInfo,
    ErrorBody,
    JobCreateRequest,
    JobInfo,
    JobTarget,
    ListParams,
    PackageInfo,
    PreflightSummary,
    cancel_outcome,
    validate_deployment,
    validate_job_create,
)
from chaeksas.contracts.center_keys import (
    BoundTo,
    CenterKeyCreated,
    CenterKeyCreateRequest,
    CenterKeyInfo,
    expires_soon,
    key_state,
    prefix_of,
)
from chaeksas.contracts.center_keys import validate_create as validate_center_key_create
from chaeksas.contracts.events import (
    EventBatchResponse,
    RejectedLine,
    RunEvent,
    missing_data_keys,
)
from chaeksas.contracts.hashing import (
    FloatInPayloadError,
    canonical_json,
    content_hash_dir,
    content_hash_from_files,
    content_hash_zip,
    sha256_hex,
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
    validate,
)
from chaeksas.contracts.resources import (
    ContributedResource,
    ExtensionResource,
    InstalledOn,
    MissingResource,
    Operation,
    ResourceIndex,
    ResourceList,
    RuntimeHost,
    RuntimeResource,
    ServiceAppResource,
    ToolpackResource,
    blocking_at_deploy,
    missing,
)
from chaeksas.contracts.signing import (
    AdminKey,
    AdminKeyClaim,
    DeploymentClaim,
    DeploymentTarget,
    Envelope,
    PackageClaim,
    RevokeClaim,
    key_id_for,
    parse_claim,
    sign,
    verify,
    verify_admin_key_addition,
    verify_package,
    verify_target,
    verify_time,
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
    # C2
    "AdminKey",
    "AdminKeyClaim",
    "DeploymentClaim",
    "DeploymentTarget",
    "Envelope",
    "FloatInPayloadError",
    "PackageClaim",
    "RevokeClaim",
    "canonical_json",
    "content_hash_dir",
    "content_hash_from_files",
    "content_hash_zip",
    "key_id_for",
    "parse_claim",
    "sha256_hex",
    "sign",
    "verify",
    "verify_admin_key_addition",
    "verify_package",
    "verify_target",
    "verify_time",
    # C3
    "EventBatchResponse",
    "RejectedLine",
    "RunEvent",
    "missing_data_keys",
    # C4 (`AdminKey`는 C2가 소유한다)
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
    # C5
    "DeploymentInfo",
    "ErrorBody",
    "JobCreateRequest",
    "JobInfo",
    "JobTarget",
    "ListParams",
    "PackageInfo",  # `MissingResource`는 C7이 소유한다
    "PreflightSummary",
    "cancel_outcome",
    "validate_deployment",
    "validate_job_create",
    # C6
    "AnswerRequest",
    "ApprovalCreateRequest",
    "ApprovalHost",
    "ApprovalInfo",
    "Form",
    "FormField",
    "apply_defaults",
    "request_id_for",
    "validate_answer",
    "validate_approval_create",
    # C7
    "BoundTo",
    "CenterKeyCreateRequest",
    "CenterKeyCreated",
    "CenterKeyInfo",
    "ContributedResource",
    "ExtensionResource",
    "InstalledOn",
    "MissingResource",
    "Operation",
    "ResourceIndex",
    "ResourceList",
    "RuntimeHost",
    "RuntimeResource",
    "ServiceAppResource",
    "ToolpackResource",
    "blocking_at_deploy",
    "expires_soon",
    "key_state",
    "missing",
    "prefix_of",
    "validate_center_key_create",
]
