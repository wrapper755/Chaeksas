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
import re
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from canned_answers import canned
from fastapi.testclient import TestClient
from stub_model import StubModel

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from chaeksas.admin import keys as keystore  # noqa: E402
from chaeksas.center.api.signing import bootstrap_key  # noqa: E402
from chaeksas.center.app import create_app  # noqa: E402
from chaeksas.center.settings import Settings as CenterSettings  # noqa: E402
from chaeksas.center.storage import Store, now_iso  # noqa: E402
from chaeksas.contracts.bpmn_ext import read_process  # noqa: E402
from chaeksas.contracts.extension import definition_hash  # noqa: E402
from chaeksas.contracts.signing import sign  # noqa: E402
from chaeksas.mock_apps import catalog  # noqa: E402
from chaeksas.mock_apps.c11 import SHARED_KEY_ENV  # noqa: E402
from chaeksas.mock_apps.c11 import build as build_mock  # noqa: E402
from chaeksas.mock_apps.external import apps as external_apps  # noqa: E402
from chaeksas.mock_apps.external import definitions as external_definitions  # noqa: E402
from chaeksas.server_runner import agent as agent_mod  # noqa: E402
from chaeksas.server_runner.center_client import CenterClient  # noqa: E402
from chaeksas.server_runner.credentials import service_key_env  # noqa: E402
from chaeksas.server_runner.settings import Settings as RunnerSettings  # noqa: E402
from chaeksas.studio.packaging import default_name, export  # noqa: E402
from chaeksas.studio.workspace import Workspace  # noqa: E402

DOCS = Path(__file__).resolve().parent.parent / "docs" / "08-business-examples"
EXAMPLES = DOCS / "bpmn"

ADMIN_TOKEN = "t-admin"
ADMIN = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
READ = {"Authorization": "Bearer t-read"}
SIGN_PASS = "열쇠말"
SIGNED_AT = "2026-10-14T09:00:00+09:00"
CENTER_URL = "http://testserver"

#: 모의 앱이 받는 키 하나 (`samples/README.md`).
DEV_KEY = "chk_svc_m7rerunkey000000000000000000000000000"

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


def case_inputs(example: str) -> dict[str, Any]:
    """작업 지시로 줄 입력 — 케이스의 `inputs`를 그대로 (C5 `inputs`)."""
    return dict(_first_case(example).get("inputs") or {})


def case_approvals(example: str) -> dict[str, dict[str, Any]]:
    """Center 결재함에서 답할 것 — 케이스가 노드 id로 적어 둔 답."""
    return dict(_first_case(example).get("approvals") or {})


def case_messages(example: str) -> list[dict[str, Any]]:
    """외부 시스템이 넣을 메시지 — 케이스의 `messages` 그대로 (C12 §메시지)."""
    return [dict(one) for one in (_first_case(example).get("messages") or [])]


# ─────────────────────────── 판 깔기 ───────────────────────────


