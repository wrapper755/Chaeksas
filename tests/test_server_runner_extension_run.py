"""확장 태스크가 든 **서버 Bot이 끝까지 돈다** (C13·ADR-0064 — 09-gaps §3-14의 마지막 증명).

**한 줄로 본다**: 실행기가 등록하며 깔린 확장을 보고 → Center가 그것을 C7 자원으로 알고
(모르면 「확장 누락」이 **배포를 막는다**) → 승인·배포·설치 → 작업 지시 → 실행기가 스레드로
돌리며 **확장 수행기를 부른다** → 출력이 변수가 되어 실행이 끝난다.

가짜 확장 하나로 돈다 (`tests/fake_server_extension.py`) — 저장소에 **서버에서 돌 수 있다고
선언한 확장 태스크가 아직 하나도 없다**(내장은 `ui-automation` 하나이고 `ui_task`는 PC 전용이다).
그래서 이 시험이 그 길을 **처음으로** 밟는다.

`test_server_runner_extensions.py`가 거르는 규칙과 사전 점검을 보고, 여기서는 **정말 맞물리나**를
본다 — 조각마다 가짜로 본 것이 이어지는지는 이런 시험만 안다.
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

import center_admin
import fake_server_extension
import pytest
from fastapi.testclient import TestClient

from chaeksas.center.app import create_app
from chaeksas.center.settings import Settings as CenterSettings
from chaeksas.center.storage import Store
from chaeksas.contracts.hashing import MANIFEST_NAME, content_hash_zip
from chaeksas.core.extensions import ExtensionHost
from chaeksas.core.run_log import log_path
from chaeksas.server_runner import agent as agent_mod
from chaeksas.server_runner.center_client import CenterClient
from chaeksas.server_runner.settings import Settings

ADMIN = {"Authorization": "Bearer t-admin"}
AT = "2026-10-16T09:00:00+09:00"
BOT = "doc.summary"
PROCESS_ID = "Proc_doc_summary"
VERSION = "1.0.0"
EXTENSION = "doc-ocr"
WAIT_S = 20.0

#: 확장 태스크 하나로 끝나는 그림 — 사람도, 바깥 앱도 없다.
PROCESS = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:chk="urn:chaeksas:bpmn:1"
                  targetNamespace="urn:chaeksas:test">
  <bpmn:process id="Proc_doc_summary" name="문서 요약" isExecutable="true">
    <bpmn:extensionElements>
      <chk:process>{"run_location": "server", "service_keys": {},
        "extensions": [], "outputs": [], "inputs": []}</chk:process>
    </bpmn:extensionElements>
    <bpmn:startEvent id="Start" />
    <bpmn:serviceTask id="Task_Sum" name="요약">
      <bpmn:extensionElements>
        <chk:task type="sum_task" extension="doc-ocr">{"length": 3}</chk:task>
      </bpmn:extensionElements>
    </bpmn:serviceTask>
    <bpmn:endEvent id="End" />
    <bpmn:sequenceFlow id="f1" sourceRef="Start" targetRef="Task_Sum" />
    <bpmn:sequenceFlow id="f2" sourceRef="Task_Sum" targetRef="End" />
  </bpmn:process>
</bpmn:definitions>
"""

#: **서버에서 돈다고 선언한** 태스크 종류 하나 (ADR-0064 — 그 약속이 `run_locations`다).
#: 런타임도 함께 선언한다 — 서버는 그것을 **띄우지 않으므로** 예약 키가 비어 있어야 한다.
DEFINITION: dict[str, Any] = {
    "schema": 2,
    "id": EXTENSION,
    "version": "1.0.0",
    "name": "문서 인식",
    "publisher": "사내",
    "tier": "internal",
    "api": ">=1,<2",
    "contributes": {
        "task_types": [
            {
                "id": "sum_task",
                "label": "요약",
                "executor": {"entry": "fake_server_extension:ServerTaskExecutor"},
                "run_locations": ["server"],
            }
        ],
        "bot_ui.local_runtimes": [
            {
                "id": "worker",
                "label": "Worker",
                "entry": "doc_ocr.worker:serve",
                "default_port": 8899,
                "health": "/v1/health",
                "token_dir": True,
                "start": "on_demand",
            }
        ],
    },
}


