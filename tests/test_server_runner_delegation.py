"""서버 Bot이 **PC Bot에 한 자리를 맡기고 결과를 받아 이어 간다** (C12 §PC 위임, ADR-0062).

한 줄로 본다: 작업 지시 → 서버 실행기가 돌림 → `chk:call.delegate`에서 **Center에 맡기고
자리를 놓음** → Center가 PC를 골라 작업으로 만듦 → PC가 작업 ack에 값을 실어 올림 →
하트비트 응답 `delegations[]` → 서버 실행이 **이어 가서 끝남** → `delegation_acks[]`.

**그림은 손으로 만든다** — 업무 예제 50개에는 위임이 없다(ADR-0062가 어제 정했다). 보려는
것은 예제의 업무가 아니라 **두 패키지·두 실행이 Center를 거쳐 맞물리는가**다.

| 보는 것 | 왜 |
| --- | --- |
| 기다리는 줄이 `delegation` + `job_id` | Center가 그 작업으로 결과를 돌려준다 (C12 짝 칸) |
| 맡기는 동안 **자리를 놓는다** | 상한 1에 위임을 들고도 새 작업을 받는다 (ADR-0062 「증명할 다섯」 1) |
| 재시작을 건너 **작업이 하나** | 작업 id가 스냅샷과 함께 간다 — 다시 맡기지 않는다 (같은 2) |
| 선언한 `outputs`가 **변수가 된다** | `chk:call.output`이 적은 것만 (같은 3) |
| 실패·거절은 **업무 실패** | 조용히 멈추지 않는다 (같은 4) |
| ack가 올라가면 Center가 **값을 지운다** | 원칙 6의 예외는 좁게 쓴다 |
| 같은 결과가 두 번 와도 **한 번만** | ack가 올라가기 전에 또 내려온다 (C12) |
| 맡길 곳이 없으면 **업무 실패** | 배포되지 않은 PC를 기다리는 것은 업무가 아니다 |
"""

from __future__ import annotations

import io
import json
import tempfile
import time
import zipfile
from collections.abc import Iterator
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
from chaeksas.contracts.server_runner import DelegationResult
from chaeksas.contracts.signing import sign
from chaeksas.core.run_log import RunLog, log_path
from chaeksas.server_runner import agent as agent_mod
from chaeksas.server_runner.center_client import Unreachable
from chaeksas.server_runner.settings import Settings
from chaeksas.server_runner.store import Store

ADMIN = {"Authorization": "Bearer t-admin"}
PASS = "열쇠말"
AT = "2026-10-13T09:00:00+09:00"
VERSION = "1.0.0"
WAIT_S = 20.0

#: 맡기는 서버 Bot과 맡겨지는 PC Bot — **따로 올리고 따로 배포한다** (ADR-0062의 값이다).
SERVER_BOT = "fin.invoice"
PC_BOT = "fin.erp-input"
CLAIM = "CLM-2026-001"

#: 서버 그림 — 위임 하나를 거쳐 그 값을 쓴다. `calledElement`는 **읽는 사람을 위한 것**이다.
SERVER_BPMN = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:chk="urn:chaeksas:bpmn:1" id="Defs_invoice">
  <bpmn:process id="Proc_fin_invoice" isExecutable="true">
    <bpmn:extensionElements><chk:process>{"run_location": "server",
      "inputs": [{"name": "청구번호", "type": "string", "required": true}]}</chk:process>
    </bpmn:extensionElements>
    <bpmn:startEvent id="Start_1" />
    <bpmn:callActivity id="Call_Erp" name="ERP 화면 입력" calledElement="Proc_erp_input">
      <bpmn:extensionElements><chk:call>{
        "delegate": {"bpm_process_id": "fin.erp-input", "version": "1.0.0"},
        "input": {"전표번호": "청구번호"},
        "output": {"입력결과": "결과코드"}}</chk:call>
      </bpmn:extensionElements>
    </bpmn:callActivity>
    <bpmn:scriptTask id="Task_After" scriptFormat="chk-expr">
      <bpmn:script>마무리 = 입력결과 + "-확인"</bpmn:script>
    </bpmn:scriptTask>
    <bpmn:endEvent id="End_1" />
    <bpmn:sequenceFlow id="f1" sourceRef="Start_1" targetRef="Call_Erp" />
    <bpmn:sequenceFlow id="f2" sourceRef="Call_Erp" targetRef="Task_After" />
    <bpmn:sequenceFlow id="f3" sourceRef="Task_After" targetRef="End_1" />
  </bpmn:process>
