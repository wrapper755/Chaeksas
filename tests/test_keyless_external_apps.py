"""키를 받지 않는 외부 앱 (ADR-0091).

보는 것:

1. **정의가 스스로 어긋나지 않는다** — `requires_keys`에 `run`이 있으면 `adapter.auth`도 있다 (E3).
   Center 등록·STU-15 「정의 파일 열기」가 같은 `validate()`를 쓴다.
2. **판단은 하나다** (`takes_key`) — `auth`가 없는 외부 앱은 키를 받지 않고, C11은 늘 받는다.
3. **키를 받지 않는 앱은 키를 묻는 자리에서 빠진다** — B7·매니페스트 `key_ref`·사전 점검. 목록을
   **주지 않으면** 지금처럼 모든 앱에 묻는다 (모르는 것으로 풀어 주지 않는다).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from chaeksas.contracts.bpmn_ext import read_process
from chaeksas.contracts.bpmn_ext import validate as validate_bpmn
from chaeksas.contracts.extension import ExtensionManifest, takes_key
from chaeksas.contracts.extension import validate as validate_extension
from chaeksas.contracts.manifest import validate as validate_manifest
from chaeksas.core import preflight
from chaeksas.studio import service_catalog
from chaeksas.studio.packaging import build_manifest
from chaeksas.studio.workspace import Workspace

EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples" / "bpmn"
#: 외부 앱 `ext-credit`을 `chk:process.service_keys`로 부르는 예제.
CREDIT = "bx06_bulk_credit_check"
APP = "ext-credit"


def external(*, auth: bool, run_key: bool) -> dict[str, Any]:
    adapter: dict[str, Any] = {
        "allowed_hosts": ["credit.example.com"],
        "operations": [
            {
                "name": "score",
                "modes": ["deterministic"],
                "request": {"method": "POST", "path": "/score", "body": {"no": "{{input.no}}"}},
                "response": {"output": {"score": "$.score"}},
            }
        ],
    }
    if auth:
        adapter["auth"] = {"type": "bearer"}
    definition: dict[str, Any] = {
        "schema": 2,
        "id": APP,
        "version": "1.0.0",
        "name": "외부 신용",
        "publisher": "외부 업체",
        "tier": "external",
        "service": {"protocol": "http-adapter", "base_url": "https://credit.example.com", "adapter": adapter},
    }
    if run_key:
        definition["requires_keys"] = [{"purpose": "run"}]
    return definition


def manifest_of(definition: dict[str, Any]) -> ExtensionManifest:
    return ExtensionManifest.model_validate(definition)


# ─────────────────────────── 정의 (C13) ───────────────────────────


def test_a_run_key_without_auth_is_refused() -> None:
    """키를 받는다고 적고 실을 자리를 두지 않으면 거부한다 — 어댑터는 보내지 않는데 점검은 요구한다."""
    found = validate_extension(manifest_of(external(auth=False, run_key=True)))
    assert [(v.rule, v.code) for v in found] == [("E3", "adapter_invalid")]
    assert found[0].items == ["service.adapter.auth"], "칸별 사유를 준다 (CON-07이 그대로 보인다)"


@pytest.mark.parametrize(("auth", "run_key"), [(True, True), (False, False), (True, False)])
def test_the_other_three_shapes_pass(auth: bool, run_key: bool) -> None:
    assert validate_extension(manifest_of(external(auth=auth, run_key=run_key))) == []


def test_takes_key_is_decided_by_auth() -> None:
    assert takes_key(manifest_of(external(auth=True, run_key=True)))
    assert not takes_key(manifest_of(external(auth=False, run_key=False)))


def test_the_catalog_carries_it() -> None:
    """Studio가 아는 길은 STU-14의 고를 거리다 — 외부 앱 줄이 `auth` 유무를 들고 온다."""
    keyless = service_catalog.build(externals=[manifest_of(external(auth=False, run_key=False))])
    keyed = service_catalog.build(externals=[manifest_of(external(auth=True, run_key=True))])
    assert keyless.keyless_ids() == (APP,)
    assert keyed.keyless_ids() == ()
    assert service_catalog.Catalog().keyless_ids() == (), "받지 못했으면 비어 있다 — 모두에 묻는다"


# ─────────────────────────── B7 (C14) ───────────────────────────


def drawing_without_keys() -> Any:
    xml = (EXAMPLES / f"{CREDIT}.bpmn").read_text(encoding="utf-8")
    process = read_process(xml)
    process.info.service_keys = {}
    return process


def test_b7_asks_every_app_when_it_is_not_told() -> None:
    assert any(v.rule == "B7" for v in validate_bpmn(drawing_without_keys()))


def test_b7_does_not_ask_an_app_that_takes_no_key() -> None:
    found = validate_bpmn(drawing_without_keys(), keyless_apps={APP})
    assert not any(v.rule == "B7" for v in found)


# ─────────────────────────── 매니페스트 (C1) · 사전 점검 ───────────────────────────


@pytest.fixture
def space(tmp_path: Path) -> Workspace:
    return Workspace(tmp_path / "작업").ensure()


def test_the_build_writes_no_key_reference_for_it(space: Workspace) -> None:
    process = space.import_example(EXAMPLES, CREDIT)

    keyed = build_manifest(process)
    [need] = keyed.requires.service_apps
    assert need.key_ref, "목록을 주지 않으면 지금처럼 적는다"

    built = build_manifest(process, keyless_apps={APP})
    [need] = built.requires.service_apps
    assert (need.app_id, need.key_ref, need.task_key_refs) == (APP, None, [])
    assert need.operations, "부르는 작업은 그대로 적는다"
    dumped: Any = built.to_json_dict()
    assert "key_ref" not in dumped["requires"]["service_apps"][0]
    assert not [v for v in validate_manifest(built) if v.rule == "R4"], "적지 않은 참조는 R4가 묻지 않는다"


def test_the_preflight_asks_for_no_value(space: Workspace) -> None:
    """사전 점검·BUI-10은 `key_apps_of()`로 매니페스트를 읽는다 — 따로 고치지 않아도 빠진다."""
    process = space.import_example(EXAMPLES, CREDIT)
    nothing = lambda _ref: None  # noqa: E731
    assert preflight.check(build_manifest(process), key_value=nothing).missing_key_refs
    built = build_manifest(process, keyless_apps={APP})
    assert preflight.key_apps_of(built) == {}
    assert preflight.check(built, key_value=nothing).missing_key_refs == ()
