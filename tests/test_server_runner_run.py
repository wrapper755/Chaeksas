"""서버 실행기가 작업을 받아 **한 건을 끝까지 돌린다** (C12·C3·C5, M7 조각 4-①).

**한 줄로 본다**: Admin 서명 → Center 배포 → 실행기 설치 → **Center 작업 지시** → 실행기가
스레드로 돌림 → 실행 기록이 Center에 닿고 작업의 `run_status`가 찬다.

그림은 업무 예제 **FX-03b**다 (`fx03b_amount_branch`) — 실행 위치가 `server`이고 입력 하나로
갈라져 **사람 없이 끝까지 간다**. 사람을 기다리는 실행은 조각 4-②의 일이다.

`tests/test_m5_pc_rerun.py`가 PC 쪽에서 같은 꼴을 보므로, 여기서 보는 것은 **서버에서만 다른
것**이다: 스레드로 돌고, 자리 셈이 기다리는 실행을 빼고, 기록을 하트비트 뒤에 보낸다.
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
from chaeksas.center.storage import Store, now_iso
from chaeksas.contracts.extension import definition_hash
from chaeksas.contracts.hashing import MANIFEST_NAME, content_hash_zip
from chaeksas.contracts.signing import sign
from chaeksas.core import seen as seen_mod
from chaeksas.core.app_directory import CACHE_NAME
from chaeksas.core.run_log import RunLog, log_path
from chaeksas.mock_apps.external import definitions as external_definitions
from chaeksas.server_runner import agent as agent_mod
from chaeksas.server_runner.center_client import CenterClient, Unreachable
from chaeksas.server_runner.settings import Settings
from chaeksas.server_runner.worker import Worker

ADMIN = {"Authorization": "Bearer t-admin"}
READ = {"Authorization": "Bearer t-read"}
PASS = "열쇠말"
AT = "2026-10-13T09:00:00+09:00"

#: 업무 예제 FX-03b — 실행 위치 `server`, 입력 하나, 사람 없이 끝까지 간다.
EXAMPLE = Path("docs/08-business-examples/bpmn/fx03b_amount_branch.bpmn")
BOT = "fx.amount-branch"
PROCESS_ID = "Proc_fx03b_amount_branch"
VERSION = "1.0.0"
#: 타이머 예제 — `PT3S`를 기다렸다가 결재로 간다 (ADR-0061의 쓸기를 보는 자리).
TIMERS = Path("docs/08-business-examples/bpmn/fx14_timers.bpmn")
TIMER_BOT = "fx.timers"
#: 한 실행이 끝나기를 기다리는 한도 (초). 스레드가 도는 것을 기다린다.
WAIT_S = 20.0


@pytest.fixture(autouse=True)
def _admin_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(keystore.PASSPHRASE_ENV, PASS)
    monkeypatch.setenv(f"{keystore.ENV_PREFIX}DATA_DIR", str(tmp_path / "admin"))


@pytest.fixture
def store() -> Iterator[Store]:
    found = Store(Path(":memory:"))
    yield found
    found.close()


@pytest.fixture
def center(store: Store, tmp_path: Path) -> Iterator[TestClient]:
    settings = CenterSettings(
        admin_token="t-admin", read_token="t-read", package_dir=tmp_path / "pkg"
    )
    with TestClient(create_app(settings, store=store)) as found:
        yield found


@pytest.fixture
def key(center: TestClient) -> str:
    response = center.post(
        "/api/v1/center-keys", json={"name": "서버 1", "type": "server_runner"}, headers=ADMIN
    )
    assert response.status_code == 201, response.text
    return str(response.json()["key"])


@pytest.fixture
def runner(tmp_path: Path, key: str, center: TestClient) -> agent_mod.Agent:
    settings = Settings(
        center_url="http://center", name="서버 1", max_concurrency=3, data_path=tmp_path / "runner"
    )
    settings.data_path.mkdir(parents=True, exist_ok=True)
    settings.runs_dir.mkdir(parents=True, exist_ok=True)
    return agent_mod.Agent(
        settings=settings,
        client=CenterClient(base_url="http://center", api_key=key, client=center),
    )


# ─────────────────────────── 거리 ───────────────────────────


def package_zip(
    *, requires: dict[str, Any] | None = None, example: Path = EXAMPLE, bot: str = BOT, process_id: str = PROCESS_ID
) -> bytes:
    """업무 예제 하나를 C1 패키지로 싼다 (Studio가 내보내는 것과 같은 모양)."""
    manifest: dict[str, Any] = {
        "schema": 1,
        "kind": "bpm_process",
        "id": bot,
        "version": VERSION,
        "name": "금액 갈래",
        "run_location": "server",
        "entry": "process/main.bpmn",
        "process_id": process_id,
        "requires": requires or {},
        "human": {},
        "built": {"by": "studio", "at": AT, "core": "0.1.0", "spec_version": 1},
        "content_hash": "sha256:" + "0" * 64,
    }
    files = {"process/main.bpmn": example.read_text(encoding="utf-8")}

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


def ready_runner(
    center: TestClient,
    store: Store,
    runner: agent_mod.Agent,
    *,
    requires: dict[str, Any] | None = None,
    after_bootstrap: Any = None,
    zip_bytes: bytes | None = None,
) -> None:
    """등록 → 승인 → 배포 → 설치까지 세워 둔다 (앞 조각들이 보는 길이다).

    `after_bootstrap(signer)`는 **첫 공개키가 들어간 뒤, 배포 전에** 불린다 — 배포는 C7
    누락 검사를 지나야 하므로 확장·서비스 앱을 미리 등록해야 하는 시험이 쓴다.
    """
    runner.tick()  # 등록
    signer = keystore.create(label="첫 키")
    bootstrap_key(store, public_key=signer.public_bytes(), label="첫 키")
    if after_bootstrap is not None:
        after_bootstrap(signer)

    uploaded = center.post(
        "/api/v1/packages",
        files={"file": ("p.zip", zip_bytes or package_zip(requires=requires), "application/zip")},
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
            keystore.load(signer, passphrase=PASS),
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
                "deployment_id": "dep_3f9a1c07",
                "target": {"type": "server_runner", "id": runner.server_runner_id},
                "bpm_process_id": info["id"],
                "version": info["version"],
                "content_hash": info["content_hash"],
            },
            keystore.load(signer, passphrase=PASS),
            signed_at=now_iso(),
        ).to_json_dict(),
        headers=ADMIN,
    )
    assert deployed.status_code in (200, 201), deployed.text

    runner.tick()  # 공개키·배포를 받아 설치한다
    assert info["id"] in [b.id for b in runner.installed_bots()]


def make_job(center: TestClient, *, amount: int = 2_000_000, **extra: Any) -> dict[str, Any]:
    """Center에 서버 대상 작업을 만든다 (C5 — `id`를 비우면 Center가 고른다)."""
    response = center.post(
        "/api/v1/jobs",
        json={
            "bpm_process_id": BOT,
            "target": {"type": "server_runner"},
            "inputs": {"금액": amount},
            **extra,
        },
        headers=ADMIN,
    )
    assert response.status_code in (200, 201), response.text
    return dict(response.json())


def drain(runner: agent_mod.Agent, *, rounds: int = 40) -> None:
    """실행이 끝날 때까지 하트비트를 돌린다. **스레드를 기다려 준다.**"""
    import time

    deadline = time.monotonic() + WAIT_S
    for _ in range(rounds):
        runner.tick()
        if not runner.workers and not runner.pending_acks:
            return
        if time.monotonic() > deadline:
            raise AssertionError("실행이 끝나지 않았다")
        time.sleep(0.05)


# ─────────────────────────── 한 줄 ───────────────────────────


def test_a_job_runs_to_the_end_and_center_knows(
    center: TestClient, store: Store, runner: agent_mod.Agent
) -> None:
    """작업 지시 → 실행 → **기록과 `run_status`가 Center에 닿는다** (C3·C5)."""
    ready_runner(center, store, runner)
    job = make_job(center)

    runner.tick()  # 작업을 받아 스레드를 띄운다
    assert len(runner.workers) == 1
    started = next(iter(runner.workers.values()))
    assert started.join(WAIT_S), "실행 스레드가 끝나지 않았다"

    runner.tick()  # 끝난 것을 거두고 ack·기록을 올린다
    runner.tick()

    found = center.get(f"/api/v1/jobs/{job['job_id']}", headers=READ).json()
    assert found["state"] == "accepted", "시작된 작업은 accepted로 남는다 (C5)"
    # **실행의 성패는 작업 상태가 아니다** (C5) — `run_status`에만 적는다. 값은 **C3의 말**이다
    # (`run_finished.status` = `success`) — ack의 `finished`는 거들 뿐이다.
    assert found["run_status"] == "success"
    assert found["run_id"] == started.run_id

    # 실행 기록이 Center에 닿았다 (C3 §전송 — 파일이 원본이고 하트비트 뒤에 보낸다).
    events = center.get(f"/api/v1/runs/{started.run_id}/events", headers=READ).json()
    kinds = [one["kind"] for one in events["events"]]
    assert kinds[0] == "run_started" and kinds[-1] == "run_finished"
    first = events["events"][0]["data"]
    assert first["run_location"] == "server" and first["executor"] == "server_runner"
    assert first["job_id"] == job["job_id"]
    assert events["events"][-1]["data"]["status"] == "success"


def test_the_run_log_file_is_the_original(
    center: TestClient, store: Store, runner: agent_mod.Agent
) -> None:
    """**파일이 원본이다** (C3) — Center로 보내는 것은 그 파일에서 읽은 줄이다."""
    ready_runner(center, store, runner)
    make_job(center)
    runner.tick()
    found = next(iter(runner.workers.values()))
    assert found.join(WAIT_S)

    path = log_path(runner.settings.data_path, found.run_id)
    assert path.is_file()
    kinds = [one.kind for one in RunLog.read(path)]
    assert kinds[0] == "run_started" and kinds[-1] == "run_finished"


def test_a_failing_run_says_why(center: TestClient, store: Store, runner: agent_mod.Agent) -> None:
    """실패도 **기록으로** 올라간다 — 작업은 `accepted`로 남고 `run_status`가 `failed`다 (C5).

    입력을 선언하지 않은 이름으로 주면 엔진이 거부한다 (C14 §6 — 조용히 흘리지 않는다).
    """
    ready_runner(center, store, runner)
    response = center.post(
        "/api/v1/jobs",
        json={
            "bpm_process_id": BOT,
            "target": {"type": "server_runner"},
            "inputs": {"없는이름": 1},
        },
        headers=ADMIN,
    )
    assert response.status_code in (200, 201), response.text
    job = dict(response.json())

    runner.tick()
    found = next(iter(runner.workers.values()))
    assert found.join(WAIT_S)
    runner.tick()
    runner.tick()

    info = center.get(f"/api/v1/jobs/{job['job_id']}", headers=READ).json()
    assert info["run_status"] == "failed"
    events = center.get(f"/api/v1/runs/{found.run_id}/events", headers=READ).json()
    # 시작조차 못 했으므로 `run_started`가 없다 — **사유는 로그 줄에 있다**.
    assert [one["kind"] for one in events["events"]] == ["log", "run_finished"]
    assert "선언하지 않은 입력" in events["events"][0]["data"]["message"]


# ─────────────────────────── 자리 셈 (C12) ───────────────────────────


def test_only_as_many_as_the_limit_run_at_once(
    center: TestClient, store: Store, runner: agent_mod.Agent
) -> None:
    """상한을 넘겨 받지 않는다 — Center가 빈자리만큼 싣지만 **이쪽에서도 다시 센다**."""
    ready_runner(center, store, runner)
    jobs = [make_job(center, idempotency_key=f"k{n}")["job_id"] for n in range(5)]
    assert len(set(jobs)) == 5

    runner.tick()
    assert len(runner.workers) <= runner.settings.max_concurrency == 3
    drain(runner)

    states = {
        one["job_id"]: center.get(f"/api/v1/jobs/{one['job_id']}", headers=READ).json()["run_status"]
        for one in [{"job_id": job_id} for job_id in jobs]
    }
    assert all(found == "success" for found in states.values()), states


def test_a_paused_runner_refuses_new_jobs(
    center: TestClient, store: Store, runner: agent_mod.Agent
) -> None:
    """일시 중지 중에는 **새 작업을 받지 않는다** (C12 `paused`) — 거절하고 그렇게 말한다."""
    ready_runner(center, store, runner)
    center.post(f"/api/v1/server-runners/{runner.server_runner_id}/pause", headers=ADMIN)
    runner.tick()  # `paused`를 듣는다
    assert runner.paused is True

    job = make_job(center)
    runner.tick()
    assert runner.workers == {}, "일시 중지 중에는 돌리지 않는다"
    # **Center가 애초에 싣지 않는다** (`free_slots`가 0이다) — 그래서 ack도 없고 작업은
    # `pending`으로 기다린다. 실행기 쪽 거절(`paused`)은 혹시 실려 왔을 때의 그물이다.
    assert runner.pending_acks == []
    assert runner.last_response is not None and runner.last_response.jobs == []
    info = center.get(f"/api/v1/jobs/{job['job_id']}", headers=READ).json()
    assert info["state"] == "pending"

    center.post(f"/api/v1/server-runners/{runner.server_runner_id}/resume", headers=ADMIN)
    runner.tick()  # 다시 시작 — **그 주기에 바로 받는다**
    drain(runner)
    # 거절이 `seen_jobs`에 남아 있었으면 이 작업은 영원히 돌지 않는다 (C4 멱등) —
    # 「일시 중지」를 작업보다 먼저 반영하는 까닭이다.
    assert center.get(f"/api/v1/jobs/{job['job_id']}", headers=READ).json()["run_status"] == "success"


def test_the_same_job_is_not_run_twice(
    center: TestClient, store: Store, runner: agent_mod.Agent
) -> None:
    """**이미 본 작업이면 마지막 ack를 되돌려 보낸다** (C4 멱등) — 두 번 돌리지 않는다."""
    ready_runner(center, store, runner)
    make_job(center)
    runner.tick()
    first = next(iter(runner.workers))
    assert next(iter(runner.workers.values())).join(WAIT_S)

    # ack를 올리기 전에 같은 작업이 또 내려온다 (C4 — ack가 올 때까지 매번 실린다).
    runner.tick()
    runner.tick()
    run_ids = {one.run_id for one in runner.seen_jobs.values() if one.run_id}
    assert run_ids == {first}, "같은 작업에 실행이 둘 생기면 안 된다"


def test_the_seen_map_forgets_once_the_ack_reached_center(
    center: TestClient, store: Store, runner: agent_mod.Agent
) -> None:
    """멱등 기억은 **ack가 Center에 닿은 뒤 두 주기에** 잊는다 (ADR-0056).

    규칙은 `core.seen`이 쥐고 `tests/test_server_runner_seen.py`가 잰다 — 여기서 보는 것은
    **진짜 하트비트가 그 자리를 정말 움직이는가**다. 아무도 `delivered()`를 부르지 않으면
    기억은 영원히 자라고, 이 시험만 그것을 본다.
    """
    ready_runner(center, store, runner)
    job = make_job(center)
    runner.tick()
    assert next(iter(runner.workers.values())).join(WAIT_S)
    drain(runner)

    assert job["job_id"] in runner.seen_jobs, "닿은 그 주기에는 아직 들고 있다"
    # 그 뒤로 몇 주기가 지나면 잊는다 — Center는 이미 반영했으니 다시 싣지 않는다.
    for _ in range(seen_mod.GRACE_CYCLES + 1):
        runner.tick()
    assert job["job_id"] not in runner.seen_jobs
    assert len(runner.seen_jobs) == 0, "몇 주 떠 있어도 자라지 않는다"
    # 잊은 것이 되살아나지 않는다 — Center는 그 작업을 끝난 것으로 안다 (C5).
    info = center.get(f"/api/v1/jobs/{job['job_id']}", headers=READ).json()
    assert info["run_status"] == "success"
    assert runner.last_response is not None and runner.last_response.jobs == []


def test_an_unshipped_ack_is_kept_even_as_cycles_pass(
    center: TestClient,
    store: Store,
    runner: agent_mod.Agent,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**올리지 못한 ack는 잊지 않는다** — 다시 내려온 작업에 그것을 되돌려 보낸다 (C4 멱등).

    Center에 닿지 못하는 동안에도 기억은 남아야 한다. 잊으면 그 작업을 「처음 본 것」으로
    다루어 **같은 작업에 실행이 둘** 생긴다.
    """
    ready_runner(center, store, runner)
    job = make_job(center)
    runner.tick()
    first = next(iter(runner.workers))
    assert next(iter(runner.workers.values())).join(WAIT_S)

    # 하트비트가 끊긴다 — ack가 올라가지 못하므로 기억은 **아무리 주기가 가도** 남는다.
    def unreachable(_request: Any) -> Any:
        raise Unreachable("Center에 닿지 못한다")

    monkeypatch.setattr(runner.client, "heartbeat", unreachable)
    for _ in range(seen_mod.GRACE_CYCLES + 5):
        runner.tick()
    kept = runner.seen_jobs.get(job["job_id"])
    assert kept is not None and kept.run_id == first, "올리지 못한 ack는 들고 있는다"

    # 다시 닿으면 그 ack가 올라가고, 다시 내려온 작업은 **그 ack를 되돌려 받는다**.
    monkeypatch.undo()
    drain(runner)
    run_ids = {one.run_id for one in runner.seen_jobs.values() if one.run_id}
    assert run_ids <= {first}, "같은 작업에 실행이 둘 생기면 안 된다"
    info = center.get(f"/api/v1/jobs/{job['job_id']}", headers=READ).json()
    assert info["run_id"] == first and info["run_status"] == "success"


