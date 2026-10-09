"""계약 모델 → JSON Schema 생성 (`docs/03-contracts/README.md` 원칙 5).

실행: `uv run python scripts/gen_schemas.py`
`--check`: 파일을 쓰지 않고 검사만 하며, 생성물이 모델과 다르면 1로 끝난다 (CI용).

다른 언어 도구(웹 화면의 `api-types` 등)가 같은 명세를 쓰도록 내보낸다.
브라우저 쪽 타입은 이 스키마에서 생성한다 (ADR-0017).

**확장이 소유한 계약도 내보낸다** — 확장마다 `<패키지>.contracts.SCHEMA_MODELS`를 읽어 **그
확장의 `schemas/`**에 쓴다. 찾는 길은 확장 호스트와 같은 엔트리 포인트이고, 그래서 **이 생성기에
확장 이름이 나오지 않는다** (ADR-0018). 확장이 소유한 계약은 그 확장 폴더에 있어야 한다
(계약 README 원칙 1).
"""

from __future__ import annotations

import json
import sys
from importlib import import_module
from importlib.metadata import entry_points
from importlib.resources import files
from pathlib import Path
from typing import Any

from chaeksas.contracts import (
    AdminKeyCreated,
    AdminKeyCreateRequest,
    AdminKeyInfo,
    AdminStatus,
    AnswerRequest,
    ApprovalCreateRequest,
    ApprovalInfo,
    BotUiInfo,
    CaseFile,
    Catalog,
    CenterKeyCreated,
    CenterKeyCreateRequest,
    CenterKeyInfo,
    ContributedResource,
    DependentInfo,
    DeploymentClaim,
    DeploymentInfo,
    Envelope,
    ErrorBody,
    EventBatchResponse,
    ExtensionClaim,
    ExtensionManifest,
    ExtensionResource,
    HealthResponse,
    HeartbeatRequest,
    HeartbeatResponse,
    JobCreateRequest,
    JobInfo,
    Manifest,
    OpRequest,
    OpResponse,
    PackageClaim,
    PackageInfo,
    RegisterRequest,
    RegisterResponse,
    ReplayMemory,
    RunEvent,
    RunEventsResponse,
    RunInfo,
    RunListing,
    RuntimeResource,
    ServiceAppManifest,
    ServiceAppResource,
    ToolpackResource,
    UsagePage,
)

# Windows 콘솔·파이프의 기본 코드페이지(cp949·cp1252)에서는 한글을 찍다 터진다.
# 이 도구들은 한글로 말하므로 stdout을 UTF-8로 고정한다 (CI의 Windows에서 실제로 터졌다).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "packages" / "contracts" / "schemas"

#: 확장을 찾는 엔트리 포인트 (확장 호스트와 같은 것).
EXTENSION_GROUP = "chaeksas.extensions"
#: 확장 패키지 안에서 스키마를 둘 폴더 이름.
EXTENSION_SCHEMA_DIR = "schemas"

