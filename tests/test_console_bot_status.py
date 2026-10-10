"""CON-02 Bot 현황이 읽을 것이 Center에 다 있다 (M6 조각 18).

화면은 **집계를 Center에 두지 않는다** — 패키지(C5)·실행 요약(C3)·보고된 준비 상태(C4)를
콘솔에서 묶어 그린다. Center에 집계 표를 두면 실행이 올 때마다 낡고 원본이 흐려진다
(CON-01의 셈 열과 같은 결).

그래서 파이썬이 볼 수 있는 것은 **재료가 정말 오는가**이고, 그것을 본다. 특히 화면이 **기대는
두 가지**를 못으로 박는다.

1. **실행 목록은 새것부터 온다** — 「최근 20회」를 앞에서 끊어 센다.
2. **셈은 끝난 실행에만 있다** — 도는 중인 실행은 `null`이라 표본에 들어가지 않는다.

타입·빌드는 `web`의 `pnpm typecheck`·`pnpm build`가 본다. **집계 함수(`summarize`)는 TypeScript라
파이썬이 시험하지 못한다** — `web`에 단위 시험 판이 없다 (`docs/09-gaps.md` §4-9).
"""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from chaeksas.center.app import create_app
from chaeksas.center.settings import Settings
from chaeksas.center.storage import Store
from chaeksas.contracts.hashing import content_hash_zip

ROOT = Path(__file__).resolve().parent.parent
CONSOLE = ROOT / "web" / "apps" / "center-console"

ADMIN = {"Authorization": "Bearer t-admin"}
READ = {"Authorization": "Bearer t-read"}

BOT = "fin.invoice"
VERSION = "1.0.0"


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(admin_token="t-admin", read_token="t-read", package_dir=tmp_path / "packages")
    store = Store(tmp_path / "center.db")
    with TestClient(create_app(settings, store=store)) as found:
        yield found
    store.close()


def package(*, requires: dict[str, Any] | None = None) -> bytes:
    """C1 매니페스트가 든 작은 Bot 패키지 (해시는 실제로 계산해 넣는다)."""
    manifest: dict[str, Any] = {
        "schema": 1,
        "kind": "bpm_process",
        "id": BOT,
        "version": VERSION,
        "name": "청구서 처리",
        "run_location": "pc",
        "entry": "process/main.bpmn",
        "process_id": "Proc_invoice",
        "requires": requires or {},
        "human": {},
        "built": {"by": "studio", "at": "2026-10-10T09:00:00+09:00", "core": "0.1.0", "spec_version": 1},
        "content_hash": "sha256:" + "0" * 64,
    }

    def zip_bytes(manifest_json: str) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("process/main.bpmn", "<definitions />")
            archive.writestr("manifest.json", manifest_json)
        return buffer.getvalue()

    staged = zip_bytes(json.dumps(manifest, ensure_ascii=False))
    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder) / "package.zip"
        tmp.write_bytes(staged)
        manifest["content_hash"] = content_hash_zip(tmp)
    return zip_bytes(json.dumps(manifest, ensure_ascii=False))


def upload(client: TestClient, raw: bytes) -> Any:
    found = client.post(
        "/api/v1/packages", files={"file": ("package.zip", raw, "application/zip")}, headers=ADMIN
    )
    assert found.status_code == 201, found.text
    return found.json()


def event(run_id: str, seq: int, kind: str, **data: Any) -> dict[str, Any]:
    return {
        "schema": 1,
        "run_id": run_id,
        "seq": seq,
        "ts": f"2026-10-10T10:{seq:02d}:00+09:00",
        "kind": kind,
        "data": data,
    }


