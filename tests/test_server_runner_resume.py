"""기다리는 실행이 상태를 담고 자리를 놓았다가 **결재함 답으로 이어 간다** (M7 기준 셋째).

**재시작을 끼워 넣어** 본다 — M7 기준 셋째의 마지막 문장이 「서버 실행기를 재시작해도 이어
간다」다. 그래서 여기서는 실행기를 **버리고 새로 만든** 뒤 답을 내려 준다.

그림은 업무 예제 **BX-03 지출 결재**다 — 실행 위치가 `server`이고 결재가 `location: center`라
서버 실행기가 맞닥뜨릴 모양 그대로다 (스파이크 `s10`이 쓴 그림이기도 하다).

| 보는 것 | 왜 |
| --- | --- |
| 멈추면 **자리를 놓는다** | 상한 1에 기다리는 1건을 들고도 새 작업을 받는다 (C12) |
| 결재를 **Center 결재함에** 올린다 | 서버의 창구는 Center만이다 (C12) |
| 답으로 **이어 간다** | M7 기준 셋째 |
| **재시작해도 이어 간다** | 같은 저장소가 넘긴다 (ADR-0054 §1~§3) |
| 기다린 적 없는 실행은 **되살리지 않는다** | 보내기는 멱등이 아니다 (ADR-0054 §4) |
"""

from __future__ import annotations

import io
import json
import tempfile
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
from chaeksas.contracts.events import KNOWN_RESUME_REASONS
from chaeksas.contracts.hashing import MANIFEST_NAME, content_hash_zip
from chaeksas.contracts.signing import sign
from chaeksas.core.run_log import RunLog, log_path
from chaeksas.server_runner import agent as agent_mod
from chaeksas.server_runner import worker as worker_mod
from chaeksas.server_runner.settings import Settings
from chaeksas.server_runner.store import WAITING, Store

ADMIN = {"Authorization": "Bearer t-admin"}
READ = {"Authorization": "Bearer t-read"}
PASS = "열쇠말"
AT = "2026-10-13T09:00:00+09:00"

EXAMPLE = Path("docs/08-business-examples/bpmn/bx03_expense_approval.bpmn")
BOT = "finance.expense-approval"
VERSION = "1.0.0"
WAIT_S = 20.0
#: 결재로 가는 입력 (금액이 자동승인한도를 넘는다).
INPUTS: dict[str, Any] = {
    "신청번호": "EX-2609-014",
    "신청자": "김하나",
    "항목": "출장 숙박",
    "금액": 480_000,
    "영수증": True,
    "회신주소": "http://127.0.0.1:1/reply",
}
ANSWER = {"승인여부": True, "결재의견": "승인합니다"}


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
        center_url="http://center", name="서버 1", max_concurrency=1, data_path=tmp_path / "runner"
    )
    found.data_path.mkdir(parents=True, exist_ok=True)
    found.runs_dir.mkdir(parents=True, exist_ok=True)
    return found


@pytest.fixture
def store(settings: Settings) -> Iterator[Store]:
    """**실행기를 버려도 남는** 저장소 — 재시작을 흉내 내는 자리다."""
    found = Store(path=settings.state_db)
    yield found
    found.close()


def runner_of(settings: Settings, key: str, center: TestClient, store: Store) -> agent_mod.Agent:
    """실행기 하나. **같은 저장소**를 넘기면 다시 뜬 것과 같다."""
    return agent_mod.build(settings, key, client=center, store=store)


# ─────────────────────────── 거리 ───────────────────────────


