"""계약 문서의 JSON 예시가 모델로 그대로 읽히는지.

계약 README의 교훈: 프로토타입에서 **문서와 코드가 달랐다**(`X-Bot-Id` 헤더 vs `?bot_id=`,
`{"events": […]}` vs 배열) → "명세에서 예시 요청을 테스트로 돌린다".
그래서 이 테스트는 예시를 복사하지 않고 **문서에서 뽑아** 검증한다. 문서를 고치면 여기가 깨진다.

문서의 예시는 읽기 쉽게 해시를 `sha256:9f2c…`처럼 줄여 쓰므로, 검증 전에 늘린다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter

from chaeksas.contracts import (
    ApprovalCreateRequest,
    Catalog,
    Envelope,
    EventBatchResponse,
    ExtensionManifest,
    HeartbeatRequest,
    HeartbeatResponse,
    Manifest,
    RunEvent,
)

DOCS = Path(__file__).resolve().parent.parent / "docs" / "03-contracts"

# (문서, 예시 번호, 모델) — 번호는 문서에 나오는 순서. 예시를 더하면 여기도 더한다.
EXAMPLES: list[tuple[str, int, Any]] = [
    ("C1-package-manifest", 0, Manifest),  # 서버 Bot
    ("C1-package-manifest", 1, Manifest),  # PC Bot
    ("C2-signing-envelope", 0, Envelope),  # 배포 봉투
    ("C3-run-events", 0, TypeAdapter(list[RunEvent])),  # 이벤트 배치
    ("C3-run-events", 1, EventBatchResponse),  # 응답
    ("C4-bot-ui-center", 0, HeartbeatRequest),
    ("C4-bot-ui-center", 1, HeartbeatResponse),
    ("C6-approvals", 0, ApprovalCreateRequest),
    ("C13-extension-manifest", 0, Catalog),  # 공통 카탈로그 형식
    ("C13-extension-manifest", 1, ExtensionManifest),  # 내장 확장
    ("C13-extension-manifest", 2, ExtensionManifest),  # 외부 확장
]


def json_blocks(doc: str) -> list[str]:
    text = (DOCS / f"{doc}.md").read_text(encoding="utf-8")
    return re.findall(r"```json\n(.*?)```", text, re.S)


def expand_abbreviations(raw: str) -> str:
    """문서가 읽기 쉽게 줄여 쓴 값을 늘린다 (`sha256:9f2c…` → 64자, `"…"` 자리 제거·채우기)."""
    raw = re.sub(r'"sha256:([0-9a-f]*)…"', lambda m: '"sha256:' + (m.group(1) + "0" * 64)[:64] + '"', raw)
    # 시간 칸의 생략 표시는 지울 수 없다 (시간대까지 있어야 통과한다) — 실제 값으로 채운다.
    raw = re.sub(r'"(\w*(?:_at|At))":\s*"…"', r'"\1": "2026-10-01T09:00:00+09:00"', raw)
    raw = re.sub(r',?\s*"…"\s*:\s*"[^"]*"', "", raw)  # 생략 표시 칸 (앞 쉼표까지)
    raw = re.sub(r'"sig":\s*"…"', '"sig": "QUJD"', raw)
    return raw


@pytest.mark.parametrize(("doc", "index", "model"), EXAMPLES, ids=[f"{d}[{i}]" for d, i, _ in EXAMPLES])
def test_doc_example_parses(doc: str, index: int, model: Any) -> None:
    blocks = json_blocks(doc)
    assert index < len(blocks), f"{doc}에 예시 {index}가 없다 (있는 것: {len(blocks)}개)"
    payload = json.loads(expand_abbreviations(blocks[index]))
    parsed = model.validate_python(payload) if isinstance(model, TypeAdapter) else model.model_validate(payload)
    assert parsed is not None


def test_every_json_example_is_covered() -> None:
    """문서에 예시를 더하면 위 표에도 더해야 한다 (조용히 빠지지 않게)."""
    for doc in {d for d, _, _ in EXAMPLES}:
        found = len(json_blocks(doc))
        covered = sum(1 for d, _, _ in EXAMPLES if d == doc)
        assert found == covered, f"{doc}: 문서에 예시 {found}개, 표에 {covered}개"


def test_c1_example_passes_validate() -> None:
    """C1 예시 두 개는 검사 규칙을 통과해야 한다 (R1·R2·R4·R7)."""
    from chaeksas.contracts import validate

    for index in (0, 1):
        m = Manifest.model_validate(json.loads(expand_abbreviations(json_blocks("C1-package-manifest")[index])))
        assert validate(m) == [], f"예시 {index}가 검사에 걸렸다: {[str(v) for v in validate(m)]}"


def test_c2_example_payload_reads_as_a_deployment_claim() -> None:
    """봉투 예시의 `payload`가 claim 모델과 맞는지 (`target`·`not_before: null` 포함)."""
    from chaeksas.contracts import DeploymentClaim, parse_claim

    env = Envelope.model_validate(json.loads(expand_abbreviations(json_blocks("C2-signing-envelope")[0])))
    claim = parse_claim(env)
    assert isinstance(claim, DeploymentClaim)
    assert claim.target.type == "bot_ui"
    assert claim.not_before is None


def test_c13_examples_pass_validate() -> None:
    """C13 예시 둘은 검사 규칙(E1·E3·모양)을 통과하고, 내장 쪽은 api 범위도 맞아야 한다."""
    from chaeksas.contracts import check_extension_api, validate_extension
    from chaeksas.extension_api import API_VERSION

    blocks = json_blocks("C13-extension-manifest")
    builtin = ExtensionManifest.model_validate(json.loads(expand_abbreviations(blocks[1])))
    external = ExtensionManifest.model_validate(json.loads(expand_abbreviations(blocks[2])))
    for m in (builtin, external):
        assert validate_extension(m) == [], f"{m.id}: {[str(v) for v in validate_extension(m)]}"
    assert check_extension_api(builtin, api_version=API_VERSION) == []


def test_c3_example_data_keys_are_complete() -> None:
    """C3 예시의 이벤트는 종류별 `data` 필수 키를 모두 갖고 있어야 한다."""
    from chaeksas.contracts import missing_data_keys

    events = TypeAdapter(list[RunEvent]).validate_python(json.loads(json_blocks("C3-run-events")[0]))
    for e in events:
        assert missing_data_keys(e) == [], f"{e.kind}(seq {e.seq})에 빠진 키: {missing_data_keys(e)}"