</bpmn:definitions>
"""

#: PC 그림 — 대개 **가짜 하트비트가 PC를 흉내 낸다**(C4는 따로 시험한다). 마지막 시험
#: 하나는 이것을 **진짜 자식 프로세스로 돌려** 현장이 만든 값이 서버 변수에 담기는지 본다.
#: 그래서 선언한 `outputs`를 **정말 채운다**.
PC_BPMN = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:chk="urn:chaeksas:bpmn:1" id="Defs_erp">
  <bpmn:process id="Proc_erp_input" isExecutable="true">
    <bpmn:extensionElements><chk:process>{"run_location": "pc",
      "inputs": [{"name": "전표번호", "type": "string", "required": true}],
      "outputs": ["결과코드"]}</chk:process>
    </bpmn:extensionElements>
    <bpmn:startEvent id="Start_1" />
    <bpmn:scriptTask id="Task_Erp" scriptFormat="chk-expr">
      <bpmn:script>결과코드 = "OK-" + 전표번호</bpmn:script>
    </bpmn:scriptTask>
    <bpmn:scriptTask id="Task_Note" scriptFormat="chk-expr">
      <bpmn:script>현장메모 = "올라가지 않는다"</bpmn:script>
    </bpmn:scriptTask>
    <bpmn:endEvent id="End_1" />
    <bpmn:sequenceFlow id="f1" sourceRef="Start_1" targetRef="Task_Erp" />
    <bpmn:sequenceFlow id="f2" sourceRef="Task_Erp" targetRef="Task_Note" />
    <bpmn:sequenceFlow id="f3" sourceRef="Task_Note" targetRef="End_1" />
  </bpmn:process>
</bpmn:definitions>
"""


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
def private(center_store: CenterStore) -> Any:
    """Admin 서명 키 — **서명이 유일한 관문이다** (C2)."""
    signer = keystore.create(label="첫 키")
    bootstrap_key(center_store, public_key=signer.public_bytes(), label="첫 키")
    return keystore.load(signer, passphrase=PASS)


def new_key(center: TestClient, *, name: str, kind: str) -> str:
    made = center.post("/api/v1/center-keys", json={"name": name, "type": kind}, headers=ADMIN)
    assert made.status_code == 201, made.text
    return str(made.json()["key"])


@pytest.fixture
def key(center: TestClient) -> str:
    return new_key(center, name="서버 1", kind="server_runner")


def settings_at(folder: Path, *, max_concurrency: int = 2) -> Settings:
    found = Settings(
        center_url="http://center",
        name="서버 1",
        max_concurrency=max_concurrency,
        data_path=folder,
    )
    found.data_path.mkdir(parents=True, exist_ok=True)
    found.runs_dir.mkdir(parents=True, exist_ok=True)
    return found


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return settings_at(tmp_path / "runner")


@pytest.fixture
def store(settings: Settings) -> Iterator[Store]:
    found = Store(path=settings.state_db)
    yield found
    found.close()


@pytest.fixture
def runner(settings: Settings, key: str, center: TestClient, store: Store) -> agent_mod.Agent:
    return agent_mod.build(settings, key, client=center, store=store)


# ─────────────────────────── 거리 (test_center_delegations에서 베껴 온 모양) ───────────────────────────


def package_zip(
    *, bot: str, where: str, xml: str, process_id: str, delegations: list[str] | None = None,
    inputs: list[dict[str, Any]] | None = None, outputs: list[str] | None = None,
) -> bytes:
    manifest: dict[str, Any] = {
        "schema": 1,
        "kind": "bpm_process",
        "id": bot,
        "version": VERSION,
        "name": bot,
        "run_location": where,
        "entry": "process/main.bpmn",
        "process_id": process_id,
        # **Studio가 그림에서 모으는 자리다** (C1 `requires.delegations`) — 배포 때 Center가
        # 「그 PC Bot이 승인되어 있나」를 본다 (422 `delegation_not_approved`).
        "requires": {"delegations": delegations or []},
        "inputs": inputs or [],
        "outputs": outputs or [],
        "human": {},
        "built": {"by": "studio", "at": AT, "core": "0.1.0", "spec_version": 1},
        "content_hash": "sha256:" + "0" * 64,
    }

    def made(body: str) -> bytes:
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("process/main.bpmn", xml)
            archive.writestr(MANIFEST_NAME, body)
        return out.getvalue()

    with tempfile.TemporaryDirectory() as folder:
        staged = Path(folder) / "p.zip"
        staged.write_bytes(made(json.dumps(manifest, ensure_ascii=False)))
        manifest["content_hash"] = content_hash_zip(staged)
    return made(json.dumps(manifest, ensure_ascii=False))


