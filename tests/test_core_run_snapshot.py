"""기다리는 실행을 담고 되살린다 (`core.run_snapshot`, ADR-0054 §1~§2).

스파이크 `spikes/s10-server-runner-state/`가 **된다**는 것을 확인했고, 여기서는 제품 코드가
그 결정을 지키는지 본다. 가장 값이 큰 것은 **칸 갈래 시험**이다 — 엔진에 칸을 더하고 담는
길에 적지 않으면 되살린 실행이 조용히 다른 답을 낸다.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from chaeksas.contracts.approvals import Form
from chaeksas.contracts.bpmn_ext import read_process
from chaeksas.contracts.replay import ReplaySpec, ReplayStep
from chaeksas.core.engine import Engine, Run, RunEnv, State
from chaeksas.core.helpers import bind
from chaeksas.core.run_log import RunLog
from chaeksas.core.run_snapshot import (
    DROPPED,
    REPLUGGED,
    STORED,
    SnapshotMismatch,
    audit_fields,
    dump,
    restore,
)
from chaeksas.core.run_state import WAIT_DELEGATION, LoopState, Pending, Token, Waiting, new_run_id
from chaeksas.core.senders import RecordingSender

EXAMPLES = Path("docs/08-business-examples/bpmn")
#: 실행 위치가 `server`이고 결재를 기다리며 경계 타이머가 둘 붙어 있다 (스파이크가 쓴 그림).
EXAMPLE = EXAMPLES / "bx03_expense_approval.bpmn"
INPUTS: dict[str, Any] = {
    "신청번호": "EX-2609-014",
    "신청자": "김하나",
    "항목": "출장 숙박",
    "금액": 480000,
    "영수증": True,
    "회신주소": "http://127.0.0.1:1/reply",
}
AT = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)


def env(tmp_path: Path) -> RunEnv:
    from chaeksas.core.files import Workspace

    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    return RunEnv(
        workspace=Workspace(output_dir=out), sender=RecordingSender(), clock=lambda: AT
    )


def waiting_run(tmp_path: Path) -> tuple[Engine, Run]:
    """결재 앞에서 멈춘 실행 하나."""
    engine = Engine()
    run_id = new_run_id(now=AT)
    run = engine.start(
        read_process(EXAMPLE.read_bytes()),
        run_id=run_id,
        log=RunLog(run_id=run_id),
        inputs=INPUTS,
        mode="deterministic",
        executor="server_runner",
        version="1.0.0",
        now=AT,
        env=env(tmp_path),
    )
    engine.run_until_blocked(run)
    assert run.state is State.WAITING
    return engine, run


def roundtrip(run: Run, *, log: RunLog | None = None) -> Run:
    """담았다 글로 바꾸고 되살린다 — **진짜 JSON을 지난다** (담을 수 없는 값이 있으면 터진다)."""
    text = json.dumps(dump(run), ensure_ascii=False, sort_keys=True)
    return restore(
        json.loads(text),
        process=run.process,
        log=log if log is not None else RunLog(run_id=run.run_id),
        env=run.env,
    )


# ─────────────────────────── 칸 갈래 (가장 값이 큰 시험) ───────────────────────────


def test_every_field_of_run_has_a_verdict() -> None:
    """`Run`의 칸이 **셋 중 하나**에 다 들어가 있다 (담는다 / 다시 꽂는다 / 버린다).

    엔진에 칸을 더하고 여기 적지 않으면 **되살린 실행이 조용히 다른 답을 낸다** — 그것이
    이 시험의 값이다. 깨지면 그 칸을 담을지 꽂을지 버릴지 정하고 `run_snapshot`에 적는다.
    """
    assert audit_fields() == []


def test_the_three_verdicts_do_not_overlap() -> None:
    assert not (set(STORED) & set(REPLUGGED))
    assert not (set(STORED) & set(DROPPED))
    assert not (set(REPLUGGED) & set(DROPPED))


# ─────────────────────────── 담았다 되살리기 ───────────────────────────


def test_a_waiting_run_survives_a_roundtrip(tmp_path: Path) -> None:
    _engine, run = waiting_run(tmp_path)
    back = roundtrip(run)
    assert dump(back) == dump(run), "담은 것 ↔ 되살려 다시 담은 것이 다르다"
    assert back.state is State.WAITING
    assert sorted(back.pendings) == sorted(run.pendings)
    assert sorted(back.waits) == sorted(run.waits)


def test_a_delegation_wait_carries_its_job_id(tmp_path: Path) -> None:
    """**위임 작업 id는 스냅샷과 함께 간다** ([ADR-0062](../docs/decisions/0062-pc-delegation.md)).

    없으면 되살린 실행이 **어느 작업을 기다리는지 모른다** — 결과가 내려와도 받을 자리가 없다.
    """
    _engine, run = waiting_run(tmp_path)
    run.waits["delegation:Call_Erp:t1"] = Waiting(
        key="delegation:Call_Erp:t1",
        node_id="Call_Erp",
        kind=WAIT_DELEGATION,
        job_id="job_dlg001",
        token_id="t1",
    )
    back = roundtrip(run)
    found = back.waits["delegation:Call_Erp:t1"]
    assert (found.kind, found.job_id) == (WAIT_DELEGATION, "job_dlg001")
    assert dump(back) == dump(run), "담은 것 ↔ 되살려 다시 담은 것이 다르다"


def test_timers_keep_their_absolute_time(tmp_path: Path) -> None:
    """`due_at`은 **절대 시각**이라 글로 적힌다 — 그래서 재시작을 넘어 간다 (ADR-0054)."""
    _engine, run = waiting_run(tmp_path)
    before = {key: found.due_at for key, found in run.waits.items()}
    back = roundtrip(run)
    assert {key: found.due_at for key, found in back.waits.items()} == before
    assert all(one is not None and one > AT for one in before.values())


def test_a_restored_run_gives_the_same_answer(tmp_path: Path) -> None:
    """쭉 돈 것과 「담고 → 모두 버리고 → 되살려 답한 것」이 **같은 답**을 낸다."""
    engine, run = waiting_run(tmp_path)
    request_id = next(iter(run.pendings))
    answer = {"승인여부": True, "결재의견": "승인합니다"}

    engine.answer(run, request_id, answer, answered_by="박결재")
    engine.run_until_blocked(run)
    straight = {k: v for k, v in run.variables.items() if k not in ("지금", "오늘", "run_id")}

    engine2, second = waiting_run(tmp_path)
    back = roundtrip(second)
    del engine2, second
    Engine().answer(back, next(iter(back.pendings)), answer, answered_by="박결재")
    Engine().run_until_blocked(back)
    found = {k: v for k, v in back.variables.items() if k not in ("지금", "오늘", "run_id")}

    assert found == straight
    assert back.state is State.DONE


def test_date_helpers_stay_bound_to_the_start(tmp_path: Path) -> None:
    """도우미는 **실행 시작 시각**에 묶인다 — 「지금」으로 묶으면 `오늘()`이 다른 답을 낸다."""
    _engine, run = waiting_run(tmp_path)
    back = roundtrip(run)
    assert back.helpers.keys() == bind(now=AT).keys()
    assert back.helpers["오늘"]() == run.helpers["오늘"]()


# ─────────────────────────── 모양을 바꾸는 셋 ───────────────────────────


def test_arrivals_come_back_as_sets(tmp_path: Path) -> None:
    """`arrivals`의 값은 **집합**이다 — 목록으로 되살리면 합류가 토큰을 두 번 센다."""
    _engine, run = waiting_run(tmp_path)
    run.arrivals = {":Gw_Join": {"t_aaa111", "t_bbb222"}}
    run.expected = {":Gw_Join": 2}
    back = roundtrip(run)
    assert back.arrivals == {":Gw_Join": {"t_aaa111", "t_bbb222"}}
    assert isinstance(back.arrivals[":Gw_Join"], set)
    assert back.expected == {":Gw_Join": 2}


def test_a_pending_form_comes_back_as_a_model(tmp_path: Path) -> None:
    """`pendings[].form`은 계약 모델이다 — 사전으로 되살리면 답 검증이 폼을 못 읽는다."""
    _engine, run = waiting_run(tmp_path)
    found = next(iter(run.pendings.values()))
    assert found.form is not None and found.form.fields

    back = roundtrip(run)
    again = back.pendings[found.request_id]
    assert isinstance(again.form, Form)
    assert [f.key for f in again.form.fields] == [f.key for f in found.form.fields]
    assert again.where == found.where == "center"


def test_a_pending_without_a_form_survives(tmp_path: Path) -> None:
    """폼이 없는 요청(확인)도 담긴다 — `None`을 모델로 바꾸려 들지 않는다."""
    _engine, run = waiting_run(tmp_path)
    run.pendings["apr_bare"] = Pending(
        request_id="apr_bare", node_id="Task_x", layer="confirmation", title="확인", form=None
    )
    back = roundtrip(run)
    assert back.pendings["apr_bare"].form is None
    assert back.pendings["apr_bare"].layer == "confirmation"


def test_a_loop_comes_back(tmp_path: Path) -> None:
    """반복(다중 인스턴스) 상태도 담긴다 — 중간에 멈춘 반복이 처음부터 다시 돌지 않게."""
    _engine, run = waiting_run(tmp_path)
    run.tokens[0].loop = LoopState(
        items=[{"거래처": "가나상사"}, {"거래처": "다라물산"}],
        item_name="청구건",
        result_name="처리결과",
        collect_into="처리결과목록",
        index=1,
        results=[{"ok": True}],
    )
    back = roundtrip(run)
    assert back.tokens[0].loop is not None
    assert back.tokens[0].loop.index == 1
    assert back.tokens[0].loop.results == [{"ok": True}]
    assert back.tokens[0].loop.items[1] == {"거래처": "다라물산"}


def test_the_package_id_travels_with_the_snapshot(tmp_path: Path) -> None:
    """되살린 서버 실행도 **같은 이름**으로 결재를 올린다 (ADR-0086). 칸이 없는 옛 스냅샷은 그림 id다."""
    _engine, run = waiting_run(tmp_path)
    run.bpm_process_id = "finance.expense"
    assert roundtrip(run).identity == "finance.expense"

    old = json.loads(json.dumps(dump(run), ensure_ascii=False))
    del old["bpm_process_id"]
    back = restore(old, process=run.process, log=RunLog(run_id=run.run_id), env=run.env)
    assert back.identity == run.process.id


def test_an_inner_run_comes_back(tmp_path: Path) -> None:
    """호출(`callActivity`)이 띄운 안쪽 실행은 **재귀로** 담기고 같은 `run_id`를 쓴다."""
    _engine, run = waiting_run(tmp_path)
    inner = Engine().start(
        run.process,
        run_id=run.run_id,
        log=RunLog(run_id=run.run_id),
        inputs=INPUTS,
        now=AT,
        env=run.env,
        nested=True,
    )
    run.children = {"sub:Call_Inner": inner}
    run.tokens.append(Token(id="t_host", node_id="Approve_Expense", waiting_for="sub:Call_Inner"))

    back = roundtrip(run)
    again = back.children["sub:Call_Inner"]
    assert isinstance(again, Run)
    assert again.nested is True and again.run_id == back.run_id


def test_learned_specs_come_back(tmp_path: Path) -> None:
    """자율 수행이 배운 것도 담긴다 (ADR-0028) — 계약 모델로 되돌린다."""
    _engine, run = waiting_run(tmp_path)
    run.learned = [
        ReplaySpec(
            bpm_process_id=run.process.id,
            node_id="Task_Parse",
            version="1.0.0",
            steps=[ReplayStep(tool="pdf_text_tool", arguments={"path": "{청구서}"})],
            answer='{"금액": 1200000}',
        )
    ]
    back = roundtrip(run)
    assert [one.key for one in back.learned] == [f"{run.process.id}:Task_Parse"]
    assert isinstance(back.learned[0], ReplaySpec)


# ─────────────────────────── 다시 꽂는 넷 ───────────────────────────


def test_the_drawing_is_not_stored(tmp_path: Path) -> None:
    """그림은 담지 않는다 — 설치된 패키지에서 다시 읽는다. 담긴 것은 **대조할 id**뿐이다."""
    _engine, run = waiting_run(tmp_path)
    found = dump(run)
    assert "process" not in found
    assert found["process_id"] == run.process.id


def test_a_different_drawing_is_refused(tmp_path: Path) -> None:
    """다른 그림으로 되살리면 **거부한다** — 없는 노드를 밟는다."""
    _engine, run = waiting_run(tmp_path)
    other = read_process((EXAMPLES / "fx03b_amount_branch.bpmn").read_bytes())
    with pytest.raises(SnapshotMismatch, match="그림이 다르다"):
        restore(dump(run), process=other, log=RunLog(run_id=run.run_id), env=run.env)


def test_the_run_log_is_not_stored(tmp_path: Path) -> None:
    """실행 기록도 담지 않는다 — **파일이 원본이다** (C3). 되살릴 때 밖에서 꽂는다."""
    _engine, run = waiting_run(tmp_path)
    assert "log" not in dump(run)

    path = tmp_path / "runs" / f"{run.run_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    for event in run.log.events:
        path.open("a", encoding="utf-8").write(event.model_dump_json() + "\n")
    reopened = RunLog(run_id=run.run_id, path=path)
    reopened.events = list(RunLog.read(path))

    back = roundtrip(run, log=reopened)
    # **`seq`를 이어 간다** — 빈 기록으로 되살리면 1부터 다시 세어 C3 멱등이 겹친다.
    assert back.log.seq == run.log.seq
    assert back.log.seq > 0


def test_the_error_is_dropped(tmp_path: Path) -> None:
    """`error`는 예외 객체다 — **실패한 실행은 되살리지 않으므로** 담지 않는다."""
    _engine, run = waiting_run(tmp_path)
    assert "error" not in dump(run)
    assert roundtrip(run).error is None


def test_a_bare_env_is_what_the_caller_gives(tmp_path: Path) -> None:
    """바깥 세계는 담을 수 없다 — **주지 않으면 기본값**이라 아무것도 못 한다 (조용히 넘어가지 않는다)."""
    _engine, run = waiting_run(tmp_path)
    assert "env" not in dump(run)
    bare = restore(dump(run), process=run.process, log=RunLog(run_id=run.run_id), env=RunEnv())
    assert bare.env.workspace.output_dir is None


# ─────────────────────────── 글로 담긴다 ───────────────────────────


def test_the_snapshot_is_plain_json(tmp_path: Path) -> None:
    """사람이 읽을 수 있는 글이다 — 저장소를 들여다볼 수 있어야 한다 (ADR-0054 §결과)."""
    _engine, run = waiting_run(tmp_path)
    text = json.dumps(dump(run), ensure_ascii=False, sort_keys=True)
    assert "신청번호" in text
    # 스파이크에서 2KB였다 — 수백 KB가 되면 담는 모양을 다시 본다 (ADR-0054 §다시 볼 조건).
    assert len(text) < 20_000


def test_a_business_value_that_is_not_json_is_caught(tmp_path: Path) -> None:
    """업무 값에 JSON으로 적을 수 없는 것이 들어오면 **담을 때 터진다** — 조용히 잃지 않는다."""
    _engine, run = waiting_run(tmp_path)
    run.variables["기한"] = timedelta(days=3)
    with pytest.raises(TypeError):
        json.dumps(dump(run), ensure_ascii=False)
