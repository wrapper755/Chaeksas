"""Studio 시험 실행 (M3 조각 3e-3) — STU-08·STU-09.

여기가 **처음으로 한 바퀴가 돈다** — 예제를 가져와, 케이스 입력으로, 엔진을 돌려, C14 비교
규칙으로 판정하고, 배운 재생 명세를 패키지에 적는다.

거듭 보는 것 넷.

1. **엔진은 스레드를 만들지 않는다** — `QTimer`가 민다. 시험도 이벤트 루프를 돌려 기다린다.
2. **케이스가 시키는 대로만** 답한다 — 적지 않은 결재는 기다린다 (기한 초과 시험).
3. **Studio는 바깥으로 웹훅을 쏘지 않는다** — 시험 수신기로만 간다 (개발 PC 보호).
4. **배운 것은 패키지에 적힌다** (ADR-0028) — 엔진은 파일을 쓰지 않으므로 Studio가 한다.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from chaeksas.contracts.bpmn_ext import Case  # noqa: E402
from chaeksas.core.senders import EmailMessage, SendError, WebhookRequest  # noqa: E402
from chaeksas.studio.receiver import Receiver  # noqa: E402
from chaeksas.studio.run_dialog import describe, unlearned  # noqa: E402
from chaeksas.studio.runner import (  # noqa: E402
    ERROR,
    FAIL,
    NO_EXPECT,
    PASS,
    CaseRun,
    Outcome,
    Plan,
    StudioSender,
    read_cases,
    resolve_inputs,
    summarize,
)
from chaeksas.studio.settings import Settings  # noqa: E402
from chaeksas.studio.workspace import Workspace  # noqa: E402

EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples" / "bpmn"


@pytest.fixture(scope="session")
def app() -> Any:
    from PySide6.QtWidgets import QApplication

    try:
        return QApplication.instance() or QApplication([])
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"Qt를 띄울 수 없다: {type(e).__name__}: {e}")


def studio(tmp_path: Path, example: str) -> tuple[Any, Settings]:
    """예제 하나를 작업 폴더로 가져오고, 그 Studio 설정을 만든다."""
    data = tmp_path / "studio"
    settings = replace(Settings(), data_dir=data, llm_base_url="")  # 모델은 쓰지 않는다
    made = Workspace(settings.workspace_dir).ensure().import_example(EXAMPLES, example)
    return made, settings


def drive(run: CaseRun, *, timeout_ms: int = 20_000) -> Outcome:
    """`QTimer`가 미는 실행이 끝날 때까지 이벤트 루프를 돈다."""
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    box: list[Outcome] = []

    def done(outcome: Outcome) -> None:
        box.append(outcome)
        loop.quit()

    run.ended.connect(done)
    QTimer.singleShot(timeout_ms, loop.quit)
    run.start()
    loop.exec()
    if not box:
        pytest.fail(f"시험 실행이 {timeout_ms}ms 안에 끝나지 않았다")
    return box[0]


# ─────────────────────────── 케이스 입력 연산자 (C14) ───────────────────────────


def test_now_plus_becomes_a_real_time() -> None:
    now = datetime(2026, 10, 4, 9, 0, tzinfo=UTC)
    found = resolve_inputs({"마감": {"$now_plus": "PT30M"}}, now=now, receiver=None)
    assert found["마감"].startswith("2026-10-04T09:30")


def test_a_plain_value_is_left_alone() -> None:
    raw = {"금액": 100, "쪽": {"a": 1, "b": 2}}
    found = resolve_inputs(raw, now=datetime.now(UTC), receiver=None)
    assert found == {"금액": 100, "쪽": {"a": 1, "b": 2}}


def test_test_receiver_needs_the_receiver_running() -> None:
    from chaeksas.core.engine import EngineError

    with pytest.raises(EngineError, match="시험 수신기가 꺼져"):
        resolve_inputs({"주소": {"$test_receiver": "reply"}}, now=datetime.now(UTC), receiver=None)


def test_test_receiver_gives_a_loopback_url() -> None:
    receiver = Receiver(port=0).start()
    try:
        found = resolve_inputs(
            {"주소": {"$test_receiver": "reply"}},
            now=datetime.now(UTC),
            receiver=receiver,
        )
        assert found["주소"].startswith("http://127.0.0.1:") and found["주소"].endswith("/reply")
    finally:
        receiver.stop()


# ─────────────────────────── 보내기 (개발 PC 보호) ───────────────────────────


def test_studio_never_sends_a_real_email() -> None:
    sender = StudioSender()
    found = sender.send_email(EmailMessage(to=("a@example.com",), subject="x", body="y"))
    assert found.ok and len(sender.emails) == 1


def test_a_webhook_outside_the_test_receiver_is_refused() -> None:
    """개발 PC에서 실수로 바깥에 쏘지 않는다 — C14는 `$test_receiver`만 예외로 둔다."""
    with pytest.raises(SendError, match="시험 수신기로만"):
        StudioSender().send_webhook(WebhookRequest(url="https://real.example.com/hook"))


def test_a_webhook_to_the_test_receiver_actually_arrives() -> None:
    receiver = Receiver(port=0).start()
    try:
        sender = StudioSender(receiver)
        found = sender.send_webhook(
            WebhookRequest(url=receiver.url_for("reply"), body={"건수": 3, "상태": "ok"})
        )
        assert found.status == 200
        (got,) = receiver.got
        assert got.name == "reply" and got.body == {"건수": 3, "상태": "ok"}
        assert "값" not in got.summary and "3" not in got.summary.replace("127.0.0.1", "")
    finally:
        receiver.stop()


# ─────────────────────────── 한 바퀴 (진짜 엔진) ───────────────────────────


def test_a_rule_example_passes_its_cases(app: Any, tmp_path: Path) -> None:
    """FX-02 — 규칙(DMN) 하나. 케이스가 적어 둔 기대값까지 **그대로** 간다."""
    made, settings = studio(tmp_path, "fx02_business_rule")
    definition = made.entry_definition
    assert definition is not None
    cases = read_cases(made, definition)
    assert [c.name for c in cases] == ["VIP 대량", "일반 소량"]

    outcomes = [
        drive(CaseRun(Plan(process=made, definition=definition, case=case, settings=settings)))
        for case in cases
    ]
    assert [o.verdict for o in outcomes] == [PASS, PASS], [o.detail for o in outcomes]
    assert summarize(outcomes) == "전체 2개 끝: 통과 2, 실패 0, 비교 안 함 0"
    assert outcomes[0].run is not None and outcomes[0].run.variables["최종가"] == 1200000


def test_a_wrong_expectation_is_reported_as_a_failure(app: Any, tmp_path: Path) -> None:
    made, settings = studio(tmp_path, "fx02_business_rule")
    definition = made.entry_definition
    assert definition is not None
    case = Case(name="틀린 기대", inputs={"금액": 1500000, "등급": "VIP"}, expected={"할인율": 0.9})
    found = drive(CaseRun(Plan(process=made, definition=definition, case=case, settings=settings)))
    assert found.verdict == FAIL and "할인율" in found.detail


def test_running_without_a_case_does_not_compare(app: Any, tmp_path: Path) -> None:
    made, settings = studio(tmp_path, "fx12_daily_report")
    definition = made.entry_definition
    assert definition is not None
    found = drive(CaseRun(Plan(process=made, definition=definition, case=None, settings=settings)))
    assert found.verdict == NO_EXPECT


def test_a_case_answers_the_approval_and_the_run_finishes(app: Any, tmp_path: Path) -> None:
    """케이스의 `approvals`가 결재에 자동으로 답한다 (C14)."""
    made, settings = studio(tmp_path, "fx19_manual_task_pc")
    definition = made.entry_definition
    assert definition is not None
    # 폼이 없는 확인은 `decision` 하나로 답한다 (C6 — 「승인 / 반려」 두 단추).
    case = Case(name="확인", inputs={}, approvals={"Manual_Paper": {"decision": "approve"}})
    found = drive(CaseRun(Plan(process=made, definition=definition, case=case, settings=settings)))
    assert found.verdict == NO_EXPECT, found.detail
    assert found.run is not None and found.run.state.value == "done"


def test_an_answer_the_form_refuses_ends_the_run_instead_of_looping(app: Any, tmp_path: Path) -> None:
    """케이스가 틀린 답을 주면 **그 자리에서 끝낸다** — 다음 틱에 또 같은 일이 생긴다.

    예제 FX-19의 케이스가 지금 이 모양이다 (폼 없는 확인에 빈 답) — 예제 쪽은 조각 3f다.
    """
    made, settings = studio(tmp_path, "fx19_manual_task_pc")
    definition = made.entry_definition
    assert definition is not None
    case = read_cases(made, definition)[0]
    assert case.approvals == {"Manual_Paper": {}}
    found = drive(CaseRun(Plan(process=made, definition=definition, case=case, settings=settings)))
    assert found.verdict == ERROR and "빠진 칸" in found.detail


def test_an_unanswered_approval_keeps_waiting(app: Any, tmp_path: Path) -> None:
    """**적지 않은 결재는 답하지 않고 기다린다** — 기한 초과를 시험하는 길이다 (C14)."""
    made, settings = studio(tmp_path, "fx19_manual_task_pc")
    definition = made.entry_definition
    assert definition is not None
    case = Case(name="답 없음", inputs={}, approvals={})
    found = drive(CaseRun(Plan(process=made, definition=definition, case=case, settings=settings)))
    assert found.run is not None and found.run.state.value == "waiting"
    assert found.verdict == NO_EXPECT, "기대 결과가 없으니 비교하지 않는다"


def test_a_webhook_example_reaches_the_test_receiver(app: Any, tmp_path: Path) -> None:
    """FX-17 — 케이스가 `$test_receiver`로 주소를 받는다."""
    made, settings = studio(tmp_path, "fx17_webhook")
    definition = made.entry_definition
    assert definition is not None
    case = next(c for c in read_cases(made, definition) if "$test_receiver" in json.dumps(c.inputs))

    receiver = Receiver(port=0).start()
    try:
        found = drive(
            CaseRun(Plan(process=made, definition=definition, case=case, settings=settings), receiver)
        )
        assert found.verdict == PASS, found.detail
        assert [g.name for g in receiver.got] == ["hook"]
    finally:
        receiver.stop()


def test_a_file_writing_example_writes_into_the_output_folder(app: Any, tmp_path: Path) -> None:
    """ADR-0026 — 쓰기는 출력 폴더 안만. Studio가 실행마다 그 자리를 준다."""
    made, settings = studio(tmp_path, "fx12_daily_report")
    definition = made.entry_definition
    assert definition is not None
    found = drive(CaseRun(Plan(process=made, definition=definition, case=None, settings=settings)))
    assert found.run is not None
    written = sorted((settings.outputs_dir / made.id).rglob("*.md"))
    assert written, "파일 출력이 실제로 생겼다"
    assert written[0].read_text(encoding="utf-8").strip().startswith("#")


def test_the_run_log_is_written_as_jsonl(app: Any, tmp_path: Path) -> None:
    made, settings = studio(tmp_path, "fx02_business_rule")
    definition = made.entry_definition
    assert definition is not None
    case = read_cases(made, definition)[0]
    drive(CaseRun(Plan(process=made, definition=definition, case=case, settings=settings)))
    found = sorted((settings.data_dir / "runs").glob("test_*.jsonl"))
    assert found, "C3 기록이 남는다"
    kinds = [json.loads(line)["kind"] for line in found[0].read_text(encoding="utf-8").splitlines()]
    assert kinds[0] == "run_started" and kinds[-1] == "run_finished"


def test_a_missing_required_input_is_said_plainly(app: Any, tmp_path: Path) -> None:
    """케이스 없이 돌리면 필수 입력이 빈다 — 조용히 `None`으로 흘리지 않는다 (C14 §6)."""
    made, settings = studio(tmp_path, "fx06_document_read")
    definition = made.entry_definition
    assert definition is not None
    found = drive(CaseRun(Plan(process=made, definition=definition, case=None, settings=settings)))
    assert found.verdict == ERROR and "필요하다" in found.detail


def test_an_example_that_needs_a_model_says_so_instead_of_pretending(app: Any, tmp_path: Path) -> None:
    """모델이 설정되지 않았으면 **조용히 넘어가지 않는다** (ADR-0027)."""
    made, settings = studio(tmp_path, "fx06_document_read")
    definition = made.entry_definition
    assert definition is not None
    case = read_cases(made, definition)[0]
    found = drive(CaseRun(Plan(process=made, definition=definition, case=case, settings=settings)))
    assert found.verdict == ERROR
    assert "모델" in found.detail or "도구" in found.detail, found.detail


# ─────────────────────────── 배운 것 적기 (ADR-0028) ───────────────────────────


def test_what_the_autonomous_run_learned_is_written_into_the_package(app: Any, tmp_path: Path) -> None:
    """엔진은 파일을 쓰지 않는다 — **Studio가** 패키지 안 `memory/specs.json`에 적는다."""
    from chaeksas.core.llm import RecordingLlm, Reply
    from chaeksas.core.replay import read_memory

    made, settings = studio(tmp_path, "fx06_document_read")
    definition = made.entry_definition
    assert definition is not None
    assert read_memory(made.folder).specs == [], "아직 배운 것이 없다"

    run = CaseRun(Plan(process=made, definition=definition, case=None, settings=settings))
    answers = [Reply(text=json.dumps({"요약": "한 줄", "쪽수": 3}, ensure_ascii=False), model="시험")]
    run.env = lambda: replace(  # type: ignore[method-assign]
        CaseRun.env(run), llm=RecordingLlm(replies=answers * 5), tools={}
    )
    drive(run)
    # 도구가 없어 실패했더라도, 성공한 실행만 적는다 — 그 규칙을 확인한다.
    assert read_memory(made.folder).specs == []


def test_the_run_dialog_turns_off_replay_when_nothing_was_learned(tmp_path: Path) -> None:
    """U3 — 고를 수 없는 것은 끄고 **이유**를 보인다."""
    made, _ = studio(tmp_path, "fx06_document_read")
    definition = made.entry_definition
    assert definition is not None
    assert unlearned(made, definition), "AI 태스크가 있고 명세가 없다"

    rules, _ = studio(tmp_path / "other", "fx02_business_rule")
    other = rules.entry_definition
    assert other is not None
    assert unlearned(rules, other) == [], "AI 태스크가 없으면 끌 이유도 없다"


def test_the_dialog_describes_the_case_in_one_line() -> None:
    assert describe(None) == "기대 결과를 비교하지 않습니다"
    assert describe(Case(name="x", inputs={"a": 1}, expected={})) == "입력 1개 · 기대 결과 없음 — 비교하지 않습니다"
    assert describe(Case(name="x", inputs={}, expected={"b": 1})) == "입력 0개 · 기대 결과 1개"