def upload(center: TestClient, private: Any, body: bytes) -> dict[str, Any]:
    """올리고 **승인까지** (C2 — 승인되지 않은 패키지는 배포할 수 없다)."""
    made = center.post(
        "/api/v1/packages",
        files={"file": ("p.zip", body, "application/zip")},
        headers=ADMIN,
    )
    assert made.status_code in (200, 201), made.text
    info = dict(made.json())
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
    return info


def deploy(
    center: TestClient, private: Any, info: dict[str, Any], *, target: dict[str, str], dep: str
) -> None:
    made = center.post(
        "/api/v1/deployments",
        json=sign(
            {
                "kind": "deployment",
                "deployment_id": dep,
                "target": target,
                "bpm_process_id": info["id"],
                "version": info["version"],
                "content_hash": info["content_hash"],
            },
            private,
            signed_at=now_iso(),
        ).to_json_dict(),
        headers=ADMIN,
    )
    assert made.status_code in (200, 201), made.text


#: 등록한 PC의 키 (ack를 올릴 때 쓴다 — **신원은 키다**, C4).
PC_KEYS: dict[str, str] = {}


def register_pc(center: TestClient, *, name: str, machine: str) -> str:
    """등록된 활성 Bot UI 하나 — 돌려주는 것은 `bot_ui_id`다 (C4).

    **등록돼 있어야 위임이 간다** (ADR-0049 — 배포 대상은 등록된 PC여야 한다).
    """
    key = new_key(center, name=name, kind="bot_ui")
    made = center.post(
        "/api/v1/bot-ui/register",
        json={
            "schema": 1,
            "machine_id": machine,
            "name": name,
            "os": "windows-11-23H2",
            "versions": {"bot_ui": "0.1.0", "core": "0.1.0"},
        },
        headers={"Authorization": f"Bearer {key}"},
    )
    assert made.status_code < 400, made.text
    bot_ui_id = str(made.json()["bot_ui_id"])
    PC_KEYS[bot_ui_id] = key
    return bot_ui_id


def pc_beat(center: TestClient, bot_ui_id: str, **over: Any) -> dict[str, Any]:
    """PC 하트비트 (C4) — 이 시험에서 PC는 **이것뿐**이다 (진짜 Bot UI는 M5가 본다)."""
    made = center.post(
        "/api/v1/bot-ui/heartbeat",
        json={
            "schema": 1,
            "status": "idle",
            "current_run": None,
            "queue": {"max": 5, "items": []},
            "worker": {"state": "off"},
            **over,
        },
        headers={"Authorization": f"Bearer {PC_KEYS[bot_ui_id]}"},
    )
    assert made.status_code == 200, made.text
    return dict(made.json())


def ready(
    center: TestClient,
    private: Any,
    runner: agent_mod.Agent,
    *,
    with_pc: bool = True,
) -> str:
    """등록 → 두 패키지 승인 → PC·서버에 배포 → 서버 실행기 설치까지. `bot_ui_id`를 준다.

    `with_pc=False`면 **PC 쪽이 없다** — 맡길 곳이 없을 때를 본다.
    """
    runner.tick()
    pc_info = upload(
        center,
        private,
        package_zip(
            bot=PC_BOT,
            where="pc",
            xml=PC_BPMN,
            process_id="Proc_erp_input",
            inputs=[{"name": "전표번호", "type": "string", "required": True}],
            outputs=["결과코드"],
        ),
    )
    bot_ui_id = ""
    if with_pc:
        bot_ui_id = register_pc(center, name="현장 1", machine="7" * 64)
        deploy(center, private, pc_info, target={"type": "bot_ui", "id": bot_ui_id}, dep="dep_pc_1")

    server_info = upload(
        center,
        private,
        package_zip(
            bot=SERVER_BOT,
            where="server",
            xml=SERVER_BPMN,
            process_id="Proc_fin_invoice",
            delegations=[f"{PC_BOT}@{VERSION}"],
            inputs=[{"name": "청구번호", "type": "string", "required": True}],
        ),
    )
    deploy(
        center,
        private,
        server_info,
        target={"type": "server_runner", "id": runner.server_runner_id},
        dep="dep_srv_1",
    )
    runner.tick()
    assert [one.id for one in runner.installed_bots()] == [SERVER_BOT]
    return bot_ui_id


def make_job(center: TestClient, *, bot: str = SERVER_BOT, claim: str = CLAIM) -> str:
    made = center.post(
        "/api/v1/jobs",
        json={
            "bpm_process_id": bot,
            "target": {"type": "server_runner"},
            "inputs": {"청구번호": claim},
        },
        headers=ADMIN,
    )
    assert made.status_code in (200, 201), made.text
    return str(made.json()["job_id"])