def package_zip() -> bytes:
    manifest: dict[str, Any] = {
        "schema": 1,
        "kind": "bpm_process",
        "id": BOT,
        "version": VERSION,
        "name": "지출 결재",
        "run_location": "server",
        "entry": "process/main.bpmn",
        "process_id": "Proc_bx03_expense_approval",
        "requires": {},
        "human": {"approvals": ["지출 결재"]},
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

    uploaded = center.post(
        "/api/v1/packages",
        files={"file": ("p.zip", package_zip(), "application/zip")},
        headers=ADMIN,
    )
    assert uploaded.status_code in (200, 201), uploaded.text
    info = dict(uploaded.json())
    signed = center.put(
        f"/api/v1/packages/{info['id']}/{info['version']}/signature",
        json=sign(
            {"kind": "package", "id": info["id"], "version": info["version"],
             "content_hash": info["content_hash"]},
            keystore.load(signer, passphrase=PASS), signed_at=AT,
        ).to_json_dict(),
        headers=ADMIN,
    )
    assert signed.status_code == 200, signed.text
    deployed = center.post(
        "/api/v1/deployments",
        json=sign(
            {"kind": "deployment", "deployment_id": "dep_3f9a1c07",
             "target": {"type": "server_runner", "id": runner.server_runner_id},
             "bpm_process_id": info["id"], "version": info["version"],
             "content_hash": info["content_hash"]},
            keystore.load(signer, passphrase=PASS), signed_at=now_iso(),
        ).to_json_dict(),
        headers=ADMIN,
    )
    assert deployed.status_code in (200, 201), deployed.text
    runner.tick()
    assert [b.id for b in runner.installed_bots()] == [BOT]


def make_job(center: TestClient, **extra: Any) -> dict[str, Any]:
    response = center.post(
        "/api/v1/jobs",
        json={"bpm_process_id": BOT, "target": {"type": "server_runner"}, "inputs": INPUTS, **extra},
        headers=ADMIN,
    )
    assert response.status_code in (200, 201), response.text
    return dict(response.json())


def until_waiting(runner: agent_mod.Agent) -> str:
    """결재 앞에서 멈출 때까지 민다. 돌려주는 것은 그 `run_id`다.

    **멈춘 것을 Center에 알린 뒤에 돌려준다** — 기다림을 알아차린 그 주기의 하트비트는 멈추기
    **전에** 나갔으므로, 한 번 더 밀지 않으면 Center가 아직 `running`으로 안다 (CI의 Windows가
    `capacity.running == 1`로 잡았다).
    """
    import time

    deadline = time.monotonic() + WAIT_S
    while time.monotonic() < deadline:
        runner.tick()
        for run_id, found in runner.workers.items():
            shot = found.snapshot()
            if shot.waiting is not None:
                found.join(WAIT_S)  # 담기까지 기다린다
                runner.tick()  # 기다린다고 보고한다
                return run_id
        time.sleep(0.05)
    raise AssertionError("결재 앞에서 멈추지 않았다")


def answer_in_center(center: TestClient, request_id: str) -> None:
    """운영자가 콘솔 결재함에서 답한다 (C6 `POST /approvals/{id}/answer`)."""
    response = center.post(
        f"/api/v1/approvals/{request_id}/answer",
        json={"schema": 1, "decision": "approve", "answer": ANSWER, "answered_by": "박결재"},
        headers=ADMIN,
    )
    assert response.status_code == 200, response.text


def drain(runner: agent_mod.Agent) -> None:
    import time

    deadline = time.monotonic() + WAIT_S
    while time.monotonic() < deadline:
        runner.tick()
        if not runner.workers:
            return
        time.sleep(0.05)
    raise AssertionError("끝나지 않았다")


# ─────────────────────────── 멈추면 담고 자리를 놓는다 ───────────────────────────


def test_a_waiting_run_is_saved_and_releases_its_slot(
    center: TestClient, center_store: CenterStore, settings: Settings, key: str, store: Store
) -> None:
    """멈추면 **담고 자리를 놓는다** (C12·ADR-0054 §3) — PC와 거꾸로다 (ADR-0014)."""
    runner = runner_of(settings, key, center, store)
    ready(center, center_store, runner)
    make_job(center)
    run_id = until_waiting(runner)

    saved = store.get(run_id)
    assert saved is not None and saved.state == WAITING
    assert saved.snapshot is not None and saved.had_wait

    # **자리를 놓았다** — 상한 1인데 기다리는 1건을 들고도 빈자리가 있다.
    assert settings.max_concurrency == 1
    assert runner.free_slots() == 1
    listed = center.get("/api/v1/server-runners", headers=READ).json()[0]
    assert listed["capacity"] == {"max": 1, "running": 0}
    assert [one["run_id"] for one in listed["waiting"]] == [run_id]
    assert listed["waiting"][0]["waiting_for"] == "approval"


def test_the_approval_reaches_the_center_inbox(
    center: TestClient, center_store: CenterStore, settings: Settings, key: str, store: Store
) -> None:
    """결재가 **Center 결재함에** 올라간다 (C6) — 서버의 창구는 Center만이다 (C12)."""
    runner = runner_of(settings, key, center, store)
    ready(center, center_store, runner)
    make_job(center)
    run_id = until_waiting(runner)
    runner.tick()  # 하트비트 뒤에 올린다

    listed = center.get("/api/v1/approvals?state=open", headers=READ).json()
    assert [one["run_id"] for one in listed] == [run_id]
    found = listed[0]
    assert found["layer"] == "approval"
    assert [f["key"] for f in found["form"]["fields"]] == ["승인여부", "결재의견"]
    # 결재자가 볼 값은 올라간다 (C6 `review` — 원칙 6의 예외다).
    assert found["review"]["신청번호"] == "EX-2609-014"


def test_the_same_approval_is_not_posted_twice(
    center: TestClient, center_store: CenterStore, settings: Settings, key: str, store: Store
) -> None:
    runner = runner_of(settings, key, center, store)
    ready(center, center_store, runner)
    make_job(center)
    until_waiting(runner)
    for _ in range(3):
        runner.tick()
    assert len(center.get("/api/v1/approvals?state=open", headers=READ).json()) == 1


# ─────────────────────────── 답으로 이어 간다 ───────────────────────────


def test_an_answer_carries_the_run_to_the_end(
    center: TestClient, center_store: CenterStore, settings: Settings, key: str, store: Store
) -> None:
    """**M7 기준 셋째의 앞쪽** — 결재함 답으로 이어 가 끝까지 간다."""
    runner = runner_of(settings, key, center, store)
    ready(center, center_store, runner)
    job = make_job(center)
    run_id = until_waiting(runner)
    runner.tick()

    request_id = center.get("/api/v1/approvals?state=open", headers=READ).json()[0]["request_id"]
    answer_in_center(center, request_id)

    drain(runner)
    assert store.get(run_id) is None, "끝났으면 담아 둔 것을 지운다"
    info = center.get(f"/api/v1/jobs/{job['job_id']}", headers=READ).json()
    assert info["run_status"] == "success"
    kinds = [
        one["kind"]
        for one in center.get(f"/api/v1/runs/{run_id}/events", headers=READ).json()["events"]
    ]
    assert "human_requested" in kinds and "human_answered" in kinds
    assert kinds[-1] == "run_finished"


def test_a_restart_does_not_lose_the_waiting_run(
    center: TestClient, center_store: CenterStore, settings: Settings, key: str, store: Store
) -> None:
    """**M7 기준 셋째** — 실행기를 재시작해도 이어 간다 (ADR-0054 §1~§3).

    실행기를 **버리고 새로 만든다** — 남는 것은 저장소·실행 기록 파일뿐이다.
    """
    first = runner_of(settings, key, center, store)
    ready(center, center_store, first)
    job = make_job(center)
    run_id = until_waiting(first)
    first.tick()  # 결재를 올린다
    request_id = center.get("/api/v1/approvals?state=open", headers=READ).json()[0]["request_id"]

    del first  # **실행기가 죽었다** (스레드도 함께 사라진다)

    second = runner_of(settings, key, center, store)
    second.tick()  # 등록하며 담아 둔 것을 되살린다
    assert second.restored == [run_id], "되살린 것을 `restored[]`로 알린다"
    assert run_id in second.workers

    answer_in_center(center, request_id)
    drain(second)
    info = center.get(f"/api/v1/jobs/{job['job_id']}", headers=READ).json()
    assert info["run_status"] == "success"
    # **기록이 이어진다** — 빈 `RunLog`로 되살리면 `seq`가 1부터 다시 시작해 겹친다.
    events = center.get(f"/api/v1/runs/{run_id}/events", headers=READ).json()["events"]
    seqs = [one["seq"] for one in events]
    assert seqs == sorted(set(seqs)), f"겹친 seq가 있다: {seqs}"
    assert events[-1]["data"]["status"] == "success"


def test_a_restored_run_is_told_once(
    center: TestClient, center_store: CenterStore, settings: Settings, key: str, store: Store
) -> None:
    """`restored[]`는 **첫 하트비트에만** 올린다 (C12) — 올린 뒤에는 비운다."""
    first = runner_of(settings, key, center, store)
    ready(center, center_store, first)
    make_job(center)
    until_waiting(first)
    del first

    second = runner_of(settings, key, center, store)
    second.tick()
    assert second.restored
    second.tick()
    assert second.restored == []


# ─────────────────────────── 기다림이 기록에 남는다 (C3) ───────────────────────────


def test_the_resume_reasons_are_the_ones_the_contract_knows() -> None:
    """깨운 까닭은 **계약이 아는 값**이다 (C3 `run_resumed.reason`).

    열린 문자열이라 받는 쪽이 거부하지는 않지만, 갈라지면 콘솔이 모르는 글을 그대로 보인다.
    """
    assert {
        worker_mod.RESUME_ANSWER,
        worker_mod.RESUME_MESSAGE,
        worker_mod.RESUME_TIMER,
        worker_mod.RESUME_RESTART,
        worker_mod.RESUME_WITHDRAW,
    } == KNOWN_RESUME_REASONS


def lines(settings: Settings, run_id: str, kind: str) -> list[dict[str, Any]]:
    """그 실행 기록에서 한 종류만 — **파일이 원본이다** (C3)."""
    return [
        one.data
        for one in RunLog.read(log_path(settings.data_path, run_id))
        if one.kind == kind
    ]


def test_a_waiting_run_leaves_a_line_saying_what_it_waits_for(
    center: TestClient, center_store: CenterStore, settings: Settings, key: str, store: Store
) -> None:
    """**기다리기 시작하면 줄 하나** (C3 `run_waiting`) — 서버만 쓴다.

    하트비트의 `waiting[]`은 **지금 모습**이라 기다림이 끝나면 사라진다. 이 줄이 없으면
    CON-01이 「이 실행이 무엇을 기다렸나」를 영영 모른다.
    """
    runner = runner_of(settings, key, center, store)
    ready(center, center_store, runner)
    make_job(center)
    run_id = until_waiting(runner)

    found = lines(settings, run_id, "run_waiting")
    assert len(found) == 1, "기다림 한 번에 한 줄이다"
    assert found[0]["waiting_for"] == "approval"
    # **짝이 되는 칸을 채운다** — 결재는 `request_id`다 (C3 선택 칸).
    assert found[0]["request_id"].startswith("apr_")
    assert "until" not in found[0], "타이머가 아니다"


def test_an_answer_says_how_long_it_waited(
    center: TestClient, center_store: CenterStore, settings: Settings, key: str, store: Store
) -> None:
    """**이어 가면 줄 하나** (C3 `run_resumed`) — `after_s`가 기다린 시간이다.

    `run_waiting`과 **짝**이고, 깨운 까닭(`reason`)이 함께 간다.
    """
    runner = runner_of(settings, key, center, store)
    ready(center, center_store, runner)
    make_job(center)
    run_id = until_waiting(runner)
    runner.tick()
    request_id = center.get("/api/v1/approvals?state=open", headers=READ).json()[0]["request_id"]
    answer_in_center(center, request_id)
    drain(runner)

    found = lines(settings, run_id, "run_resumed")
    assert len(found) == 1
    assert found[0]["reason"] == "answer"
    assert found[0]["after_s"] >= 0.0
    # 차례가 있다 — 기다리기 시작한 뒤에 이어 갔다.
    kinds = [one.kind for one in RunLog.read(log_path(settings.data_path, run_id))]
    assert kinds.index("run_waiting") < kinds.index("run_resumed")
    assert kinds[-1] == "run_finished"


def test_center_stops_calling_a_resumed_run_waiting(
    center: TestClient, center_store: CenterStore, settings: Settings, key: str, store: Store
) -> None:
    """**한 배치에 둘이 함께 온다** — 그래도 CON-01의 상태는 「기다리는 중」이 아니다.

    보내기는 하트비트 뒤라(C3) 기다리기 시작한 줄과 이어 간 줄이 같은 배치에 실린다. 받는 쪽이
    덮어쓰지 않으면 끝난 실행까지 「기다리는 중」으로 남는다.
    """
    runner = runner_of(settings, key, center, store)
    ready(center, center_store, runner)
    make_job(center)
    run_id = until_waiting(runner)
    runner.tick()
    assert center.get(f"/api/v1/runs/{run_id}", headers=READ).json()["status"] == "waiting"

    request_id = center.get("/api/v1/approvals?state=open", headers=READ).json()[0]["request_id"]
    answer_in_center(center, request_id)
    drain(runner)
    assert center.get(f"/api/v1/runs/{run_id}", headers=READ).json()["status"] == "success"


def test_a_restart_says_it_resumed_too(
    center: TestClient, center_store: CenterStore, settings: Settings, key: str, store: Store
) -> None:
    """재시작으로 되살린 것도 **이어 간 것**이다 (`reason: restart`).

    기다린 시간은 **기록에서** 읽는다 — 메모리와 함께 사라지지 않는다 (파일이 원본이다).
    """
    first = runner_of(settings, key, center, store)
    ready(center, center_store, first)
    make_job(center)
    run_id = until_waiting(first)
    first.tick()
    del first

    second = runner_of(settings, key, center, store)
    second.tick()
    assert second.restored == [run_id]
    assert second.workers[run_id].join(WAIT_S), "되살린 스레드가 다시 멈출 때까지"

    found = lines(settings, run_id, "run_resumed")
    assert [one["reason"] for one in found] == ["restart"]
    # 되살린 실행은 그 자리에서 **다시 기다린다** — 그래서 기다림 줄이 둘이다.
    assert len(lines(settings, run_id, "run_waiting")) == 2


# ─────────────────────────── 되살리지 않는 둘 (ADR-0054 §4) ───────────────────────────


def test_a_run_that_never_waited_is_not_restored(
    center: TestClient, center_store: CenterStore, settings: Settings, key: str, store: Store
) -> None:
    """**기다린 적 없는 실행은 되살리지 않는다** — 처음부터 돌리면 메일·웹훅을 두 번 보낸다.

    `runner_restarted`로 닫고 작업도 닫는다 — 안 하면 작업이 `accepted`로 영원히 남는다.
    """
    runner = runner_of(settings, key, center, store)
    ready(center, center_store, runner)
    # 돌던 중에 죽은 실행을 흉내 낸다 — 행은 있고 스냅샷은 없다 (ADR-0054 §3).
    store.mark_running(
        "run_20261013_090000_aa11bb",
        bpm_process_id=BOT,
        version=VERSION,
        job_id="job_ghost",
        started_at=AT,
    )
    second = runner_of(settings, key, center, store)
    second.tick()

    assert second.restored == [] and second.workers == {}
    assert store.get("run_20261013_090000_aa11bb") is None, "닫고 지운다"
    assert [(a.job_id, a.result, a.reason) for a in second.pending_acks] == [
        ("job_ghost", "failed", "runner_restarted")
    ]
    # 사유가 **기록에** 남는다 (Center가 아는 유일한 길이다 — C3).
    path = log_path(settings.data_path, "run_20261013_090000_aa11bb")
    kinds = [one.kind for one in RunLog.read(path)]
    assert kinds == ["log", "run_finished"]


def test_a_different_version_is_not_restored(
    center: TestClient, center_store: CenterStore, settings: Settings, key: str, store: Store
) -> None:
    """판이 다르면 되살리지 않는다 — **없는 노드를 밟는다** (`runner_version_changed`)."""
    runner = runner_of(settings, key, center, store)
    ready(center, center_store, runner)
    make_job(center)
    run_id = until_waiting(runner)
    del runner

    # 그 판이 사라졌다 (제거되었거나 다른 판으로 바뀌었다).
    with store.db:
        store.db.execute("UPDATE runs SET version = ? WHERE run_id = ?", ("9.9.9", run_id))

    second = runner_of(settings, key, center, store)
    second.tick()
    assert second.restored == [] and second.workers == {}
    assert [a.reason for a in second.pending_acks] == ["runner_version_changed"]


def test_an_unreadable_snapshot_is_not_restored(
    center: TestClient, center_store: CenterStore, settings: Settings, key: str, store: Store
) -> None:
    """깨진 글로 실행을 이어 가지 않는다 — 없는 것으로 보고 닫는다."""
    runner = runner_of(settings, key, center, store)
    ready(center, center_store, runner)
    make_job(center)
    run_id = until_waiting(runner)
    del runner

    with store.db:
        store.db.execute("UPDATE runs SET snapshot = ? WHERE run_id = ?", ("{깨진", run_id))

    second = runner_of(settings, key, center, store)
    second.tick()
    assert second.restored == [] and second.workers == {}
    assert store.get(run_id) is None
