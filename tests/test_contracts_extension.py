"""C13 확장 정의 — 모델과 검사 규칙 E1~E6.

문서의 JSON 예시는 `test_contract_examples.py`가 **문서에서 뽑아** 검증한다. 여기서는 규칙마다
걸리는 경우를 만들어 본다.
"""

from __future__ import annotations

import base64
import json
from typing import Any, cast

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from chaeksas.contracts import (
    AdminKey,
    Catalog,
    ExtensionManifest,
    check_extension_api,
    check_extension_size,
    definition_hash,
    key_id_for,
    sign,
    task_type_conflicts,
    validate_extension,
    verify_external,
)
from chaeksas.contracts.extension import MAX_DEFINITION_BYTES

NOW = "2026-10-02T09:00:00+09:00"


def builtin(**over: Any) -> dict[str, Any]:
    """내장 확장 정의 하나 (검사를 통과하는 최소 모양)."""
    base: dict[str, Any] = {
        "schema": 2,
        "id": "doc-ocr",
        "version": "1.2.0",
        "name": "문서 인식",
        "publisher": "Chaeksas",
        "tier": "builtin",
        "api": ">=1,<2",
        "contributes": {
            "task_types": [
                {
                    "id": "ocr_task",
                    "label": "문서 인식",
                    "executor": {"entry": "doc_ocr.client:OcrExecutor"},
                    "run_locations": ["pc", "server"],
                }
            ]
        },
    }
    base.update(over)
    return base


def external(**over: Any) -> dict[str, Any]:
    """외부 확장 정의 하나 (HTTP 어댑터)."""
    base: dict[str, Any] = {
        "schema": 2,
        "id": "ext-ocr",
        "version": "1.0.0",
        "name": "외부 OCR",
        "publisher": "외부 업체",
        "tier": "external",
        "service": {
            "protocol": "http-adapter",
            "base_url": "https://ocr.example.com",
            "adapter": {
                "allowed_hosts": ["ocr.example.com"],
                "auth": {"type": "bearer"},
                "operations": [
                    {
                        "name": "read_invoice",
                        "request": {"method": "POST", "path": "/v2/invoice", "body": {"url": "{{input.file_url}}"}},
                        "response": {"output": {"biz_no": "$.result.bizNo"}},
                    }
                ],
            },
        },
    }
    base.update(over)
    return base


def parse(definition: dict[str, Any]) -> ExtensionManifest:
    return ExtensionManifest.model_validate(definition)


def dumped_contributes(m: ExtensionManifest) -> dict[str, Any]:
    return cast(dict[str, Any], m.to_json_dict()["contributes"])


def codes(definition: dict[str, Any], **kw: Any) -> list[str]:
    return [v.code or v.rule for v in validate_extension(parse(definition), **kw)]


# ─────────────────────────── 모델 ───────────────────────────


def test_minimal_definitions_pass() -> None:
    assert validate_extension(parse(builtin())) == []
    assert validate_extension(parse(external())) == []


def test_contributes_keys_keep_the_dotted_names() -> None:
    """`studio.editors`처럼 점이 든 열쇠 그대로 읽고 다시 쓴다 (문서와 같은 모양)."""
    m = parse(builtin(contributes={"studio.resource_views": [{"id": "v", "label": "보기", "resource_type": "page"}]}))
    assert [v.id for v in m.contributes.studio_resource_views] == ["v"]
    assert "studio.resource_views" in dumped_contributes(m)


def test_unknown_contributes_key_is_kept_not_rejected() -> None:
    """모르는 기여 지점은 거부하지 않고 보관한다 (C13 호환 규칙 + 계약 원칙 3)."""
    m = parse(builtin(contributes={"future.thing": [{"id": "x"}]}))
    assert validate_extension(m) == []
    assert dumped_contributes(m)["future.thing"] == [{"id": "x"}]


def test_higher_schema_is_refused() -> None:
    with pytest.raises(ValueError, match="모르는"):
        parse(builtin(schema=3))


def test_bad_id_is_refused() -> None:
    for bad in ("UI", "1-ui", "ui_automation", "u", "x" * 51):
        with pytest.raises(ValueError):
            parse(builtin(id=bad))


