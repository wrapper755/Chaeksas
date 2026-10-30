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
| `delegations` | **PC 위임이 돌려주는 값**을 그 자리에서 준다. 적지 않은 위임은 **그 자리에서 실패**다 (ADR-0062) |
| `expected` | 끝난 뒤 C14 비교 규칙(`matches`)으로 판정. 비면 **비교하지 않는다** |
| `manual` | 자동 응답을 쓰지 않는다 — 실제 결재 창은 3e-4다 (지금은 기다리다 시간이 지난다) |

**PC 전환 확인**(ADR-0106)은 `approvals`에 그 태스크 노드 id로 적고, **적지 않으면 「중단」**이다 —
적지 않은 위임과 같은 결이라 `ESCALATED` 경계를 시험하는 길이 된다.

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

from chaeksas.contracts.bpmn_ext import CASE_ANSWERER, Case, CaseFile, CaseMessage, duration_hours, matches
from chaeksas.core.delegation import DelegationCall, DelegationError
from chaeksas.core.engine import (
    DECISION_KEY,
    DELEGATION_FINISHED,
    ERROR_DELEGATION_FAILED,
    ESCALATION_STOP,
    Engine,
    EngineError,
    Run,
    RunEnv,
    State,
    new_run_id,
)
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


class CaseDelegator:
    """PC 위임을 **케이스가 적어 둔 결과로** 끝낸다 (`RunEnv.delegate`, ADR-0062 §2
    — `docs/decisions/0062-pc-delegation.md`).

    **Studio는 남의 패키지를 돌리지 않는다** — 부를 PC BPM 프로세스의 그림은 다른 작업 폴더에 있고,
    있다 해도 UI 태스크라 설계자 PC에서 화면을 만지게 된다. 그래서 결재 답·메시지와 **같은
    결**로 케이스가 결과를 적는다 (C14 `delegations`).

    **적어 두지 않은 위임은 맡기는 그 자리에서 실패다** — 결재처럼 기다리게 두면 **끝나지
    않는다**(현장 PC도, Center도 없다). 그래서 이것이 **그림의 오류 경계를 시험하는 길**이기도
    하다 (C14) — 그러려면 사유 코드가 그림이 받을 수 있는 것이어야 하므로 **`DELEGATION_FAILED`**
    를 쓴다(진짜 PC 실행이 실패했을 때와 같은 코드다. 적지 않은 것은 「위임이 실패한 것으로
    다룬다」는 뜻이고, 그 말을 로그에 그대로 적는다).

    돌려주는 작업 id는 **이 창 안에서만 뜻이 있다** (진짜 Center 작업이 아니다) — 엔진은
    그것으로 기다림을 찾고, `_unblock`이 그것으로 결과를 돌려준다.
    """

    def __init__(self, case: Case | None) -> None:
        self.case = case
        #: 맡긴 것 — `job_id` → (노드 id, 돌려줄 값). `take()`가 하나씩 꺼낸다.
        self.pending: dict[str, tuple[str, dict[str, Any]]] = {}
        self.calls: list[DelegationCall] = []
        self._next = 0

    def delegate(self, call: DelegationCall) -> str:
        written = (self.case.delegations if self.case else {}).get(call.node_id)
        if written is None:
            # **업무 실패다** (그림·설치 오류가 아니다) — 그림의 오류 경계가 받는다.
            raise DelegationError(
                f"케이스에 이 위임의 결과가 없어 실패로 다룹니다: {call.node_id} "
                f"({call.bpm_process_id} — 값을 돌려주려면 케이스의 delegations에 적으세요)",
                code=ERROR_DELEGATION_FAILED,
            )
        self.calls.append(call)
        self._next += 1
        job_id = f"case_dlg{self._next}"
        self.pending[job_id] = (call.node_id, dict(written))
        return job_id

    def withdraw(self, job_id: str) -> None:
        """거뒀다 (ADR-0087 — 함께 도는 반복의 한 건이 실패했다) — 적어 둔 결과를 돌려주지 않는다."""
        self.pending.pop(job_id, None)

    def take(self) -> tuple[str, dict[str, Any]] | None:
        """아직 돌려주지 않은 것 하나 — `(job_id, 값)`. 없으면 `None`."""
        for job_id, (_, outputs) in self.pending.items():
            return job_id, outputs
        return None

    def done(self, job_id: str) -> str:
        """돌려줬다 — 그 노드 id를 준다 (로그 한 줄에 쓴다)."""
        node_id, _ = self.pending.pop(job_id)
        return node_id


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
    #: 서비스 태스크를 Center에 외부 작업으로 올리는 호출기 (`studio.services.Services.caller()`, C15).
    #: 없으면 서비스 앱 태스크가 **분명히 실패한다** — 조용히 지나가지 않는다 (`NoServiceCaller`).
    services: Any = None


