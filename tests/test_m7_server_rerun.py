"""서버 예제 재통과 — **Center 배포 → 서버 실행기 실행**으로 한 번 더 (M7 인수 시험).

로드맵 M7 인수 시험의 첫 칸이다: 「실행 위치 서버인 업무·기능 예제 전부가 서버 실행기에서
통과」. 대상 목록은 **그림에서 읽는다** (`chk:process.run_location == "server"`) — README의
묶음 표에는 「서버 예제 전부」라고만 적혀 있고, 어느 것이 서버인지는 그림이 안다.

`tests/test_m5_pc_rerun.py`가 PC 쪽에서 같은 꼴을 보므로, 여기서 다른 것만 적는다.

| | PC 재통과 (M5) | 여기 |
| --- | --- | --- |
| 무엇이 엔진을 도나 | Bot UI의 **자식 프로세스** | 실행기의 **스레드 하나** (ADR-0054 §5) |
| 동시 실행 | PC 하나에 하나 (ADR-0014) | 상한까지 여러 건 |
| 대기열 | Bot UI가 가짐 | **Center가 가짐** (C12) |
| 결재 창구 | 제어 파일(현장) 또는 Center | **Center만** (C12) |
| 메시지 | Bot UI 수신 | **Center 메시지 API** (C12 §메시지) |

**업무 값은 볼 수 없다** — C3에 남기지 않기 때문이다 (원칙 6). 그래서 여기서 보는 것은 「그
Bot이 Center를 거쳐 설치되고, 작업으로 시작되고, 끝까지 돌아, 끝났다고 Center가 아는가」다
(C5 `run_status`). 업무 결과가 맞는지는 Studio 시험 실행(M3·M4·M5 인수 시험)이 본다 — 같은
그림·같은 엔진이다.

**BX-03의 「재시작을 끼워 넣어」는 `tests/test_server_runner_resume.py`가 본다** (M7 기준
셋째). 여기서는 같은 그림을 묶음의 한 줄로 **처음부터 끝까지** 다시 돌린다.

**바깥에 나가지 않는다** — Center는 in-process, 모델·모의 앱은 127.0.0.1이다.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from canned_answers import canned
from center_admin import approve, deploy_id, register_extension
from consumers import mock_fleet
from stub_model import StubModel

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from sample_files import make_samples  # noqa: E402

from chaeksas.center.app import create_app  # noqa: E402
from chaeksas.center.settings import Settings as CenterSettings  # noqa: E402
from chaeksas.center.storage import Store  # noqa: E402
from chaeksas.contracts.bpmn_ext import read_process  # noqa: E402
from chaeksas.core.senders import WebhookConfig  # noqa: E402
from chaeksas.mock_apps import catalog  # noqa: E402
from chaeksas.mock_apps.c11 import build as build_mock  # noqa: E402
from chaeksas.mock_apps.external import apps as external_apps  # noqa: E402
from chaeksas.mock_apps.external import definitions as external_definitions  # noqa: E402
from chaeksas.server_runner import agent as agent_mod  # noqa: E402
from chaeksas.server_runner.center_client import CenterClient  # noqa: E402
from chaeksas.server_runner.settings import Settings as RunnerSettings  # noqa: E402
from chaeksas.studio.packaging import default_name, export  # noqa: E402
from chaeksas.studio.receiver import Receiver  # noqa: E402
from chaeksas.studio.runner import resolve_inputs  # noqa: E402
from chaeksas.studio.workspace import Workspace  # noqa: E402

DOCS = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples"
EXAMPLES = DOCS / "bpmn"

ADMIN_TOKEN = "t-admin"
ADMIN = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
READ = {"Authorization": "Bearer t-read"}

#: 한 예제를 끝까지 보는 데 주는 시간. 스레드가 돌고 하트비트가 오가는 시간이다.
WAIT_S = 90.0


def server_examples() -> list[str]:
    """실행 위치가 `server`인 예제 — **그림에서 읽는다**.

    사람이 목록을 옮겨 적으면 예제가 늘 때 묶음이 조용히 뒤처진다 (PC 쪽과 같은 결).
    """
    found = []
    for path in sorted(EXAMPLES.glob("*.bpmn")):
        process = read_process(path.read_text(encoding="utf-8"))
        if process.info.run_location == "server":
            found.append(path.stem)
    return found


SERVER = server_examples()


def _first_case(example: str) -> dict[str, Any]:
    """그 예제의 **첫 자동 케이스** — Studio 시험 실행이 쓰는 것과 같은 것을 쓴다."""
    path = DOCS / "cases" / f"{example}.cases.json"
    if not path.is_file():
        return {}
    cases = json.loads(path.read_text(encoding="utf-8")).get("cases") or []
    return dict(next((one for one in cases if not one.get("manual")), {}) or {})


def case_inputs(example: str, receiver: Receiver | None = None) -> dict[str, Any]:
    """작업 지시로 줄 입력 (C5 `inputs`) — **케이스 입력 연산자를 푼다**.

    푸는 것은 **Studio와 같은 함수**다 (`studio.runner.resolve_inputs`) — 연산자는 C14가
    시험 케이스 형식으로 정한 것이고(`$test_receiver`·`$now_plus`) 작업 지시(C5)에는 그런
    것이 없다. 베끼면 같은 케이스가 묶음에 따라 다른 값을 받는다.

    `receiver`를 주지 않으면 `$test_receiver`를 만났을 때 **분명히 실패한다** (조용히 dict를
    넘기면 그림이 그것을 주소로 알고 돈다).
    """
    raw = dict(_first_case(example).get("inputs") or {})
    # **값 출처가 있는 입력은 작업에 싣지 않는다** — Center가 넣는다 (ADR-0099). 케이스는 Studio에서
    # 그 값을 대신 적을 뿐이고, 작업에 실으면 Center가 422 `input_not_from_caller`로 거절한다.
    process = read_process((EXAMPLES / f"{example}.bpmn").read_text(encoding="utf-8"))
    sourced = {decl.name for decl in process.info.inputs if not decl.from_caller}
    raw = {name: value for name, value in raw.items() if name not in sourced}
    return resolve_inputs(raw, now=datetime.now().astimezone(), receiver=receiver)


def case_approvals(example: str) -> dict[str, dict[str, Any]]:
    """Center 결재함에서 답할 것 — 케이스가 노드 id로 적어 둔 답."""
    return dict(_first_case(example).get("approvals") or {})


def case_messages(example: str) -> list[dict[str, Any]]:
    """외부 시스템이 넣을 메시지 — 케이스의 `messages` 그대로 (C12 §메시지)."""
    return [dict(one) for one in (_first_case(example).get("messages") or [])]


def case_delegations(example: str) -> dict[str, Any]:
    """PC 위임이 돌려주는 값 — 케이스의 `delegations`를 **하나로 합친** 것 (C14).

    Studio 시험 실행은 노드별로 쓰지만(`CaseDelegator`) 현장에서 돌아오는 길은 **PC의 작업
    ack**다 (C4 `JobAck.outputs`). 그 PC는 자기가 어느 노드에 맡겨졌는지 모르므로 값만 올린다.
    """
    found: dict[str, Any] = {}
    for one in (_first_case(example).get("delegations") or {}).values():
        found.update(one)
    assert found, f"{example}: 케이스에 `delegations`가 없다"
    return found


# ─────────────────────────── 판 깔기 ───────────────────────────


def serve(app: Any) -> tuple[str, Any, threading.Thread]:
    """ASGI 앱 하나를 127.0.0.1의 빈 포트에 띄운다 (M5 인수 시험과 같은 것)."""
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started, "앱이 뜨지 않았다"
    return f"http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}", server, thread


@dataclass(frozen=True)
class MockApps:
    """띄운 모의 앱 — 일꾼이 맡을 C11 앱(`built`)과 외부 앱 주소(`external`)."""

    built: list[Any]
    external: dict[str, str]


@pytest.fixture(scope="session")
def mock_apps() -> Iterator[MockApps]:
    """모의 앱들 (`samples/mock_apps`).

    C11 앱 열셋은 **업무 호출을 HTTP로 받지 않는다** — 일꾼이 Center에서 가져간다(C15, ADR-0102 —
    `center`가 붙인다). 외부 앱 둘은 **각자 포트**에 띄운다 — 어댑터 일꾼이 진짜 소켓으로 부르고
    `AdapterCaller`는 `base_url`의 **경로를 버린다**(§4-3의 DNS 고정이 origin 단위다).
    """
    held = []
    built = [build_mock(one) for one in catalog.C11_APPS]
    external: dict[str, str] = {}
    for app_id, make in external_apps.BUILDERS.items():
        base, one_server, one_thread = serve(make())
        held.append((one_server, one_thread))
        external[app_id] = base

    yield MockApps(built=built, external=external)
    for one_server, one_thread in held:
        one_server.should_exit = True
        one_thread.join(timeout=10)


@dataclass
class CenterHandle:
    """시험이 띄운 Center — **진짜 소켓이다**. 서버 실행기가 외부 작업을 Center 주소로 올리고(C15)
    일꾼이 제 스레드에서 롱폴링하므로 httpx.Client로는 안 된다."""

    url: str
    client: httpx.Client
    store: Store

    def __iter__(self) -> Iterator[Any]:  # `client, store = center`
        return iter((self.client, self.store))


@pytest.fixture
def center(tmp_path: Path, mock_apps: MockApps) -> Iterator[CenterHandle]:
    """진짜 Center + 일꾼으로 붙은 모의 앱들 — 서명 키는 Center가 처음 뜰 때 만든다.

    운영자가 하는 일을 시험이 그대로 한다 — 외부 확장 정의를 **등록하고**(C13 E6, 봉투는 Center가
    짓는다) **일꾼을 승인해 들인다**(C15). 주소·키를 넣는 칸은 없다.
    """
    store = Store(tmp_path / "center.sqlite3")
    settings = CenterSettings(
        db_path=tmp_path / "center.sqlite3",
        package_dir=tmp_path / "packages",
        admin_token=ADMIN_TOKEN,
        read_token="t-read",
    )
    url, server, thread = serve(create_app(settings, store=store))
    stops: list[threading.Event] = []
    with httpx.Client(base_url=url, timeout=30.0) as client:
        for app_id, base_url in mock_apps.external.items():
            # 정의는 **주소를 담아 커밋할 수 없어** 그 자리에서 짓는다 (`samples/README.md`).
            register_extension(client, external_definitions.BUILDERS[app_id](base_url), headers=ADMIN)
        stops = mock_fleet(
            client,
            center_url=url,
            built=mock_apps.built,
            external_ids=list(external_definitions.BUILDERS),
            folder=tmp_path / "workers",
        )
        yield CenterHandle(url=url, client=client, store=store)
    for one in stops:
        one.set()
    server.should_exit = True
    thread.join(timeout=10)
    store.close()


@pytest.fixture
def model() -> Iterator[StubModel]:
    """AI 태스크가 쓰는 모델 — 127.0.0.1 스텁이다 (`tests/stub_model.py`).

    답은 **M3·M5와 같은 자리**에서 온다 (`tests/canned_answers.py`) — 전에는 「아무 값」이었고
    (`lambda: None`) 그래서 결과의 **칸을 읽는** 예제가 값을 읽다 멈췄다(BX-10·BX-30·FX-09).
    같은 그림이 묶음에 따라 다른 답을 받으면 안 된다.

    여기서 보는 것은 여전히 업무 결과가 아니라 **배포·실행 한 바퀴**다 — 결과가 맞는지는
    Studio 시험 실행이 본다 (같은 그림·같은 엔진).
    """
    with StubModel(canned) as made:
        yield made


class BundleSettings(RunnerSettings):
    """묶음만 쓰는 설정 — **웹훅의 사설망을 연다** (ADR-0059 §2).

    제품 설정에는 그 스위치가 **없다**: 한 번 켜면 모든 Bot의 모든 웹훅에 적용되어 사내 아무
    주소로나 업무 값이 나간다. 그래서 켜는 자리를 **묶음에 둔다** — ADR이 「시험과 Studio 시험
    수신기만 켠다」고 적어 둔 그 자리다. 막는 규칙 자체는 `tests/test_core_senders.py`가 본다.

    **나머지 길은 제품 그대로다** — 허용 호스트·SMTP는 설정에서 오고 어댑터는 `make_sender`가
    짓는다.
    """

    def webhook(self) -> WebhookConfig:
        return replace(super().webhook(), allow_private_network=True)


@pytest.fixture(scope="session")
def receiver() -> Iterator[Receiver]:
    """웹훅을 받는 **시험 수신기** — 케이스의 `$test_receiver`가 가리키는 곳 (C14).

    **Studio의 것과 같은 코드**다 (`studio.receiver`) — 받는 모양이 묶음마다 다를 이유가 없다.
    127.0.0.1에 뜨므로 **배포된 Bot의 규칙으로는 보낼 수 없는 주소**다: 그래서 아래 `runner`가
    사설망을 열어 준다 (ADR-0059 §2 — 제품 설정에는 그 스위치가 없다).
    """
    made = Receiver().start()
    yield made
    made.stop()


@pytest.fixture(scope="session")
def mail() -> Iterator[Any]:
    """메일을 받는 **작은 SMTP 서버** — 127.0.0.1이다 (바깥에 나가지 않는다).

    `tests/test_core_senders.py`의 것을 다시 쓴다 (두 벌을 만들지 않는다). 운영자가 사내
    중계기를 적어 주는 자리에 이것을 적는 셈이다.
    """
    from test_core_senders import FakeSmtp  # noqa: PLC0415 — 시험끼리 나눠 쓴다

    server = FakeSmtp()
    server.start()
    yield server
    server.close()


@pytest.fixture
def runner(
    tmp_path: Path,
    center: CenterHandle,
    model: StubModel,
    mail: Any,
    receiver: Receiver,
) -> agent_mod.Agent:
    """진짜 서버 실행기 — Center는 in-process이고 실행은 **제 스레드**로 돈다.

    모델·읽기 폴더·서비스 앱 키·**보내기**는 **설정·환경변수로** 준다 (운영자가 하는 일).
    **바깥 앱 명부는 실행기가 제 손으로 Center에서 받는다** (C7 — 파일을 거치지 않는다).

    메일은 127.0.0.1의 작은 SMTP 서버로 가고 **암호화하지 않는다**(`none` — 시험 서버가 TLS를
    모른다. 사내 중계기를 쓰는 현장과 같은 고름이다). **웹훅 허용 호스트는 비워 둔다** —
    `$test_receiver`는 Studio 전용이고(C14) 배포된 Bot은 사설망으로 보내지 않으므로, 웹훅을
    쓰는 예제는 이 묶음에서 돌 수 없다 (`REMAINING`).
    """
    client, _ = center
    key = client.post(
        "/api/v1/center-keys", json={"name": "시험 서버", "type": "server_runner"}, headers=ADMIN
    ).json()["key"]
    settings = BundleSettings(
        center_url=center.url,
        name="재통과 서버",
        max_concurrency=4,
        data_path=tmp_path / "runner",
        llm_base_url=model.base_url,
        llm_model="stub",
        # 예제가 읽는 표본은 저장소 안에 있다 (`samples/`) — 출력 폴더 밖이라 열어 줘야 한다.
        readable_dirs=(Path(__file__).resolve().parent.parent,),
        smtp_host="127.0.0.1",
        smtp_port=mail.port,
        smtp_security="none",
        smtp_sender="bot@example.com",
        # 시험 수신기는 127.0.0.1이다 — 허용 호스트에 적어도 **사설망을 열지 않으면** 막힌다.
        webhook_allowed_hosts=("127.0.0.1",),
    )
    settings.data_path.mkdir(parents=True, exist_ok=True)
    settings.runs_dir.mkdir(parents=True, exist_ok=True)
    return agent_mod.Agent(
        settings=settings,
        client=CenterClient(base_url=center.url, api_key=key, client=client),
    )


# ─────────────────────────── 배포 (C2·C5) ───────────────────────────


def make_samples_for(runner: agent_mod.Agent, bot: str) -> None:
    """그 Bot의 **출력 폴더 아래에** 표본 파일을 만든다 — **M3와 같은 자리**다
    (`tests/sample_files.py`).

    저장소에 이진 파일을 두지 않으므로 묶음이 만든다. **상대 경로의 기준이 출력 폴더**이므로
    (ADR-0032) 루트를 그것으로 준다 — Studio는 작업 폴더를 준다. **빈 폴더도 함께** 생긴다
    (git은 빈 폴더를 담지 않는다 — FX-04의 그 케이스다). 출력 폴더 이름은 **패키지 id**다
    (`agent.run_env()`가 `bot.id`로 짓는다).
    """
    make_samples(runner.settings.data_path / "outputs" / bot)


def packaged(tmp_path: Path, example: str) -> Path:
    """Studio가 하듯 내보낸다 — 매니페스트는 **그림에서 모은다** (`studio.packaging`)."""
    space = Workspace(tmp_path / "studio" / example).ensure()
    made = space.import_example(EXAMPLES, example)
    return export(made, tmp_path / default_name(made))


def approve_delegation_targets(
    center: CenterHandle, tmp_path: Path, example: str
) -> None:
    """그 예제가 **PC 위임으로 부르는 Bot**을 올려 승인해 둔다 (ADR-0062).

    배포가 그것을 **R8처럼 본다** — 승인되지 않은 Bot을 맡기는 그림은 422
    `delegation_not_approved`다. 그림에서 읽으므로(`requires.delegations`) 위임을 쓰는 예제가
    늘어도 이 자리는 그대로다. 패키지 id는 예제 파일 이름의 `_`를 `-`로 바꾼 것이다 (C1 `id`).
    """
    client, _ = center
    # **작업 폴더를 따로 쓴다** — `packaged()`가 쓰는 자리에 또 들이면 같은 id가 둘이 된다.
    space = Workspace(tmp_path / "delegation-targets" / example).ensure()
    made = space.import_example(EXAMPLES, example)
    from chaeksas.studio.packaging import build_manifest  # noqa: PLC0415

    for pkg in build_manifest(made).requires.delegations:
        target = pkg.replace("-", "_")
        answer = client.post(
            "/api/v1/packages",
            files={"file": (f"{target}.zip", packaged(tmp_path, target).read_bytes(), "application/zip")},
            headers=ADMIN,
        )
        assert answer.status_code in (200, 201), answer.text
        info = dict(answer.json())
        approve(client, info["id"], info["version"], headers=ADMIN)


def deploy(
    center: CenterHandle, runner: agent_mod.Agent, zip_path: Path
) -> dict[str, Any]:
    """업로드 → **승인** → **배포** → 하트비트로 설치까지 (C2 V1~V7).

    봉투는 Center가 지어 서명하고(ADR-0090), 실행기가 하트비트의 `admin_keys`로 다시 본다.
    """
    client, _ = center
    answer = client.post(
        "/api/v1/packages",
        files={"file": (zip_path.name, zip_path.read_bytes(), "application/zip")},
        headers=ADMIN,
    )
    assert answer.status_code in (200, 201), answer.text
    info = dict(answer.json())
    approve(client, info["id"], info["version"], headers=ADMIN)

    # 실행기가 등록되어야 배포 대상이 생긴다 (C12 — 키 하나 ↔ 서버 하나).
    runner.tick()
    assert runner.server_runner_id, "실행기가 등록되지 않았다"

    deploy_id(
        client,
        target={"type": "server_runner", "id": runner.server_runner_id},
        bpm_process_id=info["id"],
        version=info["version"],
        headers=ADMIN,
    )

    runner.tick()  # 공개키·배포를 받아 설치한다
    assert info["id"] in [one.id for one in runner.installed_bots()], (
        f"{info['id']}가 설치되지 않았다"
    )
    return info


def dispatch(
    center: CenterHandle, info: dict[str, Any], inputs: dict[str, Any]
) -> str:
    """Center 작업 지시 하나 (C5 — `id`를 비우면 Center가 고른다)."""
    client, _ = center
    answer = client.post(
        "/api/v1/jobs",
        json={
            "bpm_process_id": info["id"],
            "target": {"type": "server_runner"},
            "inputs": inputs,
        },
        headers=ADMIN,
    )
    assert answer.status_code in (200, 201), answer.text
    return str(answer.json()["job_id"])


# ─────────────────────────── 돌리기 ───────────────────────────


def _answer_open_approvals(
    client: httpx.Client, answers: dict[str, dict[str, Any]], run_id: str | None
) -> int:
    """Center 결재함에 올라온 것에 답한다 (C6 — 서버의 창구는 Center만이다).

    케이스가 노드 id로 적어 둔 답을 쓴다. 적어 둔 것이 없으면 **승인**이다 (여기서 보는 것은
    업무 판단이 아니라 「답이 내려가 실행이 이어 가는가」다).
    """
    given = 0
    listed = client.get("/api/v1/approvals?state=open", headers=READ).json()
    for one in listed:
        if run_id is not None and one.get("run_id") != run_id:
            continue
        body = dict(answers.get(one.get("node_id") or "") or {})
        decision = str(body.pop("decision", "approve") or "approve")
        answer = client.post(
            f"/api/v1/approvals/{one['request_id']}/answer",
            json={
                "schema": 1,
                "decision": decision,
                "answer": body,
                "answered_by": "시험",
            },
            headers=ADMIN,
        )
        # 틀린 답은 Center가 칸과 함께 돌려준다 — 그러면 그 자리에서 말한다 (조용히 넘기지
        # 않는다. 다음 주기에 또 같은 일이 생겨 영원히 돈다).
        assert answer.status_code < 400, f"{one['request_id']}: {answer.text}"
        given += 1
    return given


def _post_message(client: httpx.Client, message: dict[str, Any]) -> bool:
    """외부 시스템이 메시지를 넣는다 (C12 §메시지).

    **받을 실행이 아직 없으면 422 `no_receiver`**다 — 그때는 아직 때가 아니라는 뜻이라
    거짓을 돌려주고 다음 주기에 다시 본다 (케이스의 `after_s`를 실제로 재우지 않는다).
    """
    answer = client.post(
        "/api/v1/messages",
        json={
            "schema": 1,
            "name": message["name"],
            "correlation": message.get("correlation"),
            "payload": dict(message.get("payload") or {}),
        },
        headers=ADMIN,
    )
    if answer.status_code == 422 and (answer.json().get("code") == "no_receiver"):
        return False
    assert answer.status_code < 400, f"{message['name']}: {answer.text}"
    return True


def run_to_the_end(
    center: CenterHandle,
    runner: agent_mod.Agent,
    job_id: str,
    *,
    answers: dict[str, dict[str, Any]],
    messages: list[dict[str, Any]],
    timeout_s: float = WAIT_S,
    pc: Any = None,
) -> dict[str, Any]:
    """하트비트를 돌리며 결재에 답하고 메시지를 넣는다. 끝난 작업 정보를 돌려준다.

    **답·메시지는 Center를 거친다** — 서버 실행기에는 현장 창구가 없다 (C12).

    `pc`를 주면 주기마다 부른다 — **PC 위임을 가짜 PC가 끝내는 자리**다 (BX-16, ADR-0062).
    위임은 Center가 PC 작업으로 만들고 **그 PC의 ack로** 값이 돌아오므로, 아무도 끝내 주지
    않으면 서버 실행이 영원히 기다린다.
    """
    client, _ = center
    left = list(messages)
    until = time.monotonic() + timeout_s
    while time.monotonic() < until:
        runner.tick()
        info = client.get(f"/api/v1/jobs/{job_id}", headers=READ).json()
        run_id = info.get("run_id")
        if info.get("run_status") in ("success", "failed", "cancelled"):
            return dict(info)
        if run_id:
            _answer_open_approvals(client, answers, run_id)
            left = [one for one in left if not _post_message(client, one)]
        if pc is not None:
            pc()
        time.sleep(0.05)
    raise AssertionError(
        f"작업 {job_id}이 끝나지 않았다 — 마지막 상태 "
        f"{client.get(f'/api/v1/jobs/{job_id}', headers=READ).json()}"
    )


# ─────────────────────────── 묶음 ───────────────────────────

# **파라미터 묶음에서 빠지는 것은 이제 하나**다 — BX-33은 **일부러 실패하는** 교육 예제라
# (`_ON_PURPOSE`, ADR-0039) 「열린다」가 맞지 않는다. 아래에 **의도한 실패를 보는 시험**이 있다.
#
# **BX-16도 돈다 — 다만 전용 시험이다** (`test_bx16_delegates_a_part_to_a_pc_and_continues`).
# **PC 위임**이라(ADR-0062) 맡긴 작업을 끝내 줄 PC가 있어야 하고, 없으면 그 실행은 영원히
# 기다린다 — 묶음에 넣으면 **시험마다** 가짜 PC가 뜬다.
#
# **사유는 돌려 보고 적는다.** 조각 9에서 일곱이 틀렸고, 조각 10에서 둘, 조각 12에서 다섯,
# 조각 13에서 셋이다 — FX-04는 **빈 폴더**, **FX-13은 신호가 아니라 타이머**(`ready`·`abort`는
# 같은 실행 안에서 던지고 받는다), BX-16은 **못 하는 것이 아니라 발판이 필요한 것**이었다.
# 첫 실패만 보고 적으면 그다음 까닭을 모른 채로 남는다.
#: BX-33은 **일부러 실패한다** (ADR-0039) — 한 가지에서만 생기는 값을 뒤에서 읽는 교육 예제다.
#: 그래서 `REMAINING`이지만 「아직 못 한다」가 아니고, 아래에 **의도한 실패를 보는 시험**이 있다.
_ON_PURPOSE = (
    "**일부러 실패하는 교육 예제**다 (ADR-0039 — B11 경고가 가리키는 그 하나). 지나지 않은 "
    "가지의 변수를 뒤에서 읽어 식이 멈춘다. M5 인수 시험과 같이 **의도한 실패를 따로 본다** "
    "(`test_bx33_fails_on_purpose_on_the_server_too`). "
)

#: 아직 **돌리지는** 못하는 예제와 그 이유. **조용히 빼면 묶음이 거짓말을 한다.**
#:
#: **배포·설치는 이것들도 모두 본다** (아래 `test_every_server_example_deploys_and_installs`) —
#: 막힌 것은 **도는 것**이고, 배포 길은 44개 전부가 지나간다.
REMAINING: dict[str, str] = {
    "bx33_access_request": _ON_PURPOSE,
}

#: **묶음이 아니라 전용 시험이 보는 것**. 빠뜨린 것이 아니라 **다른 자리에서 본다** —
#: 아래 `test_every_server_example_is_in_the_bundle_or_has_a_reason`가 셋을 합쳐 44개와 맞춰
#: 본다(갈래를 더하면서 조용히 빠지는 일을 막는 자리다).
ELSEWHERE: dict[str, str] = {
    "fx24_batch_intake": (
        "`test_fx24_starts_one_server_bot_per_approved_item`가 본다 — **일괄 기동**이라(ADR-0082) "
        "맡길 서버 Bot(FX-25)도 같은 실행기에 배포되어 있어야 한다. 묶음은 예제 하나만 배포하므로 "
        "거기서는 위임이 `no_deployment`로 실패해 오류 경계로 간다. "
    ),
    "bx16_reorder_proposal": (
        "`test_bx16_delegates_a_part_to_a_pc_and_continues`가 본다 — **PC 위임**이라(ADR-0062) "
        "맡긴 작업을 끝내 줄 PC가 있어야 한다(등록된 Bot UI·배포된 BX-17·그 PC의 작업 ack). "
        "아무도 끝내 주지 않으면 그 실행은 영원히 기다리므로 파라미터 묶음에 넣지 않는다. "
    ),
}

GREEN = [one for one in SERVER if one not in REMAINING and one not in ELSEWHERE]


def test_the_server_examples_are_read_from_the_drawings() -> None:
    """목록은 **그림이 정한다** — 사람이 옮겨 적지 않는다 (README 묶음 표의 「서버 예제 전부」)."""
    assert len(SERVER) >= 40, f"서버 예제가 너무 적다: {SERVER}"
    assert "bx03_expense_approval" in SERVER
    assert "fx03b_amount_branch" in SERVER
    # PC 예제는 여기 들지 않는다 (그쪽은 `test_m5_pc_rerun.py`다).
    assert "bx04_tax_invoice_issue" not in SERVER


def test_every_server_example_is_in_the_bundle_or_has_a_reason() -> None:
    """빼는 것은 **이유와 함께** 적는다 (M4·M5 인수 시험과 같은 자리).

    갈래가 셋이다 — 묶음이 도는 것(`GREEN`), **전용 시험이 보는 것**(`ELSEWHERE`), 아직 못
    도는 것(`REMAINING`). 셋을 합쳐 44개와 맞춰 보므로 **조용히 빠지는 일이 없다**.
    """
    assert set(GREEN) | set(REMAINING) | set(ELSEWHERE) == set(SERVER)
    assert not (set(REMAINING) & set(ELSEWHERE)), "한 예제가 두 갈래에 있다"
    for example, why in (*REMAINING.items(), *ELSEWHERE.items()):
        assert example in SERVER, f"{example}는 서버 예제가 아니다"
        assert why.strip(), f"{example}: 이유가 비었다"


@pytest.mark.parametrize("example", SERVER)
def test_every_server_example_deploys_and_installs(
    example: str,
    tmp_path: Path,
    center: CenterHandle,
    runner: agent_mod.Agent,
) -> None:
    """**배포 길은 44개 전부가 지나간다** — 막힌 것은 *도는 것*이지 배포가 아니다.

    여기서 새로운 것이 배포 길이다(서버 대상 봉투·`"*"`·C7 누락 검사) — PC 재통과가 여덟 개
    모두 배포까지 보는 것과 같은 결이다. 끝까지 도는 것은 아래 시험이 본다.

    **PC 위임을 쓰는 예제는 그 대상이 승인돼 있어야 한다** (ADR-0062 — 배포가 R8처럼 본다).
    """
    approve_delegation_targets(center, tmp_path, example)
    info = deploy(center, runner, packaged(tmp_path, example))
    assert info["id"], example


@pytest.mark.parametrize("example", GREEN)
def test_a_server_example_runs_through_center_and_the_runner(
    example: str,
    tmp_path: Path,
    center: CenterHandle,
    runner: agent_mod.Agent,
    receiver: Receiver,
) -> None:
    """한 줄로 본다: 서명 → 배포 → 설치 → **Center 작업 지시** → 실행 → Center가 안다.

    **업무 값은 보지 않는다** (C3에 없다 — 원칙 6). 결과가 맞는지는 Studio 시험 실행이 본다.
    """
    info = deploy(center, runner, packaged(tmp_path, example))
    make_samples_for(runner, str(info["id"]))
    job_id = dispatch(center, info, case_inputs(example, receiver))
    done = run_to_the_end(
        center,
        runner,
        job_id,
        answers=case_approvals(example),
        messages=case_messages(example),
    )
    assert done["run_status"] == "success", f"{example}: {done}"


#: 서비스 호출이 있는 서버 예제 — **모든 호출을 기다림으로 넘겨도** 끝까지 간다 (ADR-0103).
#: 반복(BX-06)·여럿(BX-22)·**겹치는 기다림**(FX-18 병렬 반복)·외부 앱(FX-20 어댑터 일꾼).
PARKED = ["bx06_bulk_credit_check", "bx22_offboarding_access", "fx18_parallel_loop", "fx20_external_adapter"]


@pytest.mark.parametrize("example", PARKED)
def test_a_long_external_task_lets_go_of_the_slot_and_comes_back(
    example: str,
    tmp_path: Path,
    center: CenterHandle,
    runner: agent_mod.Agent,
    receiver: Receiver,
) -> None:
    """`park_after_s=0` — 올린 일감은 **곧바로 기다림**이 되고 자리를 놓는다. 결과는 하트비트 뒤에
    실행기가 묻고 넣는다(`wake_external`). 기록에 `run_waiting`·`run_resumed`가 짝으로 남는다 (C3).
    """
    runner.settings = replace(runner.settings, park_after_s=0.0)
    info = deploy(center, runner, packaged(tmp_path, example))
    make_samples_for(runner, str(info["id"]))
    job_id = dispatch(center, info, case_inputs(example, receiver))
    done = run_to_the_end(
        center, runner, job_id, answers=case_approvals(example), messages=case_messages(example)
    )
    assert done["run_status"] == "success", f"{example}: {done}"
    events = [
        json.loads(line)
        for line in (runner.settings.runs_dir / f"{done['run_id']}.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    waited = [one["data"] for one in events if one["kind"] == "run_waiting"]
    resumed = [one["data"] for one in events if one["kind"] == "run_resumed"]
    assert any(one["waiting_for"] == "external_task" and one.get("task_id") for one in waited), example
    assert any(one["reason"] == "external_task" for one in resumed), example
    assert len(waited) == len(resumed), "기다림과 이어 감은 짝이다"
    calls = [one for one in events if one["kind"] == "service_call"]
    assert calls and all("error_code" not in one["data"] for one in calls), "넘겨도 호출은 한 번씩 성공한다"


def test_bx33_fails_on_purpose_on_the_server_too(
    tmp_path: Path,
    center: CenterHandle,
    runner: agent_mod.Agent,
    receiver: Receiver,
) -> None:
    """BX-33은 **일부러 실패한다** (ADR-0039) — 서버에서도 **같은 식 오류**로 멈춘다.

    지나지 않은 가지에서만 생기는 값을 뒤에서 읽는 교육 예제다 (B11 경고가 가리키는 그 하나).
    빼지 않고 **의도한 실패를 본다** — 그냥 `REMAINING`에 두면 「언젠가 초록이 될 것」으로
    읽히고, 어느 날 다른 이유로 실패해도 아무도 모른다 (M5 인수 시험과 같은 자리).
    """
    client, _ = center
    info = deploy(center, runner, packaged(tmp_path, "bx33_access_request"))
    job_id = dispatch(center, info, case_inputs("bx33_access_request", receiver))
    done = run_to_the_end(
        center,
        runner,
        job_id,
        answers=case_approvals("bx33_access_request"),
        messages=case_messages("bx33_access_request"),
    )
    assert done["run_status"] == "failed", f"일부러 실패해야 한다: {done}"
    found = client.get(f"/api/v1/runs/{done['run_id']}", headers=READ).json()
    # **식 오류다** — 업무 실패(`TaskFailed`)가 아니라 그림의 흠이라 오류 경계로 가지 않는다.
    assert found.get("error_code") == "expr_error", found


#: 타이머로 시작하는 서버 예제 — **작업 지시 없이** Center의 일정이 깨운다 (ADR-0110).
#: BX-23(매주 수요일 10시)은 입력이 없어 케이스 값을 넣을 자리가 없다 — 일정이 그대로 돌릴 수 있다.
TIMER_STARTED = "bx23_training_reminder"


def test_a_timer_example_starts_without_a_job_order(
    tmp_path: Path,
    center: CenterHandle,
    runner: agent_mod.Agent,
) -> None:
    """서명 → 배포 → 설치 → **Center의 일정이 쓸어 작업을 만든다** → 실행 → Center가 안다.

    시계를 돌리지 않는다 — 배포가 **여드레 전에** 생긴 것으로 옮기면 그 사이 수요일 10시가 지났다.
    쓸기는 하트비트가 하는 그것이고(분마다 한 번의 관문만 건너뛴다) 실행 기록의 출처는 `schedule`이다.
    """
    from datetime import UTC, timedelta  # noqa: PLC0415

    from chaeksas.center.api import timers  # noqa: PLC0415

    client, store = center
    info = deploy(center, runner, packaged(tmp_path, TIMER_STARTED))
    assert case_inputs(TIMER_STARTED) == {}, "일정은 입력을 비워 만든다 — 입력이 있는 예제는 이 시험에 맞지 않다"
    make_samples_for(runner, str(info["id"]))
    week_ago = (datetime.now(UTC) - timedelta(days=8)).isoformat()
    with store.tx() as cur:
        cur.execute("UPDATE deployments SET at = ? WHERE bpm_process_id = ?", (week_ago, info["id"]))
    assert client.get("/api/v1/jobs", headers=READ).json() == [], "아무도 작업을 지시하지 않았다"

    made = timers.sweep(store, tz=timers.DEFAULT_ZONE, force=True)
    assert len(made) == 1, made
    done = run_to_the_end(center, runner, made[0], answers={}, messages=[])
    assert done["run_status"] == "success", done
    assert done["requested_by"].startswith("timer:"), done
    found = client.get(f"/api/v1/runs/{done['run_id']}", headers=READ).json()
    assert found["source"] == "schedule", found
    # 같은 차례는 다시 쏘지 않는다.
    assert timers.sweep(store, tz=timers.DEFAULT_ZONE, force=True) == []


def test_the_canned_answers_are_the_shared_ones() -> None:
    """짜 둔 답의 **자리가 하나다** (`tests/canned_answers.py`) — M3·M5와 같은 것을 쓴다.

    묶음마다 따로 두면 **같은 그림이 묶음에 따라 다른 답을 받는다** — 그래서 M7이 세 예제를
    돌리지 못했다.
    """
    import canned_answers

    assert canned is canned_answers.canned
    # FX-09의 그 자리 — 답이 없으면 스텁이 타입으로 때우고 케이스가 어긋난다.
    found = canned({"판정": "dict"}, {"신청": {"id": 1, "금액": 30000, "영수증": True}})
    assert found is not None and found["판정"]["승인"] is True


# ─────────── BX-16: 서버 Bot이 PC에 **한 부분을 맡긴다** (전용 발판, ADR-0062) ───────────

#: 맡길 PC 예제 — 그 PC에 **배포돼 있어야** 위임이 작업이 된다 (C5 `no_deployment`).
BX16_TARGET = "bx17_erp_po_entry"

#: 가짜 PC의 Center API 키 (`bot_ui_id` → 키). 위임 결과를 **그 PC의 ack로** 올린다 (C4).
PC_KEYS: dict[str, str] = {}

def register_a_pc(client: Any) -> str:
    """등록된 Bot UI 하나 — 작업이 갈 PC다 (C4 「키 묶기」). `bot_ui_id`를 준다.

    **하트비트까지 보낸다** — 확장을 보고하지 않으면 Center가 `ui-automation`을 몰라 그것을
    요구하는 BX-17의 **배포가 막힌다** (C7 누락 검사). `Agent`를 쓰지 않고 C4를 직접 부른다 —
    여기서 보는 것은 Bot UI가 아니라 **작업이 만들어지나**다.
    """
    from chaeksas.core.extensions import load_host

    key = client.post(
        "/api/v1/center-keys", json={"name": "BX-16 대상 PC", "type": "bot_ui"}, headers=ADMIN
    ).json()["key"]
    auth = {"Authorization": f"Bearer {key}"}
    versions = {"bot_ui": "0.1.0", "core": "0.1.0"}
    answer = client.post(
        "/api/v1/bot-ui/register",
        # C4 — PC 고유값의 SHA-256만 보낸다 (원값은 보내지 않는다).
        json={"schema": 1, "machine_id": "b" * 64, "name": "구매 PC-01", "os": "Windows 11", "versions": versions},
        headers=auth,
    )
    assert answer.status_code < 400, answer.text
    bot_ui_id = str(answer.json()["bot_ui_id"])
    PC_KEYS[bot_ui_id] = str(key)

    beat = client.post(
        "/api/v1/bot-ui/heartbeat",
        json={
            "schema": 1,
            "status": "idle",
            "current_run": None,
            "queue": {"max": 20, "items": []},
            "worker": {"state": "off", "version": "0.1.0", "restarts": 0, "session": "idle"},
            "versions": versions,
            "extensions": [one.to_json_dict() for one in load_host().states()],
        },
        headers=auth,
    )
    assert beat.status_code < 400, beat.text
    return bot_ui_id


@dataclass
class FakePc:
    """맡겨진 PC 작업을 **끝내 주는 가짜 PC** (C4 — `JobAck.outputs`는 **선언한 것만**).

    고르는 기준은 **`requested_by`** 하나다 (`server_bot:<run_id>` — 「이 작업이 위임인가」를
    말해 주는 자리이고 그 글은 `contracts.center_api`에 한 자리다, ADR-0062 §4). 진짜 Bot UI를
    띄우지 않는다 — 그쪽 한 바퀴는 `test_server_runner_delegation.py`가 **진짜 자식 프로세스**로
    본다. 여기서 보는 것은 **예제의 그림이 그 길과 맞물리나**다.
    """

    client: Any
    bot_ui_id: str
    outputs: dict[str, Any]
    seen: set[str] = field(default_factory=set)

    def __call__(self) -> None:
        listed = self.client.get("/api/v1/jobs?state=pending,dispatched,accepted", headers=READ).json()
        for one in listed:
            job_id = str(one["job_id"])
            if job_id in self.seen or not str(one.get("requested_by") or "").startswith("server_bot:"):
                continue
            self.seen.add(job_id)
            run_id = f"run_20261016_1200{len(self.seen):02d}_cccccc"
            for ack in (
                {"job_id": job_id, "result": "started", "run_id": run_id},
                {"job_id": job_id, "result": "finished", "run_id": run_id, "outputs": self.outputs},
            ):
                beat = self.client.post(
                    "/api/v1/bot-ui/heartbeat",
                    json={
                        "schema": 1,
                        "status": "idle",
                        "current_run": None,
                        "queue": {"max": 20, "items": []},
                        "worker": {"state": "off"},
                        "job_acks": [ack],
                    },
                    headers={"Authorization": f"Bearer {PC_KEYS[self.bot_ui_id]}"},
                )
                assert beat.status_code == 200, beat.text


def deploy_to_pc(client: Any, bot_ui_id: str, example: str, tmp_path: Path) -> str:
    """PC 예제 하나를 **승인 → 배포**로 그 PC에 배포한다 (C2 — 봉투는 Center가 짓는다).

    설치까지 가지 않는다 — `POST /jobs`가 보는 것은 **Center의 배포**이고(`no_deployment`)
    설치는 하트비트 뒤의 일이다 (PC 쪽 한 바퀴는 `tests/test_m5_pc_rerun.py`가 본다).
    """
    space = Workspace(tmp_path / "bx16-target").ensure()
    made = space.import_example(EXAMPLES, example)
    package = export(made, tmp_path / default_name(made))
    answer = client.post(
        "/api/v1/packages",
        files={"file": (package.name, package.read_bytes(), "application/zip")},
        headers=ADMIN,
    )
    assert answer.status_code in (200, 201), answer.text
    info = dict(answer.json())

    approve(client, info["id"], info["version"], headers=ADMIN)
    deploy_id(
        client,
        target={"type": "bot_ui", "id": bot_ui_id},
        bpm_process_id=info["id"],
        version=info["version"],
        headers=ADMIN,
    )
    return str(info["id"])


def test_bx16_delegates_a_part_to_a_pc_and_continues(
    tmp_path: Path,
    center: CenterHandle,
    runner: agent_mod.Agent,
    receiver: Receiver,
) -> None:
    """BX-16 — **서버 Bot이 한 부분을 PC에 맡기고 결과로 이어 간다** (ADR-0062).

    전에는 이 자리를 사내 확장 서비스 앱(`center-jobs`)으로 메우고 있었고, 그래서 발판이 넷
    필요했다 — **소켓 Center**(모의 앱이 제 스레드에서 `POST /jobs`를 불러야 했다)·연동용 키·
    등록된 Bot UI·배포된 BX-17. **위임이 본문이 되어 앞의 둘이 없어졌다**: 맡기는 것은 실행기
    자신이고(`CenterDelegator`) 작업을 만드는 것은 Center다. 남은 둘은 그대로다 — 맡길 PC가
    **등록돼 있고** 그 PC에 BX-17이 **배포돼 있어야** 한다 (C5 `no_deployment`).

    묶음에 넣지 않는 까닭은 하나다 — **아무도 끝내 주지 않으면 서버 실행이 영원히 기다린다**
    (위임은 PC의 작업 ack로 돌아온다, C4). 그래서 가짜 PC가 그 자리를 맡는다.

    **보는 것은 셋이다**: 위임이 **PC 작업이 되었나**, 그 값으로 서버 실행이 **끝까지 갔나**,
    그리고 Center가 ack를 받고 **업무 값을 지웠나** (원칙 6의 예외는 좁게 쓴다).
    """
    client, store = center
    bot_ui_id = register_a_pc(client)
    target = deploy_to_pc(client, bot_ui_id, BX16_TARGET, tmp_path)

    info = deploy(center, runner, packaged(tmp_path, "bx16_reorder_proposal"))
    make_samples_for(runner, str(info["id"]))
    job_id = dispatch(center, info, case_inputs("bx16_reorder_proposal", receiver))

    # 케이스가 적어 둔 위임 결과를 **가짜 PC가 올린다** (Studio는 케이스로 끝내지만 현장에서는
    # C4 ack가 그 길이다 — 같은 값을 쓴다).
    outputs = case_delegations("bx16_reorder_proposal")
    pc = FakePc(client=client, bot_ui_id=bot_ui_id, outputs=outputs)
    done = run_to_the_end(
        center,
        runner,
        job_id,
        answers=case_approvals("bx16_reorder_proposal"),
        messages=case_messages("bx16_reorder_proposal"),
        pc=pc,
    )
    assert done["run_status"] == "success", done

    # **위임이 PC 작업이 되었다** — 대상은 그 PC이고 「누가 맡겼나」가 실행 이름으로 적힌다.
    assert pc.seen, "맡긴 PC 작업이 없다"
    handed = [
        one
        for one in client.get("/api/v1/jobs?state=finished,accepted", headers=READ).json()
        if one["bpm_process_id"] == target
    ]
    assert handed, "PC에 넘긴 작업이 없다"
    assert handed[0]["target"] == {"type": "bot_ui", "id": bot_ui_id}
    assert str(handed[0]["requested_by"]).startswith("server_bot:")

    # **값은 ack와 함께 지워진다** (ADR-0062 §4) — 누가·언제·성패는 남는다.
    rows = client.get(f"/api/v1/server-runners/{runner.server_runner_id}", headers=ADMIN).json()
    assert rows, "실행기 상세를 읽지 못했다"


# ─────────────── 일괄 기동 — FX-24 → FX-25 (ADR-0079·0082) ───────────────

FX24 = "fx24_batch_intake"


def batch_children(client: httpx.Client, child: str) -> list[dict[str, Any]]:
    return [one for one in client.get("/api/v1/jobs", headers=READ).json() if one["bpm_process_id"] == child]


def bind_virtual_worker(client: httpx.Client, intake: str) -> None:
    """접수 Bot을 가상 직원에 **먼저** 묶는다 — 일괄 결재의 담당자가 그 감독자다 (ADR-0099).

    FX-24의 `감독자`는 값 출처가 가상 직원인 **필수** 입력이라 묶지 않고 돌리면 시작조차 하지 않는다.
    가상 직원이 하나뿐이라 작업에 id를 적지 않아도 Center가 그것을 고른다. 케이스의 감독자와 같다.
    """
    bound = client.post("/api/v1/virtual-workers", json={
        "id": "finance-intake", "name": "재무 가상 직원", "supervisors": ["김감독"], "intake": intake,
    }, headers=ADMIN)
    assert bound.status_code == 201, bound.text


def test_fx24_starts_one_server_bot_per_approved_item(
    tmp_path: Path,
    center: CenterHandle,
    runner: agent_mod.Agent,
    receiver: Receiver,
) -> None:
    """**접수 Bot 실행 한 번 = 일괄** — 감독자가 승인하면 건마다 서버 Bot 작업이 하나씩 생긴다.

    보는 것은 넷이다: 일괄 결재가 **담당자(감독자)로 걸러지나**, 승인 뒤 **건마다 작업 하나**인가
    (차례마다 멱등 키가 달라 2건째부터 같은 작업이 돌아오지 않는다), 자식이 **같은 실행기에서**
    돌아 결과를 돌려주나(부모는 기다리며 자리를 놓는다), 그리고 자식 실행이 **부모를 아나**.
    """
    client, _ = center
    child = deploy(center, runner, packaged(tmp_path, "fx25_batch_item"))
    info = deploy(center, runner, packaged(tmp_path, FX24))
    bind_virtual_worker(client, info["id"])
    job_id = dispatch(center, info, case_inputs(FX24, receiver))

    done = run_to_the_end(center, runner, job_id, answers=case_approvals(FX24), messages=[])
    assert done["run_status"] == "success", done
    # 감독자의 결재함 — 담당자로 걸러 본다 (ADR-0080). 담당자는 그림에 적은 이름이 아니라
    # **가상 직원의 감독자**다 — Center가 값 출처가 가상 직원인 입력을 채웠다 (ADR-0099).
    mine = client.get("/api/v1/approvals", params={"assignee": "김감독"}, headers=READ).json()
    assert [one["run_id"] for one in mine] == [done["run_id"]], "일괄 결재가 감독자의 결재함에 없다"
    assert mine[0]["review"]["건수"] == 3, "감독자는 N건을 한 번에 본다 (C6 `review`)"

    made = batch_children(client, str(child["id"]))
    assert len(made) == 3, [one["job_id"] for one in made]
    assert {one["requested_by"] for one in made} == {f"server_bot:{done['run_id']}"}
    assert {one["target"]["type"] for one in made} == {"server_runner"}
    assert {one["run_status"] for one in made} == {"success"}
    # 일괄이 맡긴 자식은 **가상 직원을 이어받는다** (ADR-0099 §3) — 부모가 넘기지 않았다.
    assert {one["virtual_worker"] for one in made} == {"finance-intake"}
    assert all("처리자" not in one["inputs"] for one in made)
    # 두 실행은 서로를 안다 (C3 `parent_run_id`) — 서버 자식도 PC 자식과 같다.
    for one in made:
        found = client.get(f"/api/v1/runs/{one['run_id']}", headers=READ).json()
        assert found["parent_run_id"] == done["run_id"], found

    # 부르는 쪽은 감독자를 줄 수 없고, 남의 가상 직원 이름으로 부를 수도 없다 (C5, ADR-0099).
    body = {"bpm_process_id": info["id"], "target": {"type": "server_runner"}, "inputs": case_inputs(FX24, receiver)}
    forged = client.post("/api/v1/jobs", json={**body, "inputs": {**body["inputs"], "감독자": ["아무나"]}},
                         headers=ADMIN)
    assert forged.status_code == 422 and forged.json()["code"] == "input_not_from_caller", forged.text
    wrong = client.post("/api/v1/jobs", json={**body, "virtual_worker": "nobody"}, headers=ADMIN)
    assert wrong.status_code == 422 and wrong.json()["code"] == "virtual_worker_mismatch", wrong.text
    assert client.get(f"/api/v1/jobs/{job_id}", headers=READ).json()["virtual_worker"] == "finance-intake"

    # 가상 직원 자리에서 이 일괄이 보인다 (ADR-0085) — 저장하지 않고 읽을 때 잇는다.
    [batch] = client.get("/api/v1/virtual-workers/finance-intake", headers=READ).json()["batches"]
    assert (batch["run_id"], batch["children"], batch["children_by_status"]) == (done["run_id"], 3, {"success": 3})


def test_fx24_starts_nothing_when_the_batch_is_rejected(
    tmp_path: Path,
    center: CenterHandle,
    runner: agent_mod.Agent,
    receiver: Receiver,
) -> None:
    """반려하면 **하나도 기동하지 않는다** — 순서는 그림이 쥔다 (지도는 BPMN이다)."""
    client, _ = center
    child = deploy(center, runner, packaged(tmp_path, "fx25_batch_item"))
    info = deploy(center, runner, packaged(tmp_path, FX24))
    bind_virtual_worker(client, info["id"])
    job_id = dispatch(center, info, case_inputs(FX24, receiver))
    done = run_to_the_end(center, runner, job_id, answers={"Approve_Batch": {"승인": False}}, messages=[])
    assert done["run_status"] == "success", done
    assert batch_children(client, str(child["id"])) == []


def test_cancelling_the_batch_cancels_the_child_that_has_not_run(
    tmp_path: Path,
    center: CenterHandle,
    runner: agent_mod.Agent,
    receiver: Receiver,
) -> None:
    """**승인 뒤 일괄 취소** — 접수 실행을 취소하면 맡겨 둔 자식도 거둔다 (W6, ADR-0084).

    실행기를 잠깐 멈춰 **자식이 아직 시작되지 않은 순간**을 만든다 (결재 답은 멈춰도 내려간다).
    **병렬 반복이라 세 건이 한 번에 맡겨진다** (ADR-0087) — 한 건도 끝나지 않았는데 셋이 다
    있다는 것이 「함께 맡긴다」의 증거다. 취소하면 셋 모두 거둬진다.
    """
    client, _ = center
    child = deploy(center, runner, packaged(tmp_path, "fx25_batch_item"))
    info = deploy(center, runner, packaged(tmp_path, FX24))
    bind_virtual_worker(client, info["id"])
    job_id = dispatch(center, info, case_inputs(FX24, receiver))

    until = time.monotonic() + WAIT_S
    while not client.get("/api/v1/approvals", params={"state": "open"}, headers=READ).json():
        assert time.monotonic() < until, "일괄 결재가 올라오지 않았다"
        runner.tick()
        time.sleep(0.05)
    paused = client.post(f"/api/v1/server-runners/{runner.server_runner_id}/pause", headers=ADMIN)
    assert paused.status_code < 400, paused.text
    _answer_open_approvals(client, case_approvals(FX24), None)
    while len(batch_children(client, str(child["id"]))) < 3:
        assert time.monotonic() < until, "승인 뒤 세 건을 함께 맡기지 않았다"
        runner.tick()
        time.sleep(0.05)
    handed = batch_children(client, str(child["id"]))
    assert {one["state"] for one in handed} == {"pending"}, "한 건도 시작되지 않았는데 셋이 다 맡겨졌다"

    cancelled = client.delete(f"/api/v1/jobs/{job_id}", headers=ADMIN)
    assert cancelled.status_code == 202, cancelled.text
    while client.get(f"/api/v1/jobs/{job_id}", headers=READ).json().get("run_status") != "cancelled":
        assert time.monotonic() < until, "접수 실행이 닫히지 않았다"
        runner.tick()
        time.sleep(0.05)

    made = batch_children(client, str(child["id"]))
    assert [one["state"] for one in made] == ["cancelled"] * 3, made
