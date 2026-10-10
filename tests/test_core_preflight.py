"""사전 점검 — 실행 전에 이 PC에서 볼 수 있는 것 (`core.preflight`, ADR-0013 §사전 점검).

여기서 보는 것은 **무엇을 막고 무엇을 막지 않는가**다. 거짓 차단은 거짓 통과보다 나쁘다 —
올바른 Bot이 「실행 불가」로 멈추면 사람이 고칠 것이 없다.
"""

from __future__ import annotations

import zipfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from chaeksas.contracts.manifest import (
    ExtensionNeed,
    Manifest,
    Requires,
    ServiceAppNeed,
    TaskTypeNeed,
)
from chaeksas.core import preflight
from chaeksas.core.extensions import ExtensionHost
from chaeksas.extension_api import SEVERITY_BLOCK, SEVERITY_WARN, Finding, PreflightTarget

#: 매니페스트의 나머지 필수 칸 — 점검은 이것들을 보지 않는다.
BASE: dict[str, Any] = {
    "schema": 1,
    "id": "erp.order-entry",
    "version": "1.0.0",
    "name": "주문 입력",
    "kind": "bpm_process",
    "run_location": "pc",
    "entry": "main.bpmn",
    "content_hash": "sha256:" + "0" * 64,
    "human": {"approval_center": False, "approval_field": False, "confirmation": False},
    "built": {"by": "studio", "at": "2026-10-08T00:00:00+09:00", "core": "0.1.0", "spec_version": 1},
}


def manifest(**requires: Any) -> Manifest:
    return Manifest.model_validate({**BASE, "requires": Requires(**requires).to_json_dict()})


def never(_ref: str) -> str | None:
    """이 PC에 키가 하나도 없다."""
    return None


def always(_ref: str) -> str | None:
    return "chk_svc_abc1234567890"


# ─────────────────────────── 키 참조 ───────────────────────────


def test_key_refs_count_both_the_inherited_and_the_task_ones() -> None:
    """C1 — 프로세스가 상속하는 `key_ref`와 태스크가 적은 `task_key_refs` **둘 다** 풀어야 한다."""
    m = manifest(
        service_apps=[
            ServiceAppNeed(app_id="erp", operations=["create"], key_ref="fin-erp", task_key_refs=["fin-erp-ro"]),
            ServiceAppNeed(app_id="crm", operations=["upsert"], key_ref="fin-crm"),
        ]
    )
    assert preflight.key_refs_of(m) == ("fin-erp", "fin-erp-ro", "fin-crm")


def test_the_same_reference_is_counted_once() -> None:
    m = manifest(
        service_apps=[
            ServiceAppNeed(app_id="erp", operations=["a"], key_ref="shared"),
            ServiceAppNeed(app_id="crm", operations=["b"], key_ref="shared", task_key_refs=["shared"]),
        ]
    )
    assert preflight.key_refs_of(m) == ("shared",)


def test_a_missing_key_blocks_and_says_which_one() -> None:
    """무엇이 빠졌는지 말해야 고칠 수 있다 (BUI-04 「서비스 앱 키 없음: <참조>」)."""
    m = manifest(service_apps=[ServiceAppNeed(app_id="erp", operations=["a"], key_ref="fin-erp")])
    found = preflight.check(m, key_value=never, fix_hint="BUI-10에서 등록하세요")

    assert found.blocks
    assert found.missing_key_refs == ("fin-erp",)
    assert found.blocked == (preflight.MISSING_KEYS,)
    only = found.findings[0]
    assert only.severity == SEVERITY_BLOCK
    assert only.fix_hint == "BUI-10에서 등록하세요"


def test_a_registered_key_is_ready() -> None:
    m = manifest(service_apps=[ServiceAppNeed(app_id="erp", operations=["a"], key_ref="fin-erp")])
    found = preflight.check(m, key_value=always)
    assert not found.blocks
    assert found.missing_key_refs == () and found.blocked == ()


def test_an_empty_value_counts_as_missing() -> None:
    """빈 글자는 키가 아니다 — 보내면 401이 날 뿐이다."""
    m = manifest(service_apps=[ServiceAppNeed(app_id="erp", operations=["a"], key_ref="fin-erp")])
    assert preflight.check(m, key_value=lambda _ref: "").blocks