# (파일 이름, 모델) — 이름 앞에 계약 번호를 붙여 문서에서 찾기 쉽게 한다.
MODELS: list[tuple[str, Any]] = [
    ("c1-manifest", Manifest),
    # C2: 봉투는 payload를 dict로 두므로(바이트 보존), claim 모양은 따로 내보낸다.
    ("c2-envelope", Envelope),
    ("c2-claim-deployment", DeploymentClaim),
    ("c2-claim-package", PackageClaim),
    ("c2-claim-extension", ExtensionClaim),
    ("c3-run-event", RunEvent),
    ("c3-event-batch-response", EventBatchResponse),
    ("c3-run-info", RunInfo),
    ("c3-run-listing", RunListing),
    ("c3-run-events-response", RunEventsResponse),
    ("c4-register-request", RegisterRequest),
    ("c4-register-response", RegisterResponse),
    ("c4-heartbeat-request", HeartbeatRequest),
    ("c4-heartbeat-response", HeartbeatResponse),
    ("c5-package-info", PackageInfo),
    ("c5-dependent-info", DependentInfo),
    ("c5-bot-ui-info", BotUiInfo),
    ("c5-deployment-info", DeploymentInfo),
    ("c5-job-create-request", JobCreateRequest),
    ("c5-job-info", JobInfo),
    ("c5-error-body", ErrorBody),  # C11과 같은 오류 형식
    ("c6-approval-create-request", ApprovalCreateRequest),
    ("c6-approval-info", ApprovalInfo),
    ("c6-answer-request", AnswerRequest),
    ("c7-extension-resource", ExtensionResource),
    ("c7-service-app-resource", ServiceAppResource),
    ("c7-contributed-resource", ContributedResource),
    ("c7-toolpack-resource", ToolpackResource),
    ("c7-runtime-resource", RuntimeResource),
    ("c7-center-key-create-request", CenterKeyCreateRequest),
    ("c7-center-key-info", CenterKeyInfo),
    ("c7-center-key-created", CenterKeyCreated),
    ("c11-service-app-manifest", ServiceAppManifest),
    ("c11-op-request", OpRequest),
    ("c11-op-response", OpResponse),
    ("c11-health-response", HealthResponse),
    ("c11-admin-status", AdminStatus),
    ("c11-admin-key-create-request", AdminKeyCreateRequest),
    ("c11-admin-key-created", AdminKeyCreated),
    ("c11-admin-key-info", AdminKeyInfo),
    ("c11-usage-page", UsagePage),
    ("c13-extension-manifest", ExtensionManifest),
    ("c13-catalog", Catalog),
    ("c14-case-file", CaseFile),
    ("c14-replay-memory", ReplayMemory),
]


def rendered(name: str, model: Any) -> str:
    schema = model.model_json_schema(by_alias=True)
    schema["$id"] = f"urn:chaeksas:contracts:{name}"
    return json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def extension_models() -> list[tuple[Path, str, Any]]:
    """설치된 확장이 내보낼 계약 — `(폴더, 이름, 모델)`.

    확장을 **엔트리 포인트로** 찾는다 (호스트와 같은 길). `contracts.SCHEMA_MODELS`가 없거나
    읽을 수 없으면 **그 확장만 건너뛰고 말한다** — 생성기가 멈추지 않는다.
    """
    out: list[tuple[Path, str, Any]] = []
    for ep in sorted(entry_points(group=EXTENSION_GROUP), key=lambda e: e.name):
        module = f"{ep.value}.contracts"
        try:
            found = getattr(import_module(module), "SCHEMA_MODELS", None)
        except ModuleNotFoundError:
            continue
        if not found:
            continue
        try:
            where = Path(str(files(ep.value))) / EXTENSION_SCHEMA_DIR
        except (ModuleNotFoundError, TypeError) as e:  # pragma: no cover - 설치가 깨진 경우
            print(f"경고: {ep.name}의 패키지 자리를 찾지 못했다 ({e}) — 건너뛴다")
            continue
        out += [(where, name, model) for name, model in found.items()]
    return out


def outputs() -> dict[Path, str]:
    out: dict[Path, str] = {}
    for name, model in MODELS:
        out[OUT_DIR / f"{name}.json"] = rendered(name, model)
    for where, name, model in extension_models():
        out[where / f"{name}.json"] = rendered(name, model)
    return out


def schema_dirs() -> list[Path]:
    """생성물이 사는 폴더들 — 버려진 파일을 찾을 때 쓴다."""
    return [OUT_DIR, *sorted({where for where, _, _ in extension_models()})]


def main() -> int:
    check = "--check" in sys.argv
    out = outputs()
    existing = {p for where in schema_dirs() if where.exists() for p in where.glob("*.json")}
    orphans = sorted(existing - set(out))

    if check:
        stale = [p for p, t in out.items() if not p.exists() or p.read_text(encoding="utf-8") != t]
        for p in [*stale, *orphans]:
            print("다름:", p.relative_to(ROOT))
        return 1 if (stale or orphans) else 0

    for where in schema_dirs():
        where.mkdir(parents=True, exist_ok=True)
    for p in orphans:
        p.unlink()
        print("지움:", p.relative_to(ROOT))
    for p, text in out.items():
        p.write_text(text, encoding="utf-8", newline="\n")
    places = ", ".join(sorted(where.relative_to(ROOT).as_posix() for where in schema_dirs()))
    print(f"스키마 {len(out)}개 → {places}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
