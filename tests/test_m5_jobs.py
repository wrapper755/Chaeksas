"""작업 지시 한 바퀴 — Center `/jobs` → 하트비트 → Bot UI 대기열 (C4·C5, M5 조각 3).

진짜 Center를 in-process로 띄우고, 진짜 Bot UI 쪽 `Agent`가 **진짜 HTTP로** 하트비트를
주고받는다. 배포(조각 2)와 달리 **봉투가 없다** — 작업은 「무엇을 실행해도 되는가」가 아니라
「언제 돌려라」라서 토큰 권한이 관문이다 (C5 권한표).

거듭 보는 것 다섯.

1. **배포되지 않은 것은 돌릴 수 없다** — 작업이 배포를 건너뛰는 뒷문이 되면 안 된다.
2. **ack가 올 때까지 매번 실린다** — 하트비트 한 번을 놓쳐도 작업이 사라지지 않는다 (C4).
3. **시작된 작업의 취소는 거절**이고 작업은 `accepted`로 남는다 (C5 「취소」 표).
4. **잃어버린 대기열은 드러난다** — 두 번 연속 보이지 않으면 `bot_ui_lost` (C4 맞추기 규칙).
5. **연동용 키는 자기 것만** 본다 (C5 권한표).
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from chaeksas.admin import keys as keystore
from chaeksas.admin.cli import main as admin_main
from chaeksas.admin.client import Center, CenterProblem
from chaeksas.bot_ui.agent import Agent
from chaeksas.bot_ui.center_client import CenterClient
from chaeksas.bot_ui.settings import Settings as BotSettings
from chaeksas.bot_ui.store import Store as BotStore
from chaeksas.center.api.signing import bootstrap_key
from chaeksas.center.app import create_app
from chaeksas.center.settings import Settings
from chaeksas.center.storage import Store
from chaeksas.contracts.bot_ui import HeartbeatResponse
from chaeksas.contracts.hashing import content_hash_zip
from chaeksas.contracts.signing import sign

TOKEN = "t-admin"
READ = "t-read"
PASS = "열쇠말"
AT = "2026-10-05T09:00:00+09:00"
BOT = "erp.order-entry"
VERSION = "2.1.0"
INPUTS = {"주문번호": "PO-2608-001"}

ADMIN_AUTH = {"Authorization": f"Bearer {TOKEN}"}
READ_AUTH = {"Authorization": f"Bearer {READ}"}


@pytest.fixture(autouse=True)
def _admin_home(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setenv(keystore.PASSPHRASE_ENV, PASS)
    monkeypatch.setenv(f"{keystore.ENV_PREFIX}DATA_DIR", str(tmp_path / "admin"))


# ─────────────────────────── 세상 하나 ───────────────────────────


@dataclass
class World:
    """Center 하나 + 그 Center에 등록된 Bot UI 하나 + 배포된 Bot 하나."""

    center: Center
    client: TestClient
    agent: Agent
    bot_ui_id: str

    # ── Center 쪽 ──

    def new_job(self, **over: Any) -> dict[str, Any]:
        body: dict[str, Any] = {
            "bpm_process_id": BOT,
            "target": {"type": "bot_ui", "id": self.bot_ui_id},
            "inputs": dict(INPUTS),
        }
        return self.center.create_job(body | over)

    def job(self, job_id: str) -> dict[str, Any]:
        return self.center.job(job_id)

    def cancel(self, job_id: str) -> Any:
        """취소 — 응답 코드까지 본다 (200과 202가 다른 뜻이다)."""
        return self.client.delete(f"/api/v1/jobs/{job_id}", headers=ADMIN_AUTH)

    # ── Bot UI 쪽 ──

    def beat(self) -> HeartbeatResponse:
        """하트비트 한 번 — **진짜 HTTP로** 오가고, 받은 지시를 진짜 `Agent`가 처리한다.

        `Agent.beat()`를 그대로 부르지 않는 것은 그것이 실행기·기록 보내기까지 돌리기
        때문이다. 여기서 보려는 것은 C4의 작업 주고받기 한 바퀴다.
        """
        request = self.agent.heartbeat_request()
        response = self.agent.client().heartbeat(request)
        self.agent.store.ack_sent(request.job_acks)
        self.agent.disabled = response.disabled
        self.agent.apply(response)
        self.agent.store.save()
        return response


def package_zip(package_id: str = BOT, version: str = VERSION) -> bytes:
    import tempfile

    manifest: dict[str, Any] = {
        "schema": 1,
        "kind": "bpm_process",
        "id": package_id,
        "version": version,
        "name": "주문 입력",
        "run_location": "pc",
        "entry": "process/main.bpmn",
        "process_id": "Proc_order",
        "requires": {},
        "human": {},
        "built": {"by": "studio", "at": AT, "core": "0.1.0", "spec_version": 1},
        "content_hash": "sha256:" + "0" * 64,
    }

    def made(body: str) -> bytes:
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("process/main.bpmn", "<definitions />")
            archive.writestr("manifest.json", body)
        return out.getvalue()

    staged = made(json.dumps(manifest, ensure_ascii=False))
    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder) / "p.zip"
        tmp.write_bytes(staged)
        manifest["content_hash"] = content_hash_zip(tmp)
    return made(json.dumps(manifest, ensure_ascii=False))


def deploy_bot(center: Center, bot_ui_id: str, *, version: str = VERSION) -> dict[str, Any]:
    """업로드 → 승인 → 배포까지. 작업은 **배포가 있어야** 만들 수 있다 (C5)."""
    answer = center.client.post(
        "/api/v1/packages",
        files={"file": ("p.zip", package_zip(version=version), "application/zip")},
        headers=ADMIN_AUTH,
    )
    assert answer.status_code in (200, 201), answer.text
    info = dict(answer.json())

    key = keystore.find(None)
    center.approve(
        info["id"],
        info["version"],
        sign(
            {"kind": "package", "id": info["id"], "version": info["version"],
             "content_hash": info["content_hash"]},
            keystore.load(key, passphrase=PASS),
            signed_at=AT,
        ),
    )
    center.deploy(
        sign(
            {
                "kind": "deployment",
                "deployment_id": f"dep_{hashlib.sha256(version.encode()).hexdigest()[:8]}",
                "target": {"type": "bot_ui", "id": bot_ui_id},
                "bpm_process_id": info["id"],
                "version": info["version"],
                "content_hash": info["content_hash"],
            },
            keystore.load(key, passphrase=PASS),
            signed_at=AT,
        )
    )
    return info


def issue_key(client: TestClient, *, name: str, key_type: str) -> str:
    answer = client.post("/api/v1/center-keys", json={"name": name, "type": key_type}, headers=ADMIN_AUTH)
    assert answer.status_code == 201, answer.text
    return str(answer.json()["key"])


@pytest.fixture
def world(tmp_path: Path) -> World:
    from conftest import FakeCredentials

    settings = Settings(
        db_path=tmp_path / "center.sqlite3",
        package_dir=tmp_path / "packages",
        admin_token=TOKEN,
        read_token=READ,
    )
    store = Store(settings.db_path)
    client = TestClient(create_app(settings, store=store))
    center = Center(base_url="http://center", token=TOKEN, client=client)

    made = keystore.create(label="첫 키")
    bootstrap_key(store, public_key=made.public_bytes(), label="첫 키")

    # Bot UI를 **진짜로 등록한다** — 신원은 키가 정한다 (C4).
    raw = issue_key(client, name="현장 PC 1", key_type="bot_ui")
    agent = Agent(
        settings=BotSettings(queue_max=2),
        store=BotStore.load(tmp_path / "state.json"),
        credentials=FakeCredentials(raw),
        client_factory=lambda url, key: CenterClient(base_url="http://center", api_key=key, client=client),
    )
    agent.register()
    bot_ui_id = agent.bot_ui_id or ""
    assert bot_ui_id.startswith("bui_")

    deploy_bot(center, bot_ui_id)
    return World(center=center, client=client, agent=agent, bot_ui_id=bot_ui_id)


# ─────────────────────────── 만들기 (C5 POST /jobs) ───────────────────────────


def test_a_job_needs_a_deployment(world: World) -> None:
    """**배포되지 않은 것은 돌릴 수 없다** — 작업이 배포를 건너뛰는 뒷문이 아니다."""
    with pytest.raises(CenterProblem) as caught:
        world.new_job(bpm_process_id="erp.없는것")
    assert caught.value.code == "no_deployment"


def test_an_unknown_bot_ui_is_not_found(world: World) -> None:
    with pytest.raises(CenterProblem) as caught:
        world.new_job(target={"type": "bot_ui", "id": "bui_00000000"})
    assert caught.value.status == 404


def test_the_version_comes_from_the_deployment(world: World) -> None:
    """`version`을 비우면 **대상에 배포된 버전**으로 채운다 (C5)."""
    made = world.new_job()
    assert made["version"] == VERSION
    assert made["state"] == "pending"
    assert made["requested_by"] == "관리자", "행위자는 본문이 아니라 토큰이 정한다"


def test_two_deployed_versions_need_an_explicit_version(world: World) -> None:
    deploy_bot(world.center, world.bot_ui_id, version="2.2.0")
    with pytest.raises(CenterProblem) as caught:
        world.new_job()
    assert caught.value.code == "version_ambiguous"
    assert world.new_job(version="2.2.0")["version"] == "2.2.0", "정해 주면 된다"


def test_inputs_must_be_an_object(world: World) -> None:
    with pytest.raises(CenterProblem) as caught:
        world.new_job(inputs=["주문번호"])
    assert caught.value.code == "inputs_not_object"


def test_a_server_runner_job_is_refused(world: World) -> None:
    """서버 실행은 M7부터다 (ADR-0016) — 배포와 같은 사유로 막는다."""
    with pytest.raises(CenterProblem) as caught:
        world.new_job(target={"type": "server_runner", "id": "*"})
    assert caught.value.code == "server_runner_not_available"


def test_the_same_idempotency_key_gives_back_the_same_job(world: World) -> None:
    """같은 키에 같은 본문이면 200, 다른 본문이면 409 (C5)."""
    first = world.client.post(
        "/api/v1/jobs",
        json={"bpm_process_id": BOT, "target": {"type": "bot_ui", "id": world.bot_ui_id},
              "inputs": dict(INPUTS), "idempotency_key": "주문-001"},
        headers=ADMIN_AUTH,
    )
    assert first.status_code == 201
    again = world.client.post(
        "/api/v1/jobs",
        json={"bpm_process_id": BOT, "target": {"type": "bot_ui", "id": world.bot_ui_id},
              "inputs": dict(INPUTS), "idempotency_key": "주문-001"},
        headers=ADMIN_AUTH,
    )
    assert again.status_code == 200
    assert again.json()["job_id"] == first.json()["job_id"]

    other = world.client.post(
        "/api/v1/jobs",
        json={"bpm_process_id": BOT, "target": {"type": "bot_ui", "id": world.bot_ui_id},
              "inputs": {"주문번호": "다른것"}, "idempotency_key": "주문-001"},
        headers=ADMIN_AUTH,
    )
    assert other.status_code == 409 and other.json()["code"] == "idempotency_conflict"


# ─────────────────────────── 권한 (C5 권한표) ───────────────────────────


def test_a_read_token_can_look_but_not_touch(world: World) -> None:
    made = world.new_job()
    assert world.client.get("/api/v1/jobs", headers=READ_AUTH).status_code == 200
    blocked = world.client.post(
        "/api/v1/jobs",
        json={"bpm_process_id": BOT, "target": {"type": "bot_ui", "id": world.bot_ui_id}, "inputs": {}},
        headers=READ_AUTH,
    )
    assert blocked.status_code == 403
    assert world.client.delete(f"/api/v1/jobs/{made['job_id']}", headers=READ_AUTH).status_code == 403


def test_a_bot_ui_key_cannot_touch_jobs(world: World) -> None:
    """실행하는 쪽의 키로는 작업을 만들지 못한다 — 자기에게 일을 시킬 수 없다 (C5)."""
    raw = issue_key(world.client, name="다른 PC", key_type="bot_ui")
    answer = world.client.post(
        "/api/v1/jobs",
        json={"bpm_process_id": BOT, "target": {"type": "bot_ui", "id": world.bot_ui_id}, "inputs": {}},
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert answer.status_code == 403


def test_an_integration_key_sees_only_its_own(world: World) -> None:
    """연동용 키는 만들 수 있고, **자기가 만든 것만** 읽고 취소한다 (C5)."""
    raw = issue_key(world.client, name="ERP 연동", key_type="integration")
    outside = {"Authorization": f"Bearer {raw}"}
    mine = world.client.post(
        "/api/v1/jobs",
        json={"bpm_process_id": BOT, "target": {"type": "bot_ui", "id": world.bot_ui_id},
              "inputs": dict(INPUTS)},
        headers=outside,
    )
    assert mine.status_code == 201
    assert mine.json()["requested_by"] == "ERP 연동", "행위자는 키 이름이다"

    theirs = world.new_job()  # 관리자가 만든 것
    listed = world.client.get("/api/v1/jobs", headers=outside).json()
    assert [one["job_id"] for one in listed] == [mine.json()["job_id"]]
    # **남의 것은 있다는 것조차 알려 주지 않는다.**
    assert world.client.get(f"/api/v1/jobs/{theirs['job_id']}", headers=outside).status_code == 404
    assert world.client.delete(f"/api/v1/jobs/{theirs['job_id']}", headers=outside).status_code == 404
    assert len(world.client.get("/api/v1/jobs", headers=ADMIN_AUTH).json()) == 2, "관리자는 다 본다"


# ─────────────────────────── 하트비트 한 바퀴 (C4) ───────────────────────────


def test_a_job_rides_the_heartbeat_into_the_queue(world: World) -> None:
    """한 바퀴 — 만들기 → 전달 → **현장 대기열** → Center가 그것을 안다."""
    made = world.new_job()

    response = world.beat()
    assert [one.job_id for one in response.jobs] == [made["job_id"]]
    assert [one.inputs for one in response.jobs] == [INPUTS], "입력이 그대로 내려간다"
    assert world.job(made["job_id"])["state"] == "dispatched"
    assert [item.job_id for item in world.agent.queue] == [made["job_id"]]

    world.beat()  # 현장의 `queued` ack가 올라간다
    found = world.job(made["job_id"])
    assert found["state"] == "queued" and found["queue_position"] == 1


def test_it_keeps_riding_until_acked(world: World) -> None:
    """**ack가 올 때까지 매번 실린다** (C4) — 하트비트를 놓쳐도 작업이 사라지지 않는다."""
    made = world.new_job()
    first = world.agent.client().heartbeat(world.agent.heartbeat_request())
    assert [one.job_id for one in first.jobs] == [made["job_id"]]
    # 응답을 못 받은 셈 치고 (ack를 만들지 않고) 한 번 더 — 같은 작업이 또 온다.
    again = world.agent.client().heartbeat(world.agent.heartbeat_request())
    assert [one.job_id for one in again.jobs] == [made["job_id"]]

    world.beat()  # 이제 진짜로 받는다
    world.beat()
    assert world.job(made["job_id"])["state"] == "queued"
    assert world.beat().jobs == [], "받은 뒤에는 더 내려오지 않는다"


def test_starting_the_bot_accepts_the_job(world: World) -> None:
    """현장이 실행 자리에 올리면 `accepted`가 되고 `run_id`가 붙는다 (C4)."""
    made = world.new_job()
    world.beat()
    run = world.agent.claim_slot(world.agent.queue[0])
    world.beat()

    found = world.job(made["job_id"])
    assert found["state"] == "accepted" and found["run_id"] == run.run_id


def test_a_full_queue_is_refused(world: World) -> None:
    """대기열이 가득 차면 거절이다 (ADR-0014) — 사유가 Center까지 온다."""
    made = [world.new_job(), world.new_job(), world.new_job()]  # queue_max=2
    world.beat()
    world.beat()
    states = {one["job_id"]: one for one in world.center.jobs()}
    rejected = [one for one in made if states[one["job_id"]]["state"] == "rejected"]
    assert len(rejected) == 1
    assert states[rejected[0]["job_id"]]["state_reason"] == "queue_full"


def test_a_disabled_bot_ui_gets_no_jobs(world: World) -> None:
    """비활성화하면 **새 작업을 보내지 않는다**. 작업은 `pending`으로 기다린다 (C5 CON-03)."""
    made = world.new_job()
    world.client.post(f"/api/v1/bot-uis/{world.bot_ui_id}/disable", headers=ADMIN_AUTH)
    assert world.beat().jobs == []
    assert world.job(made["job_id"])["state"] == "pending"

    world.client.post(f"/api/v1/bot-uis/{world.bot_ui_id}/enable", headers=ADMIN_AUTH)
    assert [one.job_id for one in world.beat().jobs] == [made["job_id"]]


# ─────────────────────────── 취소 (C5 「취소」 표) ───────────────────────────


def test_a_pending_job_cancels_at_once(world: World) -> None:
    made = world.new_job()
    answer = world.cancel(made["job_id"])
    assert answer.status_code == 200
    assert answer.json()["state"] == "cancelled"
    assert world.beat().jobs == [], "취소된 것은 내려가지 않는다"


def test_a_queued_job_is_cancelled_through_the_heartbeat(world: World) -> None:
    """**202는 아직 끝난 것이 아니다** — 현장이 빼내고 ack해야 `cancelled`다."""
    made = world.new_job()
    world.beat()
    world.beat()
    assert world.job(made["job_id"])["state"] == "queued"

    answer = world.cancel(made["job_id"])
    assert answer.status_code == 202
    assert answer.json()["cancel_requested"] is True
    assert answer.json()["state"] == "queued", "아직 취소된 것이 아니다"

    response = world.beat()  # 취소 지시가 내려가고 현장이 대기열에서 뺀다
    assert response.cancel_jobs == [made["job_id"]]
    assert world.agent.queue == []
    world.beat()  # ack가 올라간다
    assert world.job(made["job_id"])["state"] == "cancelled"


def test_a_started_job_refuses_cancellation(world: World) -> None:
    """**시작된 작업의 취소는 거절**이고 작업은 `accepted`로 남는다 (C5).

    취소 요청과 `started` ack가 엇갈린 경우다 — 현장만이 「이미 시작했다」고 말할 수 있다.
    """
    made = world.new_job()
    world.beat()
    world.agent.claim_slot(world.agent.queue[0])  # Center는 아직 모른다
    assert world.cancel(made["job_id"]).status_code == 202

    response = world.beat()  # `started` ack가 올라가고, 취소 지시가 내려온다
    assert response.cancel_jobs == [made["job_id"]]
    assert world.agent.current_run is not None, "멈추지 않는다"

    world.beat()  # `cancel_refused` ack가 올라간다
    found = world.job(made["job_id"])
    assert found["state"] == "accepted"
    assert found["cancel_result"] == "refused_already_started"


def test_an_accepted_job_cannot_be_cancelled(world: World) -> None:
    """Center가 이미 실행을 아는 경우는 409다 — 물어볼 것도 없다."""
    world.new_job()
    world.beat()
    world.agent.claim_slot(world.agent.queue[0])
    world.beat()
    found = world.center.jobs()[0]
    assert found["state"] == "accepted"

    answer = world.cancel(found["job_id"])
    assert answer.status_code == 409 and answer.json()["code"] == "already_started"


def test_a_finished_job_cannot_be_cancelled(world: World) -> None:
    made = world.new_job()
    world.cancel(made["job_id"])
    answer = world.cancel(made["job_id"])
    assert answer.status_code == 409 and answer.json()["code"] == "not_cancellable"


# ─────────────────────────── 사라지지 않게 (C4 맞추기 규칙) ───────────────────────────


def test_a_lost_queue_is_noticed(world: World) -> None:
    """Bot UI가 비정상 종료로 대기열을 잃으면 작업이 영원히 `queued`로 남는다 — 그걸 막는다."""
    made = world.new_job()
    world.beat()
    world.beat()
    assert world.job(made["job_id"])["state"] == "queued"

    # 대기열을 통째로 잃은 흉내 (ack도 없다).
    world.agent.store.state.queue.clear()
    world.beat()
    assert world.job(made["job_id"])["state"] == "queued", "한 번은 봐준다 (C4 — 두 번 연속)"
    world.beat()
    found = world.job(made["job_id"])
    assert found["state"] == "rejected" and found["state_reason"] == "bot_ui_lost"


def test_seeing_it_again_clears_the_count(world: World) -> None:
    made = world.new_job()
    world.beat()
    world.beat()
    item = world.agent.queue[0]
    world.agent.store.state.queue.clear()
    world.beat()  # 한 번 안 보임
    world.agent.store.state.queue.append(item)
    world.beat()  # 다시 보인다 — 셈이 0으로
    world.agent.store.state.queue.clear()
    world.beat()
    assert world.job(made["job_id"])["state"] == "queued", "연속이 아니면 잃은 것이 아니다"


def test_an_expired_job_never_starts(world: World) -> None:
    """`expires_at`까지 시작하지 못하면 `expired`다 (C5)."""
    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    made = world.new_job(expires_at=past)
    assert world.beat().jobs == []
    assert world.job(made["job_id"])["state"] == "expired"


def test_a_live_deadline_still_runs(world: World) -> None:
    later = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    made = world.new_job(expires_at=later)
    assert [one.job_id for one in world.beat().jobs] == [made["job_id"]]
    assert [one.expires_at for one in world.agent.jobs_waiting] == [later]


# ─────────────────────────── 명령줄 (ADM) ───────────────────────────


def test_the_command_sends_a_job(world: World, capsys: Any) -> None:
    code = admin_main(
        ["-y", "job", "new", BOT, "--bot-ui", world.bot_ui_id, "--input", "주문번호=PO-1", "--note", "급함"],
        center=world.center,
    )
    assert code == 0
    assert "작업을 만들었습니다" in capsys.readouterr().out
    found = world.center.jobs()
    assert len(found) == 1
    assert found[0]["inputs"] == {"주문번호": "PO-1"} and found[0]["note"] == "급함"


def test_the_command_refuses_an_undeployed_bot(world: World, capsys: Any) -> None:
    assert admin_main(
        ["-y", "job", "new", "erp.없는것", "--bot-ui", world.bot_ui_id], center=world.center
    ) == 2
    assert "배포" in capsys.readouterr().err


def test_the_command_lists_shows_and_cancels(world: World, capsys: Any) -> None:
    made = world.new_job()
    assert admin_main(["job", "list"], center=world.center) == 0
    assert made["job_id"] in capsys.readouterr().out

    assert admin_main(["job", "show", made["job_id"]], center=world.center) == 0
    assert BOT in capsys.readouterr().out

    assert admin_main(["-y", "job", "cancel", made["job_id"]], center=world.center) == 0
    assert "취소했습니다" in capsys.readouterr().out
    assert world.job(made["job_id"])["state"] == "cancelled"


def test_the_command_says_when_the_answer_has_to_wait(world: World, capsys: Any) -> None:
    """202 — 현장에 물어본 상태다. **끝났다고 말하지 않는다.**"""
    made = world.new_job()
    world.beat()
    world.beat()
    assert admin_main(["-y", "job", "cancel", made["job_id"]], center=world.center) == 0
    assert "취소를 요청했습니다" in capsys.readouterr().out
