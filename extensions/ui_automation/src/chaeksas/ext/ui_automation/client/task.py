"""UI 태스크 수행기 — Bot이 Worker 프로세스에 UI 조작을 맡긴다 (C10).

> 상태: **뼈대만.** 실제 수행은 M4다 (`docs/05-roadmap.md`). 지금은 확장 호스트가 이 기여를
> 찾아 모양을 확인하는 데까지만 쓰인다.

실제 흐름은 이렇게 된다 (01-architecture §3).

1. `ctx.properties`의 UI 태스크 속성(C14 `chk:*`)과 `ctx.key_ref`로 푼 서비스 앱 키를 들고
2. 127.0.0.1의 Worker에 세션을 열어 (`ctx.business_key`로 세션을 잇는다)
3. Worker가 계획을 받아 로케이터 사다리를 로컬에서 돌리고
4. 결과를 `TaskOutcome.outputs`로 돌려준다. 모드는 **받은 그대로** 싣는다.
"""

from __future__ import annotations

from chaeksas.extension_api import TaskContext, TaskOutcome


class UiTaskExecutor:
    """`task_types[].executor` — `extension_api.TaskExecutor`."""

    def execute(self, ctx: TaskContext) -> TaskOutcome:
        raise NotImplementedError("UI 태스크 수행은 M4다 (Worker 로컬 API C10 구현과 함께)")