def test_delivery_is_only_known_after_the_heartbeat_answered(
    center: TestClient,
    store: Store,
    runner: agent_mod.Agent,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """「닿았다」는 **응답을 받은 뒤에만** 안다 — 보낼 때 알려 주면 기억이 먼저 사라진다.

    평상시에는 그물(`grace`) 때문에 이 자리가 드러나지 않는다 — `pending_acks`는 성공할
    때까지 **매 주기 다시 실리므로**, 보낼 때 「닿았다」고 쳐도 다음 주기가 나이를 되돌려
    놓는다. 그래서 그물을 걷고(`grace=0`) 본다: 올리지 못한 ack를 그 자리에서 잊으면
    Center가 다시 내려보낸 작업이 「처음 본 것」이 되어 **같은 작업에 실행이 둘** 생긴다.
    """
    runner.seen_jobs = seen_mod.Seen(grace=0)  # 그물을 걷는다 — 자리가 드러난다
    ready_runner(center, store, runner)
    job = make_job(center)
    runner.tick()  # 받아서 돌렸다 — ack는 아직 올라가지 못했다
    first = next(iter(runner.workers))

    def unreachable(_request: Any) -> Any:
        raise Unreachable("Center에 닿지 못한다")

    monkeypatch.setattr(runner.client, "heartbeat", unreachable)
    for _ in range(3):
        runner.tick()
    kept = runner.seen_jobs.get(job["job_id"])
    assert kept is not None and kept.run_id == first, (
        "하트비트가 끊긴 동안에는 「닿았다」가 아니다 — 잊으면 실행이 둘 생긴다"
    )


def test_cancel_stops_the_run(center: TestClient, store: Store, runner: agent_mod.Agent) -> None:
    """취소는 **유예를 기다려 준다** — 그래야 `cancelled`가 기록에 남는다 (ADR-0031과 같은 결)."""
    ready_runner(center, store, runner)
    job = make_job(center)
    runner.tick()
    found = next(iter(runner.workers.values()))
    assert found.join(WAIT_S)  # 이 예제는 금세 끝난다

    center.post(f"/api/v1/jobs/{job['job_id']}/cancel", headers=ADMIN)
    runner.tick()
    runner.tick()
    info = center.get(f"/api/v1/jobs/{job['job_id']}", headers=READ).json()
    # 이미 끝났으면 **그대로 둔다** — 끝난 것을 취소했다고 하지 않는다 (C3가 원본이다).
    assert info["run_status"] == "success"


def test_once_does_not_take_jobs(center: TestClient, store: Store, runner: agent_mod.Agent) -> None:
    """`--once`는 **작업을 받지 않는다** — 그 프로세스는 곧 끝난다 (진짜 소켓으로 발견했다).

    받으면 띄운 스레드를 버리게 되고, 다음 `--once`가 **같은 작업을 또** 띄운다(새 프로세스는
    `seen_jobs`가 비어 있다). 받지 않은 작업은 `dispatched`로 남아 다음에 다시 실린다 (C4) —
    그래서 잃는 것이 없고 거짓 `started`도 없다.
    """
    ready_runner(center, store, runner)
    job = make_job(center)

    runner.once()
    assert runner.workers == {}, "띄우지 않았다"
    assert runner.pending_acks == [], "ack도 보내지 않는다 (거절로 닫지 않는다)"
    assert runner.last_response is not None and runner.last_response.jobs, "받기는 했다"

    info = center.get(f"/api/v1/jobs/{job['job_id']}", headers=READ).json()
    assert info["state"] == "dispatched" and info["run_id"] is None

    # 상주 루프는 그 작업을 그대로 집어 돌린다 — 잃은 것이 없다.
    runner.accepts_jobs = True
    drain(runner)
    assert center.get(f"/api/v1/jobs/{job['job_id']}", headers=READ).json()["run_status"] == "success"


def test_asking_while_it_runs_does_not_touch_the_run(
    center: TestClient, store: Store, runner: agent_mod.Agent
) -> None:
    """도는 실행을 **들여다보다 터지지 않는다** — 모습은 그 스레드가 찍어 둔 것이다.

    처음에는 `snapshot()`이 `Run`을 그 자리에서 읽었다. 그것은 경쟁이다 — 엔진이 토큰을 지우는
    사이에 `run.tokens[0]`을 읽으면 `IndexError`이고, `pendings`·`waits`를 훑는 동안 엔진이
    그 사전을 고치면 「크기가 바뀌었다」로 터진다. 드물게 나고 **실행기가 죽는다**.

    여기서는 한 실행이 도는 동안 **수없이 물어 본다** — 찍어 두는 쪽이면 아무 일도 없다.
    """
    ready_runner(center, store, runner)
    make_job(center)
    runner.tick()
    found = next(iter(runner.workers.values()))

    seen = []
    for _ in range(3000):
        shot = found.snapshot()
        seen.append(shot.state)
        if shot.done:
            break
    assert found.join(WAIT_S)
    # 마지막으로 찍힌 것은 끝난 모습이다 — 스레드가 끝내며 한 번 더 찍는다.
    assert found.snapshot().done and found.snapshot().finished == "success"
    assert seen, "한 번도 묻지 못했다"


def test_a_running_run_is_reported_with_its_node(
    center: TestClient, store: Store, runner: agent_mod.Agent
) -> None:
    """도는 실행이 **`running[]`에 내용으로** 올라간다 (C12) — 비워 올리면 셋이 깨진다.

    조각 4-①이 이 자리를 빈 채로 냈다(#109). CON-12가 아무것도 못 보이고,
    `capacity.running`이 늘 0이라 Center가 **상한을 넘겨 보내고**, 맞추기 규칙이 멀쩡한 실행을
    두 주기 뒤 `runner_lost`로 닫는다. **길이만 보는 시험은 그것을 잡지 못한다** — 여기서는
    `run_id`·`bpm_process_id`·`job_id`까지 본다.
    """
    ready_runner(center, store, runner)
    job = make_job(center)
    runner.tick()
    found = next(iter(runner.workers.values()))

    request = runner._heartbeat_request()  # noqa: SLF001 — 올리는 본문을 그 자리에서 본다
    assert request.capacity.running == len(request.running), "C12가 요구하는 짝이다"
    if request.running:  # 금세 끝나는 그림이라 이미 끝났을 수도 있다
        one = request.running[0]
        assert one.run_id == found.run_id
        # **패키지 id다** (C1) — 그림의 `process.id`를 올리면 배포·작업과 이름이 갈라진다.
        assert one.bpm_process_id == BOT
        assert one.job_id == job["job_id"]
    assert found.join(WAIT_S)
    drain(runner)


# ─────────────────── 바깥 앱 명부 (M7 조각 9, C13 「전송」) ───────────────────


def _extension_envelope(signer: Any, definition: dict[str, Any], *, kind: str) -> Any:
    """외부 확장 등록·철회 봉투 하나 (C2 `extension`·`extension_revoke`)."""
    return sign(
        {
            "kind": kind,
            "id": definition["id"],
            "version": definition["version"],
            "definition_hash": definition_hash(definition),
        },
        keystore.load(signer, passphrase=PASS),
        signed_at=AT,
    )


def test_a_job_whose_external_definition_was_revoked_does_not_start(
    center: TestClient, store: Store, runner: agent_mod.Agent
) -> None:
    """**철회된 정의로는 시작조차 하지 않는다** (C1·C13 E6).

    배포될 때는 Center에 그 정의가 있었다 — 해시가 어긋나면 **배포가** 422로 막히므로
    (C7 `blocking_at_deploy`) 실행기 쪽 관문이 실제로 잡는 것은 **배포 뒤에 거둬진** 정의다.
    철회는 보안 동작이라 「모르고 멈추는 것」보다 「철회된 정의로 도는 것」이 나쁘다.

    사전 점검은 이것을 보지 않는다 (`core.preflight` — 봉투 검증은 실행하는 쪽의 일이다).
    그래서 거절 사유는 같은 `not_ready`이고, 무엇이 왜 막혔는지는 로그가 말한다.
    """
    definition = external_definitions.credit("http://127.0.0.1:9")
    held: dict[str, Any] = {}

    def register_the_definition(signer: Any) -> None:
        """운영자가 하듯 **서명 봉투로** 등록한다 (C13 E6 — C11로는 못 한다)."""
        held["signer"] = signer
        answer = center.post(
            "/api/v1/resources/extensions",
            json={
                "definition": definition,
                "envelope": _extension_envelope(signer, definition, kind="extension").to_json_dict(),
            },
            headers=ADMIN,
        )
        assert answer.status_code < 400, answer.text

    ready_runner(
        center,
        store,
        runner,
        # 패키지가 **그 정의를** 고정한다 (C1) — 배포는 지나간다.
        requires={
            "extensions": [
                {
                    "id": definition["id"],
                    "version": ">=1,<2",
                    "definition_hash": definition_hash(definition),
                }
            ]
        },
        after_bootstrap=register_the_definition,
    )

    # 운영자가 정의를 거둔다 (C13 — 철회된 판은 되살아나지 않는다).
    revoked = center.request(
        "DELETE",
        f"/api/v1/resources/extensions/{definition['id']}",
        json=_extension_envelope(
            held["signer"], definition, kind="extension_revoke"
        ).to_json_dict(),
        headers=ADMIN,
    )
    assert revoked.status_code < 400, revoked.text

    job = make_job(center)
    runner.tick()  # 작업을 받는다 — 받고도 띄우지 않는다
    assert runner.workers == {}, "철회된 외부 정의를 쓰는 Bot을 시작했다"
    ack = next(one for one in runner.pending_acks if one.job_id == job["job_id"])
    assert (ack.result, ack.reason) == ("rejected", "not_ready")


def test_the_runner_reads_the_addresses_itself_before_it_starts(
    center: TestClient, store: Store, runner: agent_mod.Agent
) -> None:
    """실행기가 **제 손으로** C7을 읽어 명부를 짓는다 — 파일을 거치지 않는다 (ADR-0031 각주).

    그 Bot이 부르는 앱만 담는다 (여기 그림은 아무것도 부르지 않으므로 **묻지도 않는다**).
    """
    ready_runner(center, store, runner)
    bot = next(one for one in runner.installed_bots() if one.id == BOT)
    made = runner.app_directory(bot)
    assert made.addresses == {} and made.externals == {}
    assert not (runner.settings.data_path / CACHE_NAME).exists(), "부를 것이 없으면 받아 두지 않는다"


# ─────────────────── 타이머로 깨우기 (ADR-0061) ───────────────────


def timer_job(center: TestClient) -> dict[str, Any]:
    """타이머 예제(FX-14)에 작업 하나 — 입력이 없다."""
    response = center.post(
        "/api/v1/jobs",
        json={"bpm_process_id": TIMER_BOT, "target": {"type": "server_runner"}, "inputs": {}},
        headers=ADMIN,
    )
    assert response.status_code in (200, 201), response.text
    return dict(response.json())


def waiting_on_a_timer(
    center: TestClient, store: Store, runner: agent_mod.Agent
) -> Worker:
    """FX-14를 깔고 돌려 **타이머를 기다리는 자리**까지 보낸다 (`PT3S`)."""
    ready_runner(
        center,
        store,
        runner,
        zip_bytes=package_zip(example=TIMERS, bot=TIMER_BOT, process_id="Proc_fx14_timers"),
    )
    timer_job(center)
    runner.tick()
    found = next(iter(runner.workers.values()))
    deadline = time.monotonic() + 10
    while found.snapshot().waiting is None and time.monotonic() < deadline:
        time.sleep(0.02)
    assert found.snapshot().waiting is not None, "타이머를 기다리는 자리에 닿지 못했다"
    assert not found.alive, "기다리는 실행은 스레드를 놓는다 (ADR-0054 §5)"
    return found


def test_a_run_waiting_on_a_timer_is_woken_when_the_time_comes(
    center: TestClient, store: Store, runner: agent_mod.Agent
) -> None:
    """**시각이 되면 깨운다** (ADR-0061) — 그러지 않으면 기한이 영원히 오지 않는다.

    C12 §재시작과 유실의 「기한은 Center가 꺼져 있어도 간다」를 지키는 자리다. 깨우는 쪽은
    `Agent.wake_due()`이고 **네트워크를 쓰지 않는다**.
    """
    found = waiting_on_a_timer(center, store, runner)

    assert found.due_now() is False, "아직 3초가 지나지 않았다 — 일찍 깨우지 않는다"
    assert runner.wake_due() == 0

    time.sleep(3.2)
    assert found.due_now() is True
    assert runner.wake_due() == 1, "시각이 됐으니 깨운다"
    assert found.join(WAIT_S), "깨운 실행이 이어 돌아야 한다"
    # 타이머를 지나 **결재를 기다리는 자리**로 갔다 (FX-14는 그다음이 15초 결재다).
    shot = found.snapshot()
    assert shot.waiting is not None and shot.waiting.waiting_for == "approval"


def test_the_timer_wait_is_written_down(
    center: TestClient, store: Store, runner: agent_mod.Agent
) -> None:
    """**얼마나 기다렸나가 기록에 남는다** (C3 `run_waiting`·`run_resumed`).

    타이머는 짝이 되는 칸이 `until`이고, 깨운 까닭은 `timer`다. 하트비트의 `waiting[]`은 지금
    모습이라 깨어난 뒤에는 사라지므로 **이 두 줄만이** 기다림을 남긴다 (CON-01).
    """
    found = waiting_on_a_timer(center, store, runner)
    path = log_path(runner.settings.data_path, found.run_id)

    waiting = [one.data for one in RunLog.read(path) if one.kind == "run_waiting"]
    assert len(waiting) == 1
    assert waiting[0]["waiting_for"] == "timer" and waiting[0]["until"]
    assert "request_id" not in waiting[0], "결재가 아니다"

    time.sleep(3.2)
    assert runner.wake_due() == 1
    assert found.join(WAIT_S)

    resumed = [one.data for one in RunLog.read(path) if one.kind == "run_resumed"]
    assert [one["reason"] for one in resumed] == ["timer"]
    assert resumed[0]["after_s"] >= 3.0, f"3초를 기다렸다: {resumed[0]}"
    # 타이머를 지나 결재를 기다리므로 **다시 기다림 줄**이 생긴다 (짝이 맞는다).
    kinds = [one.kind for one in RunLog.read(path) if one.kind.startswith("run_")]
    assert kinds == ["run_started", "run_waiting", "run_resumed", "run_waiting"]


def test_a_full_runner_wakes_it_next_cycle_instead(
    center: TestClient, store: Store, runner: agent_mod.Agent
) -> None:
    """**자리가 없으면 깨우지 않는다** — 상한을 넘겨 돌지 않는다 (ADR-0061 §2).

    기다리는 실행은 자리를 놓았으므로 깨우면 다시 쥔다. 그래서 기한은 **「그 시각 이후」**이고,
    밀린 것은 `waiting[].until`로 보인다 (CON-12).
    """
    found = waiting_on_a_timer(center, store, runner)
    time.sleep(3.2)
    assert found.due_now() is True

    runner.settings = replace(runner.settings, max_concurrency=0)
    assert runner.free_slots() == 0
    assert runner.wake_due() == 0, "자리가 없으면 깨우지 않는다"
    assert not found.alive

    runner.settings = replace(runner.settings, max_concurrency=3)
    assert runner.wake_due() == 1, "자리가 나면 다음 주기에 깨운다"
    assert found.join(WAIT_S)


def test_a_running_run_is_not_asked(center: TestClient, store: Store, runner: agent_mod.Agent) -> None:
    """**도는 중에는 깨우지 않는다** — 그 실행은 제 루프에서 타이머를 본다 (`Worker._tick`).

    묻는 쪽이 스레드를 또 띄우면 같은 `Run`을 둘이 민다.
    """
    ready_runner(center, store, runner)
    make_job(center)
    runner.tick()
    found = next(iter(runner.workers.values()))
    assert found.due_now() is False
    drain(runner)
    assert runner.wake_due() == 0, "끝난 실행도 깨우지 않는다"
