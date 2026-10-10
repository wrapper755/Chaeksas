"""사전 점검 — Bot을 띄우기 전에 이 PC에서 볼 수 있는 것을 본다 (ADR-0013 §사전 점검, C4 `Readiness`).

보는 것은 두 갈래다.

- **플랫폼 점검**: 서비스 앱 키 참조가 이 PC에 있나, 그림이 쓰는 **확장 태스크 종류**를 수행할 수
  있나, 깔린 확장의 판이 맞나, `web`·`desktop` AI 태스크의 눈과 손을 줄 확장이 있나 (ADR-0037).
  어느 확장도 모르는 것이라 여기 둔다.
- **확장 점검**: `preflight` 기여가 한다 (C13·ADR-0018 — 예: 「쓰는 화면이 레지스트리에 있나」).
  **무엇을 보는지 플랫폼은 모른다.**

규칙 둘이 이 모듈의 모양을 정했다.

- **서버를 부르지 않는다.** Bot UI는 하트비트마다 돌려 `readiness`에 싣는다 (C4) — 한 번이 비싸면
  주기가 느려진다. 확장 점검도 같은 약속을 진다 (`PreflightCheck` 규약).
- **점검이 실행을 막지 않는다.** 점검 하나가 터지면 그것만 빼고 사유를 `skipped`에 남긴다. 막는
  것은 `severity`가 `block`인 **결과**이고, 그것으로 멈출지는 부르는 쪽이 정한다.

`Finding.id`는 C4 `Readiness.blocked`에 그대로 실린다 — 열린 문자열이다 (C4 「호환 규칙」).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from chaeksas.contracts._semver import InvalidVersion, satisfies
from chaeksas.contracts.bpmn_ext import PC_ONLY_DOMAINS
from chaeksas.contracts.manifest import Manifest
from chaeksas.core.extensions import ExtensionHost
from chaeksas.extension_api import (
    SEVERITY_BLOCK,
    ExtensionContext,
    Finding,
    PreflightTarget,
)

LOG = logging.getLogger(__name__)

#: 플랫폼 점검 코드. C4 `Readiness.blocked`와 BUI-04 「준비」가 이 이름을 쓴다.
MISSING_KEYS = "missing_service_app_keys"
TASK_TYPES_UNSUPPORTED = "task_types_unsupported"
#: 그 종류의 확장이 **깔려 있는데 사람이 꺼 뒀다** (ADR-0043). 고치는 길이 위와 다르다 — 켜면 된다.
EXTENSION_TURNED_OFF = "extension_turned_off"
EXTENSIONS_UNUSABLE = "extensions_unusable"
MISSING_ENVIRONMENT = "missing_agent_environment"


@dataclass(frozen=True)
class Preflight:
    """점검 한 번의 결과."""

    findings: tuple[Finding, ...] = ()
    #: 돌리지 못한 점검과 사유 (사람이 읽을 한 줄). **막지 않는다.**
    skipped: tuple[str, ...] = ()

    @property
    def blocks(self) -> bool:
        return any(f.blocks for f in self.findings)

    @property
    def blocked(self) -> tuple[str, ...]:
        """막는 점검의 코드들 — C4 `Readiness.blocked`에 그대로 싣는다."""
        return tuple(f.id for f in self.findings if f.blocks)

    @property
    def missing_key_refs(self) -> tuple[str, ...]:
        """이 PC에 값이 없는 서비스 앱 키 참조 — C4 `Readiness.missing_key_refs`."""
        found = next((f for f in self.findings if f.id == MISSING_KEYS), None)
        return found.items if found else ()


def key_refs_of(manifest: Manifest) -> tuple[str, ...]:
    """그 Bot이 쓰는 서비스 앱 키 참조 이름 모두 (C1 `requires.service_apps`).

    BPM 프로세스가 상속하는 `key_ref`와 태스크가 따로 적은 `task_key_refs`를 함께 센다 — 둘 다
    실행 중에 풀어야 하므로 **하나만 없어도 그 태스크가 죽는다**. 적힌 순서를 지키고 중복은 뺀다.
    """
    refs = [ref for need in manifest.requires.service_apps for ref in (need.key_ref, *need.task_key_refs)]
    return tuple(dict.fromkeys(ref for ref in refs if ref))


def _check_keys(
    manifest: Manifest,
    key_value: Callable[[str], str | None],
    *,
    fix_hint: str | None,
) -> Finding | None:
    """키 참조마다 **값이 있나**만 본다 — 맞는 키인지는 앱에 물어야 안다 (BUI-10 「확인」)."""
    missing = []
    for ref in key_refs_of(manifest):
        try:
            value = key_value(ref)
        except Exception as e:  # noqa: BLE001 - 비밀 저장소가 없는 PC도 있다 (막지 않는다)
            LOG.warning("키 참조 %s를 풀지 못했다: %s", ref, e)
            value = None
        if not value:
            missing.append(ref)
    if not missing:
        return None
    return Finding(
        id=MISSING_KEYS,
        severity=SEVERITY_BLOCK,
        message=f"서비스 앱 키 {len(missing)}개가 이 PC에 없습니다",
        items=tuple(missing),
        fix_hint=fix_hint,
    )


def _check_task_types(manifest: Manifest, host: ExtensionHost) -> Finding | None:
    """그림이 쓰는 **확장 태스크 종류**가 이 PC에 있나 (C1 `requires.task_types`, C13).

    **`requires.extensions`가 비었나로 보지 않는다** — 그 목록에는 코드가 없는 확장도 들어간다
    (외부 확장은 코드를 기여할 수 없고(C13 E1), 사내 확장도 서버 부분만 있는 것이 있다. 서비스 앱
    호출은 엔진이 `RunEnv.services`로 하므로 확장 코드가 필요 없다). 코드가 **정말** 있어야 하는
    것은 태스크 종류와 AI 환경이고, 그 둘을 따로 본다.

    종류가 없으면 엔진이 `node_kind_unsupported`로 끝낸다 — 재시도로 풀리지 않는 설치 오류라
    오류 경계도 받지 않는다 (`core.nodes`). 그러니 **시작하기 전에** 말한다.
    """
    missing = [need for need in manifest.requires.task_types if host.task_type(need.id) is None]
    if not missing:
        return None

    # **꺼 둔 것을 먼저 가른다** (ADR-0043) — 켜면 될 일에 「Bot UI를 다시 깔라」고 하면
    # 사람이 할 수 없는 일을 시키는 셈이다. 주인이 깔려 있는데 꺼져 있으면 고치는 길이 다르다.
    off = [
        f"{need.id} ({owner.manifest.name} 확장)"
        for need in missing
        if (owner := host.provider_of(need.id)) is not None and owner.off
    ]
    if off:
        return Finding(
            id=EXTENSION_TURNED_OFF,
            severity=SEVERITY_BLOCK,
            message=f"그림이 쓰는 태스크 종류 {len(off)}개의 확장이 꺼져 있습니다",
            items=tuple(off),
            fix_hint="확장 목록에서 그 확장을 켜세요",
        )
    return Finding(
        id=TASK_TYPES_UNSUPPORTED,
        severity=SEVERITY_BLOCK,
        message=f"그림이 쓰는 태스크 종류 {len(missing)}개를 이 PC에서 수행할 수 없습니다",
        items=tuple(f"{need.id} ({need.extension} 확장)" for need in missing),
        fix_hint="그 종류를 기여하는 확장이 깔린 Bot UI 판으로 올리세요",
    )


def _check_extensions(manifest: Manifest, host: ExtensionHost) -> Finding | None:
    """**깔려 있는** 확장의 판이 요구 범위에 맞나 (C1 `requires.extensions[].version`).

    깔려 있지 않은 것은 여기서 막지 않는다 (위 `_check_task_types`의 설명). 외부 확장의
    `definition_hash`도 보지 않는다 — 실행기가 봉투를 다시 검증하며 본다 (`core.app_directory`).
    """
    bad = []
    for need in manifest.requires.extensions:
        found = host.get(need.id)
        if found is None:
            continue
        if not found.enabled:
            why = found.problems[0].message if found.problems else "켜지지 않았습니다"
            bad.append(f"{need.id}: {why}")
            continue
        try:
            ok = satisfies(found.version, need.version)
        except InvalidVersion as e:
            bad.append(f"{need.id}: 버전 범위를 읽을 수 없습니다 ({need.version!r} — {e})")
            continue
        if not ok:
            bad.append(f"{need.id}: {need.version}가 필요한데 {found.version}이 깔려 있습니다")
    if not bad:
        return None
    return Finding(
        id=EXTENSIONS_UNUSABLE,
        severity=SEVERITY_BLOCK,
        message=f"깔린 확장 {len(bad)}개가 이 Bot이 요구하는 판이 아닙니다",
        items=tuple(bad),
        fix_hint="Bot UI를 새 판으로 올리거나, 그 판에 맞는 Bot을 배포하세요",
    )


def _check_environments(manifest: Manifest, host: ExtensionHost) -> Finding | None:
    """`web`·`desktop` AI 태스크의 눈과 손을 줄 확장이 있나 (ADR-0037, C13 `agent_environments`).

    그림에 확장을 적지 않아도 되는 자리다 — 매니페스트는 `requires.domains`만 적는다. 나머지
    domain(`llm`·`api`·`doc`)은 환경이 필요 없다.
    """
    missing = [
        domain
        for domain in manifest.requires.domains
        if domain in PC_ONLY_DOMAINS and host.environment_owner(domain) is None
    ]
    if not missing:
        return None

    # **꺼 둔 것을 먼저 가른다** (ADR-0043) — 태스크 종류와 같은 까닭이다. 환경을 주는 확장이
    # 깔려 있는데 꺼져 있으면 고치는 길은 「켜세요」이고, 「설치하세요」는 틀린 안내다.
    off = [
        f"{domain} ({owner.manifest.name} 확장)"
        for domain in missing
        if (owner := host.environment_provider(domain)) is not None and owner.off
    ]
    if off:
        return Finding(
            id=EXTENSION_TURNED_OFF,
            severity=SEVERITY_BLOCK,
            message="화면을 다루는 AI 태스크의 환경을 주는 확장이 꺼져 있습니다",
            items=tuple(off),
            fix_hint="확장 목록에서 그 확장을 켜세요",
        )
    return Finding(
        id=MISSING_ENVIRONMENT,
        severity=SEVERITY_BLOCK,
        message="화면을 다루는 AI 태스크의 환경을 줄 확장이 없습니다",
        items=tuple(missing),
        fix_hint="그 환경을 기여하는 확장을 설치하세요 (기본 제공: UI 자동화)",
    )


def _extension_findings(
    manifest: Manifest,
    *,
    host: ExtensionHost,
    context: Callable[[str], ExtensionContext],
    key_refs: tuple[str, ...],
) -> tuple[list[Finding], list[str]]:
    """확장이 기여한 점검들을 돌린다. **하나가 터지면 그것만 빼고 간다.**"""
    findings: list[Finding] = []
    skipped: list[str] = []
    for found in host.preflight_checks():
        where = found.extension_id
        try:
            target = PreflightTarget(extension=context(where), manifest=manifest, key_refs=key_refs)
            got: Sequence[Finding] = found.value.check(target)
        except Exception as e:  # noqa: BLE001 - 점검이 실행을 막지 않는다 (규약)
            LOG.warning("확장 %s의 사전 점검을 돌리지 못했다: %s", where, e)
            skipped.append(f"{where}: {e}")
            continue
        findings.extend(got)
    return findings, skipped


def check(
    manifest: Manifest,
    *,
    key_value: Callable[[str], str | None],
    host: ExtensionHost | None = None,
    context: Callable[[str], ExtensionContext] | None = None,
    fix_hint: str | None = None,
) -> Preflight:
    """그 Bot을 이 PC에서 지금 돌릴 수 있나.

    - `key_value`: 키 참조 이름 → 값(없으면 `None`). Bot UI는 `Credentials.service_app_key`,
      Studio는 `StudioCredentials` 쪽이다 — **값을 가진 쪽은 실행하는 쪽이다** (ADR-0013).
    - `host`: 없으면 확장 점검과 확장·환경 점검을 건너뛴다 (확장 없는 Bot UI도 Bot은 돈다).
    - `context`: 확장 id → 그 확장의 바깥 세상. `host`가 있어도 이것이 없으면 **확장 점검만**
      건너뛴다 (플랫폼 점검은 그대로 돈다).
    - `fix_hint`: 키가 없을 때 「어떻게 고치나」 한 줄. 화면 이름이 들어가므로 **부르는 쪽이 적는다**
      (Bot UI는 BUI-10, Studio는 STU-10).
    """
    findings: list[Finding] = []
    skipped: list[str] = []

    keys = _check_keys(manifest, key_value, fix_hint=fix_hint)
    if keys is not None:
        findings.append(keys)

    if host is not None:
        for platform_check in (_check_task_types, _check_extensions, _check_environments):
            found = platform_check(manifest, host)
            if found is not None:
                findings.append(found)
        if context is not None:
            more, could_not = _extension_findings(
                manifest, host=host, context=context, key_refs=key_refs_of(manifest)
            )
            findings.extend(more)
            skipped.extend(could_not)

    return Preflight(findings=tuple(findings), skipped=tuple(skipped))
