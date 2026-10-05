"""데스크톱 AI 태스크의 눈과 손 — C13 `agent_environments`의 `desktop` (ADR-0037).

엔진은 이 확장을 모른다. `domain: desktop` AI 태스크를 만나면 실행하는 쪽에게 환경을 묻고,
여기가 **Worker 세션 하나**를 열어 도구 둘을 준다. 손은 UI 태스크와 같은 Worker다 — 세션 하나
규칙(ADR-0014)·창 안에서만 찾기·입력 확인·잠금 처리가 그대로다.

- `desktop_look` — 붙은 창의 UIA 트리를 줄글로 (입력한 값·표 칸·창 제목은 가린다).
- `desktop_act` — 로케이터 조건(`target`)으로 요소 **하나**를 조작하거나 읽는다.
  맞는 것이 하나가 아니면 **글로** 알린다 (모델이 조건을 고칠 수 있게).

도구 인자가 로케이터 조건이라 **재생된다** (ADR-0028) — 실행마다 같은 것을 가리킨다.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chaeksas.ext.ui_automation.client.task import WorkerClient, WorkerUnreachable, read_value, worker_for
from chaeksas.ext.ui_automation.contracts.plan import DESKTOP_STRATEGIES
from chaeksas.ext.ui_automation.contracts.worker_local import (
    CALLER_BOT,
    CALLER_STUDIO,
    KNOWN_ACTIONS,
    Caller,
    SessionInfo,
    SessionRequest,
    StepRequest,
)
from chaeksas.extension_api import HOST_STUDIO, AgentTool, TaskContext, TaskFailed

#: 도구 이름 — 예약이다 (C14 「`web`·`desktop` AI 태스크의 도구」).
LOOK = "desktop_look"
ACT = "desktop_act"

TARGET_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "요소 하나를 가리키는 조건. desktop_look에 보이는 aid·class·이름을 쓴다.",
    "properties": {
        "type": {"type": "string", "enum": list(DESKTOP_STRATEGIES)},
        "value": {"type": "string", "description": "automation_id·class_name·control_name의 값"},
        "control_type": {"type": "string", "description": "UIA 컨트롤 종류로 좁힌다 (예: Button, Edit)"},
        "exact": {"type": "boolean", "description": "control_name이 정확히 같아야 하나 (기본: 부분 일치)"},
    },
    "required": ["type", "value"],
}


@dataclass
class DesktopEnvironment:
    """`extension_api.AgentEnvironment` — AI 태스크마다 Worker 세션 하나를 연다."""

    #: Worker 토큰 파일이 있는 곳 — 없으면 호스트가 알려 준 런타임의 것 (`runtime.worker.token_dir`).
    token_dir: Path | None = None
    port: int | None = None
    client: WorkerClient | None = None  # 시험이 끼운다

    def worker(self, ctx: TaskContext) -> WorkerClient:
        if self.client is not None:
            return self.client
        return worker_for(ctx, token_dir=self.token_dir, port=self.port)

    def open(self, ctx: TaskContext) -> DesktopSession:
        desktop = ctx.properties.get("desktop")
        app = str(desktop.get("app") or "") if isinstance(desktop, Mapping) else ""
        if not app:
            # 어느 앱인지 모른다 — 그림을 고쳐야 한다. 오류 경계가 받을 수 있게 업무 실패로 올린다.
            raise TaskFailed("desktop_app_missing", "데스크톱 AI 태스크에 앱 이름(desktop.app)이 없습니다")
        worker = self.worker(ctx)
        studio = getattr(ctx.extension, "host", None) == HOST_STUDIO
        try:
            info = self._open(worker, ctx, app, studio=studio)
        except WorkerUnreachable as e:
            # Worker가 없다 (Bot UI가 띄우지 못했거나 꺼져 있다) — 다시 해 볼 만한 업무 실패다.
            raise TaskFailed("worker_unreachable", str(e), retryable=True) from e
        return DesktopSession(worker=worker, info=info)

    def _open(self, worker: WorkerClient, ctx: TaskContext, app: str, *, studio: bool) -> SessionInfo:
        return worker.open(
            SessionRequest(
                schema=1,
                caller=Caller(
                    type=CALLER_STUDIO if studio else CALLER_BOT,
                    run_id=ctx.run_id,
                    node_id=ctx.node_id,
                    node_instance=ctx.node_instance,
                    attempt=ctx.attempt,
                ),
                mode=str(ctx.mode),
                business_key=ctx.business_key or f"{ctx.run_id}:{ctx.node_id}:{ctx.node_instance}:{ctx.attempt}",
                # 등록된 화면이 아니다 — 계획 없이 앱 이름과 그 PC의 창 조건으로 붙는다 (C10).
                app=app,
                heal=False,
                report=False,
            )
        )


@dataclass
class DesktopSession:
    """`extension_api.AgentSession` — 열린 Worker 세션 하나와 그 도구."""

    worker: WorkerClient
    info: SessionInfo
    closed: bool = field(default=False)

    def tools(self) -> Sequence[AgentTool]:
        return [
            AgentTool(
                name=LOOK,
                description=(
                    "지금 앱 창의 UI 요소 트리를 본다. 줄마다 `컨트롤종류 \"이름\" aid=… class=…`. "
                    "입력한 값·표 칸·창 제목은 •••로 가려져 있다."
                ),
                parameters={"type": "object", "properties": {}},
                run=self.look,
            ),
            AgentTool(
                name=ACT,
                description=(
                    "앱 창의 요소 **하나**를 조작하거나 읽는다. target은 desktop_look에 보이는 조건으로 고른다 "
                    "(automation_id가 있으면 그것이 가장 좋다). fill·press·select는 value가 필요하고 click·읽기는 "
                    "없다. 맞는 요소가 하나가 아니면 몇 개가 맞았는지 알려 준다 — 조건을 좁혀 다시 부른다."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "target": TARGET_SCHEMA,
                        "action": {"type": "string", "enum": sorted(KNOWN_ACTIONS)},
                        "value": {"type": "string"},
                    },
                    "required": ["target", "action"],
                },
                run=self.act,
            ),
        ]

    def look(self) -> str:
        found = self.worker.view(self.info.session_id, self.info.session_secret)
        return str(found.get("text") or "(보이는 요소가 없다)")

    def act(self, target: Mapping[str, Any], action: str, value: Any = None) -> str:
        result = self.worker.step(
            self.info.session_id,
            self.info.session_secret,
            StepRequest(target=dict(target), action=action, value=value),
        )
        if not result.ok:
            return f"실패 ({result.error_code}): {result.error}"
        if result.text is None:
            return "완료"
        read = read_value(result)
        return read if isinstance(read, str) else json.dumps(read, ensure_ascii=False)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.worker.close(self.info.session_id, self.info.session_secret)


__all__ = ["ACT", "LOOK", "DesktopEnvironment", "DesktopSession"]