def until_waiting_for_delegation(runner: agent_mod.Agent, *, skip: tuple[str, ...] = ()) -> str:
    """위임을 기다릴 때까지 민다. 돌려주는 것은 그 `run_id`다 (`skip`은 빼고 본다).

    **멈춘 것을 Center에 알린 뒤에 돌려준다** — 기다림을 알아차린 그 주기의 하트비트는 멈추기
    **전에** 나갔으므로, 한 번 더 밀지 않으면 Center의 `waiting[]`이 비어 있다 (메시지 묶음이
    Windows에서 겪은 자리다).
    """
    deadline = time.monotonic() + WAIT_S
    while time.monotonic() < deadline:
        runner.tick()
        for run_id, found in list(runner.workers.items()):
            if run_id in skip:
                continue
            shot = found.snapshot()
            if shot.waiting is not None and shot.waiting.waiting_for == "delegation":
                found.join(WAIT_S)  # 담기까지 기다린다
                runner.tick()  # 기다린다고 보고한다
                return run_id
        time.sleep(0.05)
    raise AssertionError("위임을 기다리지 않았다")


def until_done(runner: agent_mod.Agent, run_id: str) -> str:
    """그 실행이 끝날 때까지 민다. 돌려주는 것은 C3 `run_finished.status`다."""
    deadline = time.monotonic() + WAIT_S
    while time.monotonic() < deadline:
        found = runner.workers.get(run_id)
        if found is None:
            break  # 이미 거뒀다 — 기록에서 읽는다
        shot = found.snapshot()
        if shot.done:
            return str(shot.finished)
        found.join(1.0)
        runner.tick()
    for one in reversed(lines(runner.settings, run_id, "run_finished")):
        return str(one.get("status"))
    raise AssertionError("실행이 끝나지 않았다")


def lines(settings: Settings, run_id: str, kind: str) -> list[dict[str, Any]]:
    """그 실행 기록에서 한 종류만 — **파일이 원본이다** (C3)."""
    path = log_path(settings.data_path, run_id)
    return [dict(one.data) for one in RunLog.read(path) if one.kind == kind]


def pc_finishes(
    center: TestClient,
    bot_ui_id: str,
    job_id: str,
    *,
    outputs: dict[str, Any] | None = None,
    result: str = "finished",
    reason: str | None = None,
    pc_run_id: str = "run_20261015_100000_bbbbbb",
) -> None:
    """PC가 그 작업을 받아 끝냈다고 올린다 (C4 — `JobAck.outputs`에 **선언한 것만**)."""
    ack: dict[str, Any] = {"job_id": job_id, "result": "started", "run_id": pc_run_id}
    pc_beat(center, bot_ui_id, job_acks=[ack])
    done: dict[str, Any] = {"job_id": job_id, "result": result, "run_id": pc_run_id}
    if outputs is not None:
        done["outputs"] = outputs
    if reason is not None:
        done["reason"] = reason
    pc_beat(center, bot_ui_id, job_acks=[done])


def waiting_row(center: TestClient) -> dict[str, Any]:
    listed = center.get("/api/v1/server-runners", headers=ADMIN).json()
    (row,) = listed[0]["waiting"]
    return dict(row)


# ─────────────────────────── 한 줄 ───────────────────────────


def test_a_delegation_runs_on_the_pc_and_the_server_run_continues(
    center: TestClient, private: Any, runner: agent_mod.Agent
) -> None:
    """**맡기고 기다리고 받아 이어 간다** (ADR-0062 — 「증명할 다섯」의 1·3).

    보는 것은 넷이다: 기다리는 줄이 Center가 결과를 돌려줄 수 있는 모양인가, 맡기는 동안
    **자리를 놓는가**, PC가 올린 값이 `chk:call.output`이 적은 변수가 되는가, 그래서 업무가
    **끝까지 갔는가**.
    """
    bot_ui_id = ready(center, private, runner)
    make_job(center)
    run_id = until_waiting_for_delegation(runner)

    # ① 기다리는 줄의 짝 칸이 **그 작업**이다 (C12 — 비우면 Center가 422로 거부한다).
    row = waiting_row(center)
    assert row["waiting_for"] == "delegation" and row["job_id"]
    assert (row["run_id"], row["bpm_process_id"]) == (run_id, SERVER_BOT)
    job_id = str(row["job_id"])

    # ② **자리를 놓았다** — 상한에 세지 않는다 (C12, PC와 거꾸로다).
    assert runner.free_slots() == runner.settings.max_concurrency

    # ③ Center가 **PC를 골라 작업으로** 만들었다 (그림에 PC id를 적지 않았다).
    job = center.get(f"/api/v1/jobs/{job_id}", headers=ADMIN).json()
    assert (job["bpm_process_id"], job["target"]["id"]) == (PC_BOT, bot_ui_id)
    # **`requested_by`는 Center가 적는다** — 본문으로 받지 않으므로 지어낼 수 없다 (C5).
    assert job["requested_by"] == f"server_bot:{run_id}"

    # ④ PC가 값을 실어 올리면 하트비트로 내려와 실행이 이어 간다.
    pc_finishes(center, bot_ui_id, job_id, outputs={"결과코드": "OK"})
    assert until_done(runner, run_id) == "success"

    found = lines(runner.settings, run_id, "run_resumed")
    assert [one["reason"] for one in found] == ["delegation"]
    # **기다린 줄에도 그 작업이 남는다** (C3 선택 칸 `job_id`) — 하트비트의 `waiting[]`은
    # 기다림이 끝나면 사라지므로, 이 줄이 없으면 CON-01이 무엇을 기다렸는지 모른다.
    (waited,) = lines(runner.settings, run_id, "run_waiting")
    assert (waited["waiting_for"], waited["job_id"]) == ("delegation", job_id)
    # **값은 기록에 없다** (원칙 6) — 변수에만 있다.
    assert not any("OK" in str(one) for one in lines(runner.settings, run_id, "log"))


