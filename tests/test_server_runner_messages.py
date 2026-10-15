"""외부 시스템의 메시지가 **기다리는 실행을 이어 가게 한다** (C12 §메시지).

한 줄로 본다: 작업 지시 → 실행기가 돌림 → 메시지를 기다리며 **자리를 놓음** →
`POST /api/v1/messages` → 하트비트 응답 `messages[]` → 실행이 이어 감 → `message_acks`.

그림은 업무 예제 **BX-11 입찰 접수와 마감**이다 — 실행 위치가 `server`이고, 견적을 메시지
`bid_quote`(상관 키 `입찰번호`)로 받아 **다시 기다리러 돌아간다**. 그래서 「두 번째 메시지도
들어가나」까지 한 그림으로 볼 수 있다. 서비스 앱·확장이 없어 꽂을 것도 없다.

| 보는 것 | 왜 |
| --- | --- |
| 기다리는 줄에 `message_name`·`correlation`이 있다 | Center가 그것으로 받는 곳을 고른다 (C12) |
| 메시지가 들어가고 **실행이 이어 간다** | M7 §메시지 |
| 받을 곳이 없으면 `no_receiver` | Center가 고른 뒤 한 주기가 지났다 |
| 같은 메시지가 두 번 와도 **한 번만** | ack가 올라가기 전에 또 내려온다 (C12) |
| **빈자리가 없으면 ack하지 않는다** | 다음 주기에 다시 온다 (거절로 적으면 버려진다) |
| ack가 올라가기 전에 **죽어도** 한 번만 | 기억이 스냅샷과 함께 담긴다 (ADR-0058) |
| **담기 전에** 죽으면 다시 받는다 | 기억과 상태가 갈라지지 않는다 — 갈라지면 영영 잃는다 |
"""

from __future__ import annotations

import io
import json
import tempfile
import time
import zipfile
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from chaeksas.admin import keys as keystore
from chaeksas.center.api.signing import bootstrap_key
from chaeksas.center.app import create_app
from chaeksas.center.settings import Settings as CenterSettings
from chaeksas.center.storage import Store as CenterStore
from chaeksas.center.storage import now_iso
from chaeksas.contracts.hashing import MANIFEST_NAME, content_hash_zip
from chaeksas.contracts.server_runner import MessageDispatch
from chaeksas.contracts.signing import sign
from chaeksas.core import seen as seen_mod
from chaeksas.core.run_log import RunLog, log_path
from chaeksas.server_runner import agent as agent_mod
from chaeksas.server_runner.center_client import Unreachable
from chaeksas.server_runner.settings import Settings
from chaeksas.server_runner.store import Store

ADMIN = {"Authorization": "Bearer t-admin"}
PASS = "열쇠말"
AT = "2026-10-13T09:00:00+09:00"

#: 업무 예제 BX-11 — 견적을 메시지로 받아 쌓고 **다시 기다린다**.
EXAMPLE = Path("docs/08-business-examples/bpmn/bx11_bid_collection.bpmn")
BOT = "scm.bid-collection"
VERSION = "1.0.0"
WAIT_S = 20.0
BID = "BID-2026-001"
#: 마감은 **멀리** 둔다 — 경계 타이머가 울리면 접수가 닫혀 메시지를 받지 않는다.
INPUTS: dict[str, Any] = {
    "입찰번호": BID,
    "마감시각": "2099-01-01T18:00:00+09:00",
    "품목": ["A4 용지 500박스"],
}


def quote(supplier: str) -> dict[str, Any]:
    """견적 하나 — **칸은 예제의 시험 케이스가 정한 그대로**다 (`Task_Record`가 읽는다)."""
    return {
        "견적": {
            "공급사": supplier,
            "단가": 1002,
            "납기": "5일",
            "조건": "-",
            "회신메일": "q2@example.com",
        }
    }


@pytest.fixture(autouse=True)
def _admin_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(keystore.PASSPHRASE_ENV, PASS)
    monkeypatch.setenv(f"{keystore.ENV_PREFIX}DATA_DIR", str(tmp_path / "admin"))


@pytest.fixture
def center_store() -> Iterator[CenterStore]:
    found = CenterStore(Path(":memory:"))
    yield found
    found.close()


