"""Center가 실행 이벤트를 받고 보여 준다 (C3, M3 조각 3g).

받는 쪽의 태도가 계약에 또렷하다 — 그것을 시험한다.

1. **모르는 `kind`는 거부하지 않고 저장만 한다** — 하나를 거부하면 `seq`가 단조라서 그 실행의
   기록이 **영원히** 막힌다 (프로토타입에서 실제로 일어났다).
2. **줄 하나가 틀려도 나머지는 받는다** (`200` + `rejected[]`).
3. **같은 줄을 다시 보내면 무시한다** — 보내는 쪽이 같은 배치를 그대로 또 보낼 수 있다.
4. **남의 실행 기록을 덮지 못한다** (`run_owner_mismatch`).
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from chaeksas.center.api.runs import CODE_MISSING, CODE_SCHEMA
from chaeksas.center.app import create_app
from chaeksas.center.settings import Settings
from chaeksas.center.storage import Store

ADMIN = "admin-token"
READ = "read-token"
RUN = "run_20261005_101500_a1b2c3"


@pytest.fixture
def client(tmp_path: Any) -> Any:
    settings = Settings(admin_token=ADMIN, read_token=READ, package_dir=tmp_path / "packages")
    return TestClient(create_app(settings, store=Store(tmp_path / "center.db")))


def event(seq: int, kind: str = "log", **data: Any) -> dict[str, Any]:
    return {
        "schema": 1,
        "run_id": RUN,
        "seq": seq,
        "ts": f"2026-10-05T10:15:{seq:02d}+09:00",
        "kind": kind,
        "data": data or {"level": "info", "message": "한 줄"},
    }


def started(seq: int = 1, **extra: Any) -> dict[str, Any]:
    return event(
        seq,
        "run_started",
        bpm_process_id="fin.invoice",
        version="1.0.0",
        run_location="server",
        executor="bot_ui",
        mode="autonomous",
        source="job",
        **extra,
    )


def post(client: Any, lines: list[dict[str, Any]], *, token: str = ADMIN, run_id: str = RUN) -> Any:
    return client.post(
        f"/api/v1/runs/{run_id}/events", json=lines, headers={"Authorization": f"Bearer {token}"}
    )


def read(client: Any, path: str) -> Any:
    return client.get(path, headers={"Authorization": f"Bearer {READ}"})


# ─────────────────────────── 받기 ───────────────────────────


def test_a_batch_is_accepted(client: Any) -> None:
    answer = post(client, [started(), event(2)])
    assert answer.status_code == 200
    assert answer.json() == {"run_id": RUN, "accepted": 2, "duplicates": 0, "rejected": []}


def test_the_same_batch_again_is_ignored(client: Any) -> None:
    """실패하면 **같은 배치를 그대로** 다시 보낼 수 있어야 한다 (C3 §전송)."""
    post(client, [started(), event(2)])
    answer = post(client, [started(), event(2), event(3)])
    assert answer.json()["accepted"] == 1
    assert answer.json()["duplicates"] == 2


def test_an_unknown_kind_is_stored_not_refused(client: Any) -> None:
    """하나를 거부하면 그 실행의 기록이 **영원히** 막힌다 (C3 §호환 규칙)."""
    answer = post(client, [started(), event(2, "아직없는종류", 뭔가="값")])
    assert answer.json()["accepted"] == 2
    kinds = [e["kind"] for e in read(client, f"/api/v1/runs/{RUN}/events").json()["events"]]
    assert "아직없는종류" in kinds


def test_a_line_missing_required_data_is_rejected_alone(client: Any) -> None:
    """나머지 줄은 받는다 — 한 줄이 실행 전체를 막지 않는다."""
    answer = post(client, [started(), {**event(2, "node_state"), "data": {}}, event(3)])
    body = answer.json()
    assert body["accepted"] == 2
    assert body["rejected"] == [{"seq": 2, "code": CODE_MISSING}]


def test_a_higher_schema_line_is_rejected(client: Any) -> None:
    """아는 필드의 뜻이 바뀌었을 수 있다 (C3 §호환 규칙)."""
    answer = post(client, [{**event(1), "schema": 2}])
    assert answer.json()["rejected"] == [{"seq": 1, "code": CODE_SCHEMA}]


def test_a_line_for_another_run_is_rejected(client: Any) -> None:
    answer = post(client, [started(), {**event(2), "run_id": "run_20261005_101500_ffffff"}])
    assert answer.json()["accepted"] == 1
    assert answer.json()["rejected"][0]["code"] == "run_id_mismatch"


def test_a_batch_that_is_not_a_list_is_refused(client: Any) -> None:
    answer = client.post(
        f"/api/v1/runs/{RUN}/events", json={"seq": 1}, headers={"Authorization": f"Bearer {ADMIN}"}
    )
    assert answer.status_code == 422


def test_too_many_lines_are_refused(client: Any) -> None:
    answer = post(client, [event(i) for i in range(1, 502)])
    assert answer.status_code == 413


def test_another_key_cannot_write_to_the_same_run(client: Any) -> None:
    """남의 실행 기록을 덮지 못한다 (C3 §전송 「소유」)."""
    post(client, [started()])
    answer = post(client, [event(2)], token=READ)
    assert answer.status_code == 403
    assert answer.json()["code"] == "run_owner_mismatch"


# ─────────────────────────── 보여 주기 (CON-01) ───────────────────────────


def test_the_summary_comes_from_the_events(client: Any) -> None:
    post(client, [started()])
    found = read(client, f"/api/v1/runs/{RUN}").json()
    assert found["status"] == "running"
    assert found["bpm_process_id"] == "fin.invoice"
    assert found["run_location"] == "server"
    assert found["events"] == 1


def test_a_finished_run_says_so(client: Any) -> None:
    post(client, [started(), event(2, "run_finished", status="success", duration_s=12.5,
                                   ai_tasks=1, replayed_tasks=0, ui_tasks=0, service_calls=0,
                                   human_requests=0)])
    found = read(client, f"/api/v1/runs/{RUN}").json()
    assert found["status"] == "success" and found["duration_s"] == 12.5


def test_a_late_batch_does_not_un_finish_a_run(client: Any) -> None:
    """늦게 온 줄이 끝난 실행을 「도는 중」으로 되돌리면 목록이 거짓말을 한다."""
    post(client, [started(), event(5, "run_finished", status="failed", duration_s=1,
                                   ai_tasks=0, replayed_tasks=0, ui_tasks=0, service_calls=0,
                                   human_requests=0)])
    post(client, [event(2, "run_waiting", waiting_for="approval")])
    assert read(client, f"/api/v1/runs/{RUN}").json()["status"] == "failed"


def test_the_events_come_back_in_seq_order(client: Any) -> None:
    """타임라인이 순서를 만든다 — 받은 차례가 아니라 `seq` 차례다."""
    post(client, [event(3), event(1, "log", level="info", message="첫 줄")])
    post(client, [event(2)])
    seqs = [e["seq"] for e in read(client, f"/api/v1/runs/{RUN}/events").json()["events"]]
    assert seqs == [1, 2, 3]


def test_the_listing_can_be_narrowed(client: Any) -> None:
    post(client, [started()])
    post(client, [{**started(), "run_id": "run_20261005_101600_b2c3d4"}], run_id="run_20261005_101600_b2c3d4")
    assert read(client, "/api/v1/runs").json()["total"] == 2
    assert read(client, "/api/v1/runs?status=success").json()["total"] == 0
    assert read(client, "/api/v1/runs?bpm_process_id=fin.invoice").json()["total"] == 2


def test_the_listing_can_be_narrowed_by_run_location(client: Any) -> None:
    """CON-01 「실행 위치」 좁히기 — 값은 `run_started`에서 온다."""
    other = "run_20261005_101600_b2c3d4"
    post(client, [started()])  # server
    post(client, [{**started(), "run_id": other, "data": {**started()["data"], "run_location": "pc"}}], run_id=other)
    assert read(client, "/api/v1/runs?run_location=pc").json()["total"] == 1
    assert read(client, "/api/v1/runs?run_location=server").json()["total"] == 1
    assert read(client, "/api/v1/runs?run_location=nowhere").json()["total"] == 0, "모르는 값은 0건이다"


def test_the_listing_keeps_the_counts_the_sender_counted(client: Any) -> None:
    """CON-01 목록의 셈 열 — **보낸 쪽이 센 것**을 그대로 둔다 (줄을 다시 읽어 세지 않는다)."""
    post(client, [started(), event(2, "ui_session", business_key=f"{RUN}:T:1:1", page_id="p",
                                   result="success", steps=3, fallback_depth_max=1, healed=False)])
    running = read(client, f"/api/v1/runs/{RUN}").json()
    # **도는 중에는 비어 있다** — 0으로 보이면 「아무것도 없었다」로 읽힌다.
    assert running["ui_tasks"] is None and running["ai_tasks"] is None

    post(client, [event(3, "run_finished", status="success", duration_s=2, ai_tasks=2,
                        replayed_tasks=1, ui_tasks=1, service_calls=4, human_requests=0)])
    found = read(client, f"/api/v1/runs/{RUN}").json()
    assert (found["ai_tasks"], found["replayed_tasks"], found["ui_tasks"]) == (2, 1, 1)
    assert (found["service_calls"], found["human_requests"]) == (4, 0)
    assert read(client, "/api/v1/runs").json()["runs"][0]["ui_tasks"] == 1, "목록에도 실린다"


def test_an_unknown_run_is_404(client: Any) -> None:
    assert read(client, "/api/v1/runs/run_20261005_000000_000000").status_code == 404


def test_reading_needs_a_key(client: Any) -> None:
    assert client.get(f"/api/v1/runs/{RUN}").status_code == 401
