"""사전 점검 — 실행 전에 이 PC에서 볼 수 있는 것 (`core.preflight`, ADR-0013 §사전 점검).

여기서 보는 것은 **무엇을 막고 무엇을 막지 않는가**다. 거짓 차단은 거짓 통과보다 나쁘다 —
올바른 BPM 프로세스가 「실행 불가」로 멈추면 사람이 고칠 것이 없다.
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


# ─────────────────────────── 서비스 앱 ───────────────────────────


def test_a_service_app_bot_needs_no_key_on_this_pc() -> None:
    """ADR-0102 — 서비스 앱은 Center에 외부 작업으로 올린다. **키가 없다고 막지 않는다.**"""
    m = manifest(service_apps=[ServiceAppNeed(app_id="erp", operations=["a"])])
    found = preflight.check(m)
    assert not found.blocks and found.blocked == ()


# ─────────────────────────── 확장·태스크 종류·AI 환경 ───────────────────────────


def test_a_task_type_no_extension_contributes_blocks() -> None:
    """C13 — 종류가 없으면 엔진이 `node_kind_unsupported`로 끝낸다. 시작하기 전에 말한다."""
    m = manifest(task_types=[TaskTypeNeed(id="ocr_task", extension="doc-ocr", run_locations=["pc"])])
    found = preflight.check(m, host=ExtensionHost())

    assert found.blocked == (preflight.TASK_TYPES_UNSUPPORTED,)
    assert found.findings[0].items == ("ocr_task (doc-ocr 확장)",)


def test_an_extension_with_no_local_code_does_not_block() -> None:
    """**거짓 차단을 막는 자리다.**

    `requires.extensions`에는 코드가 없는 확장도 들어간다 — 외부 확장은 코드를 기여할 수 없고
    (C13 E1), 사내 확장도 서버 부분만 있는 것이 있다 (모의 앱 `crm`이 그렇다). 서비스 앱 호출은
    엔진이 `RunEnv.services`로 하므로 그 PC에 확장 코드가 없어도 된다.
    """
    m = manifest(
        extensions=[ExtensionNeed(id="crm", version=">=1,<2")],
        service_apps=[ServiceAppNeed(app_id="crm", operations=["upsert"])],
    )
    found = preflight.check(m, host=ExtensionHost())
    assert not found.blocks, "코드가 필요 없는 확장이 깔려 있지 않다고 막으면 안 된다"


def test_a_screen_domain_always_blocks() -> None:
    """ADR-0114 — `web`·`desktop` AI 태스크는 **이 판이 돌리지 못한다**. 확장을 묻지 않는다(줄 확장이 없다)."""
    found = preflight.check(manifest(domains=["desktop", "web"]), host=ExtensionHost())
    assert found.blocked == (preflight.MISSING_ENVIRONMENT,)
    assert found.findings[0].items == ("desktop", "web")
    assert "다른 domain" in (found.findings[0].fix_hint or "")
    # 호스트가 없어도 막는다 — 확장과 무관한 판단이다.
    assert preflight.check(manifest(domains=["web"]), host=None).blocked == (preflight.MISSING_ENVIRONMENT,)


def test_the_other_domains_need_no_environment() -> None:
    """`llm`·`api`·`doc`은 엔진이 제 길로 간다 (모델·HTTP·도구)."""
    found = preflight.check(manifest(domains=["llm", "api", "doc"]), host=ExtensionHost())
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


def test_an_extension_check_runs_and_its_old_key_refs_are_empty() -> None:
    """`PreflightTarget.key_refs`는 옛 칸이라 **늘 비어 있다** (ADR-0102 — 키가 없다)."""
    m = manifest(service_apps=[ServiceAppNeed(app_id="erp", operations=["a"])])
    found = preflight.check(m, host=FakeHost(Noisy()), context=context)

    assert [(f.id, f.message) for f in found.findings] == [("pages", "키 참조 0개")]
    assert not found.blocks, "경고는 막지 않는다"


def test_a_check_that_throws_is_skipped_not_fatal() -> None:
    """`PreflightCheck` 규약 — **점검이 실행을 막지 않는다.** 사유만 남는다."""
    found = preflight.check(manifest(), host=FakeHost(Broken(), Noisy()), context=context)

    assert not found.blocks
    assert len(found.skipped) == 1 and "아직 못 만들었다" in found.skipped[0]
    assert [f.id for f in found.findings] == ["pages"], "터진 것만 빠지고 나머지는 돈다"


def test_an_extension_check_can_block() -> None:
    found = preflight.check(manifest(), host=FakeHost(Blocking()), context=context)
    assert found.blocks and found.blocked == ("pages",)


def test_without_a_context_only_the_platform_checks_run() -> None:
    """확장에 줄 바깥 세상을 못 만드는 쪽도 있다 — 그때 확장 점검은 건너뛴다(막지 않는다)."""
    found = preflight.check(manifest(), host=FakeHost(Blocking()), context=None)
    assert not found.blocks


def test_without_a_host_the_extension_and_platform_extension_checks_are_skipped() -> None:
    """확장이 없는 PC 실행기도 BPM 프로세스는 돈다."""
    m = manifest(task_types=[TaskTypeNeed(id="ocr_task", extension="x", run_locations=["pc"])])
    assert not preflight.check(m, host=None).blocks


# ─────────────────────────── 진짜 예제로 ───────────────────────────


#: 업무 예제의 그림 폴더 (생성물이다 — 건드리지 않는다, CLAUDE.md §2).
EXAMPLES = Path("docs/08-business-examples/bpmn")


@pytest.mark.parametrize("example", ["bx22_offboarding_access", "fx19_manual_task_pc"])
def test_a_real_example_is_not_blocked(example: str, tmp_path: Path) -> None:
    """서비스 앱·사내 확장을 부르는 예제도, 사람 확인만 하는 PC 예제도 **막는 것이 없어야 한다**.

    서비스 앱 키는 없어졌고(ADR-0102) 코드 없는 확장이 깔려 있지 않다고 막지 않는다. 이것이 깨지면
    거짓 차단이 생긴 것이다 — 올바른 BPM 프로세스가 「실행 불가」가 된다.
    """
    from chaeksas.core.extensions import load_host  # noqa: PLC0415
    from chaeksas.studio.packaging import export  # noqa: PLC0415
    from chaeksas.studio.workspace import Workspace  # noqa: PLC0415

    made = Workspace(tmp_path / "studio").ensure().import_example(EXAMPLES, example)
    package = export(made, tmp_path / "bot.zip")
    with zipfile.ZipFile(package) as archive:
        m = Manifest.model_validate_json(archive.read("manifest.json"))

    host = load_host()
    assert not preflight.check(m, host=host).blocks


# ─────────────────────────── 사람이 끈 확장 (ADR-0043) ───────────────────────────


def _host_with(definition: dict[str, Any], *, off: tuple[str, ...] = ()) -> ExtensionHost:
    import json  # noqa: PLC0415

    host = ExtensionHost(off=off)
    host.add_installed(json.dumps(definition).encode("utf-8"), origin="test", root="fake_extension")
    return host


OCR = {
    "schema": 2,
    "id": "doc-ocr",
    "version": "1.0.0",
    "name": "문서 인식",
    "publisher": "Chaeksas",
    "tier": "builtin",
    "api": ">=2,<3",
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

    한 칸으로 뭉치면 켜면 될 일에 「PC 실행기를 다시 깔라」고 안내하게 된다 (ADR-0043).
    """
    m = manifest(task_types=[TaskTypeNeed(id="ocr_task", extension="doc-ocr", run_locations=["pc"])])

    on = preflight.check(m, host=_host_with(OCR))
    assert not on.blocks

    off = preflight.check(m, host=_host_with(OCR, off=("doc-ocr",)))
    assert off.blocked == (preflight.EXTENSION_TURNED_OFF,)
    assert off.findings[0].items == ("ocr_task (문서 인식 확장)",)
    assert off.findings[0].fix_hint == "확장 목록에서 그 확장을 켜세요"


