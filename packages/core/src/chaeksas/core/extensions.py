"""확장 호스트 — 확장을 찾아 기여를 등록한다 (ADR-0018).

**플랫폼은 특정 확장을 모른다.** Studio·Bot UI·실행기·서버 실행기는 시작할 때 이 호스트를 만들어
엔트리 포인트(`chaeksas.extensions`)로 찾은 확장 정의(C13)를 읽고, 기여 지점별 목록을 묻는다.
확장 이름이 플랫폼 코드에 나오지 않는다 (`tests/test_import_direction.py`가 막는다).

    host = ExtensionHost()
    host.load_entry_points()
    for found in host.task_types():          # Studio 팔레트
        palette.add(found.value.label, task_type=found.value.id)
    executor = host.executor("ui_task")      # 실행기

켜지 않는 경우가 세 가지다. 어느 쪽이든 **조용히 사라지지 않는다** — `disabled()`에 사유(`Violation`)와
함께 남아 화면에 「호환 안 됨」·「쓸 수 없음」으로 보인다 (BUI-01, STU-15, CON-07).

1. 정의가 검사 규칙에 걸렸다 (C13 E1·E3, 모양).
2. `api` 범위가 이 호스트의 `extension_api`와 맞지 않는다 (E5).
3. 이미 있는 확장과 `id`가 겹치거나, 태스크 종류가 겹친다 (E4).

**그리고 네 번째가 있다 — 사람이 껐다** ([ADR-0043](../../../../../docs/decisions/0043-turned-off-extensions.md)).
위 셋은 **흠**이고(`problems`), 이것은 멀쩡한데 **일부러 안 쓰는 것**이다(`off`). 둘을 섞으면
화면이 「고치세요」와 「켜세요」 중 틀린 쪽을 안내한다. 끌 id는 **부르는 쪽이 준다**
(`ExtensionHost(off=[...])`) — 플랫폼 코드가 확장 이름을 알지 않는다.

    host = ExtensionHost(off=settings.disabled_extensions)

**꺼진 확장은 기여를 하나도 내지 않는다** — 태스크 종류·편집기·런타임·점검이 한꺼번에 사라진다.
늦게(실행할 때) 죽는 것보다 낫다. 그래서 겹침(E4·E8)도 **꺼지지 않은 것들 사이에서만** 본다.

**코드는 설치 파일에 든 확장(내장·사내)에서만 돌린다** (ADR-0018 §3). 외부 확장의 정의에 `entry`가
있으면 E1에 걸려 켜지지 않고, 켜진 확장의 `entry`도 그 확장의 패키지 안만 가리킬 수 있다.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from importlib.metadata import entry_points
from importlib.resources import files
from typing import Any

from chaeksas.contracts._base import Violation
from chaeksas.contracts.bot_ui import ExtensionState
from chaeksas.contracts.extension import (
    ENTRY_POINT_GROUP,
    EXTENSION_FILE,
    AdapterOperation,
    AgentEnvironmentContribution,
    ConfigurationItem,
    ConsolePage,
    ExtensionManifest,
    LocalRuntime,
    Panel,
    PreflightContribution,
    ResourceContribution,
    ResourceView,
    StudioEditorContribution,
    TaskTypeContribution,
    Utility,
    check_api,
    check_size,
    definition_hash,
    validate,
    verify_external,
)
from chaeksas.contracts.signing import AdminKey, Envelope
from chaeksas.extension_api import (
    API_VERSION,
    AgentEnvironment,
    BotUiPanel,
    BotUiUtility,
    EntryError,
    ExtensionContext,
    LocalRuntimeEntry,
    PreflightCheck,
    Secrets,
    Settings,
    TaskEditor,
    TaskExecutor,
)
from chaeksas.extension_api.entry import resolve as resolve_entry

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class Contribution[T]:
    """기여 하나와 **누가 기여했나**. 플랫폼은 늘 이 짝으로 다룬다 (사유를 사람에게 보이려고)."""

    extension_id: str
    extension_version: str
    value: T


@dataclass(frozen=True)
class LoadedExtension:
    """읽어 들인 확장 하나."""

    manifest: ExtensionManifest
    definition_hash: str
    #: 어디서 왔나 — `entry_point:<이름>` 또는 `center`.
    origin: str
    #: 코드 기여를 찾을 파이썬 패키지. 외부 확장은 `None` (코드가 없다).
    root: str | None = None
    #: 비어 있지 않으면 켜지 않는다. **흠이다** — 고쳐야 할 것.
    problems: tuple[Violation, ...] = ()
    #: **사람이 껐다** (ADR-0043). 흠이 아니라 뜻이다 — `problems`와 섞지 않는다.
    off: bool = False

    @property
    def id(self) -> str:
        return self.manifest.id

    @property
    def version(self) -> str:
        return self.manifest.version

    @property
    def enabled(self) -> bool:
        """**지금 쓰이는가** — 흠이 없고 꺼지지도 않았다. 부르는 쪽의 뜻은 그대로다."""
        return not self.problems and not self.off

    def state(self) -> ExtensionState:
        """C4·C12 보고용 (`{id, version, definition_hash, enabled, off}`)."""
        return ExtensionState(
            id=self.id,
            version=self.version,
            definition_hash=self.definition_hash,
            enabled=self.enabled,
            off=self.off,
        )


@dataclass(frozen=True)
class LoadFailure:
    """정의를 읽지도 못한 경우 (파일이 없다, JSON이 깨졌다, 필수 필드가 없다).

    id를 모르므로 `LoadedExtension`을 만들 수 없다. 화면에는 출처와 사유만 보인다.
    """

    origin: str
    message: str


class ExtensionHost:
    """확장 목록과 기여 지점. 실행하는 쪽마다 하나씩 만든다."""

    def __init__(self, *, api_version: str = API_VERSION, off: Iterable[str] = ()) -> None:
        self.api_version = api_version
        #: 사람이 꺼 둔 확장 id (ADR-0043). **부르는 쪽이 준다** — 플랫폼은 어느 확장인지 모른다.
        self.off = frozenset(off)
        self._loaded: list[LoadedExtension] = []
        self._failures: list[LoadFailure] = []
        self._executors: dict[str, TaskExecutor] = {}
        self._environments: dict[str, AgentEnvironment] = {}

    # ─────────────────────────── 찾기 ───────────────────────────

    def load_entry_points(self, *, group: str = ENTRY_POINT_GROUP) -> list[LoadedExtension]:
        """설치된 확장(내장·사내)을 엔트리 포인트로 찾는다.

        엔트리 포인트의 값은 **확장의 파이썬 패키지**이고, 그 패키지 안에 `extension.json`이 있다
        (C13 「전송」). 설치 파일로 묶을 때 이것이 살아 있는지는 스파이크 S5가 본다.

            [project.entry-points."chaeksas.extensions"]
            ui-automation = "chaeksas.ext.ui_automation"

        하나가 깨져도 나머지는 켠다 — 사유는 `failures`·`disabled()`에 남는다.
        """
        found: list[LoadedExtension] = []
        for ep in sorted(entry_points(group=group), key=lambda e: e.name):
            origin = f"entry_point:{ep.name}"
            try:
                raw = (files(ep.value) / EXTENSION_FILE).read_bytes()
            except (ModuleNotFoundError, FileNotFoundError, OSError, TypeError) as e:
                self._failures.append(LoadFailure(origin=origin, message=f"{EXTENSION_FILE}을 읽을 수 없다: {e}"))
                continue
            loaded = self.add_installed(raw, origin=origin, root=ep.value)
            if loaded is not None:
                found.append(loaded)
        return found

    def add_installed(self, raw: bytes, *, origin: str, root: str) -> LoadedExtension | None:
        """설치 파일에 들어 있는 확장 정의 하나 — 엔트리 포인트 말고 다른 길로 넣을 때.

        사내 확장을 설치 파일 빌드 때 포함 목록으로 넣는 길(ADR-0018 §5)과 시험이 쓴다.
        `root`는 그 확장의 파이썬 패키지다 — `entry`가 그 밖을 가리키지 못하게 한다.
        """
        return self._add_bytes(raw, origin=origin, root=root)

    def add_external(
        self,
        definition: Mapping[str, Any],
        envelope: Envelope,
        *,
        keys: Sequence[AdminKey],
    ) -> LoadedExtension | None:
        """Center에서 받은 외부 확장 정의 하나 (C7 리소스 목록).

        **봉투를 다시 검증한다** (C13 E6). 관리자 토큰만 새어도 Bot의 키·업무 값이 다른 주소로
        새는 일을 막으려고, 실행하는 쪽이 Admin 서명을 직접 본다.
        """
        problems = verify_external(definition, envelope, keys=keys)
        return self._add_definition(definition, origin="center", root=None, extra=problems, from_center=True)

    def _add_bytes(self, raw: bytes, *, origin: str, root: str | None) -> LoadedExtension | None:
        problems = check_size(raw)
        try:
            definition = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as e:
            self._failures.append(LoadFailure(origin=origin, message=f"{EXTENSION_FILE}이 JSON이 아니다: {e}"))
            return None
        if not isinstance(definition, dict):
            self._failures.append(LoadFailure(origin=origin, message=f"{EXTENSION_FILE}의 최상위가 객체가 아니다"))
            return None
        return self._add_definition(definition, origin=origin, root=root, extra=problems, from_center=False)

    def _add_definition(
        self,
        definition: Mapping[str, Any],
        *,
        origin: str,
        root: str | None,
        extra: Sequence[Violation],
        from_center: bool,
    ) -> LoadedExtension | None:
        try:
            # pydantic의 ValidationError는 ValueError다 — core가 pydantic을 직접 import하지 않는다.
            manifest = ExtensionManifest.model_validate(definition)
        except ValueError as e:
            summary = " / ".join(str(e).splitlines()[:3])
            self._failures.append(LoadFailure(origin=origin, message=f"정의가 C13과 맞지 않는다: {summary}"))
            return None

        turned_off = manifest.id in self.off
        problems = (
            []
            if turned_off
            # 꺼 둔 것은 **검사하지 않는다** — 기여를 내지 않으니 겹칠 일도 없고, 흠을 함께
            # 적으면 화면이 「꺼짐」과 「호환 안 됨」 중 무엇을 보일지 다투게 된다 (ADR-0043).
            else [
                *extra,
                *validate(manifest, from_center=from_center),
                *check_api(manifest, api_version=self.api_version),
                *self._conflicts(manifest),
            ]
        )
        loaded = LoadedExtension(
            manifest=manifest,
            definition_hash=definition_hash(definition),
            origin=origin,
            off=turned_off,
            root=root if manifest.can_contribute_code else None,
            problems=tuple(problems),
        )
        self._loaded.append(loaded)
        if problems:
            LOG.warning("확장 %s@%s를 켜지 않는다: %s", loaded.id, loaded.version, [str(p) for p in problems])
        return loaded

    def _conflicts(self, manifest: ExtensionManifest) -> list[Violation]:
        """이미 켠 확장과 겹치는가 (E4, 그리고 하나뿐인 이름 공간).

        **나중에 온 쪽이 진다.** 먼저 켜진 확장이 계속 돌아야 한다 (실행 중인 Bot이 쓰고 있다).

        **꺼 둔 확장은 세지 않는다** (`enabled()`가 이미 거른다, ADR-0043) — 기여를 내지 않으니
        이름을 쥐고 있지 않다. 껐던 것을 다시 켜서 겹치면 그때 **그쪽이** 켜지지 않는다.
        """
        out: list[Violation] = []
        if any(e.id == manifest.id for e in self.enabled()):
            out.append(
                Violation(
                    rule="C13",
                    code="id_conflict",
                    message=f"확장 id {manifest.id}이 이미 있다 (확장·서비스 앱은 이름 공간을 함께 쓴다)",
                )
            )
        taken = {found.value.id: found.extension_id for found in self.task_types()}
        clashing = [t.id for t in manifest.contributes.task_types if t.id in taken]
        if clashing:
            out.append(
                Violation(
                    rule="E4",
                    code="task_type_conflict",
                    message=f"태스크 종류를 다른 확장이 이미 기여했다 ({', '.join(taken[t] for t in clashing)})",
                    items=clashing,
                )
            )
        owned = {found.value.domain: found.extension_id for found in self.agent_environments()}
        doubled = [e.domain for e in manifest.contributes.agent_environments if e.domain in owned]
        if doubled:
            out.append(
                Violation(
                    rule="E8",
                    code="environment_conflict",
                    message=f"AI 환경을 다른 확장이 이미 기여했다 ({', '.join(owned[d] for d in doubled)})",
                    items=doubled,
                )
            )
        return out

    # ─────────────────────────── 목록 ───────────────────────────

    def all(self) -> list[LoadedExtension]:
        """읽어 들인 모두 (켜지 않은 것까지). 화면 목록이 이것을 쓴다."""
        return list(self._loaded)

    def enabled(self) -> list[LoadedExtension]:
        return [e for e in self._loaded if e.enabled]

    def disabled(self) -> list[LoadedExtension]:
        """지금 쓰이지 않는 것 — **흠이 있는 것과 꺼 둔 것이 함께** 온다 (`off`로 가른다)."""
        return [e for e in self._loaded if not e.enabled]

    def turned_off(self) -> list[LoadedExtension]:
        """사람이 꺼 둔 것만 (ADR-0043)."""
        return [e for e in self._loaded if e.off]

    def provider_of(self, task_type_id: str) -> LoadedExtension | None:
        """그 태스크 종류를 기여한 확장 — **꺼 둔 것·흠이 있는 것까지** 본다.

        `task_type()`은 **지금 쓸 수 있는** 것만 주므로 「없다」와 「꺼 뒀다」를 가르지 못한다.
        사전 점검이 그 둘에 **다른 고치는 길**을 안내하려고 쓴다 (`core.preflight`).
        """
        found = [e for e in self._loaded if e.manifest.task_type(task_type_id) is not None]
        return next((e for e in found if e.enabled), found[0] if found else None)

    def environment_provider(self, domain: str) -> LoadedExtension | None:
        """그 AI 환경을 기여한 확장 — **꺼 둔 것·흠이 있는 것까지** 본다 (`provider_of`와 같은 결).

        `environment_owner()`는 **지금 쓸 수 있는** 것만 주므로 「없다」와 「꺼 뒀다」를 가르지
        못한다. 사전 점검이 그 둘에 다른 고치는 길을 안내하려고 쓴다 (ADR-0043).
        """
        found = [
            e
            for e in self._loaded
            if any(c.domain == domain for c in e.manifest.contributes.agent_environments)
        ]
        return next((e for e in found if e.enabled), found[0] if found else None)

    @property
    def failures(self) -> list[LoadFailure]:
        """정의를 읽지도 못한 것들."""
        return list(self._failures)

    def get(self, extension_id: str) -> LoadedExtension | None:
        """그 id의 확장. 같은 id가 여럿이면(앞선 것이 켜지지 않아 들어온 경우) **켠 쪽**을 준다."""
        matches = [e for e in self._loaded if e.id == extension_id]
        return next((e for e in matches if e.enabled), matches[0] if matches else None)

    def states(self) -> list[ExtensionState]:
        """C4 하트비트·C12 등록에 싣는 설치된 확장 목록."""
        return [e.state() for e in self._loaded]

    # ─────────────────────────── 기여 지점 ───────────────────────────

    def _gather[T](self, pick: Callable[[ExtensionManifest], Iterable[T]]) -> list[Contribution[T]]:
        return [
            Contribution(extension_id=e.id, extension_version=e.version, value=value)
            for e in self.enabled()
            for value in pick(e.manifest)
        ]

    def task_types(self) -> list[Contribution[TaskTypeContribution]]:
        """Studio 팔레트·속성 편집기, 실행기의 태스크 수행."""
        return self._gather(lambda m: m.contributes.task_types)

    def task_type(self, task_type_id: str) -> Contribution[TaskTypeContribution] | None:
        return next((c for c in self.task_types() if c.value.id == task_type_id), None)

    def agent_environments(self) -> list[Contribution[AgentEnvironmentContribution]]:
        """AI 태스크의 `web`·`desktop` 환경 (C13 `agent_environments`, ADR-0037)."""
        return self._gather(lambda m: m.contributes.agent_environments)

    def studio_editors(self) -> list[Contribution[StudioEditorContribution]]:
        return self._gather(lambda m: m.contributes.studio_editors)

    def resource_views(self) -> list[Contribution[ResourceView]]:
        """Studio 리소스 탐색기(STU-03)의 갈래들."""
        return self._gather(lambda m: m.contributes.studio_resource_views)

    def utilities(self) -> list[Contribution[Utility]]:
        """Bot UI 「도구」 메뉴·탭."""
        return self._gather(lambda m: m.contributes.bot_ui_utilities)

    def panels(self, surface: str) -> list[Contribution[Panel]]:
        """그 자리에 낼 칸들 (`bot_ui.panels`, ADR-0042).

        **자리 이름으로만 고른다** — 호스트는 자기가 아는 자리를 묻고, **모르는 자리를 가리키는
        칸은 조용히 사라진다** (새 확장이 가리키는 자리를 옛 Bot UI가 모를 수 있다).
        """
        return [c for c in self._gather(lambda m: m.contributes.bot_ui_panels) if c.value.surface == surface]

    def local_runtimes(self) -> list[Contribution[LocalRuntime]]:
        """Bot UI가 띄우고 감시할 로컬 프로세스 (BUI-09·11). **선언뿐이다.**"""
        return self._gather(lambda m: m.contributes.bot_ui_local_runtimes)

    def configuration(self, *, scope: str | None = None) -> list[Contribution[ConfigurationItem]]:
        """설정 화면의 칸들. `scope`로 거른다 (`bot_ui`·`studio`·`server_runner`)."""
        items: list[Contribution[ConfigurationItem]] = self._gather(lambda m: m.contributes.configuration)
        return [c for c in items if scope is None or c.value.scope == scope]

    def preflight(self) -> list[Contribution[PreflightContribution]]:
        return self._gather(lambda m: m.contributes.preflight)

    def console_pages(self) -> list[Contribution[ConsolePage]]:
        return self._gather(lambda m: m.contributes.console_pages)

    def resources(self) -> list[Contribution[ResourceContribution]]:
        """Center 리소스 목록(C7)에 올릴 갈래와 카탈로그 주소."""
        return self._gather(lambda m: m.contributes.resources)

    def adapter_operations(self) -> list[Contribution[AdapterOperation]]:
        """외부 확장이 선언한 작업들 (C13 §4).

        C11을 따르는 서비스 앱의 작업은 여기 없다 — 그쪽은 앱의 `/manifest`에서 온다 (C7).
        """
        return self._gather(lambda m: m.adapter.operations if m.adapter else [])

    def secret_config_keys(self) -> list[Contribution[ConfigurationItem]]:
        """OS 비밀 저장소에 둬야 하는 칸들 (ADR-0013). 설정 파일·로그에 남기지 않는다."""
        return [c for c in self.configuration() if c.value.secret]

    # ─────────────────────────── 코드 ───────────────────────────

    def context(
        self,
        extension_id: str,
        *,
        host: str,
        settings: Settings,
        secrets: Secrets,
        log: logging.Logger | None = None,
    ) -> ExtensionContext:
        """확장 코드에 넘길 바깥 세상. 설정·비밀은 호스트가 확장별로 갈라 준다."""
        found = self.get(extension_id)
        if found is None or not found.enabled:
            raise LookupError(f"켜진 확장이 아니다: {extension_id}")
        return ExtensionContext(
            extension_id=found.id,
            extension_version=found.version,
            api_version=self.api_version,
            host=host,
            settings=settings,
            secrets=secrets,
            log=log or logging.getLogger(f"chaeksas.ext.{extension_id}"),
        )

    def _instantiate(self, found: LoadedExtension, entry: str, *, expect: type, what: str) -> Any:
        """`entry`가 가리키는 것을 만든다. **그 확장의 패키지 안만** 가리킬 수 있다.

        가리키는 것이 클래스면 인자 없이 만들고, 이미 만들어진 객체면 그대로 쓴다.
        """
        if found.root is None:
            raise LookupError(f"확장 {found.id}은 코드를 기여할 수 없다 (등급 {found.manifest.tier})")
        obj = resolve_entry(entry, root=found.root)
        instance = obj() if isinstance(obj, type) else obj
        if not isinstance(instance, expect):
            raise EntryError(f"{entry}는 {what}({expect.__name__})의 모양이 아니다")
        return instance

    def executor(self, task_type_id: str) -> TaskExecutor:
        """태스크 종류를 수행할 객체. 한 번 만들면 호스트가 들고 있는다 (수행마다 `ctx`를 받는다)."""
        cached = self._executors.get(task_type_id)
        if cached is not None:
            return cached
        found = self.task_type(task_type_id)
        if found is None:
            raise LookupError(f"기여된 태스크 종류가 아니다: {task_type_id}")
        if found.value.executor is None:
            raise LookupError(f"태스크 종류 {task_type_id}에 수행기가 없다")
        owner = self.get(found.extension_id)
        assert owner is not None
        executor: TaskExecutor = self._instantiate(
            owner, found.value.executor.entry, expect=TaskExecutor, what="수행기"
        )
        self._executors[task_type_id] = executor
        return executor

    def environment(self, domain: str) -> AgentEnvironment | None:
        """그 domain의 AI 환경. 기여한 확장이 없으면 `None` — 엔진이 그림·설치 오류로 올린다.

        한 domain은 한 확장만 기여한다 (E8 — 나중에 온 확장은 켜지 않는다).
        """
        found = [c for c in self.agent_environments() if c.value.domain == domain]
        if len(found) != 1:
            if found:
                LOG.warning("AI 환경 %s을 여러 확장이 기여한다 (E8) — 쓰지 않는다", domain)
            return None
        cached = self._environments.get(domain)
        if cached is not None:
            return cached
        owner = self.get(found[0].extension_id)
        assert owner is not None
        made: AgentEnvironment = self._instantiate(
            owner, found[0].value.entry, expect=AgentEnvironment, what="AI 환경"
        )
        self._environments[domain] = made
        return made

    def environment_owner(self, domain: str) -> str | None:
        """그 AI 환경을 기여한 확장 id — 엔진이 그 확장의 바깥 세상(`context`)을 함께 준다."""
        found = [c for c in self.agent_environments() if c.value.domain == domain]
        return found[0].extension_id if len(found) == 1 else None

    def editor(self, task_type_id: str) -> TaskEditor | None:
        """Studio 속성 패널에 붙일 편집기. `kind="schema"`면 `None` — 자동 폼을 쓴다 (STU-14).

        편집기는 열 때마다 새로 만든다 (칸의 상태를 들고 있다).
        """
        found = self.task_type(task_type_id)
        if found is None:
            raise LookupError(f"기여된 태스크 종류가 아니다: {task_type_id}")
        owner = self.get(found.extension_id)
        assert owner is not None
        separate = next((c for c in self.studio_editors() if c.value.task_type == task_type_id), None)
        if separate is not None:
            owner = self.get(separate.extension_id) or owner
            from_contribution: TaskEditor = self._instantiate(
                owner, separate.value.entry, expect=TaskEditor, what="편집기"
            )
            return from_contribution
        editor = found.value.editor
        if editor is None or editor.kind != "builtin" or not editor.entry:
            return None
        from_task_type: TaskEditor = self._instantiate(owner, editor.entry, expect=TaskEditor, what="편집기")
        return from_task_type

    def utility(self, utility_id: str) -> BotUiUtility:
        """Bot UI 「도구」의 유틸리티. 탭을 열 때마다 새로 만든다."""
        found = next((c for c in self.utilities() if c.value.id == utility_id), None)
        if found is None:
            raise LookupError(f"기여된 유틸리티가 아니다: {utility_id}")
        owner = self.get(found.extension_id)
        assert owner is not None
        utility: BotUiUtility = self._instantiate(owner, found.value.entry, expect=BotUiUtility, what="유틸리티")
        return utility

    def panel(self, extension_id: str, panel_id: str) -> BotUiPanel:
        """플랫폼 화면의 한 칸을 그릴 것 (`bot_ui.panels`, ADR-0042).

        화면을 만들 때 한 번 만들고 호스트가 들고 있는다 (`refresh()`를 주기마다 부른다).
        """
        owner = self.get(extension_id)
        if owner is None or not owner.enabled:
            raise LookupError(f"켜진 확장이 아니다: {extension_id}")
        declared = next((p for p in owner.manifest.contributes.bot_ui_panels if p.id == panel_id), None)
        if declared is None:
            raise LookupError(f"확장 {extension_id}에 기여된 화면 칸이 아니다: {panel_id}")
        made: BotUiPanel = self._instantiate(owner, declared.entry, expect=BotUiPanel, what="화면 칸")
        return made

    def local_runtime(self, extension_id: str, runtime_id: str) -> LocalRuntimeEntry:
        """로컬 런타임의 진입점 (`<확장 id>:<런타임 id>`).

        **자식 프로세스 안에서** 쓰는 길이다. Bot UI가 자기 실행 파일을 `--local-runtime
        <확장 id>:<런타임 id>`로 다시 띄우면, 그 자식이 이것으로 진입점을 풀어 부른다
        (ADR-0024). 띄우고 감시하는 일 자체는 Bot UI의 몫이다.
        """
        owner = self.get(extension_id)
        if owner is None or not owner.enabled:
            raise LookupError(f"켜진 확장이 아니다: {extension_id}")
        declared = next((r for r in owner.manifest.contributes.bot_ui_local_runtimes if r.id == runtime_id), None)
        if declared is None:
            raise LookupError(f"확장 {extension_id}에 기여된 로컬 런타임이 아니다: {runtime_id}")
        entry: LocalRuntimeEntry = self._instantiate(
            owner, declared.entry, expect=LocalRuntimeEntry, what="로컬 런타임 진입점"
        )
        return entry

    def preflight_checks(self) -> list[Contribution[PreflightCheck]]:
        """사전 점검들. 하나가 만들어지지 않으면 그것만 빼고 기록한다 — 점검이 실행을 막지 않는다."""
        out: list[Contribution[PreflightCheck]] = []
        for found in self.preflight():
            owner = self.get(found.extension_id)
            if owner is None:
                continue
            try:
                check = self._instantiate(owner, found.value.entry, expect=PreflightCheck, what="사전 점검")
            except (EntryError, LookupError) as e:
                LOG.warning("확장 %s의 사전 점검 %s를 쓸 수 없다: %s", found.extension_id, found.value.id, e)
                continue
            out.append(
                Contribution(
                    extension_id=found.extension_id, extension_version=found.extension_version, value=check
                )
            )
        return out


def load_host(
    *, api_version: str = API_VERSION, group: str = ENTRY_POINT_GROUP, off: Iterable[str] = ()
) -> ExtensionHost:
    """설치된 확장을 모두 읽은 호스트 하나 — 실행하는 쪽이 시작할 때 부르는 길.

    끌 id는 **부르는 쪽이 준다** (ADR-0043 — 그 앱의 설정에서 온다).
    """
    host = ExtensionHost(api_version=api_version, off=off)
    host.load_entry_points(group=group)
    return host


@dataclass
class HostTasks:
    """확장 호스트를 엔진의 `RunEnv.extensions`로 — 실행하는 쪽(Studio 시험 실행·Bot UI 실행기)이 꽂는다.

    엔진은 확장을 모른다 (ADR-0018). 태스크 종류 이름으로 수행기를, AI 태스크 domain으로 환경을
    묻고(ADR-0037), 그 확장의 바깥 세상(`context`)을 받을 뿐이다.

    - 없는 태스크 종류는 **`None`** 이다 (엔진이 그림·설치 오류로 올린다). 호스트는 `LookupError`를 낸다.
    - `context`의 설정·비밀은 **실행하는 쪽이** 확장마다 갈라 준다 (`make_context`) — 예약 키
      (`runtime.<id>.*`·`service.base_url`)로 로컬 런타임과 서버 주소를 알려 준다 (C13).
    """

    host: ExtensionHost
    make_context: Callable[[str], ExtensionContext]

    def executor(self, task_type: str) -> TaskExecutor | None:
        try:
            return self.host.executor(task_type)
        except LookupError:
            return None

    def environment(self, domain: str) -> AgentEnvironment | None:
        return self.host.environment(domain)

    def environment_owner(self, domain: str) -> str | None:
        return self.host.environment_owner(domain)

    def context(self, extension_id: str) -> ExtensionContext:
        return self.make_context(extension_id)


def summarize(host: ExtensionHost) -> dict[str, list[str]]:
    """화면·로그에 한 줄로 쓰는 요약 (`{"enabled", "off", "disabled", "failed"}`).

    **꺼 둔 것을 「disabled」에 섞지 않는다** — 로그를 보는 사람이 고칠 거리로 읽는다 (ADR-0043).
    """
    return {
        "enabled": [f"{e.id}@{e.version}" for e in host.enabled()],
        "off": [f"{e.id}@{e.version}" for e in host.turned_off()],
        "disabled": [
            f"{e.id}@{e.version}: {'; '.join(str(p) for p in e.problems)}"
            for e in host.disabled()
            if not e.off
        ],
        "failed": [f"{f.origin}: {f.message}" for f in host.failures],
    }