def test_a_secret_store_that_throws_does_not_crash_the_check() -> None:
    """비밀 저장소가 잠긴 PC도 있다 — 점검이 터지는 대신 「없다」고 본다."""

    def locked(_ref: str) -> str | None:
        raise RuntimeError("저장소가 잠겼습니다")

    m = manifest(service_apps=[ServiceAppNeed(app_id="erp", operations=["a"], key_ref="fin-erp")])
    found = preflight.check(m, key_value=locked)
    assert found.missing_key_refs == ("fin-erp",)


def test_a_bot_that_calls_nothing_needs_no_keys() -> None:
    assert not preflight.check(manifest(), key_value=never).blocks


# ─────────────────────────── 확장·태스크 종류·AI 환경 ───────────────────────────


def test_a_task_type_no_extension_contributes_blocks() -> None:
    """C13 — 종류가 없으면 엔진이 `node_kind_unsupported`로 끝낸다. 시작하기 전에 말한다."""
    m = manifest(task_types=[TaskTypeNeed(id="ui_task", extension="ui-automation", run_locations=["pc"])])
    found = preflight.check(m, key_value=never, host=ExtensionHost())

    assert found.blocked == (preflight.TASK_TYPES_UNSUPPORTED,)
    assert found.findings[0].items == ("ui_task (ui-automation 확장)",)


def test_an_extension_with_no_local_code_does_not_block() -> None:
    """**거짓 차단을 막는 자리다.**

    `requires.extensions`에는 코드가 없는 확장도 들어간다 — 외부 확장은 코드를 기여할 수 없고
    (C13 E1), 사내 확장도 서버 부분만 있는 것이 있다 (모의 앱 `crm`이 그렇다). 서비스 앱 호출은
    엔진이 `RunEnv.services`로 하므로 그 PC에 확장 코드가 없어도 된다.
    """
    m = manifest(
        extensions=[ExtensionNeed(id="crm", version=">=1,<2")],
        service_apps=[ServiceAppNeed(app_id="crm", operations=["upsert"], key_ref="it-crm")],
    )
    found = preflight.check(m, key_value=always, host=ExtensionHost())
    assert not found.blocks, "코드가 필요 없는 확장이 깔려 있지 않다고 막으면 안 된다"


def test_a_pc_only_domain_with_no_environment_blocks() -> None:
    """ADR-0037 — `web`·`desktop` AI 태스크는 확장이 눈과 손을 준다."""
    found = preflight.check(manifest(domains=["desktop"]), key_value=never, host=ExtensionHost())
    assert found.blocked == (preflight.MISSING_ENVIRONMENT,)
    assert found.findings[0].items == ("desktop",)


def test_the_other_domains_need_no_environment() -> None:
    """`llm`·`api`·`doc`은 엔진이 제 길로 간다 (모델·HTTP·도구)."""
    found = preflight.check(manifest(domains=["llm", "api", "doc"]), key_value=never, host=ExtensionHost())
    assert not found.blocks


# ─────────────────────────── 확장이 기여한 점검 ───────────────────────────


class Noisy:
    """`preflight` 기여 — 경고 하나를 낸다."""

    def check(self, target: PreflightTarget) -> Sequence[Finding]:
        return [Finding(id="pages", severity=SEVERITY_WARN, message=f"키 참조 {len(target.key_refs)}개")]


class Broken:
    """터지는 점검. 호스트가 이것 때문에 실행을 막아서는 안 된다."""

    def check(self, target: PreflightTarget) -> Sequence[Finding]:
        raise NotImplementedError("아직 못 만들었다")


class Blocking:
    def check(self, target: PreflightTarget) -> Sequence[Finding]:
        return [Finding(id="pages", severity=SEVERITY_BLOCK, message="쓰는 화면이 레지스트리에 없습니다")]


