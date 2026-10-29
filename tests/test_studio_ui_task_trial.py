"""STU-13 「이 스텝까지 시험」·「계획 세워 보기」→「스텝으로 굳히기」 (ADR-0074).

화면 없이 돈다. Worker는 가짜다 — **C10 요청 모양**을 받아 적는다.

거듭 보는 것 다섯.

1. **Studio 시험 실행과 같은 길이다** — `caller: studio`, `test_…` 실행, Worker가 Center에 올릴 때
   쓰는 것은 Studio가 청한 **호출 토큰**(비밀 이름 `call_token`, C15)이고 Worker 자리는 예약 키다.
   (옛 「태스크 키 참조 → BPM 프로세스 `service.key_ref`」 순서는 서비스 앱 키와 함께 없어졌다 — ADR-0102.)
2. **보고하지 않는다**(`report: false`), **끝나면 닫는다** — 실패해도.
3. **값은 누를 때 묻고, 화면에 손대기 전에 채운다** — 취소하면 아무것도 열지 않는다.
4. **계획 세워 보기는 스텝을 돌리지 않는다**, 이름만 보낸다.
5. **굳히기는 사람이 눌러야 표에 들어가고** 목표로 계획을 끈다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from chaeksas.ext.ui_automation.client.catalog import Catalog  # noqa: E402
from chaeksas.ext.ui_automation.client.editor import GOAL_ON, NO_HOST, PICK_A_ROW, UiTaskEditor  # noqa: E402
from chaeksas.ext.ui_automation.client.editor_trial import EditorTrial, NotReady, template_names  # noqa: E402
from chaeksas.ext.ui_automation.contracts.worker_local import (  # noqa: E402
    CloseResult,
    SessionInfo,
    SessionRequest,
    StepRequest,
    StepResult,
)

TOKEN = "chk_ctk_" + "a" * 40


@dataclass
class Ctx:
    """편집기 문맥인 척 — 설정·비밀 두 길만 (`ExtensionContext.setting`·`secret`)."""

    values: dict[str, Any] = field(
        default_factory=lambda: {"runtime.worker.port": 8899, "runtime.worker.token_dir": "."}
    )
    keys: dict[str, str] = field(default_factory=lambda: {"call_token": TOKEN})
    asked: list[str] = field(default_factory=list)

    def setting(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def secret(self, ref: str) -> str | None:
        self.asked.append(ref)
        return self.keys.get(ref)


@dataclass
class FakeWorker:
    """C10 세션 셋 — 열기·스텝·닫기."""

    results: list[StepResult] = field(default_factory=list)
    planned: list[dict[str, Any]] = field(default_factory=list)
    opened: list[SessionRequest] = field(default_factory=list)
    sent: list[StepRequest] = field(default_factory=list)
    closed: int = 0

    def open(self, request: SessionRequest) -> SessionInfo:
        self.opened.append(request)
        return SessionInfo(session_id="s1", session_secret="x", planned_steps=self.planned)

    def step(self, session_id: str, secret: str, request: StepRequest) -> StepResult:
        self.sent.append(request)
        if self.results:
            return self.results.pop(0)
        return StepResult(ok=True, semantic_key=request.semantic_key, action=request.action)

    def close(self, session_id: str, secret: str) -> CloseResult:
        self.closed += 1
        return CloseResult()


def trial(ctx: Ctx | None = None, worker: FakeWorker | None = None) -> tuple[EditorTrial, list[str], FakeWorker]:
    lines: list[str] = []
    found = worker or FakeWorker()
    made = EditorTrial(ctx=ctx or Ctx(values={}), worker=found, say=lines.append)  # type: ignore[arg-type]
    return made, lines, found


SPEC: dict[str, Any] = {"page_id": "erp.order.form", "heal": True}
STEPS = [
    {"key": "order.customer", "action": "fill", "value": "{신청.거래처}"},
    {"key": "order.total", "action": "read", "result": "합계"},
]


# ─────────────────────────── 이 스텝까지 시험 ───────────────────────────


def test_a_trial_is_a_studio_session_that_does_not_report() -> None:
    made, lines, worker = trial(worker=FakeWorker(results=[StepResult(ok=True), StepResult(ok=True, text="12,000")]))
    assert made.run(SPEC, STEPS, {"신청.거래처": "한빛상사"}) == "성공"
    request = worker.opened[0]
    assert request.caller.type == "studio" and request.mode == "deterministic"
    assert request.report is False, "설계자가 돌려 본 것이 통계를 건드리지 않는다"
    assert request.call_token == TOKEN, "Worker가 이것으로 계획을 Center에 올린다 (C15)"
    assert request.business_key.startswith("test_"), "Studio는 시험 실행으로만 올린다"
    assert worker.sent[0].value == "한빛상사", "점으로 따라가는 이름도 채운다"
    assert "    12,000" in lines, "읽은 값은 결과 상자에만"
    assert worker.closed == 1 and lines[-1].startswith("결과: 성공 — 2/2")


def test_the_call_token_is_asked_by_its_name_and_an_old_key_ref_is_ignored() -> None:
    """비밀은 `call_token` 하나다 — 태스크에 옛 `key_ref`가 남아 있어도 그 이름으로 묻지 않는다."""
    ctx = Ctx(values={"runtime.worker.port": 1}, keys={"own": "k-own", "call_token": TOKEN})
    made, _, worker = trial(ctx)
    made.run({**SPEC, "key_ref": "own"}, STEPS[1:], {})
    assert [one.call_token for one in worker.opened] == [TOKEN]
    assert ctx.asked == ["call_token"]


@pytest.mark.parametrize(
    ("ctx", "says"),
    [
        (Ctx(values={}), "Worker 자리를 모릅니다"),
        (Ctx(values={"runtime.worker.port": 1}, keys={}), "호출 토큰을 받지 못했습니다"),
    ],
)
def test_what_is_missing_is_said_before_anything_opens(ctx: Ctx, says: str) -> None:
    made = EditorTrial(ctx=ctx)  # Worker를 끼우지 않는다 — 자리를 예약 키로 짓는다
    with pytest.raises(NotReady, match=says):
        made.run(SPEC, STEPS[1:], {})


def test_a_failed_or_escalated_step_stops_and_still_closes() -> None:
    made, lines, worker = trial(worker=FakeWorker(results=[StepResult(ok=False, error_code="not_found")]))
    assert made.run(SPEC, STEPS, {"신청.거래처": "x"}) == "실패"
    assert len(worker.sent) == 1 and worker.closed == 1
    made, lines, worker = trial(worker=FakeWorker(results=[StepResult(ok=False, escalated=True)]))
    assert made.run(SPEC, STEPS, {"신청.거래처": "x"}) == "사람에게 전환", "전환은 실패가 아니다"
    assert worker.closed == 1


def test_template_names_skip_braces() -> None:
    assert template_names(["{a}·{{글자}}·{b.c}", "{a}"]) == ["a", "b.c"]


# ─────────────────────────── 계획 세워 보기 ───────────────────────────


def test_planning_sends_names_runs_nothing_and_closes() -> None:
    planned = [{"semantic_key": "order.customer", "action": "fill", "value": "{거래처}"},
               {"semantic_key": "order.total", "action": "read", "result": "합계"}]
    made, lines, worker = trial(worker=FakeWorker(planned=planned))
    found = made.plan(SPEC, "{거래처}를 넣고 합계를 읽는다", ["합계"])
    request = worker.opened[0]
    assert request.mode == "autonomous" and request.values == ["거래처"] and request.results == ["합계"]
    assert request.report is False
    assert worker.sent == [] and worker.closed == 1, "스텝을 돌리지 않고 닫는다"
    assert found == [{"key": "order.customer", "action": "fill", "value": "{거래처}"},
                     {"key": "order.total", "action": "read", "result": "합계"}]
    assert any("돌리지 않았습니다" in one for one in lines)


# ─────────────────────────── 편집기 ───────────────────────────


@pytest.fixture(scope="module")
def app() -> Any:
    from PySide6.QtWidgets import QApplication  # noqa: PLC0415

    return QApplication.instance() or QApplication([])


@pytest.fixture
def editor(app: Any) -> Any:
    made = UiTaskEditor()
    made.catalog = Catalog(base_url=None)
    made.load({"page_id": "erp.order.form", "steps": STEPS + [{"key": "order.save", "action": "click"}]})
    yield made
    made.close()


def plug(editor: UiTaskEditor, worker: FakeWorker) -> None:
    editor._ctx = Ctx(values={"runtime.worker.port": 1})  # type: ignore[assignment]  # noqa: SLF001
    editor.make_trial = lambda ctx: EditorTrial(ctx=ctx, worker=worker, say=editor.trial_output.appendPlainText)  # type: ignore[arg-type]
    editor._sync()  # noqa: SLF001


def test_the_test_button_says_why_it_is_off(editor: UiTaskEditor) -> None:
    assert not editor.test_button.isEnabled() and editor.test_button.toolTip() == NO_HOST
    plug(editor, FakeWorker())
    assert editor.test_button.toolTip() == PICK_A_ROW
    editor.steps.selectRow(1)
    assert editor.test_button.isEnabled()
    editor.use_goal.setChecked(True)
    assert editor.test_button.toolTip() == GOAL_ON


def test_it_runs_up_to_the_selected_row_and_asks_for_values(editor: UiTaskEditor) -> None:
    worker = FakeWorker()
    plug(editor, worker)
    asked: list[list[str]] = []
    editor.ask_values = lambda names: asked.append(names) or {"신청.거래처": "한빛"}  # type: ignore[func-returns-value]
    editor.steps.selectRow(1)
    editor.test_to_selected()
    assert asked == [["신청.거래처"]]
    assert [one.semantic_key for one in worker.sent] == ["order.customer", "order.total"], "고른 줄까지만"
    assert "결과: 성공" in editor.trial_output.toPlainText()


def test_cancelling_the_values_opens_nothing(editor: UiTaskEditor) -> None:
    worker = FakeWorker()
    plug(editor, worker)
    editor.ask_values = lambda names: None
    editor.steps.selectRow(0)
    editor.test_to_selected()
    assert worker.opened == [] and "아무것도 열지 않았습니다" in editor.trial_output.toPlainText()


def test_freezing_puts_the_plan_in_the_table_and_turns_goal_mode_off(editor: UiTaskEditor) -> None:
    worker = FakeWorker(planned=[{"semantic_key": "order.total", "action": "read", "result": "합계"}])
    plug(editor, worker)
    editor.use_goal.setChecked(True)
    editor.goal.setText("합계를 읽는다")
    assert not editor.freeze_button.isEnabled(), "받은 계획이 없으면 굳힐 것도 없다"
    editor.try_plan()
    assert len(editor.step_rows()) == 3, "**받기만 해서는** 표가 바뀌지 않는다"
    assert editor.freeze_button.isEnabled()
    editor.freeze()
    assert editor.step_rows() == [{"key": "order.total", "action": "read", "result": "합계"}]
    assert not editor.use_goal.isChecked() and "goal" not in editor.dump(), "결정 수행이 그 스텝을 돈다"


# ─────────────────────────── Studio가 주는 문맥 ───────────────────────────


def test_studio_gives_editors_the_run_context_and_its_call_token() -> None:
    """편집기 문맥은 시험 실행과 같다 — Worker 자리, 그리고 호출 토큰을 **물을 때마다** 청하는 쪽."""
    from chaeksas.studio.extensions import Extensions, StudioSecrets  # noqa: PLC0415

    found = Extensions.load()
    tokens = ["first"]
    found.call_tokens = lambda: tokens[0]
    ctx = found.editor_context("ui-automation")
    assert ctx.setting("runtime.worker.port"), "Worker 자리는 시험 실행과 같은 것"
    assert ctx.secret("call_token") == "first"
    tokens[0] = "second"
    assert ctx.secret("call_token") == "second", "토큰이 바뀌면(24시간) 따라간다"
    assert isinstance(ctx.secrets, StudioSecrets) and ctx.secrets.extension_id == "ui-automation"
    assert found.context("ui-automation").secret("call_token") == "second", "시험 실행도 같은 토큰이다"
    assert ctx.setting("service.key_ref") is None, "옛 예약 키는 없다"
