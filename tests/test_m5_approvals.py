"""결재 한 바퀴 — 올리기 → 결재함 → 답하기 → 하트비트 (C4·C6, M5 조각 5).

진짜 Center를 in-process로 띄우고 **진짜 Bot UI 키로** 결재를 올린다. 현장 연결(엔진이
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
        "worker": {"state": "off", "restarts": 0},
    }
    body.update(over)
    return body


@pytest.fixture
def host(client: TestClient) -> dict[str, Any]:
    """등록된 Bot UI 하나와 그 키 — 결재를 올리는 쪽."""
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
    """Bot UI가 대기열을 잃으면 그 실행의 결재도 전달될 곳이 없다 (C6 `host_lost`)."""
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