def send_run(
    client: TestClient,
    run_id: str,
    *,
    status: str | None = "success",
    ai_tasks: int = 0,
    replayed: int = 0,
    human: int = 0,
) -> None:
    """실행 하나를 C3로 올린다. `status=None`이면 **아직 도는 중**이다 (셈이 없다)."""
    lines = [
        event(
            run_id,
            1,
            "run_started",
            bpm_process_id=BOT,
            version=VERSION,
            run_location="pc",
            executor="bot_ui",
            mode="deterministic",
            source="job",
        )
    ]
    if status is not None:
        lines.append(
            event(
                run_id,
                2,
                "run_finished",
                status=status,
                duration_s=12.5,
                ai_tasks=ai_tasks,
                replayed_tasks=replayed,
                # C3는 `run_finished`의 셈 **다섯을 모두** 요구한다 (한 칸이 빠지면 줄이 거부된다).
                ui_tasks=0,
                service_calls=0,
                human_requests=human,
            )
        )
    answer = client.post(f"/api/v1/runs/{run_id}/events", json=lines, headers=ADMIN)
    assert answer.status_code == 200, answer.text


def register(client: TestClient, *, readiness: list[dict[str, Any]]) -> None:
    """Bot UI 하나가 등록하고 **준비 상태를 보고한다** (C4 `readiness`)."""
    made = client.post("/api/v1/center-keys", json={"name": "현장 PC", "type": "bot_ui"}, headers=ADMIN)
    key = made.json()["key"]
    pc = {"Authorization": f"Bearer {key}"}
    body = {
        "schema": 1,
        "machine_id": hashlib.sha256(b"pc-1").hexdigest(),
        "name": "재무팀 PC-03",
        "os": "windows-11-23H2",
        "versions": {"bot_ui": "0.1.0", "core": "0.1.0"},
    }
    assert client.post("/api/v1/bot-ui/register", json=body, headers=pc).status_code in (200, 201)
    beat = client.post(
        "/api/v1/bot-ui/heartbeat",
        json={
            "schema": 1,
            "status": "idle",
            "current_run": None,
            "queue": {"max": 20, "items": []},
            "worker": {"state": "off", "restarts": 0},
            "readiness": readiness,
        },
        headers=pc,
    )
    assert beat.status_code == 200, beat.text


# ─────────────────────────── 화면이 열린다 ───────────────────────────


def test_the_nav_opens_the_page() -> None:
    """탐색의 꺼진 줄이 **주소를 갖는다** — 화면이 생겼으니 「아직 없습니다」가 남아 있으면 거짓말이다."""
    shell = (CONSOLE / "components" / "Shell.tsx").read_text(encoding="utf-8")
    assert '{ label: "Bot 현황", href: "/bots" }' in shell
    assert "CON-02는 아직" not in shell
    assert (CONSOLE / "app" / "bots" / "page.tsx").is_file()


# ─────────────────────────── 패키지에서 오는 칸 (C5) ───────────────────────────


def test_the_version_rows_come_from_the_package_listing(client: TestClient) -> None:
    """Bot·버전·실행 위치·상태·**서비스 앱 키 참조**가 한 번 읽어서 다 온다."""
    upload(
        client,
        package(
            requires={
                "service_apps": [
                    {
                        "app_id": "erp",
                        "operations": ["create"],
                        "key_ref": "fin-erp",
                        "task_key_refs": ["fin-erp-ro"],
                    }
                ]
            }
        ),
    )
    rows = client.get("/api/v1/packages?kind=bpm_process", headers=READ).json()
    assert [(one["id"], one["version"], one["run_location"], one["status"]) for one in rows] == [
        (BOT, VERSION, "pc", "candidate")
    ]
    needs = rows[0]["manifest"]["requires"]["service_apps"]
    assert [needs[0]["key_ref"], *needs[0]["task_key_refs"]] == ["fin-erp", "fin-erp-ro"]


