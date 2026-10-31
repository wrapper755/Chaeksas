"""PC 예제 재통과 — **Center 배포 → PC 실행기 실행**으로 한 번 더 (M5 조각 15).

로드맵 M5 인수 시험의 두 번째 칸이다: 「PC 예제는 Center 배포 → PC 실행기 실행으로 다시 통과」.
M3·M5 묶음에서 **실행 위치가 `pc`인 예제**가 그 대상이고, 목록은 예제에서 읽는다.

Studio 시험 실행(M3·M5 인수 시험)과 **무엇이 다른가**가 이 파일의 요점이다.

| | Studio 시험 실행 | 여기 |
| --- | --- | --- |
| 무엇이 그림을 받나 | 작업 폴더에서 바로 | **서명된 패키지**가 Center를 거쳐 설치된다 (C2·C5) |
| 무엇이 엔진을 도나 | Studio 프로세스 안 (`QTimer`) | **실행 프로세스** (ADR-0023·0031) |
| 입력은 어디서 | 시험 케이스 | **Center 작업 지시**의 `inputs` (C5) |
| 결재·확인 | 케이스가 답한다 | **제어 파일**(현장) 또는 하트비트(Center, ADR-0038) |
| 무엇을 볼 수 있나 | 변수와 기대값 | **실행 기록**(C3)뿐 — 업무 값은 거기 없다 (원칙 6) |

마지막 줄이 중요하다. **여기서는 기대값을 볼 수 없다** — C3에 업무 값을 남기지 않기 때문이다.
그래서 보는 것은 「그 BPM 프로세스가 Center를 거쳐 설치되고, 작업으로 시작되고, 끝까지 돌아, 끝났다고
Center에 알렸는가」다. 업무 결과가 맞는지는 Studio 시험 실행이 본다 (같은 그림·같은 엔진이다).

**바깥에 나가지 않는다** — Center는 in-process, 모델·모의 앱은 127.0.0.1이다.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import FakeCredentials
from fastapi.testclient import TestClient
from stub_model import StubModel

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from center_admin import approve, deploy_id  # noqa: E402
from consumers import enroll  # noqa: E402
from waiting import wait_for  # noqa: E402

from chaeksas.bot_ui.agent import Agent, load_extensions  # noqa: E402
from chaeksas.bot_ui.center_client import CenterClient  # noqa: E402
from chaeksas.bot_ui.settings import Settings as BotUiSettings  # noqa: E402
from chaeksas.bot_ui.store import Store as BotUiStore  # noqa: E402
from chaeksas.center.app import create_app  # noqa: E402
from chaeksas.center.settings import Settings as CenterSettings  # noqa: E402
from chaeksas.center.storage import Store  # noqa: E402
from chaeksas.contracts.bpmn_ext import read_process  # noqa: E402
from chaeksas.core.packages import installed  # noqa: E402
from chaeksas.core.run_log import RunLog, log_path  # noqa: E402
from chaeksas.mock_apps import catalog  # noqa: E402
from chaeksas.mock_apps.c11 import build as build_mock  # noqa: E402
from chaeksas.studio.packaging import default_name, export  # noqa: E402
from chaeksas.studio.workspace import Workspace  # noqa: E402

DOCS = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples"
EXAMPLES = DOCS / "bpmn"

ADMIN_TOKEN = "t-admin"
ADMIN = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
CENTER_URL = "http://testserver"

#: 모의 앱이 받는 키 하나 (`samples/README.md`).


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
def center(tmp_path: Path) -> Iterator[TestClient]:
    """진짜 Center + **일꾼으로 들인** 모의 앱들. 서명 키는 Center가 처음 뜰 때 만든다 (ADR-0090).

    **확장이 Center에 없으면 배포가 막히므로**(C7 누락 검사) 모의 앱을 일꾼으로 들여 manifest를 올린다 —
    사내 확장의 정의는 Center에 없고 manifest의 `extension` 칸이 출처다 (ADR-0102 — 주소를 넣는 칸은
    없다). 지금 PC 예제(FX-19)는 확장을 요구하지 않지만, PC 예제가 늘면 그대로 받는다. 여기서는 일꾼을
    **돌리지 않는다** — FX-19는 서비스 앱을 부르지 않는다.
    """
    store = Store(tmp_path / "center.sqlite3")
    settings = CenterSettings(
        db_path=tmp_path / "center.sqlite3", package_dir=tmp_path / "packages", admin_token=ADMIN_TOKEN
    )
    with TestClient(create_app(settings, store=store)) as client:
        manifests = [build_mock(one).service.manifest.to_json_dict() for one in catalog.C11_APPS]
        enroll(
            client,
            topics=[one["app_id"] for one in manifests],
            manifests=manifests,
            name="모의 앱",
            folder=tmp_path / "mock-apps",
        )
        yield client
    store.close()


@pytest.fixture
def model() -> Iterator[StubModel]:
    """AI 태스크가 있는 PC 예제를 위해. 답은 **아무 값**이어도 된다 —
    여기서 보는 것은 업무 결과가 아니라 **배포·실행 한 바퀴**다."""
    with StubModel(lambda wanted, given: None) as made:
        yield made


@pytest.fixture
def agent(
    center: TestClient, tmp_path: Path, model: StubModel, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Agent]:
    """진짜 PC 실행기 — Center는 in-process, 실행기는 **진짜 자식 프로세스**다."""
    client = center
    data_dir = tmp_path / "botui"
    monkeypatch.setattr("chaeksas.bot_ui.settings.data_dir", lambda: data_dir)
    key = client.post(
        "/api/v1/center-keys", json={"name": "시험 PC", "type": "bot_ui"}, headers=ADMIN
    ).json()["key"]

    def factory(base_url: str, api_key: str) -> CenterClient:
        return CenterClient(base_url=CENTER_URL, api_key=api_key, client=client)

    # **확장을 싣는다** — 평소 PC 실행기와 같다 (`make_agent`). 싣지 않으면 하트비트가 확장을
    # 보고하지 않고, Center가 모르는 확장을 요구하는 BPM 프로세스는 **배포가 막힌다** (C7 누락 검사).
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


# ─────────────────────────── 배포 (C2·C5) ───────────────────────────


def packaged(tmp_path: Path, example: str) -> Path:
    """Studio가 하듯 내보낸다 — 매니페스트는 **그림에서 모은다** (`studio.packaging`)."""
    space = Workspace(tmp_path / "studio" / "workspace").ensure()
    made = space.import_example(EXAMPLES, example)
    return export(made, tmp_path / default_name(made))


def deploy(center: TestClient, agent: Agent, zip_path: Path) -> dict[str, Any]:
    """업로드 → **승인** → **배포** → 하트비트로 설치까지 (C2 V1~V7).

    봉투는 Center가 지어 서명하고(ADR-0090), 설치하는 쪽이 하트비트의 `admin_keys`로 다시 본다.
    """
    client = center
    answer = client.post(
        "/api/v1/packages",
        files={"file": (zip_path.name, zip_path.read_bytes(), "application/zip")},
        headers=ADMIN,
    )
    assert answer.status_code in (200, 201), answer.text
    info = dict(answer.json())
    approve(client, info["id"], info["version"], headers=ADMIN)

    # PC 실행기가 등록되어야 배포 대상이 생긴다 (C4 — 키 하나 ↔ PC 하나).
    assert agent.beat() is not None
    assert agent.bot_ui_id, "등록되지 않았다"

    deploy_id(
        client,
        target={"type": "bot_ui", "id": agent.bot_ui_id},
        bpm_process_id=info["id"],
        version=info["version"],
        headers=ADMIN,
    )

    agent.beat()  # 배포가 내려와 설치된다
    from chaeksas.bot_ui.settings import data_dir  # noqa: PLC0415

    found = [one for one in installed(data_dir()) if one.id == info["id"]]
    assert found, f"{info['id']}가 설치되지 않았다 (배치 결정: {agent.store.state.pending_deployments})"
    return info


def dispatch(center: TestClient, agent: Agent, info: dict[str, Any], inputs: dict[str, Any]) -> str:
    """Center 작업 지시 하나 → 하트비트로 받아 실행기를 띄운다 (C5·C4)."""
    client = center
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

    PC 실행기는 실행기를 기다리지 않는다. 올라오는 것은 실행 기록이고, 그것을 읽는 자리가
    `pump()`다 (트레이의 주기가 부르는 것과 같다).
    """
    until = time.monotonic() + timeout_s
    while time.monotonic() < until:
        agent.pump()
        if check():
            return True
        time.sleep(0.1)
    return False