def test_definition_hash_is_canonical_json_of_what_came_in() -> None:
    """모르는 필드까지 든 **받은 그대로**를 해시한다 (서명이 맞아야 한다)."""
    definition = builtin(unknown_field="keep me")
    reordered = dict(reversed(list(definition.items())))
    assert definition_hash(definition) == definition_hash(reordered)
    assert definition_hash(definition) != definition_hash(builtin())
    assert definition_hash(definition).startswith("sha256:")


def test_contributes_summary_lists_ids_for_c7() -> None:
    m = parse(builtin())
    assert m.contributes_summary() == {"task_types": ["ocr_task"]}


def test_catalog_is_schema_versioned() -> None:
    cat = Catalog.model_validate({"schema": 1, "revision": 7, "items": [{"type": "ui_page", "id": "a.b"}]})
    assert cat.revision == 7 and cat.items[0].type == "ui_page"


# ─────────────────────────── E1 ───────────────────────────


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("task_types", [{"id": "t", "label": "t", "run_locations": ["pc"]}]),
        ("studio.editors", [{"task_type": "t", "entry": "x:Y"}]),
        ("bot_ui.utilities", [{"id": "u", "label": "u", "entry": "x:Y"}]),
        ("bot_ui.local_runtimes", [{"id": "r", "label": "r", "entry": "x:Y"}]),
        ("configuration", [{"key": "k", "label": "k", "scope": "bot_ui"}]),
        ("preflight", [{"id": "p", "entry": "x:Y"}]),
        ("agent_environments", [{"domain": "desktop", "entry": "x:Y"}]),
        ("bot_ui.panels", [{"id": "p", "label": "p", "surface": "bot_ui.runtimes", "entry": "x:Y"}]),
        ("console.pages", [{"id": "c", "label": "c", "module": "m"}]),
    ],
)
def test_e1_external_cannot_contribute_code(key: str, value: list[dict[str, Any]]) -> None:
    assert "external_code_not_allowed" in codes(external(contributes={key: value}))


def test_e1_external_may_declare_views_and_resources() -> None:
    """선언만으로 되는 둘은 외부 확장도 쓴다."""
    definition = external(
        contributes={
            "studio.resource_views": [{"id": "v", "label": "보기", "resource_type": "doc"}],
            "resources": [{"type": "doc", "label": "문서", "catalog_url": "/v1/catalog"}],
        }
    )
    assert validate_extension(parse(definition)) == []


# ─────────────────────────── E2 ───────────────────────────


def test_e2_builtin_cannot_arrive_from_center() -> None:
    """내장·사내 확장은 설치 파일에 든 것만 쓴다 (ADR-0018 §3)."""
    assert "id_conflict" in codes(builtin(), from_center=True)
    assert "id_conflict" not in codes(external(), from_center=True)


# ─────────────────────────── E3 ───────────────────────────


def adapter_codes(**adapter_over: Any) -> list[str]:
    definition = external()
    definition["service"]["adapter"].update(adapter_over)
    return codes(definition)


def op_codes(**op_over: Any) -> list[str]:
    definition = external()
    definition["service"]["adapter"]["operations"][0].update(op_over)
    return codes(definition)


def test_e3_requires_allowed_hosts() -> None:
    assert "adapter_invalid" in adapter_codes(allowed_hosts=[])


def test_e3_wildcard_host_is_refused() -> None:
    assert "adapter_invalid" in adapter_codes(allowed_hosts=["*.example.com"])


def test_e3_base_url_must_be_https_and_allowed() -> None:
    definition = external()
    definition["service"]["base_url"] = "http://ocr.example.com"
    assert "adapter_invalid" in codes(definition)

    definition = external()
    definition["service"]["base_url"] = "https://evil.example.net"
    assert "adapter_invalid" in codes(definition)


def test_e3_http_is_only_for_declared_private_network() -> None:
    definition = external()
    definition["service"]["base_url"] = "http://ocr.example.com"
    definition["service"]["adapter"]["allow_private_network"] = True
    assert validate_extension(parse(definition)) == []


def test_e3_protocol_and_adapter_must_match() -> None:
    definition = external()
    definition["service"]["protocol"] = "chk-c11"
    assert "adapter_invalid" in codes(definition)

    definition = external()
    del definition["service"]["adapter"]
    assert "adapter_invalid" in codes(definition)


