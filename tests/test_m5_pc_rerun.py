"""PC 예제 재통과 — **Center 배포 → Bot UI 실행**으로 한 번 더 (M5 조각 15).

로드맵 M5 인수 시험의 두 번째 칸이다: 「PC 예제는 Center 배포 → Bot UI 실행으로 다시 통과」.
M3·M4·M5 묶음에서 **실행 위치가 `pc`인 예제**가 그 대상이고, 목록은 예제에서 읽는다.

Studio 시험 실행(M3·M4·M5 인수 시험)과 **무엇이 다른가**가 이 파일의 요점이다.

| | Studio 시험 실행 | 여기 |
| --- | --- | --- |
| 무엇이 그림을 받나 | 작업 폴더에서 바로 | **서명된 패키지**가 Center를 거쳐 설치된다 (C2·C5) |
| 무엇이 엔진을 도나 | Studio 프로세스 안 (`QTimer`) | **실행기 자식 프로세스** (ADR-0023·0031) |
| 입력은 어디서 | 시험 케이스 | **Center 작업 지시**의 `inputs` (C5) |
| 결재·확인 | 케이스가 답한다 | **제어 파일**(현장) 또는 하트비트(Center, ADR-0038) |
| 무엇을 볼 수 있나 | 변수와 기대값 | **실행 기록**(C3)뿐 — 업무 값은 거기 없다 (원칙 6) |

마지막 줄이 중요하다. **여기서는 기대값을 볼 수 없다** — C3에 업무 값을 남기지 않기 때문이다.
그래서 보는 것은 「그 Bot이 Center를 거쳐 설치되고, 작업으로 시작되고, 끝까지 돌아, 끝났다고
Center에 알렸는가」다. 업무 결과가 맞는지는 Studio 시험 실행이 본다 (같은 그림·같은 엔진이다).

**바깥에 나가지 않는다** — Center는 in-process, 모델·모의 앱은 127.0.0.1이다.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from conftest import FakeCredentials
from fastapi.testclient import TestClient
from stub_model import StubModel

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from chaeksas.admin import keys as keystore  # noqa: E402
from chaeksas.bot_ui.agent import Agent, load_extensions  # noqa: E402
from chaeksas.bot_ui.bots import installed  # noqa: E402
from chaeksas.bot_ui.center_client import CenterClient  # noqa: E402
from chaeksas.bot_ui.settings import Settings as BotUiSettings  # noqa: E402
from chaeksas.bot_ui.store import Store as BotUiStore  # noqa: E402
from chaeksas.center.api.signing import bootstrap_key  # noqa: E402
from chaeksas.center.app import create_app  # noqa: E402
from chaeksas.center.settings import Settings as CenterSettings  # noqa: E402
from chaeksas.center.storage import Store  # noqa: E402
from chaeksas.contracts.bpmn_ext import read_process  # noqa: E402
from chaeksas.contracts.signing import sign  # noqa: E402
from chaeksas.core.run_log import RunLog, log_path  # noqa: E402
from chaeksas.mock_apps import catalog  # noqa: E402
from chaeksas.mock_apps.c11 import SHARED_KEY_ENV  # noqa: E402
from chaeksas.mock_apps.c11 import build as build_mock  # noqa: E402
from chaeksas.studio.packaging import default_name, export  # noqa: E402
from chaeksas.studio.workspace import Workspace  # noqa: E402

DOCS = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples"
EXAMPLES = DOCS / "bpmn"

ADMIN_TOKEN = "t-admin"
ADMIN = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
SIGN_PASS = "열쇠말"
SIGNED_AT = "2026-10-07T09:00:00+09:00"
CENTER_URL = "http://testserver"

#: 모의 앱이 받는 키 하나 (`samples/README.md`).
DEV_KEY = "chk_svc_pcrerunkey00000000000000000000000000"


def pc_examples() -> list[str]:
    """실행 위치가 `pc`인 예제 — **BPMN에서 읽는다**.

    README의 묶음 표에는 「PC 예제」라고만 적혀 있다. 어느 것이 PC인지는 그림이 안다
    (`chk:process.run_location`) — 사람이 옮겨 적으면 어긋난다.
    """
    found = []
    for path in sorted(EXAMPLES.glob("*.bpmn")):
        process = read_process(path.read_text(encoding="utf-8"))
        if process.info.run_location == "pc":
            found.append(path.stem)
    return found


PC = pc_examples()

#: 화면을 만지는 예제와 **무엇이 있어야 도는가**. 없으면 건너뛴다 (M4 인수 시험과 같은 자리).
NEEDS_BROWSER = {"bx04_tax_invoice_issue", "bx14_supplier_portal_orders", "fx15_web_form", "fx16_web_review_field"}
NEEDS_DESKTOP = {"bx17_erp_po_entry", "fx05_desktop_autonomous", "bx36_legacy_migration"}

#: 작업 지시로 줄 입력 — 케이스의 `inputs`를 그대로 쓴다 (C5 `inputs`).
#: 비어 있는 예제는 작업만 만들면 된다.
def case_inputs(example: str) -> dict[str, Any]:
    path = DOCS / "cases" / f"{example}.cases.json"
    if not path.is_file():
        return {}
    cases = json.loads(path.read_text(encoding="utf-8")).get("cases") or []
    wanted = next((one for one in cases if not one.get("manual")), None)
    return dict((wanted or {}).get("inputs") or {})


def field_answers(example: str) -> dict[str, dict[str, Any]]:
    """현장에서 답할 것 — 케이스의 `approvals`를 그대로 쓴다 (노드 id → 답)."""
    path = DOCS / "cases" / f"{example}.cases.json"
    if not path.is_file():
        return {}
    cases = json.loads(path.read_text(encoding="utf-8")).get("cases") or []
    wanted = next((one for one in cases if not one.get("manual")), None)
    return dict((wanted or {}).get("approvals") or {})


# ─────────────────────────── 판 깔기 ───────────────────────────


@pytest.fixture
def admin_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """`chk-admin`의 개인키가 사는 곳 — 임시 폴더다 (개발 PC를 건드리지 않는다)."""
    home = tmp_path / "admin"
    monkeypatch.setenv(keystore.PASSPHRASE_ENV, SIGN_PASS)
    monkeypatch.setenv(f"{keystore.ENV_PREFIX}DATA_DIR", str(home))
    return home


@pytest.fixture(scope="session")
def mock_apps() -> Iterator[dict[str, str]]:
    """모의 C11 앱들을 한 포트에 띄운다 (`samples/mock_apps`).

    PC 예제 중 BX-36이 `crm`을 쓴다. **확장이 Center에 없으면 배포가 막히므로**(C7 누락 검사)
    서비스 앱을 등록해 그 확장을 알려야 한다 — 사내 확장의 정의는 Center에 없고 manifest의
    `extension` 칸이 출처다.
    """
    from fastapi import FastAPI  # noqa: PLC0415

    os.environ[SHARED_KEY_ENV] = DEV_KEY
    root = FastAPI(title="모의 서비스 앱 (PC 재통과)")
    for one in catalog.C11_APPS:
        root.mount(f"/{one.app_id}", build_mock(one).app)
    server = uvicorn.Server(uvicorn.Config(root, host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started, "모의 앱이 뜨지 않았다"
    base = f"http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}"
    yield {one.app_id: f"{base}/{one.app_id}" for one in catalog.C11_APPS}
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture
def center(tmp_path: Path, admin_home: Path, mock_apps: dict[str, str]) -> Iterator[tuple[TestClient, Any]]:
    """진짜 Center + 첫 Admin 공개키 + 등록된 모의 앱들. `(client, 서명 키)`."""
    store = Store(tmp_path / "center.sqlite3")
    settings = CenterSettings(
        db_path=tmp_path / "center.sqlite3", package_dir=tmp_path / "packages", admin_token=ADMIN_TOKEN
    )
    with TestClient(create_app(settings, store=store)) as client:
        key = keystore.create(label="PC 재통과")
        bootstrap_key(store, public_key=key.public_bytes(), label="PC 재통과")
        for app_id, base_url in mock_apps.items():
            answer = client.post(
                "/api/v1/resources/service-apps", json={"base_url": base_url}, headers=ADMIN
            )
            assert answer.status_code < 400, f"{app_id}: {answer.text}"
        yield client, key
    store.close()


@pytest.fixture
def model() -> Iterator[StubModel]:
    """AI 태스크가 있는 PC 예제를 위해. 답은 **아무 값**이어도 된다 —
    여기서 보는 것은 업무 결과가 아니라 **배포·실행 한 바퀴**다."""
    with StubModel(lambda wanted, given: None) as made:
        yield made


@pytest.fixture
def agent(
    center: tuple[TestClient, Any], tmp_path: Path, model: StubModel, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Agent]:
    """진짜 Bot UI — Center는 in-process, 실행기는 **진짜 자식 프로세스**다."""
    client, _ = center
    data_dir = tmp_path / "botui"
    monkeypatch.setattr("chaeksas.bot_ui.settings.data_dir", lambda: data_dir)
    key = client.post(
        "/api/v1/center-keys", json={"name": "시험 PC", "type": "bot_ui"}, headers=ADMIN
    ).json()["key"]

    def factory(base_url: str, api_key: str) -> CenterClient:
        return CenterClient(base_url=CENTER_URL, api_key=api_key, client=client)

    # **확장을 싣는다** — 평소 Bot UI와 같다 (`make_agent`). 싣지 않으면 하트비트가 확장을
    # 보고하지 않고, Center가 모르는 확장을 요구하는 Bot은 **배포가 막힌다** (C7 누락 검사).
    host = load_extensions()
    made = Agent(
        settings=BotUiSettings(
            name="재통과 PC", center_url=CENTER_URL, llm_base_url=model.base_url, llm_model="stub"
        ),
        store=BotUiStore.load(tmp_path / "state.json"),
        credentials=FakeCredentials(key),
        client_factory=factory,
        host=host,
        extensions=host.states(),
    )
    yield made
    launcher = made.runner()
    if launcher.running is not None:
        launcher.stop(grace_s=2.0)


def wait_for(check: Any, *, timeout_s: float = 60.0) -> bool:
    until = time.monotonic() + timeout_s
    while time.monotonic() < until:
        if check():
            return True
        time.sleep(0.1)
    return False


# ─────────────────────────── 배포 (C2·C5) ───────────────────────────


def packaged(tmp_path: Path, example: str) -> Path:
    """Studio가 하듯 내보낸다 — 매니페스트는 **그림에서 모은다** (`studio.packaging`)."""
    space = Workspace(tmp_path / "studio" / "workspace").ensure()
    made = space.import_example(EXAMPLES, example)
    return export(made, tmp_path / default_name(made))


def deploy(center: tuple[TestClient, Any], agent: Agent, zip_path: Path) -> dict[str, Any]:
    """업로드 → **승인 서명** → **배포 서명** → 하트비트로 설치까지 (C2 V1~V7).

    서명이 유일한 관문이다 — 관리자 토큰만으로는 아무것도 배포되지 않는다.
    """
    client, key = center
    answer = client.post(
        "/api/v1/packages",
        files={"file": (zip_path.name, zip_path.read_bytes(), "application/zip")},
        headers=ADMIN,
    )
    assert answer.status_code in (200, 201), answer.text
    info = dict(answer.json())

    signer = keystore.load(key, passphrase=SIGN_PASS)
    approve = sign(
        {
            "kind": "package",
            "id": info["id"],
            "version": info["version"],
            "content_hash": info["content_hash"],
        },
        signer,
        signed_at=SIGNED_AT,
    )
    # 승인은 **봉투를 그대로** 올린다 (C2 — Center가 짓지 않는다).
    answer = client.put(
        f"/api/v1/packages/{info['id']}/{info['version']}/signature",
        json=approve.to_json_dict(),
        headers=ADMIN,
    )
    assert answer.status_code < 400, answer.text

    # Bot UI가 등록되어야 배포 대상이 생긴다 (C4 — 키 하나 ↔ PC 하나).
    assert agent.beat() is not None
    assert agent.bot_ui_id, "등록되지 않았다"

    envelope = sign(
        {
            "kind": "deployment",
            "deployment_id": "dep_" + re.sub(r"[^0-9a-f]", "", info["content_hash"])[:8],
            "target": {"type": "bot_ui", "id": agent.bot_ui_id},
            "bpm_process_id": info["id"],
            "version": info["version"],
            "content_hash": info["content_hash"],
        },
        signer,
        signed_at=SIGNED_AT,
    )
    answer = client.post("/api/v1/deployments", json=envelope.to_json_dict(), headers=ADMIN)
    assert answer.status_code < 400, answer.text

    agent.beat()  # 배포가 내려와 설치된다
    from chaeksas.bot_ui.settings import data_dir  # noqa: PLC0415

    found = [one for one in installed(data_dir()) if one.id == info["id"]]
    assert found, f"{info['id']}가 설치되지 않았다 (배치 결정: {agent.store.state.pending_deployments})"
    return info


def dispatch(center: tuple[TestClient, Any], agent: Agent, info: dict[str, Any], inputs: dict[str, Any]) -> str:
    """Center 작업 지시 하나 → 하트비트로 받아 실행기를 띄운다 (C5·C4)."""
    client, _ = center
    answer = client.post(
        "/api/v1/jobs",
        json={
            "bpm_process_id": info["id"],
            "target": {"type": "bot_ui", "id": agent.bot_ui_id},
            "inputs": inputs,
        },
        headers=ADMIN,
    )
    assert answer.status_code in (200, 201), answer.text
    job_id = str(answer.json()["job_id"])
    agent.beat()  # 작업을 받아 대기열에 넣는다 (C4 ack)
    # **실행기를 띄우는 것은 `pump()`다** — 트레이의 주기가 부르는 것과 같다 (ADR-0031).
    assert wait_for(lambda: _pumped(agent)), "실행기가 뜨지 않았다"
    return job_id


def _pumped(agent: Agent) -> bool:
    agent.pump()
    return agent.runner().running is not None


def pumping(agent: Agent, check: Any, *, timeout_s: float = 60.0) -> bool:
    """`pump()`를 돌리며 기다린다 — **기다리는 것은 기록 파일에서 읽힌다** (ADR-0031).

    Bot UI는 실행기를 기다리지 않는다. 올라오는 것은 실행 기록이고, 그것을 읽는 자리가
    `pump()`다 (트레이의 주기가 부르는 것과 같다).
    """
    until = time.monotonic() + timeout_s
    while time.monotonic() < until:
        agent.pump()
        if check():
            return True
        time.sleep(0.1)
    return False


def answer_everything(agent: Agent, answers: dict[str, dict[str, Any]], *, timeout_s: float = 60.0) -> int:
    """현장 결재·확인에 답한다 — **제어 파일로** (ADR-0031).

    케이스가 노드 id로 적어 둔 답을 쓴다. 폼이 없는 확인은 `{"decision": "approve"}`다.
    """
    given = 0
    running = agent.runner().running
    assert running is not None
    until = time.monotonic() + timeout_s
    while time.monotonic() < until and running.alive:
        agent.pump()
        for asked in running.pendings:
            body = answers.get(asked.node_id) or {"decision": "approve"}
            running.answer(asked.request_id, dict(body), answered_by="시험")
            given += 1
        time.sleep(0.1)
    return given


def finished(agent: Agent, *, timeout_s: float = 90.0) -> tuple[str, list[Any]]:
    """실행기가 끝날 때까지 기다리고 `(끝 상태, 실행 기록)`."""
    from chaeksas.bot_ui.settings import data_dir  # noqa: PLC0415

    running = agent.runner().running
    assert running is not None
    assert wait_for(lambda: not running.alive, timeout_s=timeout_s), "실행기가 끝나지 않았다"
    agent.pump()
    return running.finished, list(RunLog.read(log_path(data_dir(), running.run_id)))


# ─────────────────────────── 묶음 ───────────────────────────

#: 아직 **돌리지는** 못하는 예제와 그 이유. 조용히 빼면 묶음이 거짓말을 한다.
#:
#: 화면을 만지는 일곱은 **배포·설치까지는 여기서 보고**(아래 첫 시험), 돌리는 것은 아직이다 —
#: 가짜 앱·브라우저·**화면 등록**(C9)을 깔아야 하고 그 판은 M4 인수 시험이 가지고 있다
#: (`tests/test_m4_acceptance.py`의 `desktop_host`·페이지 등록). 거기서 **실행 자체는 초록**이다.
#: 여기서 새로운 것은 **배포 길**이고 그것은 여덟 개 모두 본다.
_SCREEN_WHY = (
    "화면 준비(가짜 앱·브라우저·C9 화면 등록)를 이 묶음이 아직 갖추지 않았다 — "
    "배포·설치는 여기서 보고, 실행 자체는 M4 인수 시험이 본다"
)
REMAINING: dict[str, str] = {one: _SCREEN_WHY for one in sorted(NEEDS_BROWSER | NEEDS_DESKTOP)}

#: 배포하고 **끝까지 돌리는** 예제 — 화면이 필요 없는 것들이다.
GREEN = [one for one in PC if one not in REMAINING]


def test_the_pc_examples_are_read_from_the_drawings() -> None:
    """어느 것이 PC 예제인지 **그림이 정한다** — 사람이 옮겨 적지 않는다."""
    assert len(PC) == 8, PC
    assert set(REMAINING) <= set(PC), f"남은 목록에 PC 밖 예제가 있다: {set(REMAINING) - set(PC)}"
    # **아무것도 안 돌리는** 일을 막는다 — 끝까지 도는 것이 하나는 있어야 한다.
    assert GREEN, "끝까지 돌리는 예제가 없다"
    assert len(GREEN) == 1, f"끝까지 도는 것이 {len(GREEN)}개다 — 늘면 REMAINING에서 지운다: {GREEN}"


@pytest.mark.parametrize("example", sorted(REMAINING))
def test_a_remaining_example_at_least_gets_deployed(example: str) -> None:
    """돌리지 못하는 것도 **왜인지 적혀 있다.** 배포는 위 시험이 여덟 개 모두 본다."""
    assert REMAINING[example], example
    assert example in NEEDS_BROWSER | NEEDS_DESKTOP, f"{example}: 사유가 화면 때문이 아니다"


def test_the_examples_ask_for_the_extension_version_we_actually_have() -> None:
    """예제의 `requires.extensions` 범위가 **설치된 확장**을 받아들이는가.

    어긋나면 Center가 배포를 막는다 (C7 누락 검사 — `version_mismatch`). 예제에는
    프로토타입 시절의 `>=0.4,<0.5`가 남아 있었고 실제 내장 확장은 0.1.0이라, **여섯 예제가
    모두 배포되지 않았다.** 여기서 둘을 대조해 다시 어긋나지 않게 한다.
    """
    from chaeksas.contracts._semver import satisfies  # noqa: PLC0415

    host = load_extensions()
    have = {one.id: one.version for one in host.states()}
    assert "ui-automation" in have, f"내장 확장이 켜지지 않았다 (켜진 것: {sorted(have)})"
    for example in PC:
        process = read_process((EXAMPLES / f"{example}.bpmn").read_text(encoding="utf-8"))
        for need in process.info.extensions:
            if need.id not in have:
                continue
            assert satisfies(have[need.id], need.version), (
                f"{example}: {need.id} {need.version}를 요구하는데 깔린 것은 {have[need.id]}다"
            )


@pytest.mark.parametrize("example", PC)
def test_every_pc_example_deploys_and_installs(
    center: tuple[TestClient, Any], agent: Agent, tmp_path: Path, example: str
) -> None:
    """**여덟 개 모두** Center를 거쳐 설치된다 — 화면이 없어도 여기까지는 돈다.

    돌리는 것(아래)은 브라우저·데스크톱이 있어야 하지만, **서명·승인·배포·설치**(C2 V1~V7)는
    환경과 무관하다. 가르지 않으면 브라우저 없는 PC에서 그 길이 하나도 시험되지 않는다.
    """
    client, _ = center
    info = deploy(center, agent, packaged(tmp_path, example))
    found = client.get("/api/v1/deployments", headers=ADMIN).json()
    rows = [one for one in found if one["bpm_process_id"] == info["id"]]
    assert rows, f"{example}: 배포 목록에 없다"
    # **서명자·유효 기간은 봉투에서 읽는다** (Center가 짓지 않는다, C5).
    assert rows[0].get("signed_by"), rows[0]
    # 배치 결정은 **쌓여 있다가 하트비트로** 올라간다 (C4 — 한 주기만 올라오는 값이다).
    # 거부가 하나도 없어야 한다 (사유가 붙었다면 V1~V7 중 무엇에 걸린 것이다).
    results = {one.result: one.reason for one in agent.store.state.pending_deployments}
    assert set(results) == {"applied"}, results


@pytest.mark.parametrize("example", GREEN)
def test_a_pc_example_deploys_and_runs(
    center: tuple[TestClient, Any], agent: Agent, tmp_path: Path, example: str
) -> None:
    """**Center 배포 → 작업 지시 → 실행기 → 끝** 한 바퀴.

    업무 값을 보지 않는다 (C3에 없다) — 보는 것은 설치·시작·완료와 **Center가 그것을 아는가**다.
    """
    client, _ = center
    info = deploy(center, agent, packaged(tmp_path, example))
    job_id = dispatch(center, agent, info, case_inputs(example))

    running = agent.runner().running
    assert running is not None, "실행기가 뜨지 않았다"
    answer_everything(agent, field_answers(example))
    status, events = finished(agent)
    # 실행기가 쓰는 말은 `success`다 — Bot UI가 그것을 작업 결과 `finished`로 옮긴다 (C4).
    assert status == "success", f"{example}: {status} (기록: {[e.kind for e in events]})"

    kinds = [e.kind for e in events]
    assert kinds[0] == "run_started" and kinds[-1] == "run_finished", kinds
    # **업무 값은 기록에 없다** (원칙 6) — 그것을 여기서 한 번 더 지킨다.
    body = json.dumps([e.to_json_dict() for e in events], ensure_ascii=False)
    assert "확인됨" not in body, "실행 기록에 업무 변수 이름·값이 새어 나갔다"

    # Center가 끝난 것을 안다 — 하트비트로 기록이 올라가고 작업에 결과가 적힌다 (C3·C4).
    # **실행의 성패는 작업 상태가 아니다** — `run_status`에만 적힌다 (C3가 원본이다).
    agent.beat()
    job = client.get(f"/api/v1/jobs/{job_id}", headers=ADMIN).json()
    assert job["run_status"] == "finished", job


def test_a_confirmation_is_answered_in_the_field(
    center: tuple[TestClient, Any], agent: Agent, tmp_path: Path
) -> None:
    """확인은 **늘 현장**이다 (ADR-0038) — Center 결재함으로 올라가지 않는다.

    FX-19가 가장 작은 PC 예제다 (확인 하나 + 스크립트).
    """
    client, _ = center
    info = deploy(center, agent, packaged(tmp_path, "fx19_manual_task_pc"))
    dispatch(center, agent, info, {})
    running = agent.runner().running
    assert running is not None
    assert pumping(agent, lambda: bool(running.pendings)), "확인이 올라오지 않았다"
    (asked,) = running.pendings
    assert asked.where == "field", "확인은 현장에서 답한다"
    assert not client.get("/api/v1/approvals", headers=ADMIN).json(), "확인은 Center로 올라가지 않는다"

    running.answer(asked.request_id, {"decision": "approve"}, answered_by="시험")
    status, _ = finished(agent)
    assert status == "success"