def test_a_missing_resource_is_counted_when_read(client: TestClient) -> None:
    """경고 띠의 둘째 줄 — **배포 때 거부될** 버전이다 (C5 `missing_resources`, C7)."""
    upload(client, package(
            requires={
                "toolpacks": [
                    # 해시로 고정한다 (C1 R7) — 고정 없는 툴팩은 업로드 자체가 막힌다.
                    {"id": "excel-tools", "version": "2.0.0", "content_hash": "sha256:" + "1" * 64}
                ]
            }
        ))
    rows = client.get("/api/v1/packages?kind=bpm_process", headers=READ).json()
    missing = rows[0]["missing_resources"]
    # `id`에 판이 붙어 온다 — 화면은 사유(`reason`)까지 툴팁에 적는다.
    assert [(one["type"], one["id"]) for one in missing] == [("toolpack", "excel-tools@2.0.0")]
    assert missing[0]["reason"]


# ─────────────────────────── 실행 요약에서 오는 칸 (C3) ───────────────────────────


def test_the_run_listing_comes_newest_first_with_the_counts(client: TestClient) -> None:
    """화면은 **앞에서 20회를 끊어** 센다 — 순서가 바뀌면 「최근 20회」가 거짓이 된다."""
    send_run(client, "run_20261010_100000_aaaaaa", status="failed")
    send_run(client, "run_20261010_110000_bbbbbb", status="success", ai_tasks=4, replayed=3, human=2)

    found = client.get(f"/api/v1/runs?bpm_process_id={BOT}&limit=200", headers=READ).json()["runs"]
    assert [one["run_id"] for one in found] == [
        "run_20261010_110000_bbbbbb",
        "run_20261010_100000_aaaaaa",
    ], "새것부터 온다"
    assert [one["version"] for one in found] == [VERSION, VERSION], "버전으로 묶을 수 있다"
    newest = found[0]
    assert (newest["status"], newest["ai_tasks"], newest["replayed_tasks"], newest["human_requests"]) == (
        "success",
        4,
        3,
        2,
    )
    assert newest["finished_at"], "「최근 성공」에 쓸 시각이 있다"


def test_a_running_run_has_no_counts_to_average(client: TestClient) -> None:
    """도는 중인 실행은 셈이 **`null`**이다 (C3) — 표본에 넣으면 성공률이 깎인다."""
    send_run(client, "run_20261010_120000_cccccc", status=None)
    found = client.get(f"/api/v1/runs?bpm_process_id={BOT}", headers=READ).json()["runs"]
    assert found[0]["status"] == "running"
    assert found[0]["ai_tasks"] is None
    assert found[0]["human_requests"] is None


def test_runs_of_another_bot_do_not_leak_into_the_sample(client: TestClient) -> None:
    """좁히기가 되는 덕에 **Bot마다** 물어 판이 많은 Bot의 옛 판이 잘리지 않는다."""
    send_run(client, "run_20261010_130000_dddddd")
    found = client.get("/api/v1/runs?bpm_process_id=ops.scan", headers=READ).json()
    assert found["runs"] == []


# ─────────────────────────── 보고된 준비 상태 (C4) ───────────────────────────


def test_readiness_reports_say_which_version_is_blocked(client: TestClient) -> None:
    """「실행 불가」 열과 경고 띠의 첫째 줄 — **PC가 보고한 것**이다 (Center가 판단하지 않는다)."""
    register(
        client,
        readiness=[
            {
                "bpm_process_id": BOT,
                "version": VERSION,
                "ready": False,
                "missing_key_refs": ["fin-erp"],
                "blocked": ["missing_service_app_keys"],
            },
            {"bpm_process_id": "ops.scan", "version": "2.0.0", "ready": True},
        ],
    )
    rows = client.get("/api/v1/bot-uis", headers=READ).json()
    reported = rows[0]["readiness"]
    assert [(one["bpm_process_id"], one["ready"]) for one in reported] == [(BOT, False), ("ops.scan", True)]
    assert reported[0]["blocked"] == ["missing_service_app_keys"]
    assert reported[0]["missing_key_refs"] == ["fin-erp"]