def test_e3_path_must_start_with_slash() -> None:
    assert "adapter_invalid" in op_codes(request={"method": "POST", "path": "v2/invoice"})


def test_e3_unknown_template_variable_is_refused() -> None:
    """`{{input.…}}`·`{{run_id}}`·`{{node_id}}`·`{{idempotency_key}}`만 쓴다. **키는 못 쓴다.**"""
    assert "adapter_invalid" in op_codes(request={"method": "POST", "path": "/v2/{{key}}"})
    assert "adapter_invalid" in op_codes(
        request={"method": "POST", "path": "/v2", "body": {"k": "{{secrets.api_key}}"}}
    )
    assert "adapter_invalid" in op_codes(
        request={"method": "POST", "path": "/v2", "query": {"q": "{{env.HOME}}"}}
    )
    # 중첩된 본문도 훑는다.
    assert "adapter_invalid" in op_codes(
        request={"method": "POST", "path": "/v2", "body": {"a": [{"b": "{{nope}}"}]}}
    )
    assert validate_extension(
        parse(
            {
                **external(),
                "service": {
                    **external()["service"],
                    "adapter": {
                        **external()["service"]["adapter"],
                        "operations": [
                            {
                                "name": "ok",
                                "request": {
                                    "method": "POST",
                                    "path": "/v2/{{input.id}}",
                                    "body": {"ref": "{{run_id}}", "node": "{{node_id}}",
                                             "key": "{{idempotency_key}}"},
                                },
                                "response": {"output": {"a": "$.a[0].b"}},
                            }
                        ],
                    },
                },
            }
        )
    ) == []


def test_e3_forbidden_headers_are_refused() -> None:
    for name in ("Authorization", "host", "Cookie"):
        assert "adapter_invalid" in op_codes(
            request={"method": "POST", "path": "/v2", "headers": {name: "x"}}
        )


def test_e3_header_value_with_newline_is_refused() -> None:
    assert "adapter_invalid" in op_codes(
        request={"method": "POST", "path": "/v2", "headers": {"X-Trace": "a\r\nX-Evil: 1"}}
    )


def test_e3_output_path_must_be_restricted_jsonpath() -> None:
    for bad in ("$..biz", "$.items[*].id", "$['a']", "result.bizNo"):
        assert "adapter_invalid" in op_codes(response={"output": {"biz_no": bad}}), bad
    assert validate_extension(parse(external())) == []


def test_e3_error_when_takes_exactly_one_comparison() -> None:
    assert "adapter_invalid" in op_codes(
        response={"output": {}, "error_when": {"path": "$.status"}}
    )
    assert "adapter_invalid" in op_codes(
        response={"output": {}, "error_when": {"path": "$.status", "equals": "bad", "exists": True}}
    )
    assert validate_extension(
        parse(
            {
                **external(),
                "service": {
                    **external()["service"],
                    "adapter": {
                        **external()["service"]["adapter"],
                        "operations": [
                            {
                                "name": "ok",
                                "request": {"method": "POST", "path": "/v2"},
                                "response": {"error_when": {"path": "$.status", "not_equals": "ok"}},
                            }
                        ],
                    },
                },
            }
        )
    ) == []


def test_e3_catalog_url_host_must_be_allowed() -> None:
    definition = external(
        contributes={"resources": [{"type": "doc", "label": "문서", "catalog_url": "https://evil.net/c"}]}
    )
    assert "adapter_invalid" in codes(definition)


def test_external_operation_defaults_are_conservative() -> None:
    """외부 작업은 **자율 수행만**, **멱등 아님**이 기본값이다 (C13 §4-1)."""
    op = parse(external()).adapter.operations[0]  # type: ignore[union-attr]
    assert op.modes == ["autonomous"]
    assert op.idempotent is False
    assert op.server_ok is True


# ─────────────────────────── 모양 검사 ───────────────────────────


def test_api_is_required_for_code_tiers() -> None:
    definition = builtin()
    del definition["api"]
    assert "api_missing" in codes(definition)


def test_task_type_needs_run_locations() -> None:
    definition = builtin()
    definition["contributes"]["task_types"][0]["run_locations"] = []
    assert "run_locations_missing" in codes(definition)
    definition["contributes"]["task_types"][0]["run_locations"] = ["laptop"]
    assert "unknown_run_location" in codes(definition)