@pytest.fixture
def center(center_store: CenterStore, tmp_path: Path) -> Iterator[TestClient]:
    settings = CenterSettings(
        admin_token="t-admin", read_token="t-read", package_dir=tmp_path / "pkg"
    )
    with TestClient(create_app(settings, store=center_store)) as found:
        yield found


@pytest.fixture
def key(center: TestClient) -> str:
    response = center.post(
        "/api/v1/center-keys", json={"name": "서버 1", "type": "server_runner"}, headers=ADMIN
    )
    assert response.status_code == 201, response.text
    return str(response.json()["key"])


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    found = Settings(
        center_url="http://center", name="서버 1", max_concurrency=2, data_path=tmp_path / "runner"
    )
    found.data_path.mkdir(parents=True, exist_ok=True)
    found.runs_dir.mkdir(parents=True, exist_ok=True)
    return found


@pytest.fixture
def store(settings: Settings) -> Iterator[Store]:
    found = Store(path=settings.state_db)
    yield found
    found.close()


@pytest.fixture
def runner(
    settings: Settings, key: str, center: TestClient, store: Store
) -> agent_mod.Agent:
    return agent_mod.build(settings, key, client=center, store=store)


# ─────────────────────────── 거리 ───────────────────────────


def package_zip() -> bytes:
    manifest: dict[str, Any] = {
        "schema": 1,
        "kind": "bpm_process",
        "id": BOT,
        "version": VERSION,
        "name": "입찰 접수와 마감",
        "run_location": "server",
        "entry": "process/main.bpmn",
        "process_id": "Proc_bx11_bid_collection",
        "requires": {},
        "human": {"approvals": ["낙찰사 선택"]},
        "built": {"by": "studio", "at": AT, "core": "0.1.0", "spec_version": 1},
        "content_hash": "sha256:" + "0" * 64,
    }
    files = {"process/main.bpmn": EXAMPLE.read_text(encoding="utf-8")}

    def made(body: str) -> bytes:
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, text in files.items():
                archive.writestr(name, text)
            archive.writestr(MANIFEST_NAME, body)
        return out.getvalue()

    with tempfile.TemporaryDirectory() as folder:
        staged = Path(folder) / "p.zip"
        staged.write_bytes(made(json.dumps(manifest, ensure_ascii=False)))
        manifest["content_hash"] = content_hash_zip(staged)
    return made(json.dumps(manifest, ensure_ascii=False))


def ready(center: TestClient, store: CenterStore, runner: agent_mod.Agent) -> None:
    """등록 → 승인 → 배포 → 설치까지."""
    runner.tick()
    signer = keystore.create(label="첫 키")
    bootstrap_key(store, public_key=signer.public_bytes(), label="첫 키")
    private = keystore.load(signer, passphrase=PASS)

    uploaded = center.post(
        "/api/v1/packages",
        files={"file": ("p.zip", package_zip(), "application/zip")},
        headers=ADMIN,
    )
    assert uploaded.status_code in (200, 201), uploaded.text
    info = dict(uploaded.json())
    approved = center.put(
        f"/api/v1/packages/{info['id']}/{info['version']}/signature",
        json=sign(
            {
                "kind": "package",
                "id": info["id"],
                "version": info["version"],
                "content_hash": info["content_hash"],
            },
            private,
            signed_at=AT,
        ).to_json_dict(),
        headers=ADMIN,
    )
    assert approved.status_code == 200, approved.text
    deployed = center.post(
        "/api/v1/deployments",
        json=sign(
            {
                "kind": "deployment",
                "deployment_id": "dep_7a1b2c3d",
                "target": {"type": "server_runner", "id": runner.server_runner_id},
                "bpm_process_id": info["id"],
                "version": info["version"],
                "content_hash": info["content_hash"],
            },
            private,
            signed_at=now_iso(),
        ).to_json_dict(),
        headers=ADMIN,
    )
    assert deployed.status_code in (200, 201), deployed.text
    runner.tick()
    assert [b.id for b in runner.installed_bots()] == [BOT]


def make_job(center: TestClient) -> dict[str, Any]:
    response = center.post(
        "/api/v1/jobs",
        json={
            "bpm_process_id": BOT,
            "target": {"type": "server_runner"},
            "inputs": INPUTS,
        },
        headers=ADMIN,
    )
    assert response.status_code in (200, 201), response.text
    return dict(response.json())


