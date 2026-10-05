"""UI 태스크 수행기 — Bot이 Worker 프로세스에 UI 조작을 맡긴다 (C10).

흐름은 하나다 (01-architecture §3).

1. `chk:task`의 UI 태스크 속성(C14)과 `key_ref`로 푼 서비스 앱 키를 들고
2. 127.0.0.1의 Worker에 세션을 열고 (`business_key`가 세션을 잇는다)
3. 스텝을 하나씩 보낸다 — **사다리는 Worker가 로컬에서** 탄다 (C8)
4. 닫으면서 받은 요약으로 C3 `ui_session`을 만든다

지키는 것 넷.

- **시맨틱 키로만 말한다** — 셀렉터는 이 경계를 넘지 않는다.
- **토큰은 호출마다 파일에서 읽는다.** Worker가 다시 뜨면 토큰이 바뀐다 (ADR-0023) — 401을
  받으면 한 번 다시 읽고 재시도한다.
- **Worker가 다시 떴을 때 함부로 다시 하지 않는다** (C10 §3). 성공한 조작 스텝이 하나라도
  있었으면 **확인으로 사람에게 넘긴다** — 같은 입력이 두 번 들어간다.
- **전환(`escalated`)은 실패가 아니다** — 확인으로 넘긴다.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chaeksas.ext.ui_automation.contracts.plan import LocatorSpec
from chaeksas.ext.ui_automation.contracts.registration import (
    AnalyzeRequest,
    AnalyzeResult,
    Candidate,
    VerifyResult,
)
from chaeksas.ext.ui_automation.contracts.worker_local import (
    CALLER_BOT,
    DEFAULT_PORT,
    LOCAL_HOST,
    RESULT_ESCALATED,
    RESULT_FAILED,
    SESSION_HEADER,
    SESSION_LOCKED,
    STEP_TIMEOUT_S,
    TOKEN_FILE,
    TOKEN_HEADER,
    Caller,
    CloseResult,
    SessionInfo,
    SessionRequest,
    StepRequest,
    StepResult,
    business_key,
    can_retry_whole_task,
)
from chaeksas.extension_api import TaskContext, TaskFailed, TaskOutcome

log = logging.getLogger(__name__)

#: 확인으로 넘길 때 사람에게 보일 말 (CMN-01).
RESTARTED_MESSAGE = (
    "화면 조작 도중 Worker가 다시 시작되었습니다. 화면 상태를 확인한 뒤 계속/중단을 고르세요."
)
ESCALATED_MESSAGE = "화면에서 요소를 찾지 못했습니다. 화면을 확인한 뒤 계속/중단을 고르세요."

#: C13 §4의 「결과를 모른다」 — 실행기가 확인(CMN-01)으로 넘긴다.
ESCALATE_CONFIRMATION = "confirmation"

#: 스텝 값의 템플릿 — `{{`·`}}`는 중괄호 글자, `{이름}`·`{이름.키}`는 변수 (C14).
TEMPLATE = re.compile(r"\{\{|\}\}|\{([^{}]*)\}")

#: 수 규칙 (ADR-0036) — 앞의 0·전화번호·백분율·통화 기호는 글로 남는다.
NUMBER = re.compile(r"-?(?:0|[1-9]\d{0,2}(?:,\d{3})+|[1-9]\d*)(?:\.\d+)?")


class WorkerUnreachable(RuntimeError):
    """Worker에 닿지 못했다 — Bot UI가 띄우지 못했거나 죽었다."""


@dataclass
class WorkerClient:
    """Worker 로컬 API를 부르는 쪽 (C10).

    **토큰은 호출마다 파일에서 읽는다** — Worker가 다시 뜨면 바뀐다.
    """

    token_dir: Path
    port: int = DEFAULT_PORT
    timeout_s: float = STEP_TIMEOUT_S + 10
    client: Any = None  # httpx.Client (시험이 끼운다)

    @property
    def base_url(self) -> str:
        return f"http://{LOCAL_HOST}:{self.port}"

    def token(self) -> str:
        path = self.token_dir / TOKEN_FILE
        return path.read_text(encoding="utf-8").strip() if path.is_file() else ""

    def call(
        self, method: str, path: str, *, body: Any = None, secret: str | None = None
    ) -> dict[str, Any]:
        """한 번 부른다. **401이면 토큰을 다시 읽고 한 번만** 다시 부른다 (ADR-0023)."""
        import httpx  # noqa: PLC0415 — 부를 때만 든다

        for retry in (False, True):
            headers = {TOKEN_HEADER: self.token()}
            if secret:
                headers[SESSION_HEADER] = secret
            own = self.client is None
            client = self.client or httpx.Client(timeout=self.timeout_s)
            try:
                response = client.request(
                    method, f"{self.base_url}{path}", json=body, headers=headers
                )
            except httpx.HTTPError as e:
                raise WorkerUnreachable(f"Worker에 닿지 못했다 ({type(e).__name__})") from e
            finally:
                if own:
                    client.close()

            if response.status_code == 401 and not retry:
                continue  # 토큰이 바뀌었다 — 다시 읽어 한 번 더
            return _checked(response)
        raise WorkerUnreachable("Worker 토큰이 계속 맞지 않는다")  # pragma: no cover

    # ── C10 경로 ──

    def open(self, request: SessionRequest) -> SessionInfo:
        return SessionInfo.model_validate(self.call("POST", "/v1/sessions", body=request.to_json_dict()))

    def step(self, session_id: str, secret: str, request: StepRequest) -> StepResult:
        return StepResult.model_validate(
            self.call(
                "POST", f"/v1/sessions/{session_id}/steps", body=request.to_json_dict(), secret=secret
            )
        )

    def info(self, session_id: str, secret: str) -> SessionInfo:
        return SessionInfo.model_validate(self.call("GET", f"/v1/sessions/{session_id}", secret=secret))

    def view(self, session_id: str, secret: str) -> dict[str, Any]:
        """지금 화면을 줄글로 — 가린 것 (C10 `view`, 데스크톱 AI 태스크)."""
        return self.call("GET", f"/v1/sessions/{session_id}/view", secret=secret)

    def close(self, session_id: str, secret: str) -> CloseResult:
        return CloseResult.model_validate(
            self.call("DELETE", f"/v1/sessions/{session_id}", secret=secret)
        )

    # ── 셀렉터 등록 (C10 §5) — **여기만 물리 정보가 넘어온다** ──

    def open_registration(self, start_url: str, *, headed: bool = True) -> SessionInfo:
        return SessionInfo.model_validate(
            self.call("POST", "/v1/registration/browser", body={"start_url": start_url, "headed": headed})
        )

    def analyze(self, session_id: str, secret: str, request: AnalyzeRequest) -> AnalyzeResult:
        return AnalyzeResult.model_validate(
            self.call(
                "POST",
                f"/v1/registration/{session_id}/analyze",
                body=request.to_json_dict(),
                secret=secret,
            )
        )

    def pick(self, session_id: str, secret: str, *, on: bool) -> None:
        self.call(
            "POST" if on else "DELETE", f"/v1/registration/{session_id}/pick", secret=secret
        )

    def picked(self, session_id: str, secret: str) -> tuple[list[Candidate], bool]:
        """담은 것을 **비워** 가져온다 (C10 §5)."""
        found = self.call("GET", f"/v1/registration/{session_id}/pick/events", secret=secret)
        return (
            [Candidate.model_validate(one) for one in found.get("candidates", [])],
            bool(found.get("picking")),
        )

    def highlight(self, session_id: str, secret: str, locators: Sequence[LocatorSpec]) -> int:
        found = self.call(
            "POST",
            f"/v1/registration/{session_id}/highlight",
            body={"locators": [one.to_json_dict() for one in locators]},
            secret=secret,
        )
        return int(found.get("found") or 0)

    def verify(
        self, session_id: str, secret: str, ladders: Mapping[str, Sequence[LocatorSpec]]
    ) -> VerifyResult:
        body = {"ladders": {key: [one.to_json_dict() for one in value] for key, value in ladders.items()}}
        return VerifyResult.model_validate(
            self.call("POST", f"/v1/registration/{session_id}/verify", body=body, secret=secret)
        )


def _checked(response: Any) -> dict[str, Any]:
    """C10 오류 본문을 우리 예외로 옮긴다."""
    if response.status_code < 400:
        found = response.json()
        return dict(found) if isinstance(found, dict) else {}
    body = response.json() if response.content else {}
    code = str(body.get("code") or f"http_{response.status_code}")
    message = str(body.get("message") or "Worker가 거절했다")
    if response.status_code == 404 and code == "session_not_found":
        raise SessionGone(message)
    if code == SESSION_LOCKED:
        raise ScreenLocked(message)
    raise TaskFailed(code, message, retryable=response.status_code >= 500)


class SessionGone(RuntimeError):
    """세션이 사라졌다 (Worker 재시작·유휴 시간 초과) — C10 §3으로 판단한다."""


class ScreenLocked(RuntimeError):
    """화면이 잠겨 있다 — **재시도 가능**하다 (풀릴 수 있다)."""


@dataclass
class UiTaskExecutor:
    """`task_types[].executor` — `extension_api.TaskExecutor`."""

    #: Bot UI가 토큰 파일을 두는 곳. 실행기가 환경에서 받는다.
    token_dir: Path | None = None
    port: int = DEFAULT_PORT
    client: WorkerClient | None = None
    #: 세션이 사라졌을 때 **읽기만 했으면** 한 번 다시 한다 (C10 §3).
    _done: list[StepResult] = field(default_factory=list)

    def worker(self, ctx: TaskContext) -> WorkerClient:
        if self.client is not None:
            return self.client
        where = self.token_dir or Path.cwd()
        return WorkerClient(token_dir=where, port=self.port)

    def execute(self, ctx: TaskContext) -> TaskOutcome:
        """UI 태스크 한 번. **다시 할지 말지는 C10 §3이 정한다.**"""
        try:
            return self._once(ctx, attempt=ctx.attempt)
        except SessionGone as e:
            # 세션이 사라졌다. 조작한 적이 없으면 **처음부터 한 번** 다시 한다.
            if not self._touched_the_screen():
                log.info("Worker가 다시 떴다 — 조작한 적이 없어 처음부터 다시 한다")
                return self._once(ctx, attempt=ctx.attempt + 1)
            # 조작했다면 같은 입력이 두 번 들어갈 수 있다 — **사람에게 넘긴다**.
            raise TaskFailed(
                "worker_restarted", RESTARTED_MESSAGE, escalate=ESCALATE_CONFIRMATION
            ) from e
        except WorkerUnreachable as e:
            raise TaskFailed("worker_unreachable", str(e), retryable=True) from e

    def _touched_the_screen(self) -> bool:
        return any(one.ok and one.action not in ("read", "read_table", "read_options", "read_selection")
                   for one in self._done)

    def _once(self, ctx: TaskContext, *, attempt: int) -> TaskOutcome:
        worker = self.worker(ctx)
        spec = dict(ctx.properties)
        goal = _goal_mode(spec, str(ctx.mode))
        values = goal_values(goal, ctx.inputs) if goal else []
        # **화면에 손대기 전에** 값을 모두 채운다 — 모르는 이름이 있으면 아무것도 입력하지 않고 실패한다.
        # 목표 모드면 스텝은 세션을 연 뒤에 온다 (앱이 세운 계획, ADR-0035).
        steps = [] if goal else [_rendered(raw, ctx.inputs) for raw in (spec.get("steps") or [])]
        key = ctx.business_key or business_key(ctx.run_id, ctx.node_id, ctx.node_instance, attempt)

        info = worker.open(
            SessionRequest(
                schema=1,
                caller=Caller(
                    type=CALLER_BOT,
                    run_id=ctx.run_id,
                    node_id=ctx.node_id,
                    node_instance=ctx.node_instance,
                    attempt=attempt,
                    bpm_process_id=spec.get("bpm_process_id"),
                ),
                mode=str(ctx.mode),
                business_key=key,
                page_id=str(spec.get("page_id") or ""),
                start_url=spec.get("start_url"),
                # 데스크톱 앱 이름 — `chk:defaults.desktop`이 엔진을 거쳐 속성 기본값으로 온다 (ADR-0033).
                app=_desktop_app(spec),
                heal=bool(spec.get("heal", True)),
                service_key=ctx.extension.secret(ctx.key_ref) if ctx.key_ref else None,
                # 목표 모드: **이름만** 간다 — 값은 아래에서 이쪽이 채운다 (원칙 6).
                goal=goal,
                values=values,
                results=[str(one) for one in (spec.get("results") or [])] if goal else [],
            )
        )

        outputs: dict[str, Any] = {}
        self._done = []
        try:
            if goal:
                steps = [_rendered(_from_plan(one), ctx.inputs) for one in info.planned_steps]
            for raw in steps:
                result = worker.step(info.session_id, info.session_secret, _step(raw))
                self._done.append(result)
                if result.escalated:
                    # **실패가 아니다** — 사람이 화면을 보고 정한다 (CMN-01).
                    raise TaskFailed(
                        "ui_escalated", ESCALATED_MESSAGE, escalate=ESCALATE_CONFIRMATION
                    )
                if not result.ok:
                    raise TaskFailed(result.error_code or "ui_step_failed", result.error or "스텝 실패")
                # 읽은 값은 **BPM 프로세스 변수로** 간다 (기록에는 남지 않는다 — 원칙 6).
                if raw.get("result") and result.text is not None:
                    outputs[str(raw["result"])] = read_value(result)
        finally:
            closed = _closed(worker, info)
            if closed is not None:
                outputs.setdefault("_ui_session", closed.summary.to_json_dict())
        return TaskOutcome(outputs=outputs)


def screen_value(text: str) -> Any:
    """화면 글 하나 → 변수 값 (ADR-0036). **수 모양이면 수**, 아니면 글 그대로."""
    cleaned = text.strip()
    if not NUMBER.fullmatch(cleaned):
        return text
    plain = cleaned.replace(",", "")
    return float(plain) if "." in plain else int(plain)


def table_rows(data: Mapping[str, Any]) -> list[dict[str, Any]]:
    """C10 표 `data`(`headers`·`rows`) → 줄 목록 `[{머리글: 값}]` (ADR-0036).

    빈 머리글은 `열1`…, 겹치는 머리글은 `_2`…. 모자란 칸은 빈 글, 남는 칸은 버린다.
    """
    names: list[str] = []
    for index, raw in enumerate(data.get("headers") or [], start=1):
        name = str(raw).strip() or f"열{index}"
        base, n = name, 2
        while name in names:
            name = f"{base}_{n}"
            n += 1
        names.append(name)
    out = []
    for row in data.get("rows") or []:
        cells = [str(one) for one in row][: len(names)]
        cells += [""] * (len(names) - len(cells))
        out.append({name: screen_value(cell) for name, cell in zip(names, cells, strict=True)})
    return out


def read_value(result: StepResult) -> Any:
    """읽기 스텝의 결과 → 변수 값 (C10 「읽은 값이 변수가 되는 모양」)."""
    if result.action == "read_table" and result.data is not None:
        return table_rows(result.data)
    if result.action in ("read_options", "read_selection"):
        return result.text
    return screen_value(result.text or "")


def _goal_mode(spec: Mapping[str, Any], mode: str) -> str | None:
    """목표로 실행할까 (C14 `goal`, ADR-0035). 자율 수행에서 목표가 있으면 목표가 이긴다.

    결정 수행은 **목표로 계획하지 않는다** — 적어 둔 스텝이 있으면 그것을 돌고, 목표뿐이면 업무
    실패다 (LLM을 몰래 부르지 않는다).
    """
    goal = str(spec.get("goal") or "").strip()
    if not goal:
        return None
    if mode != "deterministic":
        return goal
    if spec.get("steps"):
        return None
    raise TaskFailed(
        "ui_goal_needs_autonomous",
        "이 UI 태스크는 목표로만 적혀 있어 결정 수행(Bot)에서 돌 수 없습니다 — 스텝을 적어 주세요",
    )


def goal_values(goal: str, variables: Mapping[str, Any]) -> list[str]:
    """목표 안의 `{이름}`들 — 모델에게 갈 **이름 목록**. 지금 없는 이름이면 열기 전에 업무 실패다."""
    names: list[str] = []
    for match in TEMPLATE.finditer(goal):
        name = (match.group(1) or "").strip() if match.group(1) is not None else None
        if name is None:
            continue
        render("{" + name + "}", variables)  # 없으면 여기서 `TaskFailed` (화면에 손대기 전에)
        if name not in names:
            names.append(name)
    return names


def _from_plan(step: Mapping[str, Any]) -> dict[str, Any]:
    """앱이 세운 스텝(C10 `planned_steps`) → 이 수행기의 스텝 모양 (`key`·`action`·`value`·`result`)."""
    made: dict[str, Any] = {"key": step.get("semantic_key"), "action": step.get("action")}
    if step.get("value") is not None:
        made["value"] = step["value"]
    if step.get("result"):
        made["result"] = step["result"]
    return made


def _desktop_app(spec: dict[str, Any]) -> str | None:
    """UI 태스크 속성의 `desktop.app` (C14). 없으면 `None` — Worker가 계획의 화면 것을 쓴다."""
    desktop = spec.get("desktop")
    app = desktop.get("app") if isinstance(desktop, dict) else None
    return str(app) if app else None


def render(value: Any, variables: Mapping[str, Any]) -> Any:
    """스텝 값의 `{이름}`·`{이름.키}`를 실행 시점의 변수로 채운다 (C14, ADR-0033).

    - `{{`·`}}`는 중괄호 글자다.
    - 사전 안의 값은 점으로 따라간다 (`{건.품목}` — 반복 항목). 식은 아니다.
    - 사전·목록 값은 JSON으로 넣는다. `None`은 빈 글이다.
    - **모르는 이름이면 업무 실패**다 — 글자 그대로 입력하지 않는다.
    """
    if not isinstance(value, str) or ("{" not in value and "}" not in value):
        return value

    def one(match: re.Match[str]) -> str:
        if match.group(0) == "{{":
            return "{"
        if match.group(0) == "}}":
            return "}"
        path = (match.group(1) or "").strip()
        names = path.split(".")
        if not path or not all(name.strip() for name in names):
            raise TaskFailed("ui_value_invalid", f"스텝 값의 템플릿이 비어 있습니다: {{{path}}}")
        if names[0] not in variables:
            raise TaskFailed("ui_value_unknown", f"모르는 변수입니다: {{{path}}}")
        found: Any = variables[names[0]]
        for key in names[1:]:
            if not isinstance(found, Mapping) or key not in found:
                raise TaskFailed("ui_value_unknown", f"모르는 값입니다: {{{path}}}")
            found = found[key]
        if found is None:
            return ""
        if isinstance(found, (Mapping, list, tuple)):
            return json.dumps(found, ensure_ascii=False)
        return str(found)

    return TEMPLATE.sub(one, value)


def _rendered(raw: dict[str, Any], variables: Mapping[str, Any]) -> dict[str, Any]:
    if "value" not in raw:
        return dict(raw)
    return {**raw, "value": render(raw["value"], variables)}


def _step(raw: dict[str, Any]) -> StepRequest:
    return StepRequest(
        semantic_key=raw.get("key") or raw.get("semantic_key"),
        action=str(raw.get("action") or ""),
        value=raw.get("value"),
    )


def _closed(worker: WorkerClient, info: SessionInfo) -> CloseResult | None:
    """닫는다. **닫다 실패해도 태스크 결과를 바꾸지 않는다** (유휴 시간이 닫아 준다)."""
    try:
        return worker.close(info.session_id, info.session_secret)
    except Exception as e:  # noqa: BLE001 — 이미 끝난 일이다
        log.warning("세션을 닫지 못했다: %s", e)
        return None


def session_event(closed: CloseResult, *, business_key_: str, page_id: str) -> dict[str, Any]:
    """C3 `ui_session`의 `data` — 부르는 쪽이 이것으로 이벤트를 만든다.

    **값은 담지 않는다** (원칙 6) — 진행·폴백·치유만.
    """
    summary = closed.summary
    return {
        "business_key": business_key_,
        "page_id": page_id,
        "result": summary.result,
        "steps": summary.steps,
        "fallback_depth_max": summary.fallback_depth_max,
        "healed": summary.healed,
    }


__all__ = [
    "ESCALATED_MESSAGE",
    "ESCALATE_CONFIRMATION",
    "RESTARTED_MESSAGE",
    "RESULT_ESCALATED",
    "RESULT_FAILED",
    "ScreenLocked",
    "SessionGone",
    "UiTaskExecutor",
    "WorkerClient",
    "WorkerUnreachable",
    "can_retry_whole_task",
    "session_event",
]