@pytest.fixture(autouse=True)
def _no_calls() -> Iterator[None]:
    fake_server_extension.CALLS.clear()
    yield
    fake_server_extension.CALLS.clear()


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


@pytest.fixture
def key(center: TestClient) -> str:
    response = center.post(
        "/api/v1/center-keys", json={"name": "서버 1", "type": "server_runner"}, headers=ADMIN
    )
    assert response.status_code == 201, response.text
    return str(response.json()["key"])


@pytest.fixture
def host() -> ExtensionHost:
    """가짜 확장을 실은 호스트 — **실행 위치를 쥔다** (`ext.load()`가 짓는 것과 같은 꼴)."""
    found = ExtensionHost(run_location="server")
    loaded = found.add_installed(
        json.dumps(DEFINITION).encode("utf-8"), origin="test", root="fake_server_extension"
    )
    assert loaded is not None and loaded.enabled, found.failures
    return found


@pytest.fixture
def runner(tmp_path: Path, key: str, center: TestClient, host: ExtensionHost) -> agent_mod.Agent:
    settings = Settings(center_url="http://center", name="서버 1", data_path=tmp_path / "runner")
    settings.data_path.mkdir(parents=True, exist_ok=True)
    settings.runs_dir.mkdir(parents=True, exist_ok=True)
    return agent_mod.Agent(
        settings=settings,
        client=CenterClient(base_url="http://center", api_key=key, client=center),
        host=host,
    )


def package_zip() -> bytes:
    """그 그림을 C1 패키지로 싼다 (Studio가 내보내는 것과 같은 모양)."""
    manifest: dict[str, Any] = {
        "schema": 1,
        "kind": "bpm_process",
        "id": BOT,
        "version": VERSION,
        "name": "문서 요약",
        "run_location": "server",
        "entry": "process/main.bpmn",
        "process_id": PROCESS_ID,
        "requires": {
            "extensions": [{"id": EXTENSION, "version": ">=1,<2"}],
            # **실행 위치를 적는다** (C1 R2 — 서버 그림이 쓰는 종류는 서버에서 돌아야 한다).
            "task_types": [{"id": "sum_task", "extension": EXTENSION, "run_locations": ["server"]}],
        },
        "human": {},
        "built": {"by": "studio", "at": AT, "core": "0.1.0", "spec_version": 1},
        "content_hash": "sha256:" + "0" * 64,
    }

    def made(body: str) -> bytes:
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("process/main.bpmn", PROCESS)
            archive.writestr(MANIFEST_NAME, body)
        return out.getvalue()

    with tempfile.TemporaryDirectory() as folder:
        staged = Path(folder) / "p.zip"
        staged.write_bytes(made(json.dumps(manifest, ensure_ascii=False)))
        manifest["content_hash"] = content_hash_zip(staged)
    return made(json.dumps(manifest, ensure_ascii=False))


def ready_runner(center: TestClient, store: Store, runner: agent_mod.Agent) -> None:
    """등록 → 승인 → 배포 → 설치까지 세워 둔다."""
    runner.tick()  # 등록 — 이때 깔린 확장을 보고한다 (C12)

    uploaded = center.post(
        "/api/v1/packages",
        files={"file": ("p.zip", package_zip(), "application/zip")},
        headers=ADMIN,
    )
    assert uploaded.status_code in (200, 201), uploaded.text
    info = dict(uploaded.json())

    center_admin.approve(center, info["id"], info["version"])
    center_admin.deploy(
        center,
        target={"type": "server_runner", "id": runner.server_runner_id},
        bpm_process_id=info["id"],
        version=info["version"],
    )

    runner.tick()  # 공개키·배포를 받아 설치한다
    assert BOT in [one.id for one in runner.installed_bots()]