@pytest.fixture(autouse=True)
def admin_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`chk-admin`의 개인키가 사는 곳 — 임시 폴더다 (개발 PC를 건드리지 않는다)."""
    monkeypatch.setenv(keystore.PASSPHRASE_ENV, SIGN_PASS)
    monkeypatch.setenv(f"{keystore.ENV_PREFIX}DATA_DIR", str(tmp_path / "admin"))


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


@pytest.fixture(scope="session")
def mock_apps() -> Iterator[tuple[dict[str, str], dict[str, str]]]:
    """모의 앱들을 띄운다 (`samples/mock_apps`). `(C11 앱들, 외부 앱들)`.

    **확장이 Center에 없으면 배포가 막히므로**(C7 누락 검사) 둘 다 알려야 한다 — 사내 확장은
    서비스 앱 manifest의 `extension` 칸이 출처이고, **외부 확장은 서명 봉투로 등록한다**
    (C13 E6). 외부 둘(`ext-credit`·`ext-helpdesk`)은 `service_kit`을 쓰지 않으므로 C11로
    등록할 수 없다.

    C11 앱 열넷은 **한 포트**에 `/<app_id>`로 모으고, 외부 앱 둘은 **각자 포트**다 (M5 인수
    시험과 같은 까닭) — `AdapterCaller`는 `base_url`의 **경로를 버리고** 호스트·포트만 쓰므로
    (§4-3의 DNS 고정이 origin 단위다) 경로 접두사 뒤에 둘 수 없다.
    """
    from fastapi import FastAPI  # noqa: PLC0415

    os.environ[SHARED_KEY_ENV] = DEV_KEY
    held = []
    root = FastAPI(title="모의 서비스 앱 (서버 재통과)")
    for one in catalog.C11_APPS:
        root.mount(f"/{one.app_id}", build_mock(one).app)
    shared, server, thread = serve(root)
    held.append((server, thread))

    external: dict[str, str] = {}
    for app_id, make in external_apps.BUILDERS.items():
        base, one_server, one_thread = serve(make())
        held.append((one_server, one_thread))
        external[app_id] = base

    yield {one.app_id: f"{shared}/{one.app_id}" for one in catalog.C11_APPS}, external
    for one_server, one_thread in held:
        one_server.should_exit = True
        one_thread.join(timeout=10)


@pytest.fixture
def center(
    tmp_path: Path, mock_apps: tuple[dict[str, str], dict[str, str]]
) -> Iterator[tuple[TestClient, Store, Any]]:
    """진짜 Center + 첫 Admin 공개키 + 등록된 모의 앱들. `(client, store, 서명 키)`."""
    c11, external = mock_apps
    store = Store(tmp_path / "center.sqlite3")
    settings = CenterSettings(
        db_path=tmp_path / "center.sqlite3",
        package_dir=tmp_path / "packages",
        admin_token=ADMIN_TOKEN,
        read_token="t-read",
    )
    with TestClient(create_app(settings, store=store)) as client:
        key = keystore.create(label="서버 재통과")
        bootstrap_key(store, public_key=key.public_bytes(), label="서버 재통과")
        for app_id, base_url in c11.items():
            answer = client.post(
                "/api/v1/resources/service-apps", json={"base_url": base_url}, headers=ADMIN
            )
            assert answer.status_code < 400, f"{app_id}: {answer.text}"
        signer = keystore.load(key, passphrase=SIGN_PASS)
        for app_id, base_url in external.items():
            # 정의는 **주소를 담아 커밋할 수 없어** 그 자리에서 짓는다 (`samples/README.md`).
            found = external_definitions.BUILDERS[app_id](base_url)
            envelope = sign(
                {
                    "kind": "extension",
                    "id": found["id"],
                    "version": found["version"],
                    "definition_hash": definition_hash(found),
                },
                signer,
                signed_at=SIGNED_AT,
            )
            answer = client.post(
                "/api/v1/resources/extensions",
                json={"definition": found, "envelope": envelope.to_json_dict()},
                headers=ADMIN,
            )
            assert answer.status_code < 400, f"{app_id}: {answer.text}"
        yield client, store, key
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


def service_key_refs() -> list[str]:
    """예제가 쓰는 서비스 앱 키 **참조 이름** 전부 — **그림에서 읽는다**.

    사람이 옮겨 적으면 예제가 늘 때 묶음이 조용히 뒤처진다 (대상 목록과 같은 결).
    **두 자리에 있다** — BPM 프로세스가 상속하는 `service_keys`와 태스크가 따로 적은
    `chk:serviceCall.key_ref`다 (C1 `key_ref`·`task_key_refs` — 사전 점검도 둘을 센다).
    """
    found: set[str] = set()
    for path in sorted(EXAMPLES.glob("*.bpmn")):
        process = read_process(path.read_text(encoding="utf-8"))
        found |= {ref for ref in process.info.service_keys.values() if ref}
        for node in process.all_nodes():
            call = node.prop("serviceCall")
            if call is not None and call.key_ref:
                found.add(call.key_ref)
    return sorted(found)


@pytest.fixture(autouse=True)
def service_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """참조마다 키 값을 **환경변수로** 준다 — 운영자가 서버에서 하는 일이다 (ADR-0013).

    모의 앱은 키 하나를 받으므로(`CHK_MOCK_APPS__DEV_KEY`) 값은 모두 같다. **설정 파일에는
    넣지 않는다** — 참조 이름만 BPM 프로세스에 있고 값은 이 서버만 안다.
    """
    for ref in service_key_refs():
        monkeypatch.setenv(service_key_env(ref), DEV_KEY)


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
    tmp_path: Path, center: tuple[TestClient, Store, Any], model: StubModel, mail: Any
) -> agent_mod.Agent:
    """진짜 서버 실행기 — Center는 in-process이고 실행은 **제 스레드**로 돈다.

    모델·읽기 폴더·서비스 앱 키·**보내기**는 **설정·환경변수로** 준다 (운영자가 하는 일).
    **바깥 앱 명부는 실행기가 제 손으로 Center에서 받는다** (C7 — 파일을 거치지 않는다).

    메일은 127.0.0.1의 작은 SMTP 서버로 가고 **암호화하지 않는다**(`none` — 시험 서버가 TLS를
    모른다. 사내 중계기를 쓰는 현장과 같은 고름이다). **웹훅 허용 호스트는 비워 둔다** —
    `$test_receiver`는 Studio 전용이고(C14) 배포된 Bot은 사설망으로 보내지 않으므로, 웹훅을
    쓰는 예제는 이 묶음에서 돌 수 없다 (`REMAINING`).
    """
    client, _, _ = center
    key = client.post(
        "/api/v1/center-keys", json={"name": "시험 서버", "type": "server_runner"}, headers=ADMIN
    ).json()["key"]
    settings = RunnerSettings(
        center_url=CENTER_URL,
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
    )
    settings.data_path.mkdir(parents=True, exist_ok=True)
    settings.runs_dir.mkdir(parents=True, exist_ok=True)
    return agent_mod.Agent(
        settings=settings,
        client=CenterClient(base_url=CENTER_URL, api_key=key, client=client),
    )


# ─────────────────────────── 배포 (C2·C5) ───────────────────────────


def packaged(tmp_path: Path, example: str) -> Path:
    """Studio가 하듯 내보낸다 — 매니페스트는 **그림에서 모은다** (`studio.packaging`)."""
    space = Workspace(tmp_path / "studio" / example).ensure()
    made = space.import_example(EXAMPLES, example)
    return export(made, tmp_path / default_name(made))


def deploy(
    center: tuple[TestClient, Store, Any], runner: agent_mod.Agent, zip_path: Path
) -> dict[str, Any]:
    """업로드 → **승인 서명** → **배포 서명** → 하트비트로 설치까지 (C2 V1~V7).

    서명이 유일한 관문이다 — 관리자 토큰만으로는 아무것도 배포되지 않는다.
    """
    client, _, key = center
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
    answer = client.put(
        f"/api/v1/packages/{info['id']}/{info['version']}/signature",
        json=approve.to_json_dict(),
        headers=ADMIN,
    )
    assert answer.status_code < 400, answer.text

    # 실행기가 등록되어야 배포 대상이 생긴다 (C12 — 키 하나 ↔ 서버 하나).
    runner.tick()
    assert runner.server_runner_id, "실행기가 등록되지 않았다"

    envelope = sign(
        {
            "kind": "deployment",
            "deployment_id": "dep_" + re.sub(r"[^0-9a-f]", "", info["content_hash"])[:8],
            "target": {"type": "server_runner", "id": runner.server_runner_id},
            "bpm_process_id": info["id"],
            "version": info["version"],
            "content_hash": info["content_hash"],
        },
        signer,
        signed_at=now_iso(),
    )
    answer = client.post("/api/v1/deployments", json=envelope.to_json_dict(), headers=ADMIN)
    assert answer.status_code < 400, answer.text

    runner.tick()  # 공개키·배포를 받아 설치한다
    assert info["id"] in [one.id for one in runner.installed_bots()], (
        f"{info['id']}가 설치되지 않았다"
    )
    return info


def dispatch(
    center: tuple[TestClient, Store, Any], info: dict[str, Any], inputs: dict[str, Any]
) -> str:
    """Center 작업 지시 하나 (C5 — `id`를 비우면 Center가 고른다)."""
    client, _, _ = center
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
    client: TestClient, answers: dict[str, dict[str, Any]], run_id: str | None
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


def _post_message(client: TestClient, message: dict[str, Any]) -> bool:
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
    center: tuple[TestClient, Store, Any],
    runner: agent_mod.Agent,
    job_id: str,
    *,
    answers: dict[str, dict[str, Any]],
    messages: list[dict[str, Any]],
    timeout_s: float = WAIT_S,
) -> dict[str, Any]:
    """하트비트를 돌리며 결재에 답하고 메시지를 넣는다. 끝난 작업 정보를 돌려준다.

    **답·메시지는 Center를 거친다** — 서버 실행기에는 현장 창구가 없다 (C12).
    """
    client, _, _ = center
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
        time.sleep(0.05)
    raise AssertionError(
        f"작업 {job_id}이 끝나지 않았다 — 마지막 상태 "
        f"{client.get(f'/api/v1/jobs/{job_id}', headers=READ).json()}"
    )


# ─────────────────────────── 묶음 ───────────────────────────

# 아직 **돌리지는** 못하는 까닭 여섯. **짜 둔 모델 답도 이제 있다** (조각 12) — M3·M5와 **같은
# 자리**에서 온다 (`tests/canned_answers.py`). 남은 것은 **플랫폼이 아니라 묶음·계약 쪽**이다.
#
# - **계약이 가른 것**: 웹훅 넷 (`_WEBHOOK` — `$test_receiver`는 Studio 전용이다, C14). 가장 큰
#   묶음이고 **「아직」이 아니다**.
# - **묶음에 없는 것**: 시계·신호·소켓 Center·표본 파일·케이스 입력 연산자
#   (`_TIMER`·`_SIGNAL`·`_NO_SOCKET`·`_NO_SAMPLES`·`_NO_INPUT_OPS`).
# - **일부러 실패하는 것**: BX-33 (`_ON_PURPOSE` — 아래에 따로 시험이 있다).
#
# **사유는 돌려 보고 적는다.** 조각 9에서 일곱이 틀렸고(셋은 이미 초록이었다), 조각 10에서 둘,
# 조각 12에서 또 둘이다 — BX-10·BX-30은 `_NO_CANNED`로 적혀 있었지만 답을 주니 **그 뒤의
# 웹훅**에서 멈췄다. 첫 실패만 보고 적으면 그다음 까닭을 모른 채로 남는다.
_WEBHOOK = (
    "**웹훅은 이 묶음에서 보낼 곳이 없다** — 케이스가 `$test_receiver`를 가리키는데 그것은 "
    "**Studio 시험 실행 전용**이고(C14), 배포된 Bot은 사설망으로 웹훅을 보내지 않는다 "
    "(ADR-0059 §2 — 허용 호스트에 적어도 루프백은 열리지 않는다). 바깥에 나가지 않으므로 "
    "공개 주소에 수신기를 둘 수도 없다. **계약이 가른 자리**라 「아직」이 아니다. "
)
_NO_SAMPLES = (
    "묶음이 **표본 파일**을 만들지 않는다 — 그림이 `samples/<…>` 폴더를 읽는데 저장소에 "
    "이진 파일을 두지 않으므로(M3·M5 묶음은 **그 자리에서 만든다**) 폴더가 없다. "
    "그 자리를 옮겨 오는 것이 다음 일이다. "
)
_NO_INPUT_OPS = (
    "묶음이 **케이스 입력 연산자**를 풀지 않는다 — 케이스가 `{\"$now_plus\": \"PT20S\"}`를 "
    "적어 두었고(C14 — 시험 입력의 연산자다) 그것을 시각으로 바꾸는 것은 **Studio 시험 "
    "실행의 일**이다. 작업 지시(C5)에는 그런 연산자가 없어 타이머가 그 dict를 읽다 멈춘다. "
)

# 아래 셋은 실행기가 아니라 **묶음**에 없는 것이다.
_TIMER = (
    "실제 시계를 기다린다 — 묶음이 시계를 돌릴 수단이 없다 (실행기는 `RunEnv.clock`을 "
    "바깥에서 받지 않는다). Studio 시험 실행은 `QTimer`를 앞당겨 본다. "
)
_SIGNAL = (
    "신호를 넣을 길이 묶음에 없다 — C12 메시지 API는 **메시지**를 넣고(§메시지) 신호는 "
    "엔진의 `signal()`이라 Center를 거치지 않는다. "
)
_NO_SOCKET = (
    "모의 앱 `center-jobs`가 **진짜 Center 주소**를 받아야 한다 "
    "(`CHK_SVC_CENTER_JOBS__CENTER__BASE_URL`·`__TOKEN`) — 이 묶음의 Center는 in-process "
    "(`TestClient`)라 다른 스레드의 앱이 부를 주소가 없다. M5 인수 시험은 그 하나를 위해 "
    "Center를 **진짜 소켓**에 올렸다 (BX-16). 여기서도 그렇게 하는 것이 다음 일이다. "
)

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
#: 막힌 것은 **도는 것**이고, 배포 길은 42개 전부가 지나간다.
REMAINING: dict[str, str] = {
    "bx01_invoice_reconciliation": _NO_SAMPLES,
    "bx10_vendor_onboarding_review": _WEBHOOK,
    "bx11_bid_collection": _NO_INPUT_OPS,
    "bx16_reorder_proposal": _NO_SOCKET,
    "bx21_leave_request": _WEBHOOK,
    "bx30_contract_review": _WEBHOOK,
    "bx33_access_request": _ON_PURPOSE,
    "fx04_folder_poll": _TIMER,
    "fx10_operator_routing": _WEBHOOK,
    "fx13_signal": _SIGNAL,
    "fx14_timers": _TIMER,
}

GREEN = [one for one in SERVER if one not in REMAINING]


def test_the_server_examples_are_read_from_the_drawings() -> None:
    """목록은 **그림이 정한다** — 사람이 옮겨 적지 않는다 (README 묶음 표의 「서버 예제 전부」)."""
    assert len(SERVER) >= 40, f"서버 예제가 너무 적다: {SERVER}"
    assert "bx03_expense_approval" in SERVER
    assert "fx03b_amount_branch" in SERVER
    # PC 예제는 여기 들지 않는다 (그쪽은 `test_m5_pc_rerun.py`다).
    assert "bx04_tax_invoice_issue" not in SERVER


def test_every_server_example_is_in_the_bundle_or_has_a_reason() -> None:
    """빼는 것은 **이유와 함께** 적는다 (M4·M5 인수 시험과 같은 자리)."""
    assert set(GREEN) | set(REMAINING) == set(SERVER)
    for example, why in REMAINING.items():
        assert example in SERVER, f"{example}는 서버 예제가 아니다"
        assert why.strip(), f"{example}: 이유가 비었다"


@pytest.mark.parametrize("example", SERVER)
def test_every_server_example_deploys_and_installs(
    example: str,
    tmp_path: Path,
    center: tuple[TestClient, Store, Any],
    runner: agent_mod.Agent,
) -> None:
    """**배포 길은 42개 전부가 지나간다** — 막힌 것은 *도는 것*이지 배포가 아니다.

    여기서 새로운 것이 배포 길이다(서버 대상 봉투·`"*"`·C7 누락 검사) — PC 재통과가 여덟 개
    모두 배포까지 보는 것과 같은 결이다. 끝까지 도는 것은 아래 시험이 본다.
    """
    info = deploy(center, runner, packaged(tmp_path, example))
    assert info["id"], example


@pytest.mark.parametrize("example", GREEN)
def test_a_server_example_runs_through_center_and_the_runner(
    example: str,
    tmp_path: Path,
    center: tuple[TestClient, Store, Any],
    runner: agent_mod.Agent,
) -> None:
    """한 줄로 본다: 서명 → 배포 → 설치 → **Center 작업 지시** → 실행 → Center가 안다.

    **업무 값은 보지 않는다** (C3에 없다 — 원칙 6). 결과가 맞는지는 Studio 시험 실행이 본다.
    """
    info = deploy(center, runner, packaged(tmp_path, example))
    job_id = dispatch(center, info, case_inputs(example))
    done = run_to_the_end(
        center,
        runner,
        job_id,
        answers=case_approvals(example),
        messages=case_messages(example),
    )
    assert done["run_status"] == "success", f"{example}: {done}"


def test_bx33_fails_on_purpose_on_the_server_too(
    tmp_path: Path, center: tuple[TestClient, Store, Any], runner: agent_mod.Agent
) -> None:
    """BX-33은 **일부러 실패한다** (ADR-0039) — 서버에서도 **같은 식 오류**로 멈춘다.

    지나지 않은 가지에서만 생기는 값을 뒤에서 읽는 교육 예제다 (B11 경고가 가리키는 그 하나).
    빼지 않고 **의도한 실패를 본다** — 그냥 `REMAINING`에 두면 「언젠가 초록이 될 것」으로
    읽히고, 어느 날 다른 이유로 실패해도 아무도 모른다 (M5 인수 시험과 같은 자리).
    """
    client, _, _ = center
    info = deploy(center, runner, packaged(tmp_path, "bx33_access_request"))
    job_id = dispatch(center, info, case_inputs("bx33_access_request"))
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