def answer_everything(
    agent: Agent, running: Any, answers: dict[str, dict[str, Any]], *, timeout_s: float = 60.0
) -> int:
    """현장 결재·확인에 답한다 — **제어 파일로** (ADR-0031).

    케이스가 노드 id로 적어 둔 답을 쓴다. 폼이 없는 확인은 `{"decision": "approve"}`다.

    **실행 손잡이를 받아 쓴다** — 여기서 다시 꺼내면 안 된다. `pump()`가 끝난 실행을 거두면
    `agent.runner().running`이 `None`이 되어, 빨리 끝나는 예제에서 손잡이를 잃는다.
    """
    given = 0
    until = time.monotonic() + timeout_s
    while time.monotonic() < until and running.alive:
        agent.pump()
        for asked in running.pendings:
            body = answers.get(asked.node_id) or {"decision": "approve"}
            running.answer(asked.request_id, dict(body), answered_by="시험")
            given += 1
        time.sleep(0.1)
    return given


def finished(agent: Agent, running: Any, *, timeout_s: float = 90.0) -> tuple[str, list[Any]]:
    """실행기가 끝날 때까지 기다리고 `(끝 상태, 실행 기록)`.

    **손잡이를 부르는 쪽이 준다** — 여기서 `agent.runner().running`을 다시 꺼내면 이미 거둬진
    실행에서 `None`을 받는다 (답하는 동안 `pump()`가 거둔다). CI의 Linux가 FX-19에서 잡았다.
    """
    from chaeksas.bot_ui.settings import data_dir  # noqa: PLC0415

    assert wait_for(lambda: not running.alive, timeout_s=timeout_s), "실행기가 끝나지 않았다"
    agent.pump()
    return running.finished, list(RunLog.read(log_path(data_dir(), running.run_id)))