def test_the_outputs_become_the_variables_the_graph_asked_for(
    center: TestClient, private: Any, runner: agent_mod.Agent
) -> None:
    """**적은 것만 오간다** (C14 `chk:call.output`) — 그 뒤 걸음이 그 값을 쓴다.

    실행이 끝난 뒤에는 일꾼을 거두므로(`collect`) 변수를 보려면 **끝나기 전에** 본다.
    """
    bot_ui_id = ready(center, private, runner)
    make_job(center)
    run_id = until_waiting_for_delegation(runner)
    job_id = str(waiting_row(center)["job_id"])

    pc_finishes(center, bot_ui_id, job_id, outputs={"결과코드": "OK", "덤": "버린다"})
    worker = runner.workers[run_id]
    runner.tick()  # 결과를 넣는다
    worker.join(WAIT_S)

    run = worker.run
    assert run is not None
    assert run.variables["입력결과"] == "OK", "`output`이 적은 변수에 담긴다"
    assert "덤" not in run.variables and "결과코드" not in run.variables
    assert run.variables["마무리"] == "OK-확인", "위임 뒤의 걸음이 그 값을 쓴다"


def test_the_ack_makes_center_forget_the_business_value(
    center: TestClient, private: Any, runner: agent_mod.Agent
) -> None:
    """**ack가 올라가면 값이 지워진다** (원칙 6의 예외는 좁게 쓴다, C12).

    ack가 올라가기 **전에는** 매번 다시 내려온다 — 그래서 받은 뒤 한 주기는 들고 있다.
    """
    bot_ui_id = ready(center, private, runner)
    make_job(center)
    run_id = until_waiting_for_delegation(runner)
    job_id = str(waiting_row(center)["job_id"])
    pc_finishes(center, bot_ui_id, job_id, outputs={"결과코드": "OK"})

    runner.tick()  # 내려받아 넣는다 — ack는 아직 올라가지 않았다
    assert [one.job_id for one in runner.pending_delegation_acks] == [job_id]
    runner.workers[run_id].join(WAIT_S)

    runner.tick()  # ack가 올라간다
    assert runner.pending_delegation_acks == []
    # Center가 값을 지웠다 — 다시 내려 주지 않는다 (누가·언제·성패는 남는다).
    row = center.get("/api/v1/server-runners", headers=ADMIN).json()[0]
    assert row["waiting"] == []
    job = center.get(f"/api/v1/jobs/{job_id}", headers=ADMIN).json()
    assert job["run_status"] == "finished"


def test_the_same_result_is_only_put_in_once(
    center: TestClient, private: Any, runner: agent_mod.Agent
) -> None:
    """ack가 올라가기 전에 **같은 결과가 또 내려온다** (C12) — 두 번 넣지 않는다.

    두 번 넣으면 엔진이 「기다리는 위임이 아니다」로 터지고, 더 나쁘게는 지나간 자리에 값을
    덮는다. 기억은 작업·메시지와 **같은 자리**(`core.seen`)를 쓴다 (ADR-0057).
    """
    bot_ui_id = ready(center, private, runner)
    make_job(center)
    run_id = until_waiting_for_delegation(runner)
    job_id = str(waiting_row(center)["job_id"])
    pc_finishes(center, bot_ui_id, job_id, outputs={"결과코드": "OK"})

    runner.tick()  # 내려받아 넣는다
    runner.workers[run_id].join(WAIT_S)
    assert len(lines(runner.settings, run_id, "run_resumed")) == 1

    # ack가 Center에 닿지 못한 주기를 흉내 낸다 — **같은 결과가 또 내려온다** (C12).
    again = DelegationResult(
        job_id=job_id, run_id=run_id, state="finished", outputs={"결과코드": "OK"}
    )
    runner.apply_delegations([again])
    assert len(lines(runner.settings, run_id, "run_resumed")) == 1, "두 번 이어 가지 않는다"
    # ack는 **그대로 하나**다 (같은 작업을 두 줄로 올리지 않는다).
    assert [one.job_id for one in runner.pending_delegation_acks] == [job_id]