class FakeHost(ExtensionHost):
    """점검만 돌려주는 호스트 — 엔트리 포인트를 거치지 않는다."""

    def __init__(self, *checks: Any) -> None:
        super().__init__()
        self._checks = checks

    def preflight_checks(self) -> Any:
        from chaeksas.core.extensions import Contribution  # noqa: PLC0415

        return [
            Contribution(extension_id=f"ext-{at}", extension_version="1.0.0", value=one)
            for at, one in enumerate(self._checks)
        ]


def context(_extension_id: str) -> Any:
    """확장에 줄 바깥 세상 — 이 점검들은 쓰지 않으므로 아무것이나 준다."""
    return object()


def test_an_extension_check_runs_and_sees_the_key_refs() -> None:
    m = manifest(service_apps=[ServiceAppNeed(app_id="erp", operations=["a"], key_ref="fin-erp")])
    found = preflight.check(m, key_value=always, host=FakeHost(Noisy()), context=context)

    assert [(f.id, f.message) for f in found.findings] == [("pages", "키 참조 1개")]
    assert not found.blocks, "경고는 막지 않는다"


def test_a_check_that_throws_is_skipped_not_fatal() -> None:
    """`PreflightCheck` 규약 — **점검이 실행을 막지 않는다.** 사유만 남는다."""
    found = preflight.check(manifest(), key_value=never, host=FakeHost(Broken(), Noisy()), context=context)

    assert not found.blocks
    assert len(found.skipped) == 1 and "아직 못 만들었다" in found.skipped[0]
    assert [f.id for f in found.findings] == ["pages"], "터진 것만 빠지고 나머지는 돈다"


def test_an_extension_check_can_block() -> None:
    found = preflight.check(manifest(), key_value=never, host=FakeHost(Blocking()), context=context)
    assert found.blocks and found.blocked == ("pages",)


def test_without_a_context_only_the_platform_checks_run() -> None:
    """확장에 줄 바깥 세상을 못 만드는 쪽도 있다 — 그래도 키 점검은 돌아야 한다."""
    m = manifest(service_apps=[ServiceAppNeed(app_id="erp", operations=["a"], key_ref="fin-erp")])
    found = preflight.check(m, key_value=never, host=FakeHost(Blocking()), context=None)
    assert found.blocked == (preflight.MISSING_KEYS,)


def test_without_a_host_the_extension_and_platform_extension_checks_are_skipped() -> None:
    """확장이 없는 Bot UI도 Bot은 돈다."""
    m = manifest(domains=["desktop"], task_types=[TaskTypeNeed(id="ui_task", extension="x", run_locations=["pc"])])
    assert not preflight.check(m, key_value=never, host=None).blocks


# ─────────────────────────── 진짜 예제로 ───────────────────────────


#: 업무 예제의 그림 폴더 (생성물이다 — 건드리지 않는다, CLAUDE.md §2).
EXAMPLES = Path("docs/08-business-examples/bpmn")


@pytest.mark.parametrize("example", ["bx36_legacy_migration"])
def test_a_real_example_is_blocked_by_the_key_and_nothing_else(example: str, tmp_path: Path) -> None:
    """BX-36은 `it-crm` 키 하나와 `ui_task`·`desktop`을 쓴다.

    설치된 확장(`ui-automation`)이 종류와 환경을 주므로 **막는 것은 키뿐이어야 한다**. 이것이
    깨지면 거짓 차단이 생긴 것이다 — 올바른 Bot이 「실행 불가」가 된다.
    """
    from chaeksas.core.extensions import load_host  # noqa: PLC0415
    from chaeksas.studio.packaging import export  # noqa: PLC0415
    from chaeksas.studio.workspace import Workspace  # noqa: PLC0415

    made = Workspace(tmp_path / "studio").ensure().import_example(EXAMPLES, example)
    package = export(made, tmp_path / "bot.zip")
    with zipfile.ZipFile(package) as archive:
        m = Manifest.model_validate_json(archive.read("manifest.json"))

    host = load_host()
    assert preflight.check(m, key_value=never, host=host).blocked == (preflight.MISSING_KEYS,)
    assert not preflight.check(m, key_value=always, host=host).blocks


# ─────────────────────────── 사람이 끈 확장 (ADR-0043) ───────────────────────────


