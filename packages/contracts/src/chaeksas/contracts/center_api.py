"""C5. Center API: 패키지·배포·작업.

단일 원본: `docs/03-contracts/C5-packages-deployments-jobs.md`.

패키지를 올리고(후보) → 승인 서명을 붙이고 → 배포 서명으로 대상에 배치하고 → 작업으로
실행시키는 흐름. 배포·작업이 실행하는 쪽에 **내려가는** 모양은 C4(하트비트 응답)에 있다.

여기에는 요청·응답 **모양**과, 상태를 보지 않고 할 수 있는 **검사**만 둔다.
대상이 존재하는지, 같은 봉투가 이미 있는지 같은 검사는 Center가 자기 저장소를 보고 한다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Any

from pydantic import Field, model_validator

from chaeksas.contracts._base import ContractModel, Sha256, Timestamp, Violation
from chaeksas.contracts.bot_ui import (
    CurrentRun,
    ExtensionState,
    Queue,
    Readiness,
    Runtimes,
    Versions,
    WorkerState,
)
from chaeksas.contracts.manifest import Manifest
from chaeksas.contracts.resources import MissingResource
from chaeksas.contracts.signing import AdminKey, Envelope, verify, verify_time

#: 헤더 이름 — 문자열을 코드 곳곳에 흩어 두지 않는다 (프로토타입에서 문서의 `X-Bot-Id`와
#: 코드의 `?bot_id=`가 어긋났다).
ACTOR_HEADER = "X-CHK-Actor"
"""콘솔 서버(BFF)가 로그인 세션의 사용자 이름을 실어 보낸다. **관리자·읽기 토큰일 때만 믿는다.**"""

CONTENT_HASH_HEADER = "X-Content-Hash"
"""패키지 내려받기 응답에 붙는다."""

#: 목록 요청 (`limit`·`offset`).
LIST_LIMIT_DEFAULT = 100
LIST_LIMIT_MAX = 1000

#: 패키지 zip 크기 한도 (Center 설정 `CHK_CENTER__PACKAGE__MAX_MB`). 넘으면 413 `too_large`.
MAX_PACKAGE_MB = 50

#: 작업 메모 길이, 멱등 키 기억 기간.
MAX_NOTE_CHARS = 500
IDEMPOTENCY_WINDOW_DAYS = 7

# 아래는 모두 **열린 문자열**의 알려진 값이다 (README 원칙 10).
KNOWN_PACKAGE_STATUSES = frozenset({"candidate", "approved", "deprecated", "revoked"})
KNOWN_JOB_STATES = frozenset({"pending", "dispatched", "queued", "accepted", "rejected", "expired", "cancelled"})
KNOWN_REJECT_REASONS = frozenset(
    {"queue_full", "no_deployment", "not_ready", "bot_ui_shutdown", "bot_ui_lost",
     "server_location", "cancelled_on_pc"}
)
KNOWN_QUEUED_REASONS = frozenset({"global_limit", "per_bot_limit", "paused"})
KNOWN_CANCEL_RESULTS = frozenset({"cancelled", "refused_already_started"})
KNOWN_TARGET_TYPES = frozenset({"bot_ui", "server_runner"})
# `missing_resources`의 값 목록은 C7이 소유한다 (`resources.KNOWN_MISSING_TYPES`).
KNOWN_AUTH_KINDS = frozenset(
    {"read_token", "admin_token", "studio_key", "bot_ui_key", "server_runner_key", "integration_key"}
)

#: 실행 위치 → 배포·작업 대상 종류 (C2 "배포 대상 규칙").
TARGET_TYPE_FOR_RUN_LOCATION = {"pc": "bot_ui", "server": "server_runner"}

JobId = Annotated[str, Field(pattern=r"^job_[0-9a-f]{8}$")]


class ErrorBody(ContractModel):
    """오류 응답 본문. C11과 같은 형식이다."""

    code: str
    message: str
    detail: dict[str, Any] = Field(default_factory=dict)


class ListParams(ContractModel):
    """목록 요청의 공통 질의 변수."""

    limit: int = Field(default=LIST_LIMIT_DEFAULT, ge=1, le=LIST_LIMIT_MAX)
    offset: int = Field(default=0, ge=0)


# ─────────────────────────── 패키지 ───────────────────────────


class PreflightSummary(ContractModel):
    """Studio가 계산한 사전 점검 요약. 값은 코드 목록이다 (C4 `Readiness.blocked`와 같은 결)."""

    warnings: list[str] = Field(default_factory=list)
    blocked: list[str] = Field(default_factory=list)


class PackageInfo(ContractModel):
    """`GET /packages`의 한 줄, `POST /packages`의 응답."""

    id: str
    version: str
    kind: str
    name: str | None = None
    run_location: str | None = None  # bpm_process에만 있다
    status: str  # 열린 문자열 (KNOWN_PACKAGE_STATUSES)
    content_hash: Sha256
    uploaded_by: str
    uploaded_at: Timestamp
    signed_by: str | None = None
    signed_at: Timestamp | None = None
    preflight: PreflightSummary = Field(default_factory=PreflightSummary)
    manifest: Manifest | None = None
    missing_resources: list[MissingResource] = Field(default_factory=list)


class BotUiKey(ContractModel):
    """그 Bot UI가 쓰는 Center API 키 (C7). **원문·해시는 주지 않는다.**"""

    prefix: str
    expires_at: Timestamp | None = None
    state: str  # active / expired / revoked


class BotUiInfo(ContractModel):
    """`GET /bot-uis`의 한 줄 (CON-03).

    상태 값은 **Bot UI가 하트비트로 보고한 그대로**다 (C4). Center가 더하는 것은 온라인
    판정(`online`)과 키 정보(`key`)뿐이다.
    """

    bot_ui_id: str
    name: str
    os: str
    machine_id: str
    versions: Versions  # 등록할 때 반드시 받는다 (C4 `register`)
    runtimes: Runtimes | None = None
    registered_at: Timestamp
    last_seen_at: Timestamp | None = None
    #: 마지막 하트비트가 90초 이내인가 (C4 「온라인 판정」).
    online: bool = False
    disabled: bool = False
    #: 아래는 마지막 하트비트의 내용. 아직 하트비트가 없으면 비어 있다.
    status: str | None = None
    current_run: CurrentRun | None = None
    queue: Queue | None = None
    worker: WorkerState | None = None
    readiness: list[Readiness] = Field(default_factory=list)
    extensions: list[ExtensionState] = Field(default_factory=list)
    key: BotUiKey | None = None


# ─────────────────────────── 배포 ───────────────────────────


class DeploymentInfo(ContractModel):
    """`GET /deployments`의 한 줄. 봉투 자체가 아니라 Center가 정리한 모양이다.

    실행하는 쪽에 내려갈 때는 **저장된 봉투 그대로** 간다 (C4 `deployments[]`).
    """

    deployment_id: str
    target: dict[str, Any]  # {type, id} — C2 DeploymentTarget과 같은 모양
    bpm_process_id: str
    version: str
    content_hash: Sha256
    signed_by: str
    signed_at: Timestamp
    max_concurrency: int | None = None
    not_before: Timestamp | None = None
    expires_at: Timestamp | None = None
    revoked_at: Timestamp | None = None
    last_result: str | None = None  # C4 deployment_results의 마지막 값


def validate_deployment(
    envelope: Envelope,
    *,
    package: PackageInfo,
    keys: Sequence[AdminKey],
    now: str,
    server_runner_available: bool = False,
) -> list[Violation]:
    """`POST /deployments`에서 Center가 하는 검사.

    - 서명 C2 V1~V4와 V5a(`expired`). **`not_before`가 미래인 예약 배포도 받는다** (V5b는 실행하는 쪽).
    - 패키지가 `approved`다 (`not_approved`) — `deprecated`는 따로 알린다 (`deprecated`).
    - 봉투의 해시가 패키지와 같다 (`hash_mismatch`).
    - `target.type`이 패키지의 `run_location`과 맞다 (`target_mismatch`).
    - M6까지 서버 실행기 배포는 받지 않는다 (`server_runner_not_available`, ADR-0016).

    여기서 하지 않는 것: **대상이 존재하는지**(Center 저장소), **같은 `deployment_id`의 충돌**
    (`deployment_conflict`·`deployment_revoked`, C2 멱등성), **C1 R8**(C11 manifest·C7 대조).
    """
    out = [*verify(envelope, keys=keys, expect_kind="deployment")]
    out += verify_time(envelope, now=now, check_not_before=False)

    if package.status == "deprecated":
        out.append(Violation(rule="C5", code="deprecated", message="지원 종료된 패키지에는 새로 배포하지 않는다"))
    elif package.status != "approved":
        out.append(
            Violation(rule="C5", code="not_approved", message=f"패키지 상태가 {package.status}다 (승인 필요)")
        )

    if envelope.payload.get("content_hash") != package.content_hash:
        out.append(
            Violation(
                rule="C5",
                code="hash_mismatch",
                message=f"봉투의 해시가 패키지와 다르다 (봉투 {envelope.payload.get('content_hash')}, "
                f"패키지 {package.content_hash})",
            )
        )

    target_type = str(envelope.payload.get("target", {}).get("type", ""))
    expected = TARGET_TYPE_FOR_RUN_LOCATION.get(package.run_location or "")
    if expected is not None and target_type != expected:
        out.append(
            Violation(
                rule="C5",
                code="target_mismatch",
                message=f"run_location={package.run_location}이면 대상은 {expected}다 (받은 값 {target_type})",
            )
        )
    if target_type == "server_runner" and not server_runner_available:
        out.append(
            Violation(
                rule="C5",
                code="server_runner_not_available",
                message="서버 실행은 M7부터다 (ADR-0016)",
            )
        )
    return out


# ─────────────────────────── 작업 ───────────────────────────


class JobTarget(ContractModel):
    """작업 대상. 서버 실행기는 `id`를 비우거나 `"*"`로 두면 Center가 고른다."""

    type: str  # 열린 문자열 (KNOWN_TARGET_TYPES)
    id: str | None = None

    @model_validator(mode="after")
    def _bot_ui_needs_id(self) -> JobTarget:
        if self.type == "bot_ui" and not self.id:
            raise ValueError("bot_ui 대상에는 id가 필요하다 (어느 PC인지 Center가 고를 수 없다)")
        return self


class JobCreateRequest(ContractModel):
    """`POST /jobs`.

    `requested_by`는 **본문에서 받지 않는다.** 키 이름이나 `X-CHK-Actor` 헤더로 Center가 채운다.
    """

    bpm_process_id: str
    target: JobTarget
    inputs: dict[str, Any]  # JSON 객체가 아니면 422 `inputs_not_object`
    version: str | None = None  # 비우면 대상에 배포된 버전
    expires_at: Timestamp | None = None
    note: str | None = Field(default=None, max_length=MAX_NOTE_CHARS)
    idempotency_key: str | None = None


class JobInfo(JobCreateRequest):
    """`GET /jobs/{id}` — 만들 때 받은 것 + Center가 아는 것.

    취소(`DELETE /jobs/{id}`)도 이 모양으로 답한다. 202일 때는 `cancel_requested=true`이고,
    결과는 다음 하트비트의 ack로 `cancel_result`에 적힌다.
    """

    job_id: JobId
    requested_by: str
    requested_at: Timestamp
    state: str  # 열린 문자열 (KNOWN_JOB_STATES)
    state_reason: str | None = None  # KNOWN_REJECT_REASONS / KNOWN_QUEUED_REASONS
    cancel_requested: bool = False
    cancel_result: str | None = None  # KNOWN_CANCEL_RESULTS
    queue_position: int | None = None  # PC 대기열 순번 (C4)
    dispatched_at: Timestamp | None = None
    run_id: str | None = None
    run_status: str | None = None  # 실행의 성패는 작업 상태가 아니다 (C3 run_finished가 정한다)


def validate_job_create(
    req: JobCreateRequest,
    *,
    deployed_versions: Sequence[str] | None = None,
) -> list[Violation]:
    """`POST /jobs`에서 상태를 보지 않고 할 수 있는 검사 + 배포 버전 대조.

    - `deployed_versions`를 주면: 비어 있으면 `no_deployment`, `version`을 비웠는데 둘 이상이면
      `version_ambiguous`, 지정한 `version`이 그 안에 없으면 `no_deployment`.
    - 주지 않으면 그 검사를 건너뛴다 (대상의 활성 배포는 Center만 안다).

    `inputs`가 객체가 아닌 경우(`inputs_not_object`)와 `note` 길이는 모델이 막는다.
    """
    if deployed_versions is None:
        return []
    out = []
    if not deployed_versions:
        out.append(
            Violation(
                rule="C5",
                code="no_deployment",
                message=f"{req.bpm_process_id}가 이 대상에 배포되어 있지 않다",
            )
        )
    elif req.version is None:
        if len(set(deployed_versions)) > 1:
            out.append(
                Violation(
                    rule="C5",
                    code="version_ambiguous",
                    message="활성 배포가 둘 이상이라 버전을 정해야 한다",
                    items=sorted(set(deployed_versions)),
                )
            )
    elif req.version not in deployed_versions:
        out.append(
            Violation(
                rule="C5",
                code="no_deployment",
                message=f"버전 {req.version}이 이 대상에 배포되어 있지 않다",
                items=sorted(set(deployed_versions)),
            )
        )
    return out


def cancel_outcome(state: str) -> tuple[int, str | None]:
    """작업 상태 → 취소 요청의 응답 코드와 오류 `code` (C5 「취소」 표).

    - `pending` → 200 (바로 `cancelled`)
    - `dispatched`·`queued` → 202 (하트비트로 빼내야 한다. 그사이 시작했으면 `accepted` 유지)
    - `accepted` → 409 `already_started` (실행 중인 Bot을 멈추는 것은 schema 1 범위 밖)
    - 그 밖 → 409 `not_cancellable`
    """
    if state == "pending":
        return 200, None
    if state in ("dispatched", "queued"):
        return 202, None
    if state == "accepted":
        return 409, "already_started"
    return 409, "not_cancellable"
