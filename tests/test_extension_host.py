"""확장 호스트 — 확장을 찾아 기여를 등록하고, 켜지 않을 것은 사유와 함께 남긴다 (ADR-0018).

M1 완료 기준의 한 줄을 이 파일이 지킨다: "빈 내장 확장 하나가 Studio·Bot UI에 태스크 종류·
유틸리티를 기여함". 플랫폼이 특정 확장을 import하지 않는 것은 `test_import_direction.py`가 본다.
"""

from __future__ import annotations

import base64
import json
import logging
from importlib.metadata import entry_points
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from chaeksas.contracts import AdminKey, definition_hash, key_id_for, sign
from chaeksas.core import ExtensionHost, load_host, summarize
from chaeksas.extension_api import (
    API_VERSION,
    BotUiUtility,
    EntryError,
    LocalRuntimeEntry,
    PreflightCheck,
    TaskEditor,
    TaskExecutor,
)
from chaeksas.extension_api.entry import module_root

#: 저장소에 있는 하나뿐인 내장 확장. **id로만 부른다** (플랫폼 코드는 import하지 않는다).
BUILTIN_ID = "ui-automation"
BUILTIN_ROOT = module_root(BUILTIN_ID)
NOW = "2026-10-02T09:00:00+09:00"


class Settings:
    def __init__(self, values: dict[str, Any] | None = None) -> None:
        self._values = values or {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)


class Secrets:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self._values = values or {}

    def resolve(self, ref: str) -> str | None:
        return self._values.get(ref)


@pytest.fixture
def host() -> ExtensionHost:
    return load_host()


# ─────────────────────────── 찾기 ───────────────────────────


def test_entry_points_find_the_builtin_extension(host: ExtensionHost) -> None:
    """설치된 확장을 엔트리 포인트(`chaeksas.extensions`)로 찾고, 패키지 안의 정의를 읽는다."""
    found = host.get(BUILTIN_ID)
    assert found is not None, f"확장을 찾지 못했다: {summarize(host)}"
    assert found.enabled, [str(p) for p in found.problems]
    assert found.origin == f"entry_point:{BUILTIN_ID}"
    assert found.root == BUILTIN_ROOT
    assert found.definition_hash.startswith("sha256:")
    assert host.failures == []


def test_builtin_contributes_task_type_and_utility(host: ExtensionHost) -> None:
    """M1 기준 — Studio에 태스크 종류, Bot UI에 유틸리티가 더해진다."""
    task_types = {c.value.id: c for c in host.task_types()}
    assert "ui_task" in task_types
    assert task_types["ui_task"].extension_id == BUILTIN_ID
    assert task_types["ui_task"].value.run_locations == ["pc"], "UI 태스크는 PC에서만 돈다 (ADR-0015)"

    utilities = {c.value.id: c.value for c in host.utilities()}
    assert "selector-registration" in utilities
    assert utilities["selector-registration"].menu == "tools"
    assert utilities["selector-registration"].needs_runtime == "worker"


def test_builtin_declares_the_worker_as_a_local_runtime(host: ExtensionHost) -> None:
    """Worker는 플랫폼의 구성요소가 아니라 확장이 선언한 로컬 런타임이다 (ADR-0018)."""
    runtimes = {c.value.id: c.value for c in host.local_runtimes()}
    # schema 2 — 명령줄이 아니라 진입점이다 (Bot UI가 자기 실행 파일을 다시 띄운다, ADR-0024).
    assert runtimes["worker"].entry == "ui_automation.worker:serve"
    assert runtimes["worker"].default_port == 8899
    assert runtimes["worker"].port_setting == "CHK_WORKER__LOCAL_API__PORT"
    assert runtimes["worker"].start == "on_demand", "항상 띄우지 않는다 (필요할 때만)"


def test_other_contribution_points(host: ExtensionHost) -> None:
    assert [c.value.resource_type for c in host.resource_views()] == ["ui_page"]
    assert [c.value.type for c in host.resources()] == ["ui_page"]
    assert [c.value.id for c in host.console_pages()] == ["overview"]
    assert [c.value.id for c in host.preflight()] == ["pages-registered"]
    assert [c.value.key for c in host.configuration(scope="bot_ui")] == ["registrar_key"]
    assert host.configuration(scope="server_runner") == []
    assert [c.value.key for c in host.secret_config_keys()] == ["registrar_key"]
    # 서버 부분이 C11 서비스 앱이므로 어댑터 작업은 없다 (작업은 앱의 /manifest에서 온다).
    assert host.adapter_operations() == []


