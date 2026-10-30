"""C5 §가상 직원 — 사람이 아닌 업무 주체 (ADR-0085).

| 보는 것 | 왜 |
| --- | --- |
| 접수 BPM 프로세스에 **결재 없는 일괄 기동**(C14 B16)이 있으면 묶이지 않는다 | 무인 승인은 없다 (ADR-0079) |
| 묶인 뒤 **새 판**도 그것이 있으면 배포되지 않는다 | 묶을 때만 보면 다음 판이 빠져나간다 |
| 대리 답용 키는 **감독하는 것만** 읽는다 | 키가 새도 남의 가상 직원이 보이지 않는다 (ADR-0081) |
| 일괄·자식은 **읽을 때** 잇는다 | 저장하면 실행이 오갈 때마다 낡는다 |
"""

from __future__ import annotations

import io
import json
import tempfile
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import center_admin
import pytest
from fastapi.testclient import TestClient

from chaeksas.center.app import create_app
from chaeksas.center.settings import Settings as CenterSettings
from chaeksas.center.storage import Store, dumps
from chaeksas.contracts.hashing import MANIFEST_NAME, content_hash_zip

ADMIN = {"Authorization": "Bearer t-admin"}
READ = {"Authorization": "Bearer t-read"}
AT = "2026-10-20T09:00:00+09:00"
INTAKE = "fx24-batch-intake"
ROOT = Path(__file__).resolve().parent.parent
#: 결재를 지나 반복 위임하는 접수 BPM 프로세스 — 업무 예제 그대로다.
GATED = (ROOT / "docs/08-business-examples/bpmn/fx24_batch_intake.bpmn").read_text(encoding="utf-8")
#: **결재 없이** 목록으로 바로 반복 위임한다 — B16이 걸린다.
UNGATED = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" xmlns:chk="urn:chaeksas:bpmn:1" id="D">
  <bpmn:process id="Proc_fx24_batch_intake" isExecutable="true">
    <bpmn:extensionElements><chk:process>{"run_location": "server"}</chk:process></bpmn:extensionElements>
    <bpmn:startEvent id="Start" />
    <bpmn:callActivity id="Call_Batch" calledElement="Proc_item"><bpmn:extensionElements>
      <chk:call>{"delegate": {"bpm_process_id": "fx25-batch-item"}, "input": {"번호": "건"}, "output": {}}</chk:call>
      <chk:loop>{"collection": "인입", "item": "건", "collect_into": "끝"}</chk:loop>
    </bpmn:extensionElements><bpmn:multiInstanceLoopCharacteristics isSequential="true" /></bpmn:callActivity>
    <bpmn:endEvent id="End" />
    <bpmn:sequenceFlow id="f1" sourceRef="Start" targetRef="Call_Batch" />
    <bpmn:sequenceFlow id="f2" sourceRef="Call_Batch" targetRef="End" />
  </bpmn:process>
