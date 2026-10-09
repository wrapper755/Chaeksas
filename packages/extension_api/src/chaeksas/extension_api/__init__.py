"""확장이 구현하는 안정 인터페이스 — 태스크 종류·수행기, 편집기, 유틸리티, 로컬 런타임 (ADR-0018).

확장을 만드는 쪽은 **이 패키지만** import한다. `core`·`apps/*`는 보지 않는다 (의존 방향은
`docs/01-architecture.md` §5, `tests/test_import_direction.py`가 막는다).

| 기여 지점 (C13) | 구현할 것 |
| --- | --- |
| `task_types[].executor` | `TaskExecutor` |
| `task_types[].editor`, `studio.editors` | `TaskEditor` (`kind="schema"`면 필요 없다) |
| `bot_ui.utilities` | `BotUiUtility` |
| `preflight` | `PreflightCheck` |
| `bot_ui.local_runtimes` | `LocalRuntimeEntry` (자식 프로세스에서 불린다) |
| `agent_environments` | `AgentEnvironment` → `AgentSession`·`AgentTool` (AI 태스크의 눈과 손, ADR-0037) |
| `studio.resource_views`, `console.pages`, `resources`, `configuration` | (없음 — 선언뿐) |
| 외부 앱 (`service.adapter`) | (없음 — `core`의 해석기가 부른다. 규격은 `http_adapter`) |

확장 정의(`extension.json`)의 모델과 검사 규칙은 계약에 있다 (`chaeksas.contracts.extension`).
찾아서 켜는 쪽은 `chaeksas.core.extensions` (확장 호스트)다.

    # extensions/<id>/src/chaeksas/ext/<id>/client.py
    from chaeksas.extension_api import TaskContext, TaskExecutor, TaskOutcome

    class MyTaskExecutor:                       # Protocol이라 상속하지 않는다
        def execute(self, ctx: TaskContext) -> TaskOutcome:
            return TaskOutcome(outputs={"ok": True})

버전 규칙은 `_meta`에 있다 — 이름·서명을 바꾸면 주 번호를 올리고, 옛 확장은 「호환 안 됨」이 된다.
"""

from chaeksas.extension_api._meta import API_VERSION
from chaeksas.extension_api.contributions import (
    SEVERITIES,
    SEVERITY_BLOCK,
    SEVERITY_INFO,
    SEVERITY_WARN,
    AgentEnvironment,
    AgentSession,
    AgentTool,
    BotUiUtility,
    Finding,
    LocalRuntimeEntry,
    PreflightCheck,
    PreflightTarget,
    TaskEditor,
    TaskExecutor,
)
from chaeksas.extension_api.entry import (
    EXTENSION_NAMESPACE,
    EntryError,
    module_root,
    resolve,
    split_entry,
)
from chaeksas.extension_api.http_adapter import AdapterCall, AdapterCaller, AdapterOutcome
from chaeksas.extension_api.runtime import (
    ESCALATE_CONFIRMATION,
    HOST_BOT_UI,
    HOST_SERVER_RUNNER,
    HOST_STUDIO,
    RUN_LOCATION_PC,
    RUN_LOCATION_SERVER,
    ExtensionContext,
    ExtensionEvent,
    Mode,
    Secrets,
    Settings,
    TaskContext,
    TaskFailed,
    TaskOutcome,
)

__all__ = [
    "API_VERSION",
    # AI 환경
    "AgentEnvironment",
    "AgentSession",
    "AgentTool",
    # 수행
    "ESCALATE_CONFIRMATION",
    "ExtensionContext",
    "ExtensionEvent",
    "Mode",
    "RUN_LOCATION_PC",
    "RUN_LOCATION_SERVER",
    "HOST_BOT_UI",
    "HOST_SERVER_RUNNER",
    "HOST_STUDIO",
    "Secrets",
    "Settings",
    "TaskContext",
    "TaskFailed",
    "TaskOutcome",
    # 기여
    "BotUiUtility",
    "Finding",
    "LocalRuntimeEntry",
    "PreflightCheck",
    "PreflightTarget",
    "SEVERITIES",
    "SEVERITY_BLOCK",
    "SEVERITY_INFO",
    "SEVERITY_WARN",
    "TaskEditor",
    "TaskExecutor",
    # entry 해석
    "EXTENSION_NAMESPACE",
    "EntryError",
    "module_root",
    "resolve",
    "split_entry",
    # HTTP 어댑터 해석기 규격
    "AdapterCall",
    "AdapterCaller",
    "AdapterOutcome",
]
