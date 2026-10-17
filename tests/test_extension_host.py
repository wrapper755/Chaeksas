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


def test_the_run_location_table_only_holds_task_types_that_are_turned_on(host: ExtensionHost) -> None:
    """C14 B6·C1 R2가 묻는 표다. **꺼 둔 확장의 종류는 없다** (ADR-0043 — 기여를 내지 않는다).

    그래서 받는 쪽은 **표에 없는 종류를 막지 않는다** — 막으면 그 확장을 끈 PC에서 올바른
    그림이 「서버에서 안 된다」가 된다.
    """
    assert host.task_type_locations() == {"ui_task": ["pc"]}

    off = ExtensionHost(off=[BUILTIN_ID])
    off.load_entry_points()
    assert off.task_type_locations() == {}, "꺼 둔 확장의 태스크 종류가 표에 남았다"


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
    # 화면 설계서가 적은 셋이다 (UIA-01~03). 콘솔은 이 기여를 읽어 탐색 줄을 만든다 (ADR-0042).
    assert [c.value.id for c in host.console_pages()] == ["overview", "selectors", "monitoring"]
    assert [c.value.id for c in host.panels("bot_ui.runtimes")] == ["recent-ui-sessions"]
    assert [c.value.id for c in host.preflight()] == ["pages-registered"]
    assert [c.value.key for c in host.configuration(scope="bot_ui")] == ["registrar_key"]
    assert host.configuration(scope="server_runner") == []
    # **비밀 칸은 거르는 쪽이 거른다** — `credentials.py`가 `configuration()`에 `.secret`을
    # 걸어 본다 (호스트에 그 편의 메서드를 두지 않는다 — 두 길이 되면 한쪽만 고친다).
    secret = [c.value.key for c in host.configuration(scope="bot_ui") if c.value.secret]
    assert secret == ["registrar_key"]
    # 서버 부분이 C11 서비스 앱이므로 어댑터가 없다 (작업은 앱의 /manifest에서 온다).
    found = host.get("ui-automation")
    assert found is not None and found.manifest.adapter is None


def test_states_report_what_center_asks_for(host: ExtensionHost) -> None:
    """C4 하트비트·C12 등록에 싣는 `{id, version, definition_hash, enabled, off}`.

    `off`는 **사람이 껐다**이고 `enabled=false`는 **흠이 있다**다 — Center가 「꺼짐」과
    「호환 안 됨」을 가르는 자리다 (ADR-0043).
    """
    state = host.states()[0]
    assert state.id == BUILTIN_ID
    assert state.enabled is True
    assert state.definition_hash == host.states()[0].definition_hash
    assert set(state.to_json_dict()) == {"id", "version", "definition_hash", "enabled", "off"}
    assert state.off is False


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
    #
    # **이름이 겹친다.** `hook-dirs`를 선언하는 것이 우리뿐이 아니다 — PyInstaller를 깔면
    # `pyinstaller-hooks-contrib`도 같은 이름으로 선언한다(`--group build`). 사전으로 모으면
    # 하나가 다른 하나를 덮으므로 **우리 것이 그 안에 있나**로 본다 (처음에는 사전으로 모아
    # 두었고, 빌드를 들이자 그 자리가 깨져 드러났다).
    declared = [ep.value for ep in entry_points(group="pyinstaller40") if ep.name == "hook-dirs"]
    assert "chaeksas.core.__pyinstaller:get_hook_dirs" in declared, declared


# ───────────────────── 빌드 검사 (`--selftest`, ADR-0024) ─────────────────────


def test_selftest_sees_the_installed_extension() -> None:
    """묶기 전 환경에서도 **같은 검사**가 돈다 (`core.selftest`).

    이것이 보는 것은 ADR-0024가 적어 둔 세 가지 빠짐이다 — 메타데이터(엔트리 포인트가 빈
    목록)·데이터 파일·서브모듈(`entry` 해석에서 터진다). **인스턴스를 만들지 않고 풀기만**
    하므로 Qt 없이 돈다.
    """
    from chaeksas.core.selftest import check  # noqa: PLC0415

    found = check()
    assert found["all_ok"], found
    assert BUILTIN_ID in " ".join(found["steps"]["entry_points"]["value"]["enabled"])
    assert "풀린다" in str(found["steps"]["entries"]["value"])


def test_selftest_fails_when_a_wanted_extension_is_missing() -> None:
    """**빌드가 멈춰야 한다** — 묶음에 확장이 빠지면 실행 중에야 드러난다.

    `--want`는 빌드하는 쪽이 「무엇이 들어가야 하는가」를 못 박는 자리다 (ADR-0018 §5 포함 목록).
    """
    from chaeksas.core.selftest import check  # noqa: PLC0415

    found = check(want=[BUILTIN_ID, "없는-확장"])
    assert not found["all_ok"]
    assert not found["steps"]["entry_points"]["ok"]
    # 기여를 푸는 쪽은 멀쩡하다 — 「무엇이 틀렸나」가 갈라져 보여야 한다.
    assert found["steps"]["entries"]["ok"]