def _host_with(definition: dict[str, Any], *, off: tuple[str, ...] = ()) -> ExtensionHost:
    import json  # noqa: PLC0415

    host = ExtensionHost(off=off)
    host.add_installed(json.dumps(definition).encode("utf-8"), origin="test", root="chaeksas.ext.ui_automation")
    return host


#: 같은 확장이 AI 환경만 기여한 꼴 (ADR-0037 — 그림에는 `requires.domains`만 적힌다).
DESKTOP_ENV: dict[str, Any] = {
    "schema": 2,
    "id": "doc-ocr",
    "version": "1.0.0",
    "name": "문서 인식",
    "publisher": "Chaeksas",
    "tier": "builtin",
    "api": ">=1,<2",
    "contributes": {"agent_environments": [{"domain": "desktop", "entry": "doc_ocr.client:Desktop"}]},
}

OCR = {
    "schema": 2,
    "id": "doc-ocr",
    "version": "1.0.0",
    "name": "문서 인식",
    "publisher": "Chaeksas",
    "tier": "builtin",
    "api": ">=1,<2",
    "contributes": {
        "task_types": [
            {
                "id": "ocr_task",
                "label": "문서 인식",
                "executor": {"entry": "doc_ocr.client:X"},
                "run_locations": ["pc"],
            }
        ]
    },
}


def test_a_turned_off_extension_gets_its_own_finding() -> None:
    """**고치는 길이 다르다** — 깔려 있는데 꺼 둔 것은 켜면 되고, 없는 것은 판을 올려야 한다.

    한 칸으로 뭉치면 켜면 될 일에 「Bot UI를 다시 깔라」고 안내하게 된다 (ADR-0043).
    """
    m = manifest(task_types=[TaskTypeNeed(id="ocr_task", extension="doc-ocr", run_locations=["pc"])])

    on = preflight.check(m, key_value=never, host=_host_with(OCR))
    assert not on.blocks

    off = preflight.check(m, key_value=never, host=_host_with(OCR, off=("doc-ocr",)))
    assert off.blocked == (preflight.EXTENSION_TURNED_OFF,)
    assert off.findings[0].items == ("ocr_task (문서 인식 확장)",)
    assert off.findings[0].fix_hint == "확장 목록에서 그 확장을 켜세요"


def test_a_missing_extension_still_says_install_it() -> None:
    """꺼 둔 것이 아니면 안내가 그대로다 — 깔려 있지 않으면 켤 수가 없다."""
    m = manifest(task_types=[TaskTypeNeed(id="ocr_task", extension="doc-ocr", run_locations=["pc"])])
    found = preflight.check(m, key_value=never, host=ExtensionHost())
    assert found.blocked == (preflight.TASK_TYPES_UNSUPPORTED,)
    assert "판으로 올리세요" in (found.findings[0].fix_hint or "")


def test_a_turned_off_ai_environment_says_turn_it_on() -> None:
    """**그림에 확장을 적지 않는 길도 같이 가른다** (ADR-0037·ADR-0043).

    `desktop` AI 태스크는 매니페스트에 `requires.domains`만 적는다 — 환경을 주는 확장이 꺼져
    있는데 「환경을 기여하는 확장을 설치하세요」라고 하면, 이미 깔린 것을 또 깔라는 말이 된다.
    """
    m = manifest(domains=["desktop"])

    on = preflight.check(m, key_value=never, host=_host_with(DESKTOP_ENV))
    assert not on.blocks

    off = preflight.check(m, key_value=never, host=_host_with(DESKTOP_ENV, off=("doc-ocr",)))
    assert off.blocked == (preflight.EXTENSION_TURNED_OFF,)
    assert off.findings[0].items == ("desktop (문서 인식 확장)",)
    assert off.findings[0].fix_hint == "확장 목록에서 그 확장을 켜세요"


def test_an_absent_ai_environment_still_says_install_it() -> None:
    found = preflight.check(manifest(domains=["desktop"]), key_value=never, host=ExtensionHost())
    assert found.blocked == (preflight.MISSING_ENVIRONMENT,)
    assert "설치하세요" in (found.findings[0].fix_hint or "")