class CaseRun(QObject):
    """케이스 하나를 돌린다. **스레드를 만들지 않는다** — `QTimer`가 한 걸음씩 민다."""

    #: 로그 한 줄 (STU-09 「로그」 탭).
    said = Signal(str)
    #: 캔버스 노드 색 `{노드 id: running|done|failed|waiting}` (STU-09).
    marked = Signal(dict)
    #: 변수 한 벌 (STU-09 「변수」 탭).
    varied = Signal(dict)
    #: UI 세션 하나가 끝났다 — C3 `ui_session`의 `data` (STU-09 「UI 태스크」 탭).
    ui_session = Signal(object)
    #: 끝났다.
    ended = Signal(object)

    def __init__(self, plan: Plan, receiver: Receiver | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.plan = plan
        self.receiver = receiver
        # `sender`는 QObject의 메서드 이름이라 쓰지 않는다.
        self.adapter = StudioSender(receiver)
        # PC 위임은 **케이스가 적어 둔 결과**로 끝낸다 (ADR-0062 §2).
        self.delegator = CaseDelegator(plan.case)
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
        if self.plan.services is not None:
            # 서비스 태스크는 Center에 외부 작업으로 올린다 (C15) — **엔진은 어디로 가는지 모른다**.
            extra["services"] = self.plan.services
        return RunEnv(
            workspace=space,
            sender=self.adapter,
            # **맡길 곳이 없으면 그림·설치 오류다** (`NoDelegator`) — 케이스가 적어 둔 결과를
            # 돌려주는 것이 Studio의 꽂는 쪽이다 (ADR-0062 §2).
            delegate=self.delegator,
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
            given = resolve_inputs(
                case.inputs if case else {}, now=self._started, receiver=self.receiver
            )
            # **값 출처로 가른다** (ADR-0099) — 현장에서는 Center가 넣는 값(가상 직원)을 시험에서는
            # 케이스가 같은 「입력 변수」에 적는다. 엔진은 부르는 쪽 값과 따로 받는다.
            not_caller = {decl.name for decl in definition.process.info.inputs if not decl.from_caller}
            inputs = {name: value for name, value in given.items() if name not in not_caller}
            sourced = {name: value for name, value in given.items() if name in not_caller}
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
                # 작업 폴더의 id — 내보내면 매니페스트 `id`가 되는 값이다 (ADR-0086).
                bpm_process_id=self.plan.process.id,
                # C3 `case_id` — 어느 케이스로 돌렸나 (CON-01이 보인다). 케이스 이름이 그 id다.
                case_id=case.name if case else None,
                sourced=sourced,
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
                if answer is None and pending.escalation:
                    # **적지 않은 전환 확인은 「중단」이다** (ADR-0106) — 적지 않은 위임과 같은 결이라
                    # `ESCALATED` 경계를 시험하는 길이 된다. 기다리면 답할 사람이 없어 끝나지 않는다.
                    answer = {DECISION_KEY: ESCALATION_STOP}
                if answer is None:
                    continue  # **적지 않은 결재는 기다린다** (기한 초과 시험, C14)
                self.said.emit(f"[케이스] 결재 자동 응답: {pending.node_id}")
                # 답한 사람도 케이스가 적는다 (ADR-0096) — 적지 않으면 「시험 케이스」다.
                who = case.answered_by.get(pending.node_id, CASE_ANSWERER)
                self.engine.answer(run, request_id, answer, answered_by=who)
                return True

        # **위임은 바로 돌려준다** — 여기 오는 것은 케이스에 적혀 있던 것뿐이다(적지 않은 것은
        # 맡기는 자리에서 이미 실패했다). **`manual`이 막지 않는다**: 결재는 사람이 창에서
        # 답할 수 있지만 위임은 Studio에 답할 사람이 없어, 막으면 그 케이스가 끝나지 않는다.
        found = self.delegator.take()
        if found is not None:
            job_id, outputs = found
            node_id = self.delegator.done(job_id)
            self.said.emit(f"[케이스] PC 위임 결과: {node_id} (값 {len(outputs)}개)")
            self.engine.delegation_done(run, job_id, state=DELEGATION_FINISHED, outputs=outputs)
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
        elif event.kind == "ui_session":
            # 줄은 「UI 태스크」 탭이 짓는다 — 여기서는 **그 이벤트를 그대로** 올린다 (ADR-0041).
            self.ui_session.emit(event)
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
    "CaseDelegator",
    "CaseRun",
    "StudioSender",
    "compare",
    "read_cases",
    "resolve_inputs",
    "summarize",
]