def test_a_rejected_delegation_is_a_task_failure(
    center: TestClient, private: Any, runner: agent_mod.Agent
) -> None:
    """PC 쪽이 실패·거절·만료되면 **업무 실패**다 (ADR-0062 「증명할 다섯」의 4).

    오류 경계가 없는 그림이라 실행이 실패로 닫힌다 — **조용히 멈추지 않는 것**이 요점이다.
    """
    bot_ui_id = ready(center, private, runner)
    make_job(center)
    run_id = until_waiting_for_delegation(runner)
    job_id = str(waiting_row(center)["job_id"])

    pc_finishes(center, bot_ui_id, job_id, result="failed", reason="not_ready")
    assert until_done(runner, run_id) == "failed"
    (one,) = lines(runner.settings, run_id, "run_finished")
    assert one["error_code"] == "DELEGATION_FAILED"
    # **이어 간 것은 이어 간 것이다** — 오류 경계로 가는 길도 기다림을 끝냈다.
    assert [found["reason"] for found in lines(runner.settings, run_id, "run_resumed")] == [
        "delegation"
    ]


def test_a_delegation_with_nowhere_to_go_fails_the_run(
    center: TestClient, private: Any, runner: agent_mod.Agent
) -> None:
    """맡길 PC가 없으면 **업무 실패**다 (ADR-0062 §3 — 기다리지 않는다).

    배포되지 않은 PC를 기다리는 것은 업무가 아니라 설정 잘못이고, 오류 경계가 받아야 사람이
    안다. 사유 코드는 Center가 준 것(`no_deployment`)이 그대로 온다.
    """
    ready(center, private, runner, with_pc=False)
    make_job(center)

    deadline = time.monotonic() + WAIT_S
    while time.monotonic() < deadline and not runner.workers:
        runner.tick()
        time.sleep(0.05)
    (run_id,) = list(runner.workers)
    assert until_done(runner, run_id) == "failed"
    (one,) = lines(runner.settings, run_id, "run_finished")
    assert one["error_code"] == "no_deployment"
    assert lines(runner.settings, run_id, "run_waiting") == [], "맡기지 못했으면 기다림도 없다"


def test_waiting_for_a_delegation_leaves_the_slot_for_another_job(
    center: TestClient, private: Any, key: str, store: Store, tmp_path: Path
) -> None:
    """**상한 1에 위임 하나를 들고도 새 작업을 받는다** (ADR-0062 「증명할 다섯」의 1).

    PC와 거꾸로다 — PC Bot은 결재를 기다려도 자리를 끝까지 쥐지만(ADR-0014) 서버는 놓는다.
    """
    settings = settings_at(tmp_path / "runner1", max_concurrency=1)
    runner = agent_mod.build(settings, key, client=center, store=store)
    ready(center, private, runner)
    make_job(center)
    first = until_waiting_for_delegation(runner)
    assert runner.free_slots() == 1, "기다리는 실행은 자리를 쥐지 않는다"

    # 상한이 1인데도 둘째 작업이 내려와 **돈다** — Center도 그 자리를 빈 것으로 센다.
    make_job(center, claim="CLM-2026-002")
    second = until_waiting_for_delegation(runner, skip=(first,))
    assert len(runner.workers) == 2

    # **실행이 둘이면 PC 작업도 둘**이다 (멱등 키에 `run_id`가 들어 있어 같은 자리라도 다르다).
    rows = center.get("/api/v1/jobs", headers=ADMIN).json()
    made = sorted(one["job_id"] for one in rows if one["bpm_process_id"] == PC_BOT)
    assert len(made) == 2 and second != first