def test_builtin_editor_needs_an_entry() -> None:
    definition = builtin()
    definition["contributes"]["task_types"][0]["editor"] = {"kind": "builtin"}
    assert "editor_entry_missing" in codes(definition)
    definition["contributes"]["task_types"][0]["editor"] = {"kind": "schema"}
    assert validate_extension(parse(definition)) == []


def test_utility_key_must_land_in_a_secret_config_field() -> None:
    """키를 받는 칸은 OS 비밀 저장소에 둔다 (ADR-0013)."""
    definition = builtin(requires_keys=[{"purpose": "utility"}])
    assert "config_key_missing" in codes(definition)

    definition = builtin(requires_keys=[{"purpose": "utility", "config_key": "nope"}])
    assert "config_key_not_found" in codes(definition)

    definition = builtin(
        requires_keys=[{"purpose": "utility", "config_key": "k"}],
        contributes={"configuration": [{"key": "k", "label": "키", "scope": "bot_ui"}]},
    )
    assert "key_config_not_secret" in codes(definition)

    definition = builtin(
        requires_keys=[{"purpose": "utility", "config_key": "k"}],
        contributes={"configuration": [{"key": "k", "label": "키", "scope": "bot_ui", "secret": True}]},
    )
    assert validate_extension(parse(definition)) == []


def test_local_runtime_needs_an_entry() -> None:
    definition = builtin(contributes={"bot_ui.local_runtimes": [{"id": "r", "label": "r", "entry": ""}]})
    assert "entry_missing" in codes(definition)


# ─────────────────────────── 화면 칸 (ADR-0042) ───────────────────────────


def panel(**over: Any) -> dict[str, Any]:
    base = {"id": "recent", "label": "최근", "surface": "bot_ui.runtimes", "entry": "x:Y"}
    return base | over


def test_a_panel_needs_an_entry_and_a_known_surface() -> None:
    """**모르는 자리는 거부가 아니라 알려 주기다** — 호스트가 조용히 무시하므로 칸이 사라진다."""
    assert "entry_missing" in codes(builtin(contributes={"bot_ui.panels": [panel(entry="")]}))
    assert "unknown_surface" in codes(builtin(contributes={"bot_ui.panels": [panel(surface="nowhere")]}))
    assert validate_extension(parse(builtin(contributes={"bot_ui.panels": [panel()]}))) == []


def test_a_panel_waiting_for_a_runtime_that_is_not_there_is_caught() -> None:
    """그 런타임이 떠 있을 때만 보이는 칸인데 런타임이 없으면 **영원히 안 보인다.**"""
    one = builtin(contributes={"bot_ui.panels": [panel(runtime="worker")]})
    assert "panel_runtime_not_found" in codes(one)
    both = builtin(
        contributes={
            "bot_ui.panels": [panel(runtime="worker")],
            "bot_ui.local_runtimes": [{"id": "worker", "label": "W", "entry": "x:Serve"}],
        }
    )
    assert validate_extension(parse(both)) == []


def test_panels_are_listed_for_c7() -> None:
    found = parse(builtin(contributes={"bot_ui.panels": [panel()]})).contributes_summary()
    assert found["bot_ui.panels"] == ["recent"]


def test_old_command_field_is_refused_not_ignored() -> None:
    """schema 1의 `command`만 적은 정의는 **거부된다** (schema 2에서 `entry`가 필수, ADR-0024).

    조용히 무시하면 Bot UI가 로컬 런타임을 띄우지 못하는데 확장은 켜진 것처럼 보인다.
    """
    definition = builtin(
        schema=1, contributes={"bot_ui.local_runtimes": [{"id": "worker", "label": "W", "command": ["chk-worker"]}]}
    )
    with pytest.raises(ValueError, match="entry"):
        parse(definition)


def test_unknown_scope_and_start_are_reported() -> None:
    definition = builtin(contributes={"configuration": [{"key": "k", "label": "k", "scope": "bot"}]})
    assert "unknown_scope" in codes(definition)
    definition = builtin(
        contributes={"bot_ui.local_runtimes": [{"id": "r", "label": "r", "entry": "x:Y", "start": "someday"}]}
    )
    assert "unknown_start" in codes(definition)