def test_a_missing_extension_still_says_install_it() -> None:
    """꺼 둔 것이 아니면 안내가 그대로다 — 깔려 있지 않으면 켤 수가 없다."""
    m = manifest(task_types=[TaskTypeNeed(id="ocr_task", extension="doc-ocr", run_locations=["pc"])])
    found = preflight.check(m, host=ExtensionHost())
    assert found.blocked == (preflight.TASK_TYPES_UNSUPPORTED,)
    assert "판으로 올리세요" in (found.findings[0].fix_hint or "")


# ───────────── 실행 위치가 아닌 태스크 종류 (ADR-0064 — 서버에서만 생긴다) ─────────────


def _server_host(definition: dict[str, Any]) -> ExtensionHost:
    import json  # noqa: PLC0415

    host = ExtensionHost(run_location="server")
    host.add_installed(json.dumps(definition).encode("utf-8"), origin="test", root="fake_extension")
    return host


def test_a_pc_only_task_type_gets_its_own_finding_on_the_server() -> None:
    """**셋째 까닭이다** (ADR-0064) — 꺼 둔 것도, 없는 것도 아니고 **이 위치에서 못 돈다**.

    뭉치면 「그 확장이 깔린 판으로 올리세요」라고 하는데, 올려도 서버에서는 못 돈다 — 고칠
    것은 **실행 위치**(STU-06)나 그림(PC 위임)이다. 전에는 이것을 아무도 막지 않아 배포·시작
    까지 가서 **실행 중에** `node_kind_unsupported`로 죽었다.
    """
    m = manifest(task_types=[TaskTypeNeed(id="ocr_task", extension="doc-ocr", run_locations=["pc"])])

    found = preflight.check(m, host=_server_host(OCR))
    assert found.blocked == (preflight.TASK_TYPES_WRONG_LOCATION,)
    assert found.findings[0].items == ("ocr_task (문서 인식 확장 — pc)",)
    assert "실행 위치를" in (found.findings[0].fix_hint or "")


