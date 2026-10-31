"""서버에서 돌 수 있다고 **선언한** 확장 태스크 하나 — 시험용 (ADR-0064).

저장소에 확장이 **하나도 없다** (ADR-0114). 그래서 「서버 실행기가 확장 태스크를 정말 수행하는가」를
보려면 가짜 하나가 필요하다 — 확장 호스트가 `root` 밖을 가리키지 못하게 하므로(C13 `entry`) 이 모듈이 **그 확장의 패키지
자리**를 맡는다.

**스레드를 건너 값을 보여 준다** — 실행기는 실행 하나를 스레드 하나로 돌리므로(ADR-0054 §5)
모듈 수준에 적어 두고 시험이 그것을 읽는다.
"""

from __future__ import annotations

from typing import Any

from chaeksas.extension_api import TaskContext, TaskOutcome

#: 수행된 태스크마다 한 줄 — `(node_id, 실행 위치, 런타임 포트)`.
CALLS: list[tuple[str, str, Any]] = []


class ServerTaskExecutor:
    """`extension_api.TaskExecutor` — 받은 것을 적고 정해진 값을 돌려준다.

    **걷은 예약 키를 묻는다** (`runtime.worker.port`) — **`None`이어야 한다**: 로컬 런타임은 없고
    호스트가 그 이름을 채우지 않는다 (ADR-0064·ADR-0114).
    """

    def execute(self, ctx: TaskContext) -> TaskOutcome:
        CALLS.append((ctx.node_id, ctx.run_location, ctx.extension.setting("runtime.worker.port")))
        return TaskOutcome(outputs={"요약": "세 줄로 줄였습니다"})