def drain(runner: agent_mod.Agent, *, rounds: int = 40) -> None:
    deadline = time.monotonic() + WAIT_S
    for _ in range(rounds):
        runner.tick()
        if not runner.workers and not runner.pending_acks:
            return
        if time.monotonic() > deadline:
            raise AssertionError("실행이 끝나지 않았다")
        time.sleep(0.05)


# ─────────────────────────── 한 줄 ───────────────────────────


def test_the_center_knows_the_extension_the_runner_reported(
    center: TestClient, store: Store, runner: agent_mod.Agent
) -> None:
    """**싣지 않으면 배포가 막힌다** — C7이 그 확장을 모르면 「확장 누락」이 배포를 거부한다.

    계약은 처음부터 「C4·C12 보고」라고 적어 두었는데(C7 `installed_on`) Center가 `bot_uis`만
    읽고 있었다 — 서버에만 깔린 확장은 **없는 것**이 되어 멀쩡한 서버 Bot을 배포할 수 없었다.
    """
    runner.tick()

    listed = center.get("/api/v1/resources?type=extension", headers=ADMIN)
    assert listed.status_code == 200, listed.text
    rows = {one["id"]: one for one in listed.json()["items"]}
    assert EXTENSION in rows
    assert rows[EXTENSION]["installed_on"]["hosts"] == 1
    assert rows[EXTENSION]["installed_on"]["by_version"] == {"1.0.0": 1}
    # **기여 목록은 비어 있다** — 그것은 정의가 말하는 것이고 내장·사내 정의는 Center에
    # 오지 않는다 (E2). 보고가 말해 주는 것은 「깔려 있다」까지다.
    assert rows[EXTENSION]["contributes_summary"] == {}
    assert rows[EXTENSION]["tier"] == "builtin"


def test_an_extension_task_runs_to_the_end_on_the_server(
    center: TestClient, store: Store, runner: agent_mod.Agent
) -> None:
    """**확장 수행기가 서버에서 불린다** (ADR-0064 「증명할 것」 다섯째).

    보는 것 셋: 수행기가 **불렸고**, 실행 위치를 `server`로 **받았고**, 런타임 포트는
    **`None`이다**(실행기는 로컬 런타임을 띄우지 않는다).
    """
    ready_runner(center, store, runner)
    assert runner.readiness()[0].ready is True

    made = center.post(
        "/api/v1/jobs",
        json={"bpm_process_id": BOT, "target": {"type": "server_runner"}, "inputs": {}},
        headers=ADMIN,
    )
    assert made.status_code in (200, 201), made.text
    drain(runner)

    assert fake_server_extension.CALLS == [("Task_Sum", "server", None)]

    job = center.get(f"/api/v1/jobs/{made.json()['job_id']}", headers=ADMIN)
    assert job.json()["run_status"] == "success"


def test_the_run_log_says_the_task_ran_without_business_values(
    center: TestClient, store: Store, runner: agent_mod.Agent
) -> None:
    """기록은 **파일이 원본이고**(C3) 업무 값은 거기 없다 (원칙 6)."""
    ready_runner(center, store, runner)
    center.post(
        "/api/v1/jobs",
        json={"bpm_process_id": BOT, "target": {"type": "server_runner"}, "inputs": {}},
        headers=ADMIN,
    )
    drain(runner)

    assert fake_server_extension.CALLS, "수행기가 불리지 않았다"
    files = sorted(runner.settings.runs_dir.glob("*.jsonl"))
    assert len(files) == 1

    text = files[0].read_text(encoding="utf-8")
    assert "세 줄로 줄였습니다" not in text
    rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    assert rows[0]["kind"] == "run_started" and rows[-1]["kind"] == "run_finished"
    # **파일 이름이 그 실행 이름이다** (C3) — 보내는 쪽·BUI-02가 그것으로 찾는다.
    assert log_path(runner.settings.data_path, str(rows[0]["run_id"])) == files[0]
