"""결재 한 바퀴 — 올리기 → 결재함 → 답하기 → 하트비트 (C4·C6, M5 조각 5).

진짜 Center를 in-process로 띄우고 **진짜 PC 실행기 키로** 결재를 올린다. 현장 연결(엔진이
`where=center`를 고르고 실행기가 올리는 길)은 다음 조각이라, 여기서는 C6의 경계인
`POST /approvals`를 직접 두드린다.

거듭 보는 것 다섯.

1. **확인은 올라오지 않는다** — `layer=confirmation`은 422다 (화면 앞 사람만 답할 수 있다).
2. **답은 올린 키에게만** 내려간다 — 남의 실행·남의 결재는 403이다.
3. **거절은 되돌림이다** — 실행하는 쪽이 받아들이지 못하면 곧바로 `open`으로 돌아간다.
4. **답할 곳이 없어지면 자동으로 회수한다** — 실행이 끝나거나 대기열을 잃으면.
5. **값은 30일 뒤 지운다** — 누가·언제·결과는 남는다 (C6 §`review`).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from chaeksas.center.app import create_app
from chaeksas.center.settings import Settings
from chaeksas.center.storage import Store
from chaeksas.contracts.approvals import request_id_for

TOKEN = "t-admin"
READ = "t-read"
ADMIN = {"Authorization": f"Bearer {TOKEN}"}
READ_AUTH = {"Authorization": f"Bearer {READ}"}

RUN = "run_20261006_091500_a1b2c3"
NODE = "Task_approve"
BOT = "finance.invoice-issue"
REQUEST = request_id_for(RUN, NODE, 1)

FORM = {
    "fields": [
        {"key": "approved", "label": "승인", "type": "bool", "required": True},
        {"key": "memo", "label": "메모", "type": "text", "required": False},
    ]
}
REVIEW = {"거래처": "주식회사 예시", "금액": 1100000}


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    made = Store(tmp_path / "center.sqlite3")
    yield made
    made.close()


@pytest.fixture
def client(tmp_path: Path, store: Store) -> Iterator[TestClient]:
    settings = Settings(
        db_path=tmp_path / "center.sqlite3",
        package_dir=tmp_path / "packages",
        admin_token=TOKEN,
        read_token=READ,
    )
    with TestClient(create_app(settings, store=store)) as found:
        yield found


def issue_key(client: TestClient, *, name: str = "현장 PC 1", key_type: str = "bot_ui") -> str:
    answer = client.post(
        "/api/v1/center-keys", json={"name": name, "type": key_type}, headers=ADMIN
    )
    assert answer.status_code == 201, answer.text
    return str(answer.json()["key"])


def register(client: TestClient, raw: str, *, name: str = "현장 PC 1", seed: str = "pc1") -> str:
    body = {
        "schema": 1,
        "machine_id": hashlib.sha256(seed.encode()).hexdigest(),
        "name": name,
        "os": "windows-11-23H2",
        "versions": {"bot_ui": "0.1.0", "core": "0.1.0"},
    }
    answer = client.post(
        "/api/v1/bot-ui/register", json=body, headers={"Authorization": f"Bearer {raw}"}
    )
    assert answer.status_code == 200, answer.text
    return str(answer.json()["bot_ui_id"])


def request_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema": 1,
        "request_id": REQUEST,
        "layer": "approval",
        "run_id": RUN,
        "node_id": NODE,
        "node_instance": 1,
        "bpm_process_id": BOT,
        "version": "1.0.0",
        "title": "세금계산서 발행 승인",
        "form": FORM,
        "review": dict(REVIEW),
    }
    body.update(over)
    return body


def heartbeat_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema": 1,
        "status": "waiting_approval",
        "current_run": None,
        "queue": {"max": 20, "items": []},
    }
    body.update(over)
    return body


@pytest.fixture
def host(client: TestClient) -> dict[str, Any]:
    """등록된 PC 실행기 하나와 그 키 — 결재를 올리는 쪽."""
    raw = issue_key(client)
    bot_ui_id = register(client, raw)
    return {"raw": raw, "auth": {"Authorization": f"Bearer {raw}"}, "bot_ui_id": bot_ui_id}


def put(client: TestClient, host: dict[str, Any], **over: Any) -> dict[str, Any]:
    answer = client.post("/api/v1/approvals", json=request_body(**over), headers=host["auth"])
    assert answer.status_code in (200, 201), answer.text
    return dict(answer.json())


# ─────────────────────────── 올리기 (C6 POST /approvals) ───────────────────────────


def test_an_approval_lands_in_the_inbox(client: TestClient, host: dict[str, Any]) -> None:
    made = put(client, host)
    assert made["state"] == "open"
    assert made["host"]["id"] == host["bot_ui_id"]
    assert made["host"]["name"] == "현장 PC 1", "실행하는 곳의 이름이 보인다 (CON-04)"
    assert made["review"] == REVIEW, "검토 자료는 올라온다 (원칙 6의 예외)"

    [listed] = client.get("/api/v1/approvals", headers=READ_AUTH).json()
    assert listed["request_id"] == REQUEST


def test_a_confirmation_is_refused(client: TestClient, host: dict[str, Any]) -> None:
    """**확인은 Center로 올라오지 않는다** — 화면 앞 사람만 답할 수 있다 (C6)."""
    answer = client.post(
        "/api/v1/approvals", json=request_body(layer="confirmation"), headers=host["auth"]
    )
    assert answer.status_code == 422
    assert answer.json()["code"] == "confirmation_not_allowed"


def test_a_request_id_that_does_not_match_the_node_is_refused(
    client: TestClient, host: dict[str, Any]
) -> None:
    """어긋나면 답이 엉뚱한 노드로 돌아간다 — 모델이 막는다 (C6)."""
    answer = client.post(
        "/api/v1/approvals", json=request_body(request_id="apr_엉뚱한것"), headers=host["auth"]
    )
    assert answer.status_code == 422


def test_an_admin_token_cannot_raise_an_approval(client: TestClient) -> None:
    """결재는 **실행하는 쪽이** 올린다 (C6 §전송) — 토큰으로는 올리지 못한다."""
    answer = client.post("/api/v1/approvals", json=request_body(), headers=ADMIN)
    assert answer.status_code == 403 and answer.json()["code"] == "wrong_key_type"


def test_the_same_request_twice_is_idempotent(client: TestClient, host: dict[str, Any]) -> None:
    first = client.post("/api/v1/approvals", json=request_body(), headers=host["auth"])
    again = client.post("/api/v1/approvals", json=request_body(), headers=host["auth"])
    assert (first.status_code, again.status_code) == (201, 200)
    assert len(client.get("/api/v1/approvals", headers=READ_AUTH).json()) == 1

    other = client.post(
        "/api/v1/approvals", json=request_body(title="딴 제목"), headers=host["auth"]
    )
    assert other.status_code == 409 and other.json()["code"] == "idempotency_conflict"


def test_another_key_cannot_raise_an_approval_on_my_request(
    client: TestClient, host: dict[str, Any]
) -> None:
    """**남의 결재를 가로채지 못한다** (C6 §소유)."""
    put(client, host)
    stranger = issue_key(client, name="딴 PC", key_type="bot_ui")
    answer = client.post(
        "/api/v1/approvals", json=request_body(), headers={"Authorization": f"Bearer {stranger}"}
    )
    assert answer.status_code == 409 and answer.json()["code"] == "idempotency_conflict"


def test_another_keys_run_is_refused(client: TestClient, host: dict[str, Any]) -> None:
    """실행 기록이 먼저 올라와 있으면 C3 소유와 대조한다 (C6 `run_owner_mismatch`)."""
    stranger = issue_key(client, name="딴 PC", key_type="bot_ui")
    register(client, stranger, name="딴 PC", seed="pc2")
    # 남의 키로 그 실행의 기록을 먼저 올린다 → 그 실행의 주인이 된다.
    sent = client.post(
        f"/api/v1/runs/{RUN}/events",
        json=[{"schema": 1, "run_id": RUN, "seq": 1, "ts": "2026-10-06T09:15:00+09:00",
               "kind": "run_started", "data": {"bpm_process_id": BOT, "version": "1.0.0", "run_location": "pc",
                        "executor": "bot_ui", "mode": "deterministic", "source": "job"}}],
        headers={"Authorization": f"Bearer {stranger}"},
    )
    assert sent.status_code == 200, sent.text

    answer = client.post("/api/v1/approvals", json=request_body(), headers=host["auth"])
    assert answer.status_code == 403 and answer.json()["code"] == "run_owner_mismatch"


# ─────────────────────────── 답하기 (C6 answer) ───────────────────────────


def test_answering_validates_against_the_form(client: TestClient, host: dict[str, Any]) -> None:
    """**Center가 폼으로 검증한다** — 칸마다 오류를 돌려준다 (콘솔이 칸에 표시한다)."""
    put(client, host)
    bad = client.post(
        f"/api/v1/approvals/{REQUEST}/answer", json={"answer": {"approved": "네"}}, headers=ADMIN
    )
    assert bad.status_code == 422
    assert bad.json()["code"] == "answer_invalid"
    assert bad.json()["detail"]["fields"] == ["approved"]

    missing = client.post(
        f"/api/v1/approvals/{REQUEST}/answer", json={"answer": {"memo": "좋음"}}, headers=ADMIN
    )
    assert missing.json()["detail"]["fields"] == ["approved"], "필수 칸이 빠졌다"


def test_a_good_answer_sticks(client: TestClient, host: dict[str, Any]) -> None:
    put(client, host)
    answer = client.post(
        f"/api/v1/approvals/{REQUEST}/answer",
        json={"answer": {"approved": True, "memo": "확인했습니다"}},
        headers={**ADMIN, "X-CHK-Actor": "%EC%9A%B4%EC%98%81%EC%9E%90%20%EA%B9%80"},
    )
    assert answer.status_code == 200, answer.text
    found = answer.json()
    assert found["state"] == "answered"
    assert found["answer"] == {"approved": True, "memo": "확인했습니다"}
    assert found["answered_by"] == "운영자 김", "행위자는 본문이 아니라 헤더가 정한다 (C6)"


def test_a_read_token_cannot_answer(client: TestClient, host: dict[str, Any]) -> None:
    put(client, host)
    answer = client.post(
        f"/api/v1/approvals/{REQUEST}/answer", json={"answer": {"approved": True}}, headers=READ_AUTH
    )
    assert answer.status_code == 403


def test_answering_twice_is_refused(client: TestClient, host: dict[str, Any]) -> None:
    put(client, host)
    body = {"answer": {"approved": True}}
    assert client.post(f"/api/v1/approvals/{REQUEST}/answer", json=body, headers=ADMIN).status_code == 200
    again = client.post(f"/api/v1/approvals/{REQUEST}/answer", json=body, headers=ADMIN)
    assert again.status_code == 409 and again.json()["code"] == "already_answered"


def test_without_a_form_it_is_approve_or_reject(client: TestClient, host: dict[str, Any]) -> None:
    """폼이 없으면 「승인 / 반려」다 (C6). **거절도 답이다.**"""
    put(client, host, form=None)
    bad = client.post(
        f"/api/v1/approvals/{REQUEST}/answer", json={"answer": {"memo": "응"}}, headers=ADMIN
    )
    assert bad.json()["detail"]["fields"] == ["decision"]

    good = client.post(
        f"/api/v1/approvals/{REQUEST}/answer",
        json={"answer": {"decision": "reject", "comment": "금액이 다릅니다"}},
        headers=ADMIN,
    )
    assert good.status_code == 200 and good.json()["answer"]["decision"] == "reject"


def test_an_expired_approval_cannot_be_answered(client: TestClient, host: dict[str, Any]) -> None:
    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    put(client, host, expires_at=past)
    answer = client.post(
        f"/api/v1/approvals/{REQUEST}/answer", json={"answer": {"approved": True}}, headers=ADMIN
    )
    assert answer.status_code == 409 and answer.json()["code"] == "not_open"
    assert client.get(f"/api/v1/approvals/{REQUEST}", headers=READ_AUTH).json()["state"] == "expired"


# ─────────────────────────── 회수 (C6 DELETE) ───────────────────────────


def test_the_host_withdraws_when_answered_in_the_field(
    client: TestClient, host: dict[str, Any]
) -> None:
    """현장에서 먼저 답했으면 올린 쪽이 거둔다 — **실행에는 영향이 없다** (C6)."""
    put(client, host)
    answer = client.delete(
        f"/api/v1/approvals/{REQUEST}?reason=answered_in_field", headers=host["auth"]
    )
    assert answer.status_code == 200
    assert answer.json()["state"] == "withdrawn"
    assert answer.json()["withdraw_reason"] == "answered_in_field"


def test_the_host_cannot_claim_an_admin_reason(client: TestClient, host: dict[str, Any]) -> None:
    put(client, host)
    answer = client.delete(
        f"/api/v1/approvals/{REQUEST}?reason=admin_withdraw", headers=host["auth"]
    )
    assert answer.status_code == 403


def test_someone_elses_approval_cannot_be_withdrawn(client: TestClient, host: dict[str, Any]) -> None:
    put(client, host)
    stranger = issue_key(client, name="딴 PC", key_type="bot_ui")
    answer = client.delete(
        f"/api/v1/approvals/{REQUEST}?reason=run_ended",
        headers={"Authorization": f"Bearer {stranger}"},
    )
    assert answer.status_code == 403 and answer.json()["code"] == "not_owner"


def test_the_admin_withdraws(client: TestClient, host: dict[str, Any]) -> None:
    put(client, host)
    answer = client.delete(f"/api/v1/approvals/{REQUEST}", headers=ADMIN)
    assert answer.status_code == 200
    assert answer.json()["withdraw_reason"] == "admin_withdraw"


def test_an_answered_approval_cannot_be_withdrawn(client: TestClient, host: dict[str, Any]) -> None:
    put(client, host)
    client.post(f"/api/v1/approvals/{REQUEST}/answer", json={"answer": {"approved": True}}, headers=ADMIN)
    answer = client.delete(f"/api/v1/approvals/{REQUEST}", headers=ADMIN)
    assert answer.status_code == 409 and answer.json()["code"] == "already_answered"


# ─────────────────────────── 자동 회수 (C6 §상태 전이) ───────────────────────────


def test_a_finished_run_takes_its_approvals_with_it(
    client: TestClient, host: dict[str, Any]
) -> None:
    """**답할 곳이 없어진 결재를 남기지 않는다** (C6 `run_ended`)."""
    put(client, host)
    sent = client.post(
        f"/api/v1/runs/{RUN}/events",
        json=[
            {"schema": 1, "run_id": RUN, "seq": 1, "ts": "2026-10-06T09:15:00+09:00",
             "kind": "run_started", "data": {"bpm_process_id": BOT, "version": "1.0.0", "run_location": "pc",
                        "executor": "bot_ui", "mode": "deterministic", "source": "job"}},
            {"schema": 1, "run_id": RUN, "seq": 2, "ts": "2026-10-06T09:20:00+09:00",
             "kind": "run_finished", "data": {"status": "failed", "duration_s": 12.5, "ai_tasks": 0,
                        "replayed_tasks": 0, "ui_tasks": 0, "service_calls": 0,
                        "human_requests": 1}},
        ],
        headers=host["auth"],
    )
    assert sent.status_code == 200, sent.text

    found = client.get(f"/api/v1/approvals/{REQUEST}", headers=READ_AUTH).json()
    assert found["state"] == "withdrawn" and found["withdraw_reason"] == "run_ended"


def test_a_lost_queue_takes_its_approvals_with_it(
    client: TestClient, store: Store, host: dict[str, Any]
) -> None:
    """PC 실행기가 대기열을 잃으면 그 실행의 결재도 전달될 곳이 없다 (C6 `host_lost`)."""
    from chaeksas.center.api import jobs

    # 그 실행을 `accepted` 작업으로 만들어 둔다 (작업이 `run_id`를 쥐고 있어야 한다).
    with store.tx() as cur:
        cur.execute(
            "INSERT INTO jobs (job_id, bpm_process_id, version, target_type, target_id, inputs_json,"
            " owner, body_hash, requested_by, requested_at, state, run_id, misses)"
            " VALUES ('job_11112222', ?, '1.0.0', 'bot_ui', ?, '{}', 'actor:관리자', 'h',"
            " '관리자', '2026-10-06T09:00:00+09:00', 'accepted', ?, 1)",
            (BOT, host["bot_ui_id"], RUN),
        )
    put(client, host)

    # 대기열·실행 자리에 보이지 않는 하트비트 한 번 더 → 두 번 연속이라 잃은 것으로 본다.
    client.post("/api/v1/bot-ui/heartbeat", json=heartbeat_body(), headers=host["auth"])

    assert jobs.info_of(store, store.row("SELECT * FROM jobs")).state_reason == "bot_ui_lost"
    found = client.get(f"/api/v1/approvals/{REQUEST}", headers=READ_AUTH).json()
    assert found["state"] == "withdrawn" and found["withdraw_reason"] == "host_lost"



def finish_run(client: TestClient, host: dict[str, Any], *, status: str = "cancelled") -> None:
    """C3 `run_started`·`run_finished` 두 줄 — 그 실행이 끝났다."""
    sent = client.post(
        f"/api/v1/runs/{RUN}/events",
        json=[
            {"schema": 1, "run_id": RUN, "seq": 1, "ts": "2026-10-06T09:15:00+09:00",
             "kind": "run_started", "data": {"bpm_process_id": BOT, "version": "1.0.0", "run_location": "pc",
                        "executor": "bot_ui", "mode": "deterministic", "source": "job"}},
            {"schema": 1, "run_id": RUN, "seq": 2, "ts": "2026-10-06T09:20:00+09:00",
             "kind": "run_finished", "data": {"status": status, "duration_s": 12.5, "ai_tasks": 0,
                        "replayed_tasks": 0, "ui_tasks": 0, "service_calls": 0,
                        "human_requests": 1}},
        ],
        headers=host["auth"],
    )
    assert sent.status_code == 200, sent.text


def test_a_refused_withdrawal_does_not_reopen_the_approval(client: TestClient, host: dict[str, Any]) -> None:
    """**되돌리는 것은 답뿐이다** (C6) — 회수에 `not_waiting`이 와도 `open`이 되지 않는다.

    서버 실행기가 이미 닫은 실행의 회수에 그렇게 답해 취소된 실행의 결재가 되살아났다.
    """
    put(client, host)
    finish_run(client, host)
    down = client.post("/api/v1/bot-ui/heartbeat", json=heartbeat_body(), headers=host["auth"]).json()
    assert [one["state"] for one in down["approvals"]] == ["withdrawn"]

    client.post(
        "/api/v1/bot-ui/heartbeat",
        json=heartbeat_body(approval_acks=[{"request_id": REQUEST, "accepted": False, "reason": "not_waiting"}]),
        headers=host["auth"],
    )
    found = client.get(f"/api/v1/approvals/{REQUEST}", headers=READ_AUTH).json()
    assert found["state"] == "withdrawn" and found["withdraw_reason"] == "run_ended"
    again = client.post("/api/v1/bot-ui/heartbeat", json=heartbeat_body(), headers=host["auth"]).json()
    assert again["approvals"] == [], "받아 간 것으로 적었다 — 다시 내려가지 않는다"


def test_a_refused_answer_of_an_ended_run_is_withdrawn_not_reopened(
    client: TestClient, host: dict[str, Any]
) -> None:
    """답이 내려가는 사이 실행이 끝났다 — 거절이 와도 **다시 열지 않고 거둔다** (C6)."""
    put(client, host)
    client.post(f"/api/v1/approvals/{REQUEST}/answer", json={"answer": {"approved": True}}, headers=ADMIN)
    finish_run(client, host)  # 이미 답했으니 `run_ended`로 거두지 않는다
    client.post(
        "/api/v1/bot-ui/heartbeat",
        json=heartbeat_body(approval_acks=[{"request_id": REQUEST, "accepted": False, "reason": "not_waiting"}]),
        headers=host["auth"],
    )
    found = client.get(f"/api/v1/approvals/{REQUEST}", headers=READ_AUTH).json()
    assert found["state"] == "withdrawn" and found["withdraw_reason"] == "run_ended"


def test_an_open_approval_of_an_ended_run_refuses_an_answer(
    client: TestClient, store: Store, host: dict[str, Any]
) -> None:
    """`run_finished` 뒤에도 `open`인 결재(늦게 닿았거나 옛 규칙으로 다시 열린 것)에 온 답은 409다.

    받아 두면 기다리는 이가 없어 **효과 없이 200**이다. 그 자리에서 `run_ended`로 거둔다.
    """
    finish_run(client, host)
    put(client, host)  # 실행이 끝난 뒤에 닿았다
    assert client.get(f"/api/v1/approvals/{REQUEST}", headers=READ_AUTH).json()["state"] == "open"

    refused = client.post(f"/api/v1/approvals/{REQUEST}/answer", json={"answer": {"approved": True}}, headers=ADMIN)
    assert refused.status_code == 409 and refused.json()["code"] == "not_open", refused.text
    found = client.get(f"/api/v1/approvals/{REQUEST}", headers=READ_AUTH).json()
    assert found["state"] == "withdrawn" and found["withdraw_reason"] == "run_ended"


def test_the_heartbeat_sweeps_open_approvals_of_ended_runs(client: TestClient, host: dict[str, Any]) -> None:
    """답을 기다리지 않아도 **하트비트가 쓸어 거둔다** — 결재함·가상 직원 일괄에 남지 않는다."""
    finish_run(client, host)
    put(client, host)
    client.post("/api/v1/bot-ui/heartbeat", json=heartbeat_body(), headers=host["auth"])
    assert client.get("/api/v1/approvals?state=open", headers=READ_AUTH).json() == []
    found = client.get(f"/api/v1/approvals/{REQUEST}", headers=READ_AUTH).json()
    assert found["state"] == "withdrawn" and found["withdraw_reason"] == "run_ended"


# ─────────────────────────── 하트비트가 답을 나른다 (C4) ───────────────────────────


def test_the_answer_rides_the_heartbeat(client: TestClient, host: dict[str, Any]) -> None:
    """한 바퀴 — 올리기 → 답하기 → **현장이 받아 간다**."""
    put(client, host)
    assert client.post("/api/v1/bot-ui/heartbeat", json=heartbeat_body(), headers=host["auth"]).json()[
        "approvals"
    ] == [], "답이 없으면 내려갈 것도 없다"

    client.post(
        f"/api/v1/approvals/{REQUEST}/answer",
        json={"answer": {"approved": True, "memo": "좋음"}},
        headers=ADMIN,
    )
    down = client.post("/api/v1/bot-ui/heartbeat", json=heartbeat_body(), headers=host["auth"]).json()
    assert [one["request_id"] for one in down["approvals"]] == [REQUEST]
    assert down["approvals"][0]["answer"] == {"approved": True, "memo": "좋음"}

    # **ack가 올 때까지 다시 실린다.**
    again = client.post("/api/v1/bot-ui/heartbeat", json=heartbeat_body(), headers=host["auth"]).json()
    assert len(again["approvals"]) == 1

    done = client.post(
        "/api/v1/bot-ui/heartbeat",
        json=heartbeat_body(approval_acks=[{"request_id": REQUEST, "accepted": True}]),
        headers=host["auth"],
    ).json()
    assert done["approvals"] == [], "받아 갔으면 더 내려가지 않는다"
    assert client.get(f"/api/v1/approvals/{REQUEST}", headers=READ_AUTH).json()["delivered"] is True


def test_a_refused_answer_goes_back_to_open(client: TestClient, host: dict[str, Any]) -> None:
    """**거절은 되돌림이다** (C6) — 사유를 남기고 다시 답할 수 있게 연다."""
    put(client, host)
    client.post(f"/api/v1/approvals/{REQUEST}/answer", json={"answer": {"approved": True}}, headers=ADMIN)
    client.post("/api/v1/bot-ui/heartbeat", json=heartbeat_body(), headers=host["auth"])

    client.post(
        "/api/v1/bot-ui/heartbeat",
        json=heartbeat_body(
            approval_acks=[{"request_id": REQUEST, "accepted": False, "reason": "폼이 바뀌었습니다"}]
        ),
        headers=host["auth"],
    )
    found = client.get(f"/api/v1/approvals/{REQUEST}", headers=READ_AUTH).json()
    assert found["state"] == "open", "실행하는 쪽은 계속 기다린다"
    assert found["delivery_accepted"] is False
    assert found["delivery_reason"] == "폼이 바뀌었습니다"
    assert found.get("answer") is None, "고쳐서 다시 답할 수 있다"

    # 다시 답할 수 있다 (`already_answered`가 막지 않는다).
    assert client.post(
        f"/api/v1/approvals/{REQUEST}/answer", json={"answer": {"approved": False}}, headers=ADMIN
    ).status_code == 200


def test_another_bot_ui_cannot_ack_my_approval(client: TestClient, host: dict[str, Any]) -> None:
    put(client, host)
    client.post(f"/api/v1/approvals/{REQUEST}/answer", json={"answer": {"approved": True}}, headers=ADMIN)

    stranger = issue_key(client, name="딴 PC", key_type="bot_ui")
    register(client, stranger, name="딴 PC", seed="pc2")
    client.post(
        "/api/v1/bot-ui/heartbeat",
        json=heartbeat_body(approval_acks=[{"request_id": REQUEST, "accepted": True}]),
        headers={"Authorization": f"Bearer {stranger}"},
    )
    assert client.get(f"/api/v1/approvals/{REQUEST}", headers=READ_AUTH).json()["delivered"] is False


# ─────────────────────────── 값 보관 (C6 §review) ───────────────────────────


def test_values_are_purged_but_the_record_stays(
    client: TestClient, store: Store, host: dict[str, Any]
) -> None:
    """**누가·언제·결과는 남고 값만 지운다** — 거래처 이름과 금액을 영영 둘 이유가 없다."""
    from chaeksas.center.api import approvals

    put(client, host)
    client.post(f"/api/v1/approvals/{REQUEST}/answer", json={"answer": {"approved": True}}, headers=ADMIN)

    assert approvals.purge_values(store) == 0, "끝난 지 얼마 안 됐다"

    later = (datetime.now(UTC) + timedelta(days=31)).isoformat()
    assert approvals.purge_values(store, now=later) == 1

    found = client.get(f"/api/v1/approvals/{REQUEST}", headers=READ_AUTH).json()
    assert found["review"] == {} and found.get("answer") is None, "값은 지웠다"
    assert found["state"] == "answered" and found["answered_by"] == "관리자", "사실은 남았다"


def test_open_approvals_keep_their_values(
    client: TestClient, store: Store, host: dict[str, Any]
) -> None:
    """아직 답을 기다리는 결재의 값은 **지우지 않는다** (결재자가 봐야 한다)."""
    from chaeksas.center.api import approvals

    put(client, host)
    later = (datetime.now(UTC) + timedelta(days=99)).isoformat()
    assert approvals.purge_values(store, now=later) == 0
    assert client.get(f"/api/v1/approvals/{REQUEST}", headers=READ_AUTH).json()["review"] == REVIEW


# ─────────────── 결재 담당자·대리 답 (ADR-0080·0081) ───────────────

#: 「김감독」을 퍼센트 인코딩한 것 — 헤더에 한글을 넣지 않는다 (C5).
KIM = "%EA%B9%80%EA%B0%90%EB%8F%85"


def relay(client: TestClient, *, name: str = "chaeksachat") -> dict[str, str]:
    """대리 답용 키 하나의 인증 헤더 (사람 이름 없이)."""
    return {"Authorization": f"Bearer {issue_key(client, name=name, key_type='relay')}"}


def test_assignees_ride_the_body_and_filter_the_inbox(client: TestClient, host: dict[str, Any]) -> None:
    made = put(client, host, assignees=["김감독", "이감독"])
    assert made["assignees"] == ["김감독", "이감독"]
    assert [one["request_id"] for one in client.get(
        "/api/v1/approvals", params={"assignee": " 김감독 "}, headers=READ_AUTH).json()] == [REQUEST]
    assert client.get("/api/v1/approvals", params={"assignee": "박감독"}, headers=READ_AUTH).json() == []


def test_other_assignees_are_another_body(client: TestClient, host: dict[str, Any]) -> None:
    """담당자는 본문의 일부다 — 같은 `request_id`에 다른 담당자는 409 (C6 멱등)."""
    put(client, host, assignees=["김감독"])
    again = client.post("/api/v1/approvals", json=request_body(assignees=["박감독"]), headers=host["auth"])
    assert again.status_code == 409 and again.json()["code"] == "idempotency_conflict"


def test_a_relay_key_sees_only_what_its_person_is_assigned(
    client: TestClient, host: dict[str, Any]
) -> None:
    put(client, host, assignees=["김감독"])
    auth = relay(client)
    assert client.get("/api/v1/approvals", headers=auth).json()["code"] == "on_behalf_required"
    mine = {**auth, "X-CHK-On-Behalf-Of": KIM}
    assert [one["request_id"] for one in client.get("/api/v1/approvals", headers=mine).json()] == [REQUEST]
    other = {**auth, "X-CHK-On-Behalf-Of": "%EB%B0%95"}  # 「박」
    assert client.get("/api/v1/approvals", headers=other).json() == []
    # 남의 결재 하나는 **있다는 것조차** 알리지 않는다 (404).
    assert client.get(f"/api/v1/approvals/{REQUEST}", headers=other).status_code == 404
    assert client.get(f"/api/v1/approvals/{REQUEST}", headers=mine).status_code == 200
    # 거르기는 그 사람으로 고정된다.
    asked = client.get("/api/v1/approvals", params={"assignee": "박"}, headers=mine)
    assert asked.status_code == 403 and asked.json()["code"] == "not_assignee"


def test_a_relay_answer_records_the_person_and_the_route(client: TestClient, host: dict[str, Any]) -> None:
    put(client, host, assignees=["김감독"])
    mine = {**relay(client), "X-CHK-On-Behalf-Of": KIM}
    answered = client.post(f"/api/v1/approvals/{REQUEST}/answer", json={"answer": {"approved": True}}, headers=mine)
    assert answered.status_code == 200, answered.text
    found = answered.json()
    assert (found["answered_by"], found["answered_via"]) == ("김감독", "chaeksachat")

    [dispatched] = client.post(
        "/api/v1/bot-ui/heartbeat", json=heartbeat_body(), headers=host["auth"]
    ).json()["approvals"]
    assert (dispatched["answered_by"], dispatched["answered_via"]) == ("김감독", "chaeksachat")

    # 어느 쪽으로 답해도 결재는 한 번만 닫힌다.
    twice = client.post(f"/api/v1/approvals/{REQUEST}/answer", json={"answer": {"approved": False}},
                        headers={**ADMIN, "X-CHK-Actor": "%EC%9A%B4%EC%98%81%EC%9E%90"})
    assert twice.status_code == 409 and twice.json()["code"] == "already_answered"


def test_a_relay_answer_for_someone_not_assigned_is_refused(client: TestClient, host: dict[str, Any]) -> None:
    put(client, host, assignees=["이감독"])
    mine = {**relay(client), "X-CHK-On-Behalf-Of": KIM}
    refused = client.post(f"/api/v1/approvals/{REQUEST}/answer", json={"answer": {"approved": True}}, headers=mine)
    assert refused.status_code == 403 and refused.json()["code"] == "not_assignee"


def test_an_approval_without_assignees_is_answered_only_in_the_console(
    client: TestClient, host: dict[str, Any]
) -> None:
    put(client, host)
    mine = {**relay(client), "X-CHK-On-Behalf-Of": KIM}
    refused = client.post(f"/api/v1/approvals/{REQUEST}/answer", json={"answer": {"approved": True}}, headers=mine)
    assert refused.status_code == 403 and refused.json()["code"] == "not_assignee"
    # 콘솔(관리자 토큰)은 담당자로 막지 않는다 — 이름이 자칭이라서다 (ADR-0080).
    ok = client.post(f"/api/v1/approvals/{REQUEST}/answer", json={"answer": {"approved": True}}, headers=ADMIN)
    assert ok.status_code == 200 and ok.json()["answered_via"] is None


def test_the_console_is_not_blocked_by_assignees(client: TestClient, host: dict[str, Any]) -> None:
    put(client, host, assignees=["이감독"])
    ok = client.post(f"/api/v1/approvals/{REQUEST}/answer", json={"answer": {"approved": True}},
                     headers={**ADMIN, "X-CHK-Actor": KIM})
    assert ok.status_code == 200 and ok.json()["answered_by"] == "김감독"


def test_a_bad_on_behalf_name_is_refused(client: TestClient, host: dict[str, Any]) -> None:
    put(client, host, assignees=["김감독"])
    auth = relay(client)
    for bad in ("server_bot%3Arun_x", "%20", "%FF"):
        found = client.get("/api/v1/approvals", headers={**auth, "X-CHK-On-Behalf-Of": bad})
        assert found.status_code == 422 and found.json()["code"] == "on_behalf_invalid", bad


def test_a_relay_key_does_nothing_but_approvals(client: TestClient, host: dict[str, Any]) -> None:
    """권한은 결재 셋뿐이다 (ADR-0081) — 키가 새도 다른 것이 열리지 않는다."""
    mine = {**relay(client), "X-CHK-On-Behalf-Of": KIM}
    assert client.get("/api/v1/resources", headers=mine).status_code == 403
    assert client.get("/api/v1/runs", headers=mine).status_code == 403
    assert client.post(f"/api/v1/runs/{RUN}/events", json=[], headers=mine).status_code == 403
    job = {"bpm_process_id": BOT, "target": {"type": "bot_ui", "id": host["bot_ui_id"]}, "inputs": {}}
    assert client.post("/api/v1/jobs", json=job, headers=mine).status_code == 403


def test_other_keys_do_not_read_the_inbox(client: TestClient, host: dict[str, Any]) -> None:
    """결재에는 검토 자료(업무 값)가 있다 — 실행하는 쪽 키로는 읽지 못한다 (C6 권한표)."""
    put(client, host)
    assert client.get("/api/v1/approvals", headers=host["auth"]).status_code == 403
    assert client.get(f"/api/v1/approvals/{REQUEST}", headers=host["auth"]).status_code == 403


def test_requested_by_comes_from_the_job_that_started_the_run(
    client: TestClient, store: Store, host: dict[str, Any]
) -> None:
    put(client, host)
    assert client.get(f"/api/v1/approvals/{REQUEST}", headers=READ_AUTH).json().get("requested_by") is None
    with store.tx() as cur:
        cur.execute(
            "INSERT INTO jobs (job_id, bpm_process_id, version, target_type, target_id, inputs_json, owner,"
            " body_hash, requested_by, requested_at, state, run_id)"
            " VALUES ('job_0000abcd', ?, '1.0.0', 'bot_ui', ?, '{}', 'key:x', 'h', 'intake-key', ?, 'accepted', ?)",
            (BOT, host["bot_ui_id"], "2026-10-06T09:15:00+00:00", RUN),
        )
    assert client.get(f"/api/v1/approvals/{REQUEST}", headers=READ_AUTH).json()["requested_by"] == "intake-key"


# ─────────────── 내용 고정 (ADR-0083) ───────────────


def test_the_review_digest_is_set_and_kept_after_the_values_go(
    client: TestClient, store: Store, host: dict[str, Any]
) -> None:
    from chaeksas.center.api import approvals as approvals_api  # noqa: PLC0415
    from chaeksas.contracts.approvals import review_digest  # noqa: PLC0415

    made = put(client, host)
    assert made["review_digest"] == review_digest(REVIEW)
    assert made["review_digest"].startswith("sha256:")
    client.post(f"/api/v1/approvals/{REQUEST}/answer", json={"answer": {"approved": True}}, headers=ADMIN)
    assert approvals_api.purge_values(store, now="2099-01-01T00:00:00+00:00") == 1
    found = client.get(f"/api/v1/approvals/{REQUEST}", headers=READ_AUTH).json()
    assert found["review"] == {} and found["review_digest"] == made["review_digest"], "지문은 남는다"


def test_an_answer_for_what_someone_else_saw_is_refused(client: TestClient, host: dict[str, Any]) -> None:
    """답하는 쪽이 본 것과 다르면 받지 않는다 — 다시 읽어 사람에게 보여야 한다."""
    made = put(client, host, assignees=["김감독"])
    mine = {**relay(client), "X-CHK-On-Behalf-Of": KIM}
    wrong = client.post(f"/api/v1/approvals/{REQUEST}/answer",
                        json={"answer": {"approved": True}, "if_review_digest": "sha256:" + "0" * 64}, headers=mine)
    assert wrong.status_code == 409 and wrong.json()["code"] == "review_changed"
    assert client.get(f"/api/v1/approvals/{REQUEST}", headers=READ_AUTH).json()["state"] == "open"
    right = client.post(f"/api/v1/approvals/{REQUEST}/answer",
                        json={"answer": {"approved": True}, "if_review_digest": made["review_digest"]}, headers=mine)
    assert right.status_code == 200, right.text


def test_the_digest_rule_is_the_one_the_request_named() -> None:
    """정규화는 키 정렬·`,`/`:`·한글 그대로 — 연동하는 쪽(`args_digest`)과 같은 규칙이다."""
    import hashlib  # noqa: PLC0415
    import json  # noqa: PLC0415

    from chaeksas.contracts.approvals import review_digest  # noqa: PLC0415

    review = {"금액": 1100000, "거래처": "주식회사 예시"}
    body = json.dumps(review, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert review_digest(review) == "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()
    assert review_digest({"b": 1, "a": 2}) == review_digest({"a": 2, "b": 1})
