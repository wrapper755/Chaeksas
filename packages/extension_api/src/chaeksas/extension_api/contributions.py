"""확장이 **구현하는** 것 — 기여 지점마다 하나씩 (ADR-0018 §2).

모두 `Protocol`이다. 확장은 상속하지 않고 모양만 맞추면 된다. 호스트는 `entry`로 찾은 객체가
이 모양인지 보고 켠다.

**Qt를 import하지 않는다.** 화면을 만드는 기여(`TaskEditor`·`BotUiUtility`)는 위젯을 `object`로
돌려준다. `core`가 이 패키지를 쓰는데 `core`는 Qt를 모르기 때문이다 (01-architecture §5).
위젯을 받아 붙이는 것은 Studio·Bot UI의 몫이다.

로컬 런타임(`bot_ui.local_runtimes`)에는 여기 인터페이스가 없다 — **선언뿐이고**, 띄우고 감시하는
것은 Bot UI다 (C13, BUI-09·11).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from chaeksas.contracts.manifest import Manifest
from chaeksas.extension_api.runtime import ExtensionContext, TaskContext, TaskOutcome

#: 사전 점검 결과의 등급. `block`만 실행·배포를 막는다.
SEVERITY_BLOCK = "block"
SEVERITY_WARN = "warn"
SEVERITY_INFO = "info"
SEVERITIES = frozenset({SEVERITY_BLOCK, SEVERITY_WARN, SEVERITY_INFO})


@runtime_checkable
class TaskExecutor(Protocol):
    """태스크 종류 하나를 수행한다 (`task_types[].executor`).

    실패는 `TaskFailed`로 알린다. **모드를 바꾸지 않는다** — 받은 `ctx.mode`를 그대로 따른다
    (계약 README 원칙 7).
    """

    def execute(self, ctx: TaskContext) -> TaskOutcome: ...


@runtime_checkable
class TaskEditor(Protocol):
    """Studio 속성 패널의 태스크 편집기 (`task_types[].editor`, `studio.editors`).

    `editor.kind="schema"`면 이것이 필요 없다 — Studio가 입력 JSON Schema로 자동 폼을 만든다.
    """

    def widget(self, ctx: ExtensionContext) -> object:
        """편집기 위젯 (Qt). 호스트가 속성 패널에 붙인다."""
        ...

    def load(self, properties: Mapping[str, Any]) -> None:
        """BPMN `chk:*` 속성(C14)을 칸에 채운다."""
        ...

    def dump(self) -> Mapping[str, Any]:
        """칸의 값을 BPMN `chk:*` 속성으로 돌려준다."""
        ...


@runtime_checkable
class BotUiUtility(Protocol):
    """Bot UI 「도구」 메뉴·탭의 유틸리티 (`bot_ui.utilities`, 예: BUI-06~08 셀렉터 등록)."""

    def widget(self, ctx: ExtensionContext) -> object:
        """탭에 붙일 위젯 (Qt)."""
        ...

    def closed(self) -> None:
        """탭을 닫을 때. 잡아 둔 자원(로컬 런타임 세션 등)을 놓는다."""
        ...


@dataclass(frozen=True)
class Finding:
    """사전 점검이 찾은 것 하나. 화면에 한 줄로 보인다 (STU-16·BUI-04)."""

    id: str
    severity: str  # SEVERITIES
    message: str
    items: tuple[str, ...] = ()
    #: 「어떻게 고치나」 한 줄 (예: 「실행 위치를 PC로 바꾸세요」).
    fix_hint: str | None = None

    @property
    def blocks(self) -> bool:
        return self.severity == SEVERITY_BLOCK


@dataclass(frozen=True)
class PreflightTarget:
    """무엇을 점검하나 — 그 BPM 프로세스의 매니페스트(C1)와 돌릴 자리."""

    extension: ExtensionContext
    manifest: Manifest
    #: 쓰려는 서비스 앱 키 참조 이름들 (값이 있나 보려고). 값은 `extension.secret()`로 푼다.
    key_refs: tuple[str, ...] = field(default_factory=tuple)


@runtime_checkable
class PreflightCheck(Protocol):
    """실행 전 점검 하나 (`preflight`). 서버를 부르지 않고 끝낼 수 있으면 그렇게 한다.

    점검은 **막지 않는다** — 결과를 돌려주고, 막을지는 호스트가 `severity`로 정한다.
    """

    def check(self, target: PreflightTarget) -> Sequence[Finding]: ...