def until_waiting_for_message(runner: agent_mod.Agent) -> str:
    """메시지를 기다릴 때까지 민다. 돌려주는 것은 그 `run_id`다.

    **멈춘 것을 Center에 알린 뒤에 돌려준다** — 기다림을 알아차린 그 주기의 하트비트는 멈추기
    **전에** 나갔으므로, 한 번 더 밀지 않으면 Center의 `waiting[]`이 비어 있다. 그러면 메시지가
    받을 곳을 못 찾고(`no_receiver`) 시험이 Windows에서만 깨진다 (CI가 잡았다).
    """
    deadline = time.monotonic() + WAIT_S
    while time.monotonic() < deadline:
        runner.tick()
        for run_id, found in runner.workers.items():
            shot = found.snapshot()
            if shot.waiting is not None and shot.waiting.waiting_for == "message":
                found.join(WAIT_S)  # 담기까지 기다린다
                runner.tick()  # 기다린다고 보고한다
                return run_id
        time.sleep(0.05)
    raise AssertionError("메시지를 기다리지 않았다")


def put_message(center: TestClient, **body: Any) -> Any:
    """메시지를 넣는다. **받아들여졌는지 여기서 본다** — 조용한 422가 숨으면 뒤에서 「왜 안
    들어갔나」가 되고, 그것이 이 시험 묶음이 Windows에서 깨진 까닭이었다."""
    response = center.post("/api/v1/messages", json={"schema": 1, **body}, headers=ADMIN)
    assert response.status_code == 201, response.text
    return response


def settle(runner: agent_mod.Agent) -> None:
    """지금 도는 스레드들이 멈출 때까지 기다린다 (담기까지)."""
    for found in list(runner.workers.values()):
        found.join(WAIT_S)


def quotes(runner: agent_mod.Agent, run_id: str) -> list[Any]:
    found = runner.workers[run_id].run
    assert found is not None
    return list(found.variables.get("견적목록") or [])


# ─────────────────────────── 한 줄 ───────────────────────────


def test_a_message_continues_the_waiting_run(
    center: TestClient, center_store: CenterStore, runner: agent_mod.Agent
) -> None:
    """메시지가 **기다리는 실행을 이어 가게 한다** (C12 §메시지 — M7의 마지막 자리).

    보는 것은 셋이다: 기다리는 줄이 Center가 고를 수 있는 모양인가, 메시지가 하트비트로
    내려와 들어가는가, 그래서 **업무가 한 걸음 나아갔는가**.
    """
    ready(center, center_store, runner)
    make_job(center)
    run_id = until_waiting_for_message(runner)

    # ① 기다리는 줄에 Center가 고를 거리가 있다 (C12 `waiting[]`).
    listed = center.get("/api/v1/server-runners", headers=ADMIN).json()
    row = listed[0]["waiting"][0]
    assert (row["waiting_for"], row["message_name"], row["correlation"]) == (
        "message",
        "bid_quote",
        BID,
    )
    # **패키지 id다** (C1 — Bot의 신원). 그림의 `process.id`가 아니다.
    assert row["bpm_process_id"] == BOT
    # 기다리는 실행은 **자리를 쥐지 않는다** (ADR-0054 §5).
    assert listed[0]["capacity"]["running"] == 0

    # ② 외부 시스템이 견적을 넣는다.
    response = put_message(
        center,
        name="bid_quote",
        correlation=BID,
        payload=quote("가나상사"),
    )
    assert response.status_code == 201, response.text
    assert response.json()["run_id"] == run_id

    # ③ 하트비트가 그것을 받아 실행에 넣는다.
    runner.tick()
    settle(runner)
    assert [one.accepted for one in runner.pending_message_acks] == [True]
    assert runner.pending_message_acks[0].run_id == run_id

    # ④ 업무가 나아갔다 — 견적이 쌓이고 **다시 기다린다** (BX-11은 돌아온다).
    assert len(quotes(runner, run_id)) == 1
    assert runner.workers[run_id].snapshot().waiting is not None

    # ⑤ 두 번째 견적도 들어간다.
    assert put_message(
        center, name="bid_quote", correlation=BID, payload=quote("다라물산")
    ).status_code == 201
    runner.tick()
    settle(runner)
    assert len(quotes(runner, run_id)) == 2


