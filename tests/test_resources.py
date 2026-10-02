"""C7 리소스 — 누락 검사와 버전 범위.

`missing()`은 C1 `requires`를 Center 리소스 목록과 대조한다. **확장 종류를 가리지 않는
같은 규칙**이어야 하므로(ADR-0018), 내장이든 외부든 같은 경로로 검사되는지 본다.
"""

from __future__ import annotations

from typing import Any

import pytest

from chaeksas.contracts import (
    ExtensionResource,
    Manifest,
    Operation,
    ResourceIndex,
    ResourceList,
    ServiceAppResource,
    ToolpackResource,
    blocking_at_deploy,
    missing,
)
from chaeksas.contracts._semver import InvalidVersion, compare, satisfies

NOW = "2026-10-01T10:00:00+09:00"
HASH = "sha256:" + "ab" * 32


def manifest(**over: Any) -> Manifest:
    base: dict[str, Any] = {
        "schema": 1,
        "kind": "bpm_process",
        "id": "erp.order-entry",
        "version": "2.1.0",
        "run_location": "pc",
        "entry": "process/main.bpmn",
        "process_id": "order_entry",
        "requires": {},
        "human": {},
        "built": {"by": "studio", "at": NOW, "core": "0.3.0", "spec_version": 1},
        "content_hash": HASH,
    }
    return Manifest.model_validate(base | over)


def index(**over: Any) -> ResourceIndex:
    return ResourceIndex.model_validate(over)


def ui_automation(version: str = "0.4.2", **over: Any) -> ExtensionResource:
    base: dict[str, Any] = {"id": "ui-automation", "version": version, "tier": "builtin",
                            "protocol": "chk-c11", "service_app_id": "ui-automation"}
    return ExtensionResource.model_validate(base | over)


def app(*ops: Operation, app_id: str = "ui-automation") -> ServiceAppResource:
    return ServiceAppResource(app_id=app_id, operations=list(ops))


def op(name: str, *, modes: list[str] | None = None, server_ok: bool = True) -> Operation:
    return Operation(name=name, modes=modes if modes is not None else ["deterministic"], server_ok=server_ok)


# ─────────────── 버전 범위 (SemVer) ───────────────


def test_version_ranges() -> None:
    assert satisfies("0.4.2", ">=0.4,<0.5")
    assert not satisfies("0.5.0", ">=0.4,<0.5")
    assert not satisfies("0.3.9", ">=0.4,<0.5")
    assert satisfies("1.0.0", "")  # 빈 범위는 제한 없음
    assert satisfies("1.2.3", "==1.2.3")
    assert satisfies("1.2.3", "1.2.3")  # 연산자를 적지 않으면 ==
    assert satisfies("2.0.0", "!=1.0.0")


def test_partial_versions_in_ranges() -> None:
    """`>=1,<2`처럼 짧게 적어도 된다 (C13 `api` 필드가 이렇게 쓴다)."""
    assert satisfies("1.5.9", ">=1,<2")
    assert not satisfies("2.0.0", ">=1,<2")
    assert satisfies("0.4.0", ">=0.4")


def test_prerelease_is_lower_than_release() -> None:
    """SemVer 우선순위 — `1.0.0-rc.1`은 `1.0.0`보다 낮다."""
    assert compare("1.0.0-rc.1", "1.0.0") == -1
    assert compare("1.0.0", "1.0.0+build.5") == 0  # 빌드 메타데이터는 무시
    assert compare("1.0.0-alpha", "1.0.0-beta") == -1
    assert compare("1.0.0-rc.1", "1.0.0-rc.2") == -1
    assert compare("1.0.0-1", "1.0.0-alpha") == -1  # 숫자 식별자가 더 낮다
    # 그래서 사전 배포는 `>=1.0.0`을 만족하지 않는다
    assert not satisfies("1.0.0-rc.1", ">=1.0.0")


def test_bad_version_is_reported() -> None:
    with pytest.raises(InvalidVersion):
        compare("1.0", "butter")
    with pytest.raises(InvalidVersion):
        satisfies("1.0.0", ">=일")