def test_states_report_what_center_asks_for(host: ExtensionHost) -> None:
    """C4 하트비트·C12 등록에 싣는 `{id, version, definition_hash, enabled}`."""
    state = host.states()[0]
    assert state.id == BUILTIN_ID
    assert state.enabled is True
    assert state.definition_hash == host.states()[0].definition_hash
    assert set(state.to_json_dict()) == {"id", "version", "definition_hash", "enabled"}


def test_pyinstaller_hook_is_shipped_with_core() -> None:
    """ADR-0024 — 설치 파일에 확장을 넣는 훅을 `core`가 준다.

    확장은 문자열(엔트리 포인트·`entry`)로만 닿아서 PyInstaller의 정적 분석에 보이지 않는다.
    훅이 빠지면 **묶은 뒤에만** 확장이 사라지므로(S5 스파이크), 여기서 배선을 지킨다.
    PyInstaller가 깔려 있지 않아도 돌아간다 — 훅 파일을 import하지 않고 자리만 본다.
    """
    from pathlib import Path

    from chaeksas.core.__pyinstaller import get_hook_dirs

    dirs = [Path(d) for d in get_hook_dirs()]
    assert dirs, "훅 폴더가 없다"
    hooks = [p.name for d in dirs for p in d.glob("hook-*.py")]
    assert "hook-chaeksas.core.extensions.py" in hooks, hooks

    # PyInstaller가 훅 폴더를 찾는 길 (`pyinstaller40` 엔트리 포인트).
    declared = {ep.name: ep.value for ep in entry_points(group="pyinstaller40")}
    assert declared.get("hook-dirs") == "chaeksas.core.__pyinstaller:get_hook_dirs", declared


def test_unknown_entry_point_group_loads_nothing() -> None:
    empty = ExtensionHost()
    assert empty.load_entry_points(group="chaeksas.extensions.none") == []
    assert empty.all() == [] and empty.failures == []


# ─────────────────────────── 코드 기여 해석 ───────────────────────────


def test_resolved_code_matches_the_interface(host: ExtensionHost) -> None:
    """`entry`가 가리키는 객체가 `extension_api`의 모양인지 호스트가 확인한다."""
    assert isinstance(host.executor("ui_task"), TaskExecutor)
    assert isinstance(host.editor("ui_task"), TaskEditor)
    assert isinstance(host.utility("selector-registration"), BotUiUtility)
    checks = host.preflight_checks()
    assert len(checks) == 1
    assert isinstance(checks[0].value, PreflightCheck)


def test_local_runtime_entry_resolves(host: ExtensionHost) -> None:
    """Bot UI가 자식으로 다시 떴을 때 쓰는 길 (`--local-runtime ui-automation:worker`)."""
    entry = host.local_runtime(BUILTIN_ID, "worker")
    assert isinstance(entry, LocalRuntimeEntry)
    with pytest.raises(LookupError, match="로컬 런타임이 아니다"):
        host.local_runtime(BUILTIN_ID, "nope")
    with pytest.raises(LookupError):
        host.local_runtime("nope", "worker")


def test_executor_is_made_once_editor_every_time(host: ExtensionHost) -> None:
    assert host.executor("ui_task") is host.executor("ui_task")
    assert host.editor("ui_task") is not host.editor("ui_task")


def test_unknown_task_type_or_utility_raises(host: ExtensionHost) -> None:
    with pytest.raises(LookupError):
        host.executor("nope_task")
    with pytest.raises(LookupError):
        host.utility("nope")


def test_context_carries_settings_and_secrets(host: ExtensionHost) -> None:
    ctx = host.context(
        BUILTIN_ID,
        host="bot_ui",
        settings=Settings({"registrar_key": "ref-name"}),
        secrets=Secrets({"ref-name": "chk_svc_xxx"}),
        log=logging.getLogger("test"),
    )
    assert ctx.extension_id == BUILTIN_ID
    assert ctx.api_version == API_VERSION
    assert ctx.setting("registrar_key") == "ref-name"
    assert ctx.secret("ref-name") == "chk_svc_xxx"
    assert ctx.secret("없는-참조") is None