def test_doc_urls_must_be_http() -> None:
    assert "url_scheme" in codes(builtin(docs_url="file:///etc/passwd"))
    assert validate_extension(parse(builtin(docs_url="https://example.com/doc"))) == []


# ─────────────────────────── E4·E5·크기 ───────────────────────────


def test_e4_task_type_ids_do_not_overlap_between_extensions() -> None:
    other = builtin(id="doc-ocr-2")
    conflicts = task_type_conflicts([parse(builtin()), parse(other)])
    assert [v.code for v in conflicts] == ["task_type_conflict"]
    assert conflicts[0].items == ["doc-ocr", "doc-ocr-2"]
    assert task_type_conflicts([parse(builtin())]) == []


def test_e5_api_range_decides_compatibility() -> None:
    m = parse(builtin(api=">=1,<2"))
    assert check_extension_api(m, api_version="1.4.0") == []
    assert [v.code for v in check_extension_api(m, api_version="2.0.0")] == ["api_incompatible"]
    assert [v.code for v in check_extension_api(parse(builtin(api="nonsense")), api_version="1.0.0")] == [
        "api_invalid"
    ]


def test_size_limit() -> None:
    assert check_extension_size(b"{}") == []
    assert [v.code for v in check_extension_size(b"x" * (MAX_DEFINITION_BYTES + 1))] == ["too_large"]


# ─────────────────────────── E6 ───────────────────────────


def signed(definition: dict[str, Any], **claim_over: Any) -> tuple[Any, list[AdminKey]]:
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes_raw()
    claim: dict[str, Any] = {
        "kind": "extension",
        "id": definition["id"],
        "version": definition["version"],
        "definition_hash": definition_hash(definition),
    }
    claim.update(claim_over)
    envelope = sign(claim, private, signed_at=NOW)
    return envelope, [AdminKey(key_id=key_id_for(public), public_key=base64.b64encode(public).decode())]


def test_e6_signed_external_definition_verifies() -> None:
    definition = external()
    envelope, keys = signed(definition)
    assert verify_external(definition, envelope, keys=keys) == []


def test_e6_changed_definition_breaks_the_hash() -> None:
    definition = external()
    envelope, keys = signed(definition)
    tampered = json.loads(json.dumps(definition))
    tampered["service"]["base_url"] = "https://ocr.example.com/v2"
    assert [v.code for v in verify_external(tampered, envelope, keys=keys)] == ["hash_mismatch"]


def test_e6_unknown_key_is_refused() -> None:
    definition = external()
    envelope, _ = signed(definition)
    assert [v.code for v in verify_external(definition, envelope, keys=[])] == ["bad_envelope"]


def test_e6_wrong_claim_kind_is_refused() -> None:
    definition = external()
    envelope, keys = signed(definition, kind="package")
    assert [v.code for v in verify_external(definition, envelope, keys=keys)] == ["bad_envelope"]


def test_e6_envelope_for_another_extension_is_refused() -> None:
    definition = external()
    envelope, keys = signed(definition)
    other = {**definition, "id": "ext-other"}
    # 해시가 먼저 걸린다 — id를 바꾸면 내용이 달라지므로.
    assert [v.code for v in verify_external(other, envelope, keys=keys)] == ["hash_mismatch"]



# ─────────────────────────── AI 환경 (ADR-0037) ───────────────────────────


def test_an_agent_environment_needs_a_known_domain() -> None:
    known = builtin(contributes={"agent_environments": [{"domain": "desktop", "entry": "x:Y"}]})
    assert "unknown_domain" not in codes(known)
    odd = builtin(contributes={"agent_environments": [{"domain": "llm", "entry": "x:Y"}]})
    assert "unknown_domain" in codes(odd), "`llm`·`doc`·`api`는 엔진이 스스로 돈다 — 환경이 없다"


def test_e8_one_domain_one_extension() -> None:
    from chaeksas.contracts.extension import environment_conflicts  # noqa: PLC0415

    first = parse(builtin(contributes={"agent_environments": [{"domain": "desktop", "entry": "x:Y"}]}))
    second = parse(builtin(id="other-ui", contributes={"agent_environments": [{"domain": "desktop", "entry": "x:Z"}]}))
    found = environment_conflicts([first, second])
    assert [v.code for v in found] == ["environment_conflict"]
    assert environment_conflicts([first]) == []