def test_a_restart_does_not_delegate_the_same_spot_twice(
    center: TestClient, private: Any, key: str, store: Store, tmp_path: Path
) -> None:
    """**재시작을 건너 작업이 하나다** (ADR-0062 「증명할 다섯」의 2).

    작업 id가 **스냅샷과 함께** 가므로(네 번째 기다림의 짝 칸이다) 되살린 실행은 어느 작업을
    기다리는지 알고 **다시 맡기지 않는다**. 멱등 키가 같아 다시 맡겨도 같은 작업이 돌아오지만,
    아예 맡기지 않는 것이 더 싸고 기록도 깨끗하다.
    """
    settings = settings_at(tmp_path / "runner2")
    first = agent_mod.build(settings, key, client=center, store=store)
    bot_ui_id = ready(center, private, first)
    make_job(center)
    run_id = until_waiting_for_delegation(first)
    job_id = str(waiting_row(center)["job_id"])
    del first

    second = agent_mod.build(settings, key, client=center, store=store)
    second.tick()
    assert second.restored == [run_id], "담아 둔 실행을 되살렸다"
    second.workers[run_id].join(WAIT_S)
    second.tick()
    # **같은 작업을 기다린다** — 새로 맡기지 않았다.
    assert second.workers[run_id].waits_for_delegation(job_id)
    jobs = center.get("/api/v1/jobs", headers=ADMIN).json()
    assert [one["job_id"] for one in jobs if one["bpm_process_id"] == PC_BOT] == [job_id]

    # 되살린 실행도 그 결과로 이어 간다.
    pc_finishes(center, bot_ui_id, job_id, outputs={"결과코드": "OK"})
    assert until_done(second, run_id) == "success"
    found = [one["reason"] for one in lines(settings, run_id, "run_resumed")]
    assert found == ["restart", "delegation"], "되살린 것과 이어 간 것이 함께 남는다"


# ─────────────────────────── 현장이 만든 값이 서버 변수에 담긴다 (ADR-0062 §4) ───────────────────────────


def test_the_field_outputs_reach_the_server_variables(
    center: TestClient, private: Any, runner: agent_mod.Agent, tmp_path: Path
) -> None:
    """**PC가 진짜로 돌려 만든 값**이 서버 실행의 변수가 된다 (증명할 다섯의 3).

    위의 시험들은 PC를 가짜 하트비트로 흉내 내지만, 값을 만드는 **현장 쪽 길**(실행기가
    선언한 `outputs`를 출력 파일에 쓰고 Bot UI가 거두며 지운다)은 그렇게는 보이지 않는다.
    그래서 여기서는 그 Bot을 **진짜 자식 프로세스로** 돌리고, 그 결과를 작업 ack로 올린다.

    흉내 내는 것은 **C4 하트비트 한 번**뿐이다 (그 전송은 C4 시험이 본다).
    """
    from waiting import wait_for

    from chaeksas.bot_ui.runner import Launcher
    from chaeksas.core.packages import install

    bot_ui_id = ready(center, private, runner)
    make_job(center)
    run_id = until_waiting_for_delegation(runner)
    job_id = str(waiting_row(center)["job_id"])

    # ① 그 PC에 Bot을 깔고 **위임으로 받은 작업처럼** 돌린다.
    pc_zip = tmp_path / "pc.zip"
    pc_zip.write_bytes(
        package_zip(
            bot=PC_BOT,
            where="pc",
            xml=PC_BPMN,
            process_id="Proc_erp_input",
            inputs=[{"name": "전표번호", "type": "string", "required": True}],
            outputs=["결과코드"],
        )
    )
    pc_dir = tmp_path / "botui"
    bot = install(pc_dir, pc_zip)
    launcher = Launcher(data_dir=pc_dir)
    running = launcher.start(
        bot,
        inputs={"전표번호": CLAIM},
        source="delegation",
        job_id=job_id,
        parent_run_id=run_id,
    )
    assert wait_for(lambda: not running.alive), "PC 실행기가 끝나지 않았다"
    assert wait_for(lambda: launcher.tick() is not None), "거두지 못했다"
    assert running.finished == "success", running.failure
    # **선언한 것만** 올라간다 (C1) — 현장 메모는 PC에 남는다.
    assert running.outputs == {"결과코드": f"OK-{CLAIM}"}

    # ② 그 값을 작업 ack로 올린다 (C4 — 여기만 흉내다).
    pc_finishes(center, bot_ui_id, job_id, outputs=running.outputs, pc_run_id=running.run_id)

    # ③ 서버 실행이 그 값을 받아 이어 간다 — `chk:call.output`이 적은 변수에 담긴다.
    worker = runner.workers[run_id]
    runner.tick()
    worker.join(WAIT_S)
    run = worker.run
    assert run is not None
    assert run.variables["입력결과"] == f"OK-{CLAIM}"
    assert run.variables["마무리"] == f"OK-{CLAIM}-확인", "위임 뒤의 걸음이 그 값을 쓴다"


# ─────────────────────────── 서버 실행이 취소되면 맡긴 것도 거둔다 (ADR-0062 §5) ───────────────────────────