def test_the_ack_goes_up_on_the_next_heartbeat(
    center: TestClient, center_store: CenterStore, runner: agent_mod.Agent
) -> None:
    """ack가 올라가면 Center가 **다시 싣지 않는다** (C12)."""
    ready(center, center_store, runner)
    make_job(center)
    until_waiting_for_message(runner)
    put_message(center, name="bid_quote", correlation=BID, payload=quote("가나상사"))

    runner.tick()  # 받아서 넣는다
    settle(runner)
    runner.tick()  # ack를 올린다
    settle(runner)
    assert runner.pending_message_acks == []
    answer = runner.last_response
    assert answer is not None and answer.messages == []


def test_a_message_for_a_run_that_moved_on_is_refused(
    center: TestClient, center_store: CenterStore, runner: agent_mod.Agent
) -> None:
    """**받을 곳을 이쪽에서 다시 찾는다** — 그 사이 지나갔으면 `no_receiver`다 (C12).

    Center가 고른 뒤 하트비트 한 주기가 있다. 여기서는 상관 키가 다른 메시지를 실행기에
    바로 넣어 그 자리를 본다 (Center는 이런 것을 내려보내지 않는다).
    """
    ready(center, center_store, runner)
    make_job(center)
    until_waiting_for_message(runner)

    runner.apply_messages(
        [
            MessageDispatch(
                message_id="msg_deadbeef",
                name="bid_quote",
                correlation="BID-다른건",
                payload={},
                received_at=now_iso(),
            )
        ]
    )
    assert [(one.accepted, one.reason) for one in runner.pending_message_acks] == [
        (False, "no_receiver")
    ]


def test_the_same_message_is_only_put_once(
    center: TestClient, center_store: CenterStore, runner: agent_mod.Agent
) -> None:
    """ack가 올라가기 전에 **같은 메시지가 또 내려온다** (C12) — 두 번 넣지 않는다."""
    ready(center, center_store, runner)
    make_job(center)
    run_id = until_waiting_for_message(runner)
    one = MessageDispatch(
        message_id="msg_1a2b3c4d",
        name="bid_quote",
        correlation=BID,
        payload=quote("가나상사"),
        received_at=now_iso(),
    )

    runner.apply_messages([one])
    settle(runner)
    runner.apply_messages([one])  # Center가 다시 실었다
    settle(runner)

    assert len(quotes(runner, run_id)) == 1, "같은 메시지로 두 번 나아갔다"
    assert [found.message_id for found in runner.pending_message_acks] == ["msg_1a2b3c4d"]


def test_the_message_memory_does_not_grow_forever(
    center: TestClient, center_store: CenterStore, runner: agent_mod.Agent
) -> None:
    """ack가 Center에 닿고 몇 주기가 지나면 **잊는다** (ADR-0056).

    메시지는 바깥 시스템이 밀어 넣는 것이라 수가 크다 — 잊지 않으면 몇 주 떠 있는 실행기가
    끝없이 커진다. 규칙은 `core.seen`이 쥐고 셈은 `tests/test_server_runner_seen.py`가 잰다.
    """
    ready(center, center_store, runner)
    make_job(center)
    until_waiting_for_message(runner)

    runner.apply_messages(
        [
            MessageDispatch(
                message_id="msg_1a2b3c4d",
                name="bid_quote",
                correlation=BID,
                payload=quote("가나상사"),
                received_at=now_iso(),
            )
        ]
    )
    settle(runner)
    assert "msg_1a2b3c4d" in runner.seen_messages
    runner.tick()  # ack가 올라간다
    assert "msg_1a2b3c4d" in runner.seen_messages, "닿은 그 주기에는 아직 들고 있다"

    for _ in range(seen_mod.GRACE_CYCLES + 1):
        runner.tick()
    assert "msg_1a2b3c4d" not in runner.seen_messages
    assert len(runner.seen_messages) == 0