def test_selftest_catches_an_entry_that_cannot_be_resolved() -> None:
    """**서브모듈이 빠진 꼴** — 확장은 켜지는데 `entry`가 풀리지 않는다 (ADR-0024의 셋째 증상)."""
    from chaeksas.core.selftest import check  # noqa: PLC0415

    broken = ExtensionHost()
    install(
        broken,
        definition(contributes={"task_types": [
            {"id": "ocr_task", "label": "OCR", "executor": {"entry": "doc_ocr.gone:Missing"},
             "run_locations": ["pc"]}
        ]}),
    )
    found = check(host=broken)
    assert not found["all_ok"]
    assert found["steps"]["entry_points"]["ok"], "확장은 켜져 있다 — 터지는 자리는 entry다"
    assert "ocr_task" in str(found["steps"]["entries"]["value"])


def test_unknown_entry_point_group_loads_nothing() -> None:
    empty = ExtensionHost()
    assert empty.load_entry_points(group="chaeksas.extensions.none") == []
    assert empty.all() == [] and empty.failures == []


# ─────────────────────────── 코드 기여 해석 ───────────────────────────


def test_resolved_code_matches_the_interface(host: ExtensionHost) -> None:
    """`entry`가 가리키는 객체가 `extension_api`의 모양인지 호스트가 확인한다.

    편집기·유틸리티는 **Qt 위젯을 만든다** — `QApplication`을 먼저 세운다. 앞선 시험이 세워 둔 것에
    기대면 이 파일만 돌릴 때 Qt가 프로세스를 죽인다(전체로 돌 때만 통과하던 시험이다).
    """
    import os  # noqa: PLC0415

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication  # noqa: PLC0415

    _app = QApplication.instance() or QApplication([])
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
    # **작업은 정의에서 읽는다** — 창(STU-15)과 어댑터가 그렇게 본다 (`m.adapter.operations`).
    assert loaded.manifest.adapter is not None
    assert [one.name for one in loaded.manifest.adapter.operations] == ["read_invoice"]


def test_unsigned_external_definition_is_not_enabled() -> None:
    """실행하는 쪽이 봉투를 다시 검증한다 (C13 E6) — 관리자 토큰만 새는 경우를 막는다."""
    host = ExtensionHost()
    definition = external_definition()
    envelope, _ = signed_envelope(definition)
    loaded = host.add_external(definition, envelope, keys=[])  # 아는 Admin 키가 없다
    assert loaded is not None and not loaded.enabled
    assert [p.code for p in loaded.problems] == ["bad_envelope"]
    # **꺼진 확장은 기여를 하나도 내지 않는다** (ADR-0043) — 작업도 그렇다.
    assert host.task_types() == [] and host.resources() == []


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



# ─────────────────────────── AI 환경 (ADR-0037) ───────────────────────────


def test_the_builtin_contributes_the_desktop_environment(host: ExtensionHost) -> None:
    from chaeksas.extension_api import AgentEnvironment  # noqa: PLC0415

    found = host.environment("desktop")
    assert isinstance(found, AgentEnvironment)
    assert host.environment("desktop") is found, "한 번 만들면 들고 있는다"
    assert host.environment_owner("desktop") == BUILTIN_ID
    assert host.environment("web") is None, "웹 AI 환경은 아직 아무도 기여하지 않는다"


def test_a_second_desktop_environment_loses(host: ExtensionHost) -> None:
    """E8 — 한 domain의 눈과 손은 하나다. 나중에 온 확장은 켜지 않는다."""
    clash = install(
        host, definition(contributes={"agent_environments": [{"domain": "desktop", "entry": "doc_ocr.client:X"}]})
    )
    assert clash is not None and not clash.enabled
    assert [p.code for p in clash.problems] == ["environment_conflict"]
    assert host.environment_owner("desktop") == BUILTIN_ID


# ─────────────────────────── 사람이 껐다 (ADR-0043) ───────────────────────────


def test_turned_off_is_not_a_problem() -> None:
    """**흠과 섞이지 않는다** — 꺼 둔 것은 고칠 거리가 아니라 사람의 뜻이다."""
    host = ExtensionHost(off=["doc-ocr"])
    loaded = install(host, definition())
    assert loaded is not None
    assert loaded.off and loaded.problems == () and not loaded.enabled
    assert [one.id for one in host.turned_off()] == ["doc-ocr"]
    assert host.enabled() == []