def test_a_task_type_that_declares_the_server_is_not_blocked_there() -> None:
    """**적어 둔 것은 돈다** — 거짓 차단이 거짓 통과보다 나쁘다."""
    task: dict[str, Any] = {
        "id": "ocr_task",
        "label": "문서 인식",
        "executor": {"entry": "doc_ocr.client:X"},
        "run_locations": ["pc", "server"],
    }
    server_ocr = {**OCR, "contributes": {"task_types": [task]}}
    m = manifest(task_types=[TaskTypeNeed(id="ocr_task", extension="doc-ocr", run_locations=["pc", "server"])])

    assert not preflight.check(m, host=_server_host(server_ocr)).blocks


def test_an_absent_extension_on_the_server_does_not_say_bot_ui() -> None:
    """**서버에서 「PC 실행기를 올리세요」는 할 수 없는 일을 시키는 셈이다** — 그 자리에 PC 실행기가 없다."""
    m = manifest(task_types=[TaskTypeNeed(id="ocr_task", extension="doc-ocr", run_locations=["server"])])
    found = preflight.check(m, host=ExtensionHost(run_location="server"))

    assert found.blocked == (preflight.TASK_TYPES_UNSUPPORTED,)
    assert "서버 실행기" in (found.findings[0].fix_hint or "")
    assert "PC 실행기" not in (found.findings[0].fix_hint or "")
    assert "서버에서 수행할 수 없습니다" in found.findings[0].message


def test_the_pc_wording_is_unchanged_when_nobody_holds_a_run_location() -> None:
    """실행 위치를 쥐지 않은 호스트(Studio·PC 실행기)의 안내는 **그대로다**."""
    m = manifest(task_types=[TaskTypeNeed(id="ocr_task", extension="doc-ocr", run_locations=["pc"])])
    found = preflight.check(m, host=ExtensionHost())

    assert "이 PC에서" in found.findings[0].message
    assert "PC 실행기 판으로 올리세요" in (found.findings[0].fix_hint or "")


# ─────────────────── 갖춰야 할 설정 (C1 `requires.settings`, ADR-0059) ───────────────────


def test_a_bot_that_sends_mail_needs_smtp() -> None:
    """**메일을 보내는 BPM 프로세스는 SMTP가 있어야 띄운다** — 실행 중에 알면 늦다 (ADR-0059 §4)."""
    m = Manifest.model_validate({**BASE, "requires": {"settings": ["smtp"]}})

    blocked = preflight.check(m, settings=())
    assert blocked.blocks and blocked.blocked == (preflight.SETTINGS_MISSING,)
    assert blocked.findings[0].items == ("smtp",)

    assert not preflight.check(m, settings=("smtp",)).blocks


def test_not_knowing_what_is_configured_does_not_block() -> None:
    """**모르는 것으로 막지 않는다** — 갖춘 목록을 주지 않으면 그 점검을 돌리지 않는다.

    Studio처럼 「그 자리가 없는」 쪽이 있기 때문이다 (시험 실행은 진짜로 보내지 않는다).
    """
    m = Manifest.model_validate({**BASE, "requires": {"settings": ["smtp"]}})
    assert not preflight.check(m).blocks


def test_a_bot_that_sends_nothing_does_not_ask_for_smtp() -> None:
    assert not preflight.check(manifest(), settings=()).blocks