def test_an_unacked_message_is_not_put_twice_however_long_it_waits(
    center: TestClient,
    center_store: CenterStore,
    runner: agent_mod.Agent,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**올리지 못한 ack는 잊지 않는다** — 잊으면 한 메시지로 견적이 **두 번** 들어간다.

    Center는 ack가 올 때까지 매번 다시 싣는다 (C12). 그 동안 기억을 버리면 같은 메시지가
    「처음 본 것」이 되어 실행에 두 번 들어간다 — 입찰 견적이 두 번 접수되는 꼴이다.

    그물(`grace`)을 걷고 본다: 평상시에는 `pending_message_acks`가 **매 주기 다시 실려**
    나이를 0으로 되돌리므로, 「닿았다」를 보낼 때 적어도 드러나지 않는다 (ADR-0056).
    """
    ready(center, center_store, runner)
    make_job(center)
    run_id = until_waiting_for_message(runner)
    runner.seen_messages = seen_mod.Seen(grace=0)  # 그물을 걷는다 — 자리가 드러난다

    one = MessageDispatch(
        message_id="msg_1a2b3c4d",
        name="bid_quote",
        correlation=BID,
        payload=quote("가나상사"),
        received_at=now_iso(),
    )
    runner.apply_messages([one])
    settle(runner)

    def unreachable(_request: Any) -> Any:
        raise Unreachable("Center에 닿지 못한다")

    monkeypatch.setattr(runner.client, "heartbeat", unreachable)
    for _ in range(seen_mod.GRACE_CYCLES + 5):
        runner.tick()
        runner.apply_messages([one])  # ack가 안 갔으니 Center가 또 싣는다
        settle(runner)

    assert len(quotes(runner, run_id)) == 1, "한 메시지로 견적이 두 번 들어갔다"
    kept = runner.seen_messages.get("msg_1a2b3c4d")
    assert kept is not None and kept.accepted is True


def test_a_message_waits_when_there_is_no_slot(
    center: TestClient, center_store: CenterStore, runner: agent_mod.Agent
) -> None:
    """빈자리가 없으면 **ack하지 않고 둔다** — 다음 주기에 다시 온다 (C12).

    거절로 적으면 Center가 다시 싣지 않아 **멀쩡한 메시지가 버려진다**.
    """
    ready(center, center_store, runner)
    make_job(center)
    run_id = until_waiting_for_message(runner)
    runner.settings = replace(runner.settings, max_concurrency=0)  # 자리가 없다

    runner.apply_messages(
        [
            MessageDispatch(
                message_id="msg_99887766",
                name="bid_quote",
                correlation=BID,
                payload=quote("가나상사"),
                received_at=now_iso(),
            )
        ]
    )
    assert runner.pending_message_acks == [], "자리가 없는데 ack를 보냈다"
    assert quotes(runner, run_id) == []

    runner.settings = replace(runner.settings, max_concurrency=2)  # 자리가 생겼다
    runner.apply_messages(
        [
            MessageDispatch(
                message_id="msg_99887766",
                name="bid_quote",
                correlation=BID,
                payload=quote("가나상사"),
                received_at=now_iso(),
            )
        ]
    )
    settle(runner)
    assert [found.accepted for found in runner.pending_message_acks] == [True]
    assert len(quotes(runner, run_id)) == 1


def test_the_run_log_is_the_original(
    center: TestClient, center_store: CenterStore, runner: agent_mod.Agent
) -> None:
    """메시지로 이어 간 걸음도 **파일에 남는다** (C3 — `seq`가 겹치지 않는다)."""
    ready(center, center_store, runner)
    make_job(center)
    run_id = until_waiting_for_message(runner)
    put_message(center, name="bid_quote", correlation=BID, payload=quote("가나상사"))
    runner.tick()
    settle(runner)

    found = list(RunLog.read(log_path(runner.settings.data_path, run_id)))
    seqs = [event.seq for event in found]
    assert seqs == sorted(set(seqs)), "이어 간 뒤 `seq`가 겹쳤다"
    assert found[0].kind == "run_started"
    # 메시지를 받고 **지나간 노드**가 줄로 남았다 (C3 `node_state`).
    assert any(
        one.kind == "node_state"
        and one.node_id == "Task_Record"
        and one.data.get("state") == "completed"
        for one in found
    )


def test_the_message_wait_is_written_down(
    center: TestClient, center_store: CenterStore, runner: agent_mod.Agent
) -> None:
    """**메시지를 기다린 것도 기록에 남는다** (C3 `run_waiting`·`run_resumed`).

    `waiting[]`은 지금 모습이라 이어 간 뒤에는 사라진다. BX-11은 받고 **다시 기다리러**
    돌아가므로 짝이 두 번 생기는 것까지 한 그림으로 본다.
    """
    ready(center, center_store, runner)
    make_job(center)
    run_id = until_waiting_for_message(runner)
    path = log_path(runner.settings.data_path, run_id)

    put_message(center, name="bid_quote", correlation=BID, payload=quote("가나상사"))
    runner.tick()
    settle(runner)

    found = [one for one in RunLog.read(path) if one.kind.startswith("run_")]
    assert [one.kind for one in found] == [
        "run_started",
        "run_waiting",
        "run_resumed",
        "run_waiting",
    ]
    assert found[1].data["waiting_for"] == "message"
    # 메시지는 **짝이 되는 선택 칸이 없다** (C3는 `request_id`·`until` 둘만 둔다) — 이름·상관
    # 키는 업무 값에 닿으므로 `waiting[]`에만 있다 (원칙 6).
    assert set(found[1].data) == {"waiting_for"}
    assert found[2].data["reason"] == "message" and found[2].data["after_s"] >= 0.0


def test_a_restarted_runner_still_takes_the_message(
    center: TestClient,
    center_store: CenterStore,
    runner: agent_mod.Agent,
    settings: Settings,
    key: str,
    store: Store,
) -> None:
    """**재시작을 넘어서도** 메시지로 이어 간다 (ADR-0054 §2 + C12 §메시지).

    담아 둔 실행을 되살리는 길과 메시지를 넣는 길이 **맞물리는지**를 본다 — 되살린 실행이
    `waits`를 되돌려 받지 못하면 메시지가 `no_receiver`로 돌아간다.
    """
    ready(center, center_store, runner)
    make_job(center)
    run_id = until_waiting_for_message(runner)
    assert store.get(run_id) is not None, "담아 두지 않았다"

    # 실행기를 **버리고 새로 만든다** — 남는 것은 같은 저장소뿐이다.
    again = agent_mod.build(settings, key, client=center, store=store)
    again.tick()  # 등록 → 되살린다
    assert again.restored == [run_id] or run_id in again.workers

    put_message(center, name="bid_quote", correlation=BID, payload=quote("가나상사"))
    again.tick()
    for found in list(again.workers.values()):
        found.join(WAIT_S)

    assert [one.accepted for one in again.pending_message_acks] == [True]
    assert len(quotes(again, run_id)) == 1


def test_a_message_put_before_a_restart_is_not_put_again(
    center: TestClient,
    center_store: CenterStore,
    runner: agent_mod.Agent,
    settings: Settings,
    key: str,
    store: Store,
) -> None:
    """**ack가 올라가기 전에 실행기가 죽어도** 같은 메시지가 두 번 들어가지 않는다.

    가장 나쁜 짜임을 그대로 만든다 (ADR-0056 「어려워지거나 포기하는 것」이 적어 둔 자리):

    1. 메시지가 기다리는 실행에 들어간다 — ack는 `pending_message_acks`에만 있다.
    2. **그 ack가 올라가기 전에** 실행기가 죽는다 (`seen_messages`는 메모리였다).
    3. 다시 뜬 실행기가 담아 둔 실행을 되살린다. BX-11은 견적을 받고 **또 기다리는 그림**이라
       되살린 실행이 같은 이름·상관 키를 다시 기다린다.
    4. Center는 ack를 못 받았으니 **같은 메시지를 다시 싣는다** (C12).

    그때 「처음 본 것」으로 다루면 **견적이 두 번 접수된다**.
    """
    ready(center, center_store, runner)
    make_job(center)
    run_id = until_waiting_for_message(runner)
    posted = put_message(center, name="bid_quote", correlation=BID, payload=quote("가나상사"))
    message_id = str(posted.json()["message_id"])

    # ① 메시지가 들어가고 실행이 이어 가 **다시 기다린다**.
    runner.tick()
    settle(runner)
    assert len(quotes(runner, run_id)) == 1
    # ② ack는 아직 Center에 올라가지 않았다 — 올라갔으면 이 시험이 볼 것이 없다.
    assert [one.accepted for one in runner.pending_message_acks] == [True]

    # ③ 실행기가 죽는다. 남는 것은 같은 저장소뿐 — `seen_messages`는 메모리였다.
    again = agent_mod.build(settings, key, client=center, store=store)
    again.tick()  # 등록 → 되살린다
    assert run_id in again.workers, "되살리지 않았다"
    for found in list(again.workers.values()):
        found.join(WAIT_S)
    # 되살린 기억이 **받아들였다**를 들고 있다 (ADR-0058) — 거절로 적으면 Center가 접수를
    # 놓친 줄 알고, 비어 있으면 아래에서 견적이 두 번 들어간다.
    assert [(one.message_id, one.accepted, one.run_id) for one in again.pending_message_acks] == [
        (message_id, True, run_id)
    ]

    # ④ Center가 같은 메시지를 **다시 싣는 가장 나쁜 짜임**을 그대로 건넨다 (ack가 안 갔다).
    again.apply_messages(
        [
            MessageDispatch(
                message_id=message_id,
                name="bid_quote",
                correlation=BID,
                payload=quote("가나상사"),
                received_at=now_iso(),
            )
        ]
    )
    for found in list(again.workers.values()):
        found.join(WAIT_S)
    assert len(quotes(again, run_id)) == 1, "재시작을 건너 같은 메시지로 견적이 두 번 들어갔다"

    # ⑤ 그래서 첫 하트비트가 ack를 올리고 Center는 그 메시지를 **더 싣지 않는다**.
    again.tick()
    for found in list(again.workers.values()):
        found.join(WAIT_S)
    answer = again.last_response
    assert answer is not None and answer.messages == []
    assert len(quotes(again, run_id)) == 1


def test_a_message_absorbed_but_not_saved_is_not_lost(
    center: TestClient,
    center_store: CenterStore,
    runner: agent_mod.Agent,
    settings: Settings,
    key: str,
    store: Store,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**담기 전에** 죽으면 그 메시지를 **다시 받는다** — 잊어서가 아니라 상태도 그 전이라서다.

    ADR-0058이 기억을 스냅샷과 **한 트랜잭션**에 둔 까닭이 이 자리다. 기억만 따로 적었다면
    여기서 「이미 받았다」와 「상태는 그 전」이 갈라져 **견적이 영영 사라진다** (두 번 들어가는
    것보다 나쁘다 — 아무 자리에도 남지 않는다).

    메시지를 넣은 뒤 담지 못하고 죽는 틈을 `save_waiting`을 비워 만든다.
    """
    ready(center, center_store, runner)
    make_job(center)
    run_id = until_waiting_for_message(runner)
    saved_before = store.get(run_id)
    assert saved_before is not None and saved_before.snapshot is not None

    # 넣은 뒤 **담지 못하고 죽는다** — 스냅샷은 메시지 전 그대로다.
    monkeypatch.setattr(store, "save_waiting", lambda *a, **k: 0)
    put_message(center, name="bid_quote", correlation=BID, payload=quote("가나상사"))
    runner.tick()
    settle(runner)
    assert len(quotes(runner, run_id)) == 1  # 메모리에서는 나아갔다
    assert store.absorbed() == {}, "담기지 않았는데 기억만 남았다"

    monkeypatch.undo()
    again = agent_mod.build(settings, key, client=center, store=store)
    again.tick()  # 등록 → **메시지 전 상태**를 되살린다
    for found in list(again.workers.values()):
        found.join(WAIT_S)
    assert quotes(again, run_id) == [], "되살린 것이 메시지 전 상태가 아니다"

    again.tick()  # Center가 다시 싣는다 — ack를 못 받았다
    for found in list(again.workers.values()):
        found.join(WAIT_S)
    assert len(quotes(again, run_id)) == 1, "견적을 잃었다"


def test_the_absorbed_memory_goes_and_comes_with_the_run(store: Store) -> None:
    """빨아들인 메시지의 기억은 **그 실행과 함께** 담기고 함께 지워진다 (ADR-0058).

    실행이 끝나면 되살릴 상태가 없으니 그 기억에 쓸 데도 없다 — 그래서 이 표는 **기다리는
    실행**만큼만 자라고 ADR-0056처럼 잊는 규칙을 따로 둘 것이 없다.
    """
    store.mark_running("run_1", bpm_process_id=BOT, version=VERSION, job_id=None, started_at=AT)
    assert store.absorbed() == {}

    store.save_waiting("run_1", {"run_id": "run_1"}, absorbed=["msg_aaaa1111"])
    assert store.absorbed() == {"msg_aaaa1111": "run_1"}
    # 같은 것을 또 담아도 한 줄이다 (담을 때마다 그 실행이 받은 것을 전부 넘긴다).
    store.save_waiting("run_1", {"run_id": "run_1"}, absorbed=["msg_aaaa1111", "msg_bbbb2222"])
    assert store.absorbed() == {"msg_aaaa1111": "run_1", "msg_bbbb2222": "run_1"}

    store.forget("run_1")
    assert store.absorbed() == {}, "실행은 끝났는데 기억만 남았다"