def test_context_for_an_unknown_extension_raises(host: ExtensionHost) -> None:
    with pytest.raises(LookupError):
        host.context("nope", host="studio", settings=Settings(), secrets=Secrets())


# ─────────────────────────── 켜지 않는 경우 ───────────────────────────


def definition(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "schema": 2,
        "id": "doc-ocr",
        "version": "1.0.0",
        "name": "문서 인식",
        "publisher": "사내",
        "tier": "internal",
        "api": ">=1,<2",
        "contributes": {},
    }
    base.update(over)
    return base


def install(host: ExtensionHost, definition: dict[str, Any], *, root: str = BUILTIN_ROOT) -> Any:
    return host.add_installed(json.dumps(definition).encode("utf-8"), origin="test", root=root)


def test_incompatible_api_is_not_enabled() -> None:
    host = ExtensionHost(api_version="1.0.0")
    loaded = install(host, definition(api=">=2,<3"))
    assert loaded is not None and not loaded.enabled
    assert [p.code for p in loaded.problems] == ["api_incompatible"]
    assert host.enabled() == [] and len(host.disabled()) == 1
    # 켜지 않은 확장의 기여는 보이지 않는다.
    assert host.task_types() == []


def test_duplicate_id_loses_to_the_one_already_loaded(host: ExtensionHost) -> None:
    """이름 공간은 하나다 (C13). **먼저 켜진 쪽이 남는다** — 실행 중인 Bot이 쓰고 있다."""
    again = install(host, definition(id=BUILTIN_ID, tier="internal"))
    assert again is not None and not again.enabled
    assert [p.code for p in again.problems] == ["id_conflict"]
    assert host.get(BUILTIN_ID) is not None and host.get(BUILTIN_ID).enabled  # type: ignore[union-attr]


def test_duplicate_task_type_loses(host: ExtensionHost) -> None:
    """E4 — 태스크 종류 id는 확장 사이에 겹치지 않는다."""
    clash = install(
        host,
        definition(
            contributes={
                "task_types": [
                    {"id": "ui_task", "label": "내 UI 태스크", "run_locations": ["pc"],
                     "executor": {"entry": "doc_ocr.client:X"}}
                ]
            }
        ),
    )
    assert clash is not None and not clash.enabled
    assert [p.code for p in clash.problems] == ["task_type_conflict"]
    assert [c.extension_id for c in host.task_types()] == [BUILTIN_ID]


def test_external_definition_with_code_is_not_enabled() -> None:
    host = ExtensionHost()
    loaded = install(
        host,
        definition(
            tier="external",
            api=None,
            contributes={"bot_ui.utilities": [{"id": "u", "label": "u", "entry": "evil:Thing"}]},
        ),
    )
    assert loaded is not None and not loaded.enabled
    assert [p.code for p in loaded.problems] == ["external_code_not_allowed"]
    assert host.utilities() == []


def test_entry_cannot_point_outside_the_extension(host: ExtensionHost) -> None:
    """정의가 아무 모듈이나 가리켜 import시키지 못한다 (코드는 믿는 확장 안에서만)."""
    installed = install(
        host,
        definition(
            contributes={
                "task_types": [
                    {"id": "ocr_task", "label": "OCR", "run_locations": ["pc"],
                     "executor": {"entry": "os:getcwd"}}
                ]
            }
        ),
    )
    assert installed is not None and installed.enabled, [str(p) for p in installed.problems]
    with pytest.raises(EntryError, match="밖이거나"):
        host.executor("ocr_task")


def test_entry_pointing_at_the_wrong_shape_is_refused(host: ExtensionHost) -> None:
    installed = install(
        host,
        definition(
            contributes={
                "task_types": [
                    {"id": "ocr_task", "label": "OCR", "run_locations": ["pc"],
                     # 편집기를 수행기 자리에 적었다 — execute()가 없다.
                     "executor": {"entry": "ui_automation.client:UiTaskEditor"}}
                ]
            }
        ),
    )
    assert installed is not None and installed.enabled
    with pytest.raises(EntryError, match="모양이 아니다"):
        host.executor("ocr_task")


def test_schema_kind_editor_means_no_widget(host: ExtensionHost) -> None:
    """`editor.kind="schema"`면 Studio가 입력 JSON Schema로 자동 폼을 만든다 (STU-14)."""
    install(
        host,
        definition(
            contributes={
                "task_types": [
                    {"id": "ocr_task", "label": "OCR", "run_locations": ["pc"], "editor": {"kind": "schema"}}
                ]
            }
        ),
    )
    assert host.editor("ocr_task") is None