# ─────────────────────────── 묶음 ───────────────────────────

#: 아직 **돌리지는** 못하는 예제와 그 이유. 조용히 빼면 묶음이 거짓말을 한다. **지금은 없다** —
#: 화면을 만지는 PC 예제는 UI 자동화 확장과 함께 걷었다 (ADR-0114).
REMAINING: dict[str, str] = {}

#: 배포하고 **끝까지 돌리는** 예제.
GREEN = [one for one in PC if one not in REMAINING]


def test_the_pc_examples_are_read_from_the_drawings() -> None:
    """어느 것이 PC 예제인지 **그림이 정한다** — 사람이 옮겨 적지 않는다."""
    assert PC == ["fx19_manual_task_pc"], PC
    assert set(REMAINING) <= set(PC), f"남은 목록에 PC 밖 예제가 있다: {set(REMAINING) - set(PC)}"
    # **아무것도 안 돌리는** 일을 막는다 — 끝까지 도는 것이 하나는 있어야 한다.
    assert GREEN == PC, f"끝까지 돌지 못하는 PC 예제가 생겼다 — REMAINING에 사유를 적는다: {set(PC) - set(GREEN)}"


@pytest.mark.parametrize("example", PC)
def test_every_pc_example_deploys_and_installs(
    center: TestClient, agent: Agent, tmp_path: Path, example: str
) -> None:
    """PC 예제가 **모두** Center를 거쳐 설치된다 — **서명·승인·배포·설치**(C2 V1~V7)."""
    client = center
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
    center: TestClient, agent: Agent, tmp_path: Path, example: str
) -> None:
    """**Center 배포 → 작업 지시 → 실행기 → 끝** 한 바퀴.

    업무 값을 보지 않는다 (C3에 없다) — 보는 것은 설치·시작·완료와 **Center가 그것을 아는가**다.
    """
    client = center
    info = deploy(center, agent, packaged(tmp_path, example))
    job_id = dispatch(center, agent, info, case_inputs(example))

    running = agent.runner().running
    assert running is not None, "실행기가 뜨지 않았다"
    answer_everything(agent, running, field_answers(example))
    status, events = finished(agent, running)
    # 실행기가 쓰는 말은 `success`다 — PC 실행기가 그것을 작업 결과 `finished`로 옮긴다 (C4).
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
    center: TestClient, agent: Agent, tmp_path: Path
) -> None:
    """확인은 **늘 현장**이다 (ADR-0038) — Center 결재함으로 올라가지 않는다.

    FX-19가 가장 작은 PC 예제다 (확인 하나 + 스크립트).
    """
    client = center
    info = deploy(center, agent, packaged(tmp_path, "fx19_manual_task_pc"))
    dispatch(center, agent, info, {})
    running = agent.runner().running
    assert running is not None
    assert pumping(agent, lambda: bool(running.pendings)), "확인이 올라오지 않았다"
    (asked,) = running.pendings
    assert asked.where == "field", "확인은 현장에서 답한다"
    assert not client.get("/api/v1/approvals", headers=ADMIN).json(), "확인은 Center로 올라가지 않는다"

    running.answer(asked.request_id, {"decision": "approve"}, answered_by="시험")
    status, _ = finished(agent, running)
    assert status == "success"