# ─────────────── 누락 검사 ───────────────


def test_nothing_required_nothing_missing() -> None:
    assert missing(manifest(), index()) == []


def test_extension_not_found() -> None:
    m = manifest(requires={"extensions": [{"id": "ui-automation", "version": ">=0.4,<0.5"}]})
    assert [(x.type, x.reason) for x in missing(m, index())] == [("extension", "not_found")]


def test_extension_version_mismatch() -> None:
    m = manifest(requires={"extensions": [{"id": "ui-automation", "version": ">=0.4,<0.5"}]})
    have = index(extensions=[ui_automation("0.5.1")])
    assert [(x.type, x.reason) for x in missing(m, have)] == [("extension", "version_mismatch")]
    assert missing(m, index(extensions=[ui_automation("0.4.9")])) == []


def test_external_extension_definition_is_pinned_by_hash() -> None:
    """외부 확장은 정의를 해시로 고정한다 — 바뀌면 누락으로 잡는다 (C13)."""
    m = manifest(requires={"extensions": [
        {"id": "ext-ocr", "version": ">=1,<2", "definition_hash": "sha256:aaa"}]})
    have = index(extensions=[ExtensionResource(
        id="ext-ocr", version="1.2.0", tier="external", protocol="http-adapter",
        definition_hash="sha256:bbb")])
    assert [(x.type, x.reason) for x in missing(m, have)] == [("extension", "hash_mismatch")]


def test_bad_version_range_counts_as_mismatch_not_a_crash() -> None:
    m = manifest(requires={"extensions": [{"id": "ui-automation", "version": "최신"}]})
    assert [x.reason for x in missing(m, index(extensions=[ui_automation()]))] == ["version_mismatch"]


def test_service_app_not_registered() -> None:
    m = manifest(requires={"service_apps": [
        {"app_id": "tax-invoice", "operations": ["issue"], "key_ref": "fin"}]})
    assert [(x.type, x.reason) for x in missing(m, index())] == [("service_app", "not_registered")]


def test_operation_not_found() -> None:
    m = manifest(requires={"service_apps": [
        {"app_id": "ui-automation", "operations": ["plan", "heal"], "key_ref": "erp"}]})
    have = index(service_apps=[app(op("plan"))])
    v = missing(m, have)
    assert [(x.type, x.id, x.reason) for x in v] == [("operation", "ui-automation.heal", "not_found")]


def test_operation_must_support_deterministic() -> None:
    """실행하는 쪽(Bot UI·서버 실행기)은 결정 수행으로 부른다."""
    m = manifest(requires={"service_apps": [
        {"app_id": "ui-automation", "operations": ["plan"], "key_ref": "erp"}]})
    have = index(service_apps=[app(op("plan", modes=["autonomous"]))])
    assert [x.reason for x in missing(m, have)] == ["not_deterministic"]


def test_server_ok_is_only_required_for_server_processes() -> None:
    """C1 R8 — 서버 BPM 프로세스는 `server_ok` 작업만 부를 수 있다."""
    requires = {"service_apps": [{"app_id": "ui-automation", "operations": ["plan"], "key_ref": "erp"}]}
    have = index(service_apps=[app(op("plan", server_ok=False))])

    assert missing(manifest(run_location="pc", requires=requires), have) == []  # PC는 상관없다
    v = missing(manifest(run_location="server", requires=requires, human={}), have)
    assert [x.reason for x in v] == ["not_server_ok"]


def test_contributed_resource_not_found() -> None:
    m = manifest(requires={"resources": [{"type": "ui_page", "id": "erp.order.form"}]})
    v = missing(m, index())
    assert [(x.type, x.id, x.reason) for x in v] == [("resource", "ui_page:erp.order.form", "not_found")]


def test_contributed_resource_found() -> None:
    m = manifest(requires={"resources": [{"type": "ui_page", "id": "erp.order.form"}]})
    have = index(contributed=[{"resource_type": "ui_page", "id": "erp.order.form",
                               "extension_id": "ui-automation", "revision": 482}])
    assert missing(m, have) == []