</bpmn:definitions>
"""


@pytest.fixture
def store() -> Iterator[Store]:
    found = Store(Path(":memory:"))
    yield found
    found.close()


@pytest.fixture
def center(store: Store, tmp_path: Path) -> Iterator[TestClient]:
    settings = CenterSettings(admin_token="t-admin", read_token="t-read", package_dir=tmp_path / "pkg")
    with TestClient(create_app(settings, store=store)) as found:
        yield found


def package_zip(*, bot: str, bpmn: str, version: str = "1.0.0", where: str = "server") -> bytes:
    manifest: dict[str, Any] = {
        "schema": 1, "kind": "bpm_process", "id": bot, "version": version, "name": bot,
        "run_location": where, "entry": "process/main.bpmn", "process_id": "Proc_fx24_batch_intake",
        "requires": {}, "human": {},
        "built": {"by": "studio", "at": AT, "core": "0.1.0", "spec_version": 1},
        "content_hash": "sha256:" + "0" * 64,
    }

    def made(body: str) -> bytes:
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("process/main.bpmn", bpmn)
            archive.writestr(MANIFEST_NAME, body)
        return out.getvalue()

    with tempfile.TemporaryDirectory() as folder:
        staged = Path(folder) / "p.zip"
        staged.write_bytes(made(json.dumps(manifest, ensure_ascii=False)))
        manifest["content_hash"] = content_hash_zip(staged)
    return made(json.dumps(manifest, ensure_ascii=False))


def approved(center: TestClient, **kw: Any) -> dict[str, Any]:
    made = center.post("/api/v1/packages", files={"file": ("p.zip", package_zip(**kw), "application/zip")},
                       headers=ADMIN)
    assert made.status_code in (200, 201), made.text
    info = dict(made.json())
    center_admin.approve(center, info["id"], info["version"])
    return info


def register(center: TestClient, **over: Any) -> Any:
    body = {"id": "finance-intake", "name": "재무 가상 직원", "supervisors": [" 김감독 "], "intake": INTAKE, **over}
    return center.post("/api/v1/virtual-workers", json=body, headers=ADMIN)


def relay(center: TestClient, person: str) -> dict[str, str]:
    made = center.post("/api/v1/center-keys", json={"name": "chaeksachat", "type": "relay"}, headers=ADMIN)
    from urllib.parse import quote  # noqa: PLC0415

    return {"Authorization": f"Bearer {made.json()['key']}", "X-CHK-On-Behalf-Of": quote(person)}


# ─────────────────────────── 관문 ───────────────────────────


def test_a_gated_intake_bot_is_bound(center: TestClient) -> None:
    approved(center, bot=INTAKE, bpmn=GATED)
    made = register(center)
    assert made.status_code == 201, made.text
    body = made.json()
    assert (body["supervisors"], body["state"], body["batches"]) == (["김감독"], "active", [])
    again = register(center)
    assert again.status_code == 409 and again.json()["code"] == "id_conflict"


def test_an_intake_bot_that_starts_a_batch_without_approval_is_refused(center: TestClient) -> None:
    """**무인 일괄 기동은 묶이지 않는다** — Center가 저장된 그림을 읽어 B16을 본다."""
    approved(center, bot=INTAKE, bpmn=UNGATED)
    refused = register(center)
    assert refused.status_code == 422 and refused.json()["code"] == "intake_not_gated"
    assert "1.0.0" in refused.json()["detail"]["violations"]


@pytest.mark.parametrize(("setup", "code"), [("none", "intake_unknown"), ("pc", "intake_not_server")])
def test_an_intake_bot_must_be_an_approved_server_bot(
    center: TestClient, setup: str, code: str
) -> None:
    if setup == "pc":
        approved(center, bot=INTAKE, bpmn=GATED, where="pc")
    refused = register(center)
    assert refused.status_code == 422 and refused.json()["code"] == code


def test_a_new_version_without_the_gate_is_not_deployed(center: TestClient) -> None:
    """묶인 뒤 **새 판**으로 결재 없는 일괄 기동이 들어오는 길도 막는다 (409)."""
    approved(center, bot=INTAKE, bpmn=GATED)
    assert register(center).status_code == 201
    later = approved(center, bot=INTAKE, bpmn=UNGATED, version="1.1.0")
    runner = center.post("/api/v1/center-keys", json={"name": "서버", "type": "server_runner"}, headers=ADMIN)
    registered = center.post(
        "/api/v1/server-runner/register",
        json={"schema": 1, "machine_id": "b2" * 32, "name": "서버", "os": "Linux",
              "versions": {"server_runner": "0.1.0", "core": "0.1.0"}, "max_concurrency": 3},
        headers={"Authorization": f"Bearer {runner.json()['key']}"},
    )
    refused = center_admin.deploy(
        center,
        target={"type": "server_runner", "id": registered.json()["server_runner_id"]},
        bpm_process_id=INTAKE,
        version=later["version"],
        expect=None,
    )
    assert refused.status_code == 409 and refused.json()["code"] == "intake_not_gated", refused.text


# ─────────────────────────── 읽기 ───────────────────────────


def test_a_relay_key_reads_only_what_its_person_supervises(center: TestClient) -> None:
    approved(center, bot=INTAKE, bpmn=GATED)
    register(center)
    mine = relay(center, "김감독")
    assert [one["id"] for one in center.get("/api/v1/virtual-workers", headers=mine).json()] == ["finance-intake"]
    assert center.get("/api/v1/virtual-workers/finance-intake", headers=mine).status_code == 200
    other = relay(center, "박감독")
    assert center.get("/api/v1/virtual-workers", headers=other).json() == []
    assert center.get("/api/v1/virtual-workers/finance-intake", headers=other).status_code == 404
    asked = center.get("/api/v1/virtual-workers", params={"supervisor": "박감독"}, headers=mine)
    assert asked.status_code == 403 and asked.json()["code"] == "not_supervisor"
    # 실행 목록은 여전히 못 읽는다 (ADR-0081) — 진행은 이 자리의 최근 일괄로 본다.
    assert center.get("/api/v1/runs", headers=mine).status_code == 403


def test_batches_and_children_are_joined_when_read(center: TestClient, store: Store) -> None:
    """일괄 = 접수 BPM 프로세스 실행, 자식 = `parent_run_id`가 그 실행인 것 — 읽을 때 센다."""
    approved(center, bot=INTAKE, bpmn=GATED)
    register(center)
    batch, other = "run_20261020_091500_aaaaaa", "run_20261020_091600_bbbbbb"
    rows = [
        (batch, {"bpm_process_id": INTAKE, "status": "success", "started_at": "2026-10-20T09:15:00+09:00"}),
        ("run_20261020_091501_c1", {"bpm_process_id": "fx25-batch-item", "status": "success", "parent_run_id": batch}),
        ("run_20261020_091502_c2", {"bpm_process_id": "fx25-batch-item", "status": "failed", "parent_run_id": batch}),
        (other, {"bpm_process_id": "someone.else", "status": "success"}),
    ]
    with store.tx() as cur:
        for run_id, summary in rows:
            cur.execute(
                "INSERT INTO runs (run_id, owner_key_id, first_seen_at, last_seen_at, summary_json)"
                " VALUES (?, 'ck_00000000', ?, ?, ?)",
                (run_id, AT, AT, dumps(summary)),
            )
        cur.execute(
            "INSERT INTO jobs (job_id, bpm_process_id, version, target_type, target_id, inputs_json, owner,"
            " body_hash, requested_by, requested_at, state) VALUES"
            " ('job_0000aaa1', 'fx25-batch-item', '1.0.0', 'server_runner', '', '{}', 'key:x', 'h', ?, ?, 'accepted'),"
            " ('job_0000aaa2', 'someone.else', '1.0.0', 'server_runner', '', '{}', 'key:x', 'h', 'key', ?, 'accepted')",
            (f"server_bot:{batch}", AT, AT),
        )

    [found] = center.get("/api/v1/virtual-workers/finance-intake", headers=READ).json()["batches"]
    assert (found["run_id"], found["children"], found["children_by_status"]) == (batch, 2, {"success": 1, "failed": 1})
    runs = center.get("/api/v1/runs", params={"virtual_worker": "finance-intake"}, headers=READ).json()["runs"]
    assert sorted(one["run_id"] for one in runs) == sorted(run_id for run_id, _ in rows[:3])
    jobs = center.get("/api/v1/jobs", params={"virtual_worker": "finance-intake"}, headers=READ).json()
    assert [one["job_id"] for one in jobs] == ["job_0000aaa1"]


def test_update_and_remove(center: TestClient) -> None:
    approved(center, bot=INTAKE, bpmn=GATED)
    register(center)
    changed = center.put("/api/v1/virtual-workers/finance-intake",
                         json={"id": "ignored", "name": "재무", "supervisors": ["이감독"], "intake": INTAKE,
                               "state": "stopped"}, headers=ADMIN)
    assert changed.status_code == 200 and changed.json()["id"] == "finance-intake", "경로가 이긴다"
    assert (changed.json()["supervisors"], changed.json()["state"]) == (["이감독"], "stopped")
    assert center.delete("/api/v1/virtual-workers/finance-intake", headers=ADMIN).status_code == 200
    assert center.get("/api/v1/virtual-workers/finance-intake", headers=READ).status_code == 404


def test_writes_need_the_admin_token(center: TestClient) -> None:
    refused = center.post("/api/v1/virtual-workers", json={}, headers=READ)
    assert refused.status_code == 403


# ─────────────────────────── 신원·연동용 키 (ADR-0098) ───────────────────────────


def integration(center: TestClient, *, person: str | None = None) -> dict[str, str]:
    made = center.post("/api/v1/center-keys", json={"name": "nowview", "type": "integration"}, headers=ADMIN)
    assert made.status_code == 201, made.text
    out = {"Authorization": f"Bearer {made.json()['key']}"}
    if person is not None:
        from urllib.parse import quote  # noqa: PLC0415

        out["X-CHK-On-Behalf-Of"] = quote(person)
    return out


def test_an_integration_key_reads_every_virtual_worker(center: TestClient) -> None:
    """회사 시스템이 가상 직원 카드를 그린다 — **전부** 읽고, 사람을 실어도 거르지 않는다."""
    approved(center, bot=INTAKE, bpmn=GATED)
    register(center)
    for headers in (integration(center), integration(center, person="박감독")):
        listed = center.get("/api/v1/virtual-workers", headers=headers)
        assert listed.status_code == 200 and [one["id"] for one in listed.json()] == ["finance-intake"]
        one = center.get("/api/v1/virtual-workers/finance-intake", headers=headers)
        assert one.status_code == 200 and one.json()["batches"] == []
    # **넓히지 않는 것** — 결재(검토 자료)는 그대로 못 읽는다.
    key = integration(center)
    assert center.get("/api/v1/approvals", headers=key).status_code == 403
    # 쓰기는 여전히 관리자만이다.
    assert center.post("/api/v1/virtual-workers", json={}, headers=key).status_code == 403


def test_other_keys_still_cannot_read_virtual_workers(center: TestClient) -> None:
    made = center.post("/api/v1/center-keys", json={"name": "pc-1", "type": "bot_ui"}, headers=ADMIN)
    refused = center.get("/api/v1/virtual-workers", headers={"Authorization": f"Bearer {made.json()['key']}"})
    assert refused.status_code == 403


def test_one_intake_bot_is_shared_by_many_virtual_workers(center: TestClient, store: Store) -> None:
    """**접수 BPM 프로세스 하나를 여러 가상 직원이 쓴다** (ADR-0099) — 어느 쪽 일인지는 작업이 id로 말한다."""
    from chaeksas.center.api.virtual_workers import pick  # noqa: PLC0415
    from chaeksas.center.errors import ApiError  # noqa: PLC0415

    approved(center, bot=INTAKE, bpmn=GATED)
    assert register(center).status_code == 201
    assert pick(store, bot=INTAKE, requested=None) == "finance-intake", "하나뿐이면 적지 않아도 그것이다"
    shared = register(center, id="sales-intake", name="영업 가상 직원", supervisors=["박감독"])
    assert shared.status_code == 201, shared.text
    assert pick(store, bot=INTAKE, requested=None) is None, "여럿인데 고르지 않으면 조용히 고르지 않는다"
    assert pick(store, bot=INTAKE, requested="sales-intake") == "sales-intake"
    for wrong in ("nobody", "finance-intake"):
        with pytest.raises(ApiError) as caught:
            pick(store, bot="someone.else" if wrong == "finance-intake" else INTAKE, requested=wrong)
        assert caught.value.code == "virtual_worker_mismatch"


def test_the_identity_is_read_from_the_registration(center: TestClient, store: Store) -> None:
    """Center가 서버 작업을 내려줄 때 붙이는 값 — **저장하지 않고** 그때 등록에서 읽는다."""
    from chaeksas.center.api.virtual_workers import identity_of  # noqa: PLC0415

    approved(center, bot=INTAKE, bpmn=GATED)
    assert identity_of(store, "finance-intake") is None, "묶이기 전에는 없다"
    assert identity_of(store, None) is None
    register(center)
    found = identity_of(store, "finance-intake")
    assert found is not None
    assert (found.id, found.name, found.supervisors) == ("finance-intake", "재무 가상 직원", ["김감독"])
    center.put("/api/v1/virtual-workers/finance-intake",
               json={"name": "재무", "supervisors": ["이감독"], "intake": INTAKE, "state": "stopped"}, headers=ADMIN)
    changed = identity_of(store, "finance-intake")
    assert changed is not None and changed.supervisors == ["이감독"], "감독자를 바꾸면 다음 작업부터 맞는다"
