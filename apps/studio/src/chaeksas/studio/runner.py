"""Studio 시험 실행 — 케이스 하나를 엔진에 물려 돌린다 (STU-08·STU-09, C14 시험 케이스 형식).

**엔진은 스레드를 만들지 않는다** — 여기서도 만들지 않는다. `QTimer`로 한 번에 몇 걸음씩
밟아 화면이 멎지 않게 한다. 엔진이 멈추면(`blocked()`) 케이스가 시킨 대로 답하거나 메시지를
넣고, 그래도 움직이지 않으면 끝낸다.

케이스가 시키는 것 (C14):

| 케이스 | 여기서 하는 일 |
| --- | --- |
| `inputs` | 프로세스 입력. `{"$now_plus": "PT20S"}`·`{"$test_receiver": "reply"}`를 푼다 |
| `approvals` | 결재·확인에 자동으로 답한다. **적지 않은 결재는 답하지 않고 기다린다** (기한 초과 시험) |
| `messages` | 시작 뒤 `after_s`초에 넣는다. 받는 곳이 없으면 기록만 남는다 |
| `expected` | 끝난 뒤 C14 비교 규칙(`matches`)으로 판정. 비면 **비교하지 않는다** |
| `manual` | 자동 응답을 쓰지 않는다 — 실제 결재 창은 3e-4다 (지금은 기다리다 시간이 지난다) |

자율 수행이 배운 것(`Run.learned`)은 **패키지 안 `memory/specs.json`**에 적는다 (ADR-0028) —
엔진은 파일을 쓰지 않으므로 그 일이 여기 있다.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from chaeksas.contracts.bpmn_ext import Case, CaseFile, CaseMessage, duration_hours, matches
from chaeksas.core.app_directory import AppDirectory
from chaeksas.core.engine import Engine, EngineError, Run, RunEnv, State, new_run_id
from chaeksas.core.files import Workspace as FileSpace
from chaeksas.core.llm import NoLlm, OpenAiCompatibleLlm
from chaeksas.core.replay import write_memory
from chaeksas.core.run_log import RunLog
from chaeksas.core.senders import EmailMessage, SendError, SendResult, WebhookRequest
from chaeksas.core.tools import builtin_tools
from chaeksas.studio.receiver import Receiver
from chaeksas.studio.settings import Settings
from chaeksas.studio.workspace import BpmProcess, Definition

log = logging.getLogger(__name__)

#: 한 번의 `QTimer` 틱에 밟을 노드 수. 화면이 멎지 않을 만큼만.
STEPS_PER_TICK = 25
TICK_MS = 10

PASS = "통과"
FAIL = "실패"
NO_EXPECT = "비교 안 함"
STOPPED = "중지"
ERROR = "오류"

NO_CASE = "[케이스] 선택 없음 — 기대 결과를 비교하지 않습니다"


class StudioSender:
    """Studio 시험 실행의 보내기 어댑터.

    **진짜로 보내지 않는다.** 메일은 담아 두기만 하고, 웹훅은 **시험 수신기로만** 보낸다
    (C14 — `$test_receiver`가 Studio 시험 실행의 예외다). 개발 PC에서 실수로 바깥에
    쏘는 일을 막는다.
    """

    def __init__(self, receiver: Receiver | None = None) -> None:
        self.receiver = receiver
        self.emails: list[EmailMessage] = []
        self.webhooks: list[WebhookRequest] = []

    def send_email(self, message: EmailMessage) -> SendResult:
        self.emails.append(message)
        return SendResult(ok=True, id=f"studio_{len(self.emails)}")

    def send_webhook(self, request: WebhookRequest) -> SendResult:
        base = self.receiver.base_url if (self.receiver and self.receiver.running) else None
        if base is None or not request.url.startswith(base):
            raise SendError(
                "Studio 시험 실행은 시험 수신기로만 웹훅을 보냅니다 "
                "— 케이스 입력에 {\"$test_receiver\": \"이름\"}을 쓰세요 (C14)"
            )
        import httpx  # noqa: PLC0415

        self.webhooks.append(request)
        try:
            answer = httpx.post(
                request.url,
                json=request.body if isinstance(request.body, Mapping) else {"body": request.body},
                timeout=request.timeout_s or 10,
            )
        except httpx.HTTPError as e:
            raise SendError(f"시험 수신기에 닿지 못했습니다 ({type(e).__name__})") from e
        return SendResult(ok=True, status=answer.status_code, text=answer.text[:200])


def read_cases(process: BpmProcess, definition: Definition) -> list[Case]:
    """그 정의 옆의 케이스 파일 (`cases/<이름>.cases.json`). 없으면 빈 목록."""
    path = process.case_file(definition)
    if not path.is_file():
        return []
    try:
        return list(CaseFile.model_validate_json(path.read_text(encoding="utf-8")).cases)
    except ValueError as e:
        log.warning("케이스 파일을 읽지 못했다 (%s): %s", path.name, e)
        return []


def resolve_inputs(raw: Mapping[str, Any], *, now: datetime, receiver: Receiver | None) -> dict[str, Any]:
    """케이스 입력 연산자를 푼다 (C14 「케이스 입력 연산자」)."""
    out: dict[str, Any] = {}
    for name, value in raw.items():
        if isinstance(value, Mapping) and len(value) == 1:
            (key, argument), = value.items()
            if key == "$now_plus":
                hours = duration_hours(str(argument))
                out[name] = (now + timedelta(hours=hours or 0)).isoformat()
                continue
            if key == "$test_receiver":
                if receiver is None or not receiver.running:
                    raise EngineError("시험 수신기가 꺼져 있다", code="receiver_off")
                out[name] = receiver.url_for(str(argument))
                continue
        out[name] = value
    return out


def compare(case: Case, run: Run) -> tuple[str, str]:
    """C14 「기대 결과 비교 규칙」. `(판정, 한 줄)`."""
    if run.state is State.FAILED:
        return ERROR, f"실패: {run.error}"
    if not case.expected:
        return NO_EXPECT, "기대 결과가 없어 비교하지 않았습니다"
    wrong = [
        name
        for name, wanted in case.expected.items()
        if name not in run.variables or not matches(wanted, run.variables[name])
    ]
    if wrong:
        return FAIL, f"실패: 다른 항목 {', '.join(wrong)}"
    return PASS, "통과"


@dataclass
class Outcome:
    """케이스 한 번의 결과 (STU-09 로그·상태 줄이 쓴다)."""

    case: str
    verdict: str
    detail: str
    run: Run | None = None
    learned: int = 0


@dataclass
class Plan:
    """무엇을 어떻게 돌릴지 — STU-08이 모아 준다."""

    process: BpmProcess
    definition: Definition
    case: Case | None
    mode: str = "autonomous"  # autonomous | deterministic
    settings: Settings = field(default_factory=Settings)
    #: 확장 태스크·`web`·`desktop` AI 태스크를 수행할 쪽 (C13·ADR-0018·ADR-0037) —
    #: `Extensions.tasks()`. 없으면 그 태스크를 만났을 때 분명히 실패한다 (그림·설치 오류).
    extensions: Any = None
    #: 바깥 앱 한 벌 (`studio.services.Services.directory()`) — 주소는 Center 리소스 등록,
    #: 외부 확장은 검증된 정의다 (C7·C13 「전송」). 없으면 서비스 앱 태스크가 **분명히
    #: 실패한다** — 조용히 지나가지 않는다 (`NoServiceCaller`).
    apps: AppDirectory | None = None


class CaseRun(QObject):
    """케이스 하나를 돌린다. **스레드를 만들지 않는다** — `QTimer`가 한 걸음씩 민다."""

    #: 로그 한 줄 (STU-09 「로그」 탭).
    said = Signal(str)
    #: 캔버스 노드 색 `{노드 id: running|done|failed|waiting}` (STU-09).
    marked = Signal(dict)
    #: 변수 한 벌 (STU-09 「변수」 탭).
    varied = Signal(dict)
    #: 끝났다.
    ended = Signal(object)

    def __init__(self, plan: Plan, receiver: Receiver | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.plan = plan
        self.receiver = receiver
        # `sender`는 QObject의 메서드 이름이라 쓰지 않는다.
        self.adapter = StudioSender(receiver)
        self.run: Run | None = None
        self.engine = Engine()
        self.stopped = False
        self.states: dict[str, str] = {}
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._started = datetime.now(UTC)
        self._sent: set[int] = set()

    # ── 바깥 세계 ──

    def env(self) -> RunEnv:
        """`RunEnv` 한 벌 — 출력 폴더·읽기 허용 폴더·보내기·모델·도구·DMN·호출 대상·재생 기억."""
        settings = self.plan.settings
        outputs = settings.outputs_dir / self.plan.process.id
        outputs.mkdir(parents=True, exist_ok=True)
        model = (
            OpenAiCompatibleLlm(
                base_url=settings.llm_base_url,
                api_key=_llm_key(),
                model=settings.llm_model,
            )
            if settings.llm_base_url
            else NoLlm()
        )
        space = FileSpace(
            output_dir=outputs,
            readable=tuple(settings.readable_dirs),
            writable=tuple(settings.writable_dirs),
        )
        # 주지 않으면 `RunEnv`의 기본값이 남는다 — 기본값은 **부르지 않고 실패한다**.
        extra: dict[str, Any] = {}
        if self.plan.extensions is not None:
            extra["extensions"] = self.plan.extensions
        if self.plan.apps is not None:
            # 외부 확장은 어댑터로, 서비스 앱은 C11로 (`RoutedCaller`) — **엔진은 어느 쪽인지
            # 모른다** (C13 §4).
            extra["services"] = self.plan.apps.caller(caller_type="studio")
        return RunEnv(
            workspace=space,
            sender=self.adapter,
            decisions=self.plan.process.decisions(),
            processes=self.plan.process.processes(),
            llm=model,
            # 내장 도구 넷 (ADR-0030). 파일 도구는 **이 실행의 폴더만** 본다.
            tools=builtin_tools(space),
            memory=self.plan.process.memory(),
            **extra,
        )

    # ── 돌리기 ──

    def start(self) -> None:
        case = self.plan.case
        definition = self.plan.definition
        if definition.process is None:
            self._finish(Outcome(case=case.name if case else "", verdict=ERROR, detail="정의를 읽지 못했습니다"))
            return

        self._started = datetime.now(UTC)
        log_file = self.plan.settings.data_dir / "runs" / f"{new_run_id(test=True)}.jsonl"
        record = RunLog(run_id=log_file.stem, path=log_file)
        record.sinks.append(self._on_event)
        try:
            inputs = resolve_inputs(
                case.inputs if case else {}, now=self._started, receiver=self.receiver
            )
            self.run = self.engine.start(
                definition.process,
                run_id=record.run_id,
                log=record,
                env=self.env(),
                inputs=inputs,
                mode=self.plan.mode,
                executor="studio",
                source="test",
                version=self.plan.process.version,
            )
        except EngineError as e:
            self._finish(Outcome(case=case.name if case else "", verdict=ERROR, detail=str(e)))
            return

        self.said.emit(
            f"[케이스] {case.name}: 입력 {len(inputs)}개" if case else NO_CASE
        )
        self._timer.start()

    def stop(self) -> None:
        self.stopped = True

    def _tick(self) -> None:
        run = self.run
        if run is None:
            return
        for _ in range(STEPS_PER_TICK):
            if self.stopped:
                self._timer.stop()
                self._finish(
                    Outcome(case=self._case_name, verdict=STOPPED,
                            detail="사용자가 중지했습니다 — 케이스를 판정하지 않습니다", run=run)
                )
                return
            if run.finished:
                self._timer.stop()
                self._settle(run)
                return
            if self.engine.blocked(run):
                try:
                    moved = self._unblock(run)
                except EngineError as e:
                    # **여기서 멈춘다.** 케이스가 시킨 답이 맞지 않으면 다음 틱에 또 같은 일이
                    # 생겨 영원히 돈다 — 그 전에 끝내고 사유를 말한다.
                    self._timer.stop()
                    self._finish(
                        Outcome(case=self._case_name, verdict=ERROR, detail=f"실패: {e}", run=run)
                    )
                    return
                if not moved:
                    self._timer.stop()
                    self._settle(run)
                    return
                continue
            self.engine.step(run)
        self.varied.emit(dict(run.variables))

    def _unblock(self, run: Run) -> bool:
        """멈춘 실행을 케이스가 시킨 대로 민다. 민 것이 있으면 참."""
        case = self.plan.case
        if case is not None and not case.manual:
            for request_id, pending in list(run.pendings.items()):
                answer = case.approvals.get(pending.node_id)
                if answer is None:
                    continue  # **적지 않은 결재는 기다린다** (기한 초과 시험, C14)
                self.said.emit(f"[케이스] 결재 자동 응답: {pending.node_id}")
                self.engine.answer(run, request_id, answer, answered_by="시험 케이스")
                return True

        # **케이스 메시지도 예정된 일이다** — 타이머와 한 줄에 세워 이른 것부터 민다.
        # 진짜 초를 기다리지 않는다 (하루짜리 기한을 기다릴 수 없는 것과 같은 이유). 차례가
        # 뒤집히면 결과가 달라진다 — 마감 타이머를 먼저 당기면 견적이 한 건도 안 들어온다.
        waiting = self._next_message()
        due = run.next_due()
        if waiting is not None:
            index, message = waiting
            at = self._started + timedelta(seconds=message.after_s)
            if due is None or at <= due:
                self._sent.add(index)
                self.said.emit(f"[케이스] 메시지: {message.name}")
                self.engine.deliver(
                    run, message.name, correlation=message.correlation, payload=dict(message.payload)
                )
                return True

        if due is not None:
            self.said.emit(f"[케이스] 타이머를 앞당깁니다 ({due.isoformat(timespec='seconds')})")
            self.engine.tick(run, due)
            return True
        return False

    def _next_message(self) -> tuple[int, CaseMessage] | None:
        """아직 안 보낸 케이스 메시지 중 **가장 이른** 것."""
        case = self.plan.case
        if case is None:
            return None
        left = [(i, m) for i, m in enumerate(case.messages) if i not in self._sent]
        return min(left, key=lambda pair: (pair[1].after_s, pair[0])) if left else None

    def _settle(self, run: Run) -> None:
        case = self.plan.case
        if case is None:
            verdict, detail = (ERROR, f"실패: {run.error}") if run.state is State.FAILED else (
                NO_EXPECT, "기대 결과가 없어 비교하지 않았습니다"
            )
        else:
            verdict, detail = compare(case, run)
        learned = self._remember(run)
        self.varied.emit(dict(run.variables))
        self._finish(Outcome(case=self._case_name, verdict=verdict, detail=detail, run=run, learned=learned))

    def _remember(self, run: Run) -> int:
        """자율 수행이 배운 것을 패키지에 적는다 (ADR-0028 — 엔진은 파일을 쓰지 않는다)."""
        if not run.learned or run.state is not State.DONE:
            return 0
        memory = self.plan.process.memory()
        for spec in run.learned:
            memory = memory.with_spec(spec)
        write_memory(self.plan.process.folder, memory)
        self.said.emit(f"[학습] 재생 명세 {len(run.learned)}개를 패키지에 적었습니다")
        return len(run.learned)

    @property
    def _case_name(self) -> str:
        return self.plan.case.name if self.plan.case else ""

    def _finish(self, outcome: Outcome) -> None:
        """**늘 비동기로** 알린다 — `start()`가 곧바로 실패하면 부르는 쪽이 아직 연결 중이고,
        케이스를 줄줄이 돌릴 때 `_next_run`이 재귀로 쌓인다."""
        self._timer.stop()
        QTimer.singleShot(0, lambda: self.ended.emit(outcome))

    # ── 기록 → 화면 ──

    def _on_event(self, event: Any) -> None:
        """C3 이벤트 하나를 STU-09의 로그·캔버스 색으로 옮긴다."""
        data = event.data
        if event.kind == "node_state" and event.node_id:
            mark = {"started": "running", "completed": "done", "failed": "failed",
                    "waiting": "waiting", "replayed": "done"}.get(str(data.get("state")))
            if mark:
                self.states[event.node_id] = mark
                self.marked.emit(dict(self.states))
            if data.get("state") == "failed":
                self.said.emit(f"[실패] {event.node_id}: {data.get('message') or data.get('error_code')}")
            return
        if event.kind == "log":
            head = {"warn": "[경고] ", "error": "[오류] "}.get(str(data.get("level")), "")
            self.said.emit(f"{head}{data.get('message')}")
        elif event.kind == "agent":
            self.said.emit(f"[AI] {event.node_id} {data.get('step')}단계 {data.get('action')}")
        elif event.kind == "service_call":
            self.said.emit(f"[서비스 앱] {data.get('app_id')}/{data.get('operation')} → {data.get('status')}")
        elif event.kind == "human_requested":
            self.said.emit(f"[결재] {event.node_id} 요청")
        elif event.kind == "run_finished":
            self.said.emit(f"[끝] {data.get('status')} · {data.get('duration_s')}초")


def _llm_key() -> str:
    """모델 키는 **설정 파일에 두지 않는다** (CLAUDE.md §5) — 환경변수, 그다음 OS 비밀 저장소 (STU-10)."""
    from chaeksas.studio.credentials import StudioCredentials  # noqa: PLC0415

    return StudioCredentials().llm_api_key() or ""


def summarize(outcomes: list[Outcome]) -> str:
    """모든 케이스를 돌렸을 때의 한 줄 (STU-09)."""
    counts = {name: sum(1 for o in outcomes if o.verdict == name) for name in (PASS, FAIL, NO_EXPECT)}
    return (
        f"전체 {len(outcomes)}개 끝: 통과 {counts[PASS]}, 실패 {counts[FAIL]}, "
        f"비교 안 함 {counts[NO_EXPECT]}"
    )


__all__ = [
    "ERROR",
    "FAIL",
    "NO_CASE",
    "NO_EXPECT",
    "PASS",
    "STEPS_PER_TICK",
    "STOPPED",
    "Outcome",
    "Plan",
    "CaseRun",
    "StudioSender",
    "compare",
    "read_cases",
    "resolve_inputs",
    "summarize",
]