def test_task_type_without_executor_raises(host: ExtensionHost) -> None:
    install(
        host,
        definition(contributes={"task_types": [{"id": "ocr_task", "label": "OCR", "run_locations": ["pc"]}]}),
    )
    with pytest.raises(LookupError, match="수행기가 없다"):
        host.executor("ocr_task")


# ─────────────────────────── 읽지도 못한 경우 ───────────────────────────


def test_broken_json_is_a_failure_not_a_crash() -> None:
    host = ExtensionHost()
    assert host.add_installed(b"{not json", origin="test", root=BUILTIN_ROOT) is None
    assert len(host.failures) == 1
    assert "JSON이 아니다" in host.failures[0].message
    assert host.all() == []


def test_definition_missing_required_fields_is_a_failure() -> None:
    host = ExtensionHost()
    assert host.add_installed(b'{"schema": 1, "id": "x-y"}', origin="test", root=BUILTIN_ROOT) is None
    assert "C13과 맞지 않는다" in host.failures[0].message


def test_oversized_definition_is_not_enabled() -> None:
    host = ExtensionHost()
    padded = definition(description="가" * 300_000)
    loaded = install(host, padded)
    assert loaded is not None and not loaded.enabled
    assert "too_large" in [p.code for p in loaded.problems]


def test_summarize_shows_why(host: ExtensionHost) -> None:
    install(host, definition(api=">=9"))
    summary = summarize(host)
    assert summary["enabled"] == [f"{BUILTIN_ID}@0.1.0"]
    assert "api_incompatible" in summary["disabled"][0]
    assert summary["failed"] == []


# ─────────────────────────── 외부 확장 (Center에서 받은 것) ───────────────────────────


def external_definition() -> dict[str, Any]:
    return {
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


def signed_envelope(definition: dict[str, Any]) -> tuple[Any, list[AdminKey]]:
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes_raw()
    envelope = sign(
        {
            "kind": "extension",
            "id": definition["id"],
            "version": definition["version"],
            "definition_hash": definition_hash(definition),
        },
        private,
        signed_at=NOW,
    )
    return envelope, [AdminKey(key_id=key_id_for(public), public_key=base64.b64encode(public).decode())]


def test_signed_external_definition_is_enabled_without_code() -> None:
    host = ExtensionHost()
    definition = external_definition()
    envelope, keys = signed_envelope(definition)
    loaded = host.add_external(definition, envelope, keys=keys)
    assert loaded is not None
    assert loaded.enabled, [str(p) for p in loaded.problems]
    assert loaded.root is None, "외부 확장은 코드를 돌리지 않는다"
    assert [c.value.name for c in host.adapter_operations()] == ["read_invoice"]


def test_unsigned_external_definition_is_not_enabled() -> None:
    """실행하는 쪽이 봉투를 다시 검증한다 (C13 E6) — 관리자 토큰만 새는 경우를 막는다."""
    host = ExtensionHost()
    definition = external_definition()
    envelope, _ = signed_envelope(definition)
    loaded = host.add_external(definition, envelope, keys=[])  # 아는 Admin 키가 없다
    assert loaded is not None and not loaded.enabled
    assert [p.code for p in loaded.problems] == ["bad_envelope"]
    assert host.adapter_operations() == []


def test_tampered_external_definition_is_not_enabled() -> None:
    host = ExtensionHost()
    definition = external_definition()
    envelope, keys = signed_envelope(definition)
    definition["service"]["adapter"]["allowed_hosts"].append("evil.example.net")
    loaded = host.add_external(definition, envelope, keys=keys)
    assert loaded is not None and not loaded.enabled
    assert [p.code for p in loaded.problems] == ["hash_mismatch"]


def test_builtin_tier_from_center_is_not_enabled() -> None:
    """E2 — 내장·사내 확장은 설치 파일에 든 것만. Center에서 내려온 것은 쓰지 않는다."""
    host = ExtensionHost()
    definition = {**external_definition(), "tier": "builtin", "api": ">=1,<2"}
    envelope, keys = signed_envelope(definition)
    loaded = host.add_external(definition, envelope, keys=keys)
    assert loaded is not None and not loaded.enabled
    assert "id_conflict" in [p.code for p in loaded.problems]