def test_toolpack_checks() -> None:
    m = manifest(requires={"toolpacks": [{"id": "doc", "version": "1.0.0", "content_hash": HASH}]})
    assert [x.reason for x in missing(m, index())] == ["not_found"]

    other = "sha256:" + "cd" * 32
    have = index(toolpacks=[ToolpackResource(id="doc", version="1.0.0", status="approved", content_hash=other)])
    assert [x.reason for x in missing(m, have)] == ["hash_mismatch"]

    have = index(toolpacks=[ToolpackResource(id="doc", version="1.0.0", status="candidate", content_hash=HASH)])
    assert [x.reason for x in missing(m, have)] == ["not_approved"]

    have = index(toolpacks=[ToolpackResource(id="doc", version="1.0.0", status="approved", content_hash=HASH)])
    assert missing(m, have) == []


def test_several_misses_are_all_reported() -> None:
    m = manifest(requires={
        "extensions": [{"id": "ui-automation", "version": ">=0.4,<0.5"}],
        "service_apps": [{"app_id": "tax-invoice", "operations": ["issue"], "key_ref": "fin"}],
        "resources": [{"type": "ui_page", "id": "erp.order.form"}],
    })
    assert [x.type for x in missing(m, index())] == ["extension", "service_app", "resource"]


# ─────────────── 업로드 경고 vs 배포 거부 ───────────────


def test_only_some_misses_block_deployment() -> None:
    """서비스 앱이 잠시 응답이 없다고 배포를 막지는 않는다 (업로드는 경고만)."""
    m = manifest(
        run_location="server",
        human={},
        requires={
            "extensions": [{"id": "ui-automation", "version": ">=0.4,<0.5"}],
            "service_apps": [{"app_id": "svc", "operations": ["a", "b"], "key_ref": "k"}],
            "resources": [{"type": "ui_page", "id": "p"}],
        },
    )
    have = index(service_apps=[app(op("a", server_ok=False), op("b"), app_id="svc")])
    all_misses = missing(m, have)
    assert [(x.type, x.reason) for x in all_misses] == [
        ("extension", "not_found"),
        ("operation", "not_server_ok"),
        ("resource", "not_found"),
    ]
    # 배포를 막는 것은 확장 누락과 R8(서버에서 못 쓰는 작업)뿐이다.
    assert [(x.type, x.reason) for x in blocking_at_deploy(all_misses)] == [
        ("extension", "not_found"),
        ("operation", "not_server_ok"),
    ]


def test_hash_mismatch_always_blocks() -> None:
    m = manifest(requires={"toolpacks": [{"id": "doc", "version": "1.0.0", "content_hash": HASH}]})
    other = "sha256:" + "cd" * 32
    have = index(toolpacks=[ToolpackResource(id="doc", version="1.0.0", status="approved", content_hash=other)])
    assert [x.reason for x in blocking_at_deploy(missing(m, have))] == ["hash_mismatch"]


def test_not_registered_does_not_block() -> None:
    m = manifest(requires={"service_apps": [{"app_id": "svc", "operations": [], "key_ref": "k"}]})
    assert blocking_at_deploy(missing(m, index())) == []


# ─────────────── 목록 응답 ───────────────


def test_resource_list_is_typed() -> None:
    lst = ResourceList[ServiceAppResource].model_validate(
        {"items": [{"app_id": "tax-invoice", "status": "ok"}], "fetched_at": NOW}
    )
    assert isinstance(lst.items[0], ServiceAppResource)
    assert lst.items[0].status == "ok"


def test_center_does_not_interpret_contributed_data() -> None:
    """`data`의 모양은 확장이 정한다 — 플랫폼은 그대로 보관해 Studio에 넘긴다."""
    have = index(contributed=[{"resource_type": "ui_page", "id": "p",
                               "data": {"무엇이든": {"깊게": [1, 2, 3]}}}])
    assert have.contributed[0].data["무엇이든"]["깊게"] == [1, 2, 3]