#: **취소는 Center에서 온다** ([ADR-0063](../docs/decisions/0063-stopping-a-running-server-run.md)) —
#: 서버 대상 작업은 `accepted`에도 취소를 받아 `cancel_jobs`로 내려온다 (PC는 그대로 거절이다).
#: 그래서 아래 셋은 **운영자가 하는 그대로** `DELETE /jobs/{id}`로 민다.


def test_cancelling_the_server_run_revokes_the_pc_job(
    center: TestClient, private: Any, runner: agent_mod.Agent
) -> None:
    """서버 실행이 취소되면 **그 위임 작업도 거둔다** — PC가 받을 쪽 없는 일을 하지 않는다.

    **기다리는 실행도 정말 닫힌다** (ADR-0054 §5) — 스레드를 놓았으므로 부탁만 해 두면 볼
    사람이 없어 영원히 기다린다. 거둘 작업은 **기다림이 걷히기 전에** 읽어야 한다
    (`Engine.cancel`이 비운다).
    """
    ready(center, private, runner)
    job_id = make_job(center)
    run_id = until_waiting_for_delegation(runner)
    delegated_job = str(waiting_row(center)["job_id"])

    # 운영자가 CON-05에서 취소한다 — **서버 대상이라 `accepted`에도 받아 준다** (ADR-0063).
    dropped = center.delete(f"/api/v1/jobs/{job_id}", headers=ADMIN)
    assert dropped.status_code == 202, dropped.text
    runner.tick()  # 취소 지시를 받아 실행을 닫고, 그 주기의 끝에서 위임을 거둔다

    # ① 서버 실행이 **정말 끝났다** (부탁만 해 두지 않는다).
    assert runner.workers[run_id].snapshot().finished == "cancelled"
    (one,) = lines(runner.settings, run_id, "run_finished")
    assert one["status"] == "cancelled"

    # ② 맡긴 PC 작업이 **같은 주기에** 거둬졌다 (하트비트 뒤가 그 자리다). 거둘 것은
    # **기다림이 걷히기 전에** 읽어야 하는데(`Engine.cancel`이 비운다) 순서를 뒤집으면
    # 여기서 드러난다 — 거둘 것이 없어 PC 작업이 `accepted`로 남는다.
    assert runner.pending_cancels == []
    revoked = center.get(f"/api/v1/jobs/{delegated_job}", headers=ADMIN).json()
    assert revoked["state"] == "cancelled"


def test_a_pc_job_that_already_started_is_left_alone(
    center: TestClient, private: Any, runner: agent_mod.Agent
) -> None:
    """**이미 시작된 PC 실행은 끝까지 간다** (C5) — 거절도 답이라 다시 걸지 않는다."""
    bot_ui_id = ready(center, private, runner)
    job_id = make_job(center)
    until_waiting_for_delegation(runner)
    delegated_job = str(waiting_row(center)["job_id"])
    pc_beat(
        center,
        bot_ui_id,
        job_acks=[{"job_id": delegated_job, "result": "started", "run_id": "run_20261015_100000_bbbbbb"}],
    )

    assert center.delete(f"/api/v1/jobs/{job_id}", headers=ADMIN).status_code == 202
    runner.tick()
    runner.tick()

    assert runner.pending_cancels == [], "4xx는 다시 걸지 않는다"
    kept = center.get(f"/api/v1/jobs/{delegated_job}", headers=ADMIN).json()
    assert kept["state"] == "accepted", "시작된 PC 실행을 멈추지 않는다"


def test_a_cancel_that_did_not_reach_center_is_tried_again(
    center: TestClient, private: Any, runner: agent_mod.Agent, monkeypatch: pytest.MonkeyPatch
) -> None:
    """닿지 못한 것은 **들고 있다 다시 건다** (ADR-0007) — 거두지 못하면 PC가 헛일을 한다."""
    ready(center, private, runner)
    job_id = make_job(center)
    until_waiting_for_delegation(runner)
    delegated_job = str(waiting_row(center)["job_id"])

    assert center.delete(f"/api/v1/jobs/{job_id}", headers=ADMIN).status_code == 202

    def unreachable(_: str) -> dict[str, Any]:
        raise Unreachable("Center에 닿지 못했습니다")

    monkeypatch.setattr(runner.client, "cancel_delegation", unreachable)
    runner.tick()
    assert runner.pending_cancels == [delegated_job], "닿지 못한 것을 버렸다"

    monkeypatch.undo()
    assert runner.cancel_delegations() == 1
    assert center.get(f"/api/v1/jobs/{delegated_job}", headers=ADMIN).json()["state"] == "cancelled"