def test_a_turned_off_extension_contributes_nothing() -> None:
    """기여가 **한꺼번에** 빠진다 — 늦게(실행할 때) 죽지 않는다."""
    contributes = {
        "task_types": [
            {"id": "ocr_task", "label": "OCR", "executor": {"entry": "x:Y"}, "run_locations": ["pc"]}
        ],
        "studio.resource_views": [{"id": "v", "label": "서식", "resource_type": "ocr_form"}],
        "configuration": [{"key": "k", "label": "k", "scope": "studio"}],
    }
    on = ExtensionHost()
    install(on, definition(contributes=contributes))
    assert [c.value.id for c in on.task_types()] == ["ocr_task"]

    off = ExtensionHost(off=["doc-ocr"])
    install(off, definition(contributes=contributes))
    assert off.task_types() == []
    assert off.resource_views() == []
    assert off.configuration() == []


#: 양쪽에서 돈다고 적은 종류와 PC 전용 하나 (ADR-0064).
BOTH_AND_PC: dict[str, Any] = {
    "task_types": [
        {"id": "ocr_task", "label": "OCR", "executor": {"entry": "x:Y"}, "run_locations": ["pc"]},
        {"id": "sum_task", "label": "요약", "executor": {"entry": "x:Y"}, "run_locations": ["pc", "server"]},
    ]
}


def test_a_host_that_holds_a_run_location_only_contributes_what_runs_there() -> None:
    """**거르는 자리가 하나다** (ADR-0064) — 수행기·사전 점검·위치 표가 같은 것을 본다.

    서버 실행기는 로컬 런타임을 띄우지 않으므로(런타임은 Bot UI의 것이다) PC 전용 종류는
    서버에서 **없는 것**이 된다. 「깔려 있는데 못 돈다」는 사전 점검이 따로 말한다.
    """
    server = ExtensionHost(run_location="server")
    install(server, definition(contributes=BOTH_AND_PC))

    assert [c.value.id for c in server.task_types()] == ["sum_task"]
    assert server.task_type("ocr_task") is None
    assert server.task_type_locations() == {"sum_task": ["pc", "server"]}
    with pytest.raises(LookupError):
        server.executor("ocr_task")


def test_a_host_without_a_run_location_contributes_everything() -> None:
    """**주지 않으면 거르지 않는다** — Studio는 양쪽 그림을 편집하므로 팔레트에 둘 다 있어야 한다."""
    both = ExtensionHost()
    install(both, definition(contributes=BOTH_AND_PC))
    assert [c.value.id for c in both.task_types()] == ["ocr_task", "sum_task"]


def test_the_provider_is_still_found_for_a_filtered_task_type() -> None:
    """걸러진 종류의 **주인은 보인다** — 사전 점검이 「이 위치에서 못 돈다」를 그것으로 말한다."""
    server = ExtensionHost(run_location="server")
    install(server, definition(contributes=BOTH_AND_PC))

    owner = server.provider_of("ocr_task")
    assert owner is not None and owner.id == "doc-ocr" and not owner.off


def test_a_turned_off_extension_does_not_hold_the_task_type_name() -> None:
    """겹침(E4)은 **꺼지지 않은 것들 사이에서만** 본다 — 꺼진 것은 이름을 쥐고 있지 않다."""
    task = {
        "task_types": [
            {"id": "ocr_task", "label": "OCR", "executor": {"entry": "x:Y"}, "run_locations": ["pc"]}
        ]
    }
    clashing = ExtensionHost()
    install(clashing, definition(contributes=task))
    second = install(clashing, definition(id="doc-ocr-2", contributes=task))
    assert second is not None and [p.code for p in second.problems] == ["task_type_conflict"]

    freed = ExtensionHost(off=["doc-ocr"])
    install(freed, definition(contributes=task))
    other = install(freed, definition(id="doc-ocr-2", contributes=task))
    assert other is not None and other.problems == () and other.enabled


def test_the_report_tells_center_which_of_the_two_it_is() -> None:
    """C4 `ExtensionState` — `off`가 있어야 CON-03이 「꺼짐」과 「호환 안 됨」을 가른다."""
    host = ExtensionHost(api_version="1.0.0", off=["doc-ocr"])
    install(host, definition())
    install(host, definition(id="doc-ocr-2", api=">=9,<10"))
    states = {one.id: one for one in host.states()}
    assert states["doc-ocr"].off and not states["doc-ocr"].enabled
    assert not states["doc-ocr-2"].off and not states["doc-ocr-2"].enabled


def test_summarize_keeps_the_off_ones_out_of_the_fix_list(host: ExtensionHost) -> None:
    """로그를 보는 사람이 꺼 둔 것을 고칠 거리로 읽지 않게."""
    install(host, definition(api=">=9"))
    off_host = ExtensionHost(off=["doc-ocr"])
    install(off_host, definition())
    assert summarize(off_host) == {"enabled": [], "off": ["doc-ocr@1.0.0"], "disabled": [], "failed": []}
    assert summarize(host)["off"] == []
