"""실행하는 쪽의 연결 — 받아서 **다시 검증하고** 꽂는다 (C13 「전송」, M5 조각 12).

진짜 Center를 in-process로 띄우고, 진짜 Admin 키로 서명하고, **진짜 외부 앱**을 127.0.0.1에
띄워 Bot UI → 실행기 → 어댑터까지 한 바퀴를 본다.

거듭 보는 것 다섯.

1. **봉투가 관문이다** — 손댄 정의·모르는 키·봉투 없는 정의는 쓰지 않는다 (C2 V1~V3, E6).
2. **패키지가 고정한 해시여야 한다** (C1) — 정의가 바뀌면 실행 **전에** 거절한다.
3. **닿지 못하면 들고 있던 것을 쓴다** (ADR-0007). **404는 버린다** (철회는 보안 동작이다).
4. **엔진은 어느 쪽인지 모른다** — 외부 확장은 어댑터로, 서비스 앱은 C11로 갈린다.
5. **그 Bot이 쓰는 것만** 파일에 담는다 (키 값은 담지 않는다, ADR-0013).
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from chaeksas.admin import keys as keystore
from chaeksas.bot_ui.center_client import CenterClient, CenterProblem, Unreachable
from chaeksas.bot_ui.services import Services, app_ids, external_ids
from chaeksas.center.api.signing import bootstrap_key
from chaeksas.center.app import create_app
from chaeksas.center.settings import Settings
from chaeksas.center.storage import Store
from chaeksas.contracts.extension import definition_hash
from chaeksas.contracts.manifest import Manifest
from chaeksas.contracts.signing import sign
from chaeksas.core.app_directory import build, read_directory, to_json_dict
from chaeksas.core.services import OpCall

TOKEN = "t-admin"
ADMIN = {"Authorization": f"Bearer {TOKEN}"}
PASS = "열쇠말"
AT = "2026-10-08T09:00:00+09:00"
APP = "ext-ocr"


# ─────────────────────────── 거리 ───────────────────────────


@pytest.fixture(autouse=True)
def _admin_home(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setenv(keystore.PASSPHRASE_ENV, PASS)
    monkeypatch.setenv(f"{keystore.ENV_PREFIX}DATA_DIR", str(tmp_path / "admin"))


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    made = Store(tmp_path / "center.sqlite3")
    yield made
    made.close()


@pytest.fixture
def client(tmp_path: Path, store: Store) -> Iterator[TestClient]:
    settings = Settings(
        db_path=tmp_path / "center.sqlite3",
        package_dir=tmp_path / "packages",
        admin_token=TOKEN,
        read_token="t-read",
    )
    with TestClient(create_app(settings, store=store)) as found:
        yield found


@pytest.fixture
def key(store: Store) -> Any:
    made = keystore.create(label="첫 키")
    bootstrap_key(store, public_key=made.public_bytes(), label="첫 키")
    return made


def public_keys(client: TestClient) -> list[Any]:
    """Center가 가진 Admin 공개키 — Bot UI는 하트비트로 받는다 (C4 `admin_keys`)."""
    from chaeksas.contracts.signing import AdminKey

    found = client.get("/api/v1/admin-keys", headers=ADMIN).json()
    return [AdminKey.model_validate(one) for one in found]


def definition(port: int, **over: Any) -> dict[str, Any]:
    """외부 OCR 앱. 시험이 띄운 127.0.0.1을 부르므로 사설 주소를 열어 둔다 (§4-3 4번)."""
    base: dict[str, Any] = {
        "schema": 2,
        "id": APP,
        "version": "1.0.0",
        "name": "외부 OCR",
        "publisher": "외부 업체",
        "tier": "external",
        "service": {
            "protocol": "http-adapter",
            "base_url": f"http://127.0.0.1:{port}",
            "adapter": {
                "allowed_hosts": ["127.0.0.1"],
                "allow_private_network": True,
                "auth": {"type": "bearer"},
                "limits": {"timeout_s": 5, "max_response_kb": 64},
                "operations": [
                    {
                        "name": "read_invoice",
                        "modes": ["autonomous", "deterministic"],
                        "idempotent": False,
                        "request": {
                            "method": "POST",
                            "path": "/v2/invoice",
                            "body": {"url": "{{input.file_url}}", "ref": "{{run_id}}"},
                        },
                        "response": {
                            "output": {"biz_no": "$.result.bizNo"},
                            "error_when": {"path": "$.status", "not_equals": "ok"},
                        },
                    }
                ],
            },
        },
        "requires_keys": [{"purpose": "run", "extra_scopes": []}],
        "contributes": {},
    }
    base.update(over)
    return base


def envelope_for(key: Any, found: dict[str, Any], **over: Any) -> Any:
    claim = {
        "kind": "extension",
        "id": found["id"],
        "version": found["version"],
        "definition_hash": definition_hash(found),
    }
    claim.update(over)
    return sign(claim, keystore.load(key, passphrase=PASS), signed_at=AT)


def register(client: TestClient, found: dict[str, Any], envelope: Any) -> Any:
    return client.post(
        "/api/v1/resources/extensions",
        json={"definition": found, "envelope": envelope.to_json_dict()},
        headers=ADMIN,
    )


class Ocr(BaseHTTPRequestHandler):
    """외부 OCR 앱 흉내 — 받은 것을 담아 두고 정해진 답을 준다."""

    seen: dict[str, Any] = {}

    def do_POST(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler 규약
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length) if length else b""
        type(self).seen = {
            "path": self.path,
            # 헤더 이름은 보낸 그대로의 대소문자로 온다 — 소문자로 모아 둔다.
            "headers": {name.lower(): value for name, value in self.headers.items()},
            "body": json.loads(raw or b"{}"),
        }
        payload = json.dumps({"status": "ok", "result": {"bizNo": "123-45-67890"}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: Any) -> None:  # 조용히
        return


@pytest.fixture
def ocr() -> Iterator[tuple[int, type[Ocr]]]:
    Ocr.seen = {}
    made = ThreadingHTTPServer(("127.0.0.1", 0), Ocr)
    thread = threading.Thread(target=made.serve_forever, daemon=True)
    thread.start()
    yield made.server_address[1], Ocr
    made.shutdown()
    made.server_close()
    thread.join(timeout=5)


def manifest(found: dict[str, Any] | None = None, **over: Any) -> Manifest:
    """그 외부 확장을 쓰는 패키지 하나 (C1). `definition_hash`로 정의를 고정한다."""
    requires: dict[str, Any] = {"extensions": [], "service_apps": []}
    if found is not None:
        requires["extensions"] = [
            {"id": found["id"], "version": found["version"], "definition_hash": definition_hash(found)}
        ]
    base: dict[str, Any] = {
        "schema": 1,
        "kind": "bpm_process",
        "id": "finance.invoice",
        "version": "1.0.0",
        "name": "세금계산서 처리",
        "entry": "process/main.bpmn",
        "process_id": "Proc_main",
        "run_location": "server",
        "requires": requires,
        "human": {},
        "built": {"by": "studio", "at": AT, "core": "0.1.0", "spec_version": 1},
        "content_hash": "sha256:" + "0" * 64,
    }
    base.update(over)
    return Manifest.model_validate(base)


def op_call(**over: Any) -> OpCall:
    base: dict[str, Any] = {
        "app_id": APP,
        "operation": "read_invoice",
        "mode": "deterministic",
        "input": {"file_url": "https://files.example.com/a.pdf"},
        "run_id": "run_20261008_090000_a1b2c3",
        "node_id": "Task_ocr",
        "key_ref": "ocr-key",
        "bpm_process_id": "finance.invoice",
        "version": "1.0.0",
    }
    base.update(over)
    return OpCall(**base)


# ─────────────────────────── 봉투를 다시 검증한다 (C13 「전송」) ───────────────────────────


def test_a_signed_definition_is_usable(client: TestClient, key: Any, ocr: tuple[int, type[Ocr]]) -> None:
    port, _ = ocr
    found = definition(port)
    made = build(
        to_json_dict(
            addresses={},
            keys=public_keys(client),
            extensions=[{"definition": found, "envelope": envelope_for(key, found).to_json_dict()}],
        )
    )
    assert set(made.externals) == {APP}
    assert made.problems == {}
    assert made.externals[APP].definition_hash == definition_hash(found)


def test_a_tampered_definition_is_refused(client: TestClient, key: Any, ocr: tuple[int, type[Ocr]]) -> None:
    """**한 글자만 고쳐도 쓰지 않는다** — 봉투는 그 정의에 대한 것이어야 한다 (E6)."""
    port, _ = ocr
    found = definition(port)
    envelope = envelope_for(key, found)
    # 주소를 다른 데로 돌린다 — 바로 이것을 막으려고 서명이 있다 (키가 다른 주소로 새는 것).
    tampered = {**found, "service": {**found["service"], "base_url": "https://evil.example.com"}}
    made = build(
        to_json_dict(
            addresses={}, keys=public_keys(client),
            extensions=[{"definition": tampered, "envelope": envelope.to_json_dict()}],
        )
    )
    assert made.externals == {}
    assert "hash_mismatch" in made.problems[APP]


def test_an_unknown_key_is_refused(ocr: tuple[int, type[Ocr]]) -> None:
    """Center에 등록되지 않은 키로 서명한 정의는 쓰지 않는다 (V2)."""
    port, _ = ocr
    found = definition(port)
    stranger = keystore.create(label="남의 키")
    made = build(
        to_json_dict(
            addresses={}, keys=[],
            extensions=[{"definition": found, "envelope": envelope_for(stranger, found).to_json_dict()}],
        )
    )
    assert made.externals == {}
    assert "unknown_key" in made.problems[APP]


def test_a_definition_without_an_envelope_is_refused(ocr: tuple[int, type[Ocr]]) -> None:
    """**서명이 유일한 관문이다** — 봉투 없는 정의는 쓰지 않는다 (C2)."""
    port, _ = ocr
    made = build({"keys": [], "extensions": [{"definition": definition(port)}]})
    assert made.externals == {}
    assert made.problems[APP] == "서명 봉투가 없다"


# ─────────────────────────── 패키지가 고정한 해시 (C1) ───────────────────────────


def test_a_changed_definition_is_unusable_for_that_package(
    client: TestClient, key: Any, ocr: tuple[int, type[Ocr]]
) -> None:
    """정의가 바뀌었으면 그 Bot은 **승인·배포를 다시 받아야 한다** — 몰래 새 정의로 돌지 않는다."""
    port, _ = ocr
    approved = definition(port)  # 패키지가 승인받을 때 본 정의
    newer = definition(port, version="1.1.0")  # Center에 올라온 새 판
    made = build(
        to_json_dict(
            addresses={}, keys=public_keys(client),
            extensions=[{"definition": newer, "envelope": envelope_for(key, newer).to_json_dict()}],
        )
    )
    unusable = made.unusable(manifest(approved).requires.extensions)
    assert len(unusable) == 1
    assert "패키지가 고정한 정의가 아니다" in unusable[0]


def test_a_missing_definition_is_unusable(ocr: tuple[int, type[Ocr]]) -> None:
    port, _ = ocr
    unusable = build({}).unusable(manifest(definition(port)).requires.extensions)
    assert len(unusable) == 1
    assert "정의를 받지 못했다" in unusable[0]


def test_a_builtin_extension_is_not_checked_here(client: TestClient) -> None:
    """내장·사내 확장은 정의가 설치 파일에 있다 (C13) — 받을 것도, 대조할 것도 없다."""
    needs = manifest(
        requires={"extensions": [{"id": "ui-automation", "version": ">=0.4,<1"}]}
    ).requires.extensions
    assert build({}).unusable(needs) == []


# ─────────────────────────── 꽂기 (엔진은 어느 쪽인지 모른다) ───────────────────────────


def test_the_engine_calls_the_external_app_through_the_adapter(
    client: TestClient, key: Any, ocr: tuple[int, type[Ocr]], tmp_path: Path
) -> None:
    """한 바퀴 — 파일로 받은 정의를 검증하고, 어댑터로 **진짜** 외부 앱을 부른다."""
    port, echo = ocr
    found = definition(port)
    path = tmp_path / "services.json"
    path.write_text(
        json.dumps(
            to_json_dict(
                addresses={}, keys=public_keys(client),
                extensions=[{"definition": found, "envelope": envelope_for(key, found).to_json_dict()}],
            )
        ),
        encoding="utf-8",
    )

    directory = read_directory(path, secrets=lambda ref: "ocr-secret-1" if ref == "ocr-key" else None)
    outcome = directory.caller().call(op_call())

    assert outcome.output == {"biz_no": "123-45-67890"}
    assert echo.seen["path"] == "/v2/invoice"
    assert echo.seen["headers"]["authorization"] == "Bearer ocr-secret-1"
    # 주소는 정의의 것이다 — 외부 앱은 C11이 아니라 Center 리소스 등록에 없다.
    assert echo.seen["body"] == {"url": "https://files.example.com/a.pdf", "ref": op_call().run_id}


def test_an_unverified_definition_is_not_called(key: Any, ocr: tuple[int, type[Ocr]], tmp_path: Path) -> None:
    """검증되지 않은 정의는 **부르지 않는다** — C11 쪽으로 가고 주소를 모른다고 실패한다."""
    from chaeksas.core.services import ServiceCallError

    port, echo = ocr
    found = definition(port)
    path = tmp_path / "services.json"
    # 공개키를 싣지 않았다 → 봉투를 검증할 수 없다.
    path.write_text(
        json.dumps(
            to_json_dict(
                addresses={}, keys=[],
                extensions=[{"definition": found, "envelope": envelope_for(key, found).to_json_dict()}],
            )
        ),
        encoding="utf-8",
    )
    directory = read_directory(path, secrets=lambda ref: "ocr-secret-1")
    with pytest.raises(ServiceCallError):
        directory.caller().call(op_call())
    assert echo.seen == {}, "검증되지 않았으면 **나가지 않는다**"


def test_a_service_app_goes_to_c11_not_the_adapter(tmp_path: Path) -> None:
    """서비스 앱(C11)은 어댑터로 가지 않는다 — 주소는 Center 등록에서 온다."""
    directory = build({"addresses": {"svc-erp": "https://127.0.0.1:1"}, "keys": [], "extensions": []})
    assert directory.base_url("svc-erp") == "https://127.0.0.1:1"
    caller = directory.caller()
    assert not caller.adapter.knows("svc-erp")  # type: ignore[attr-defined]


# ─────────────────────────── Bot UI가 받아 온다 (C7) ───────────────────────────


def test_bot_ui_fetches_and_writes_what_the_bot_uses(
    client: TestClient, key: Any, ocr: tuple[int, type[Ocr]], tmp_path: Path
) -> None:
    port, _ = ocr
    found = definition(port)
    assert register(client, found, envelope_for(key, found)).status_code == 201

    made = Services(
        data_dir=tmp_path / "data",
        client=CenterClient(base_url="http://center", api_key=TOKEN, client=client),
    )
    path = made.write_for(manifest(found), path=tmp_path / "run.services.json", keys=public_keys(client))

    assert path is not None
    body = json.loads(path.read_text(encoding="utf-8"))
    assert [one["definition"]["id"] for one in body["extensions"]] == [APP]
    assert body["keys"], "Admin 공개키가 함께 간다 (실행기가 다시 검증한다)"
    # 파일 그대로 실행기가 읽어 검증한다.
    assert set(read_directory(path).externals) == {APP}


def test_an_unreachable_center_uses_what_we_held(
    client: TestClient, key: Any, ocr: tuple[int, type[Ocr]], tmp_path: Path
) -> None:
    """**Center가 꺼졌다고 업무가 멈추지 않는다** (ADR-0007) — 들고 있던 정의를 쓴다."""
    port, _ = ocr
    found = definition(port)
    assert register(client, found, envelope_for(key, found)).status_code == 201
    data_dir = tmp_path / "data"
    good = Services(data_dir=data_dir, client=CenterClient(base_url="http://center", api_key=TOKEN, client=client))
    good.refresh(externals=[APP])

    class Dead:
        def service_apps(self) -> list[Any]:
            raise Unreachable("닿지 못했습니다")

        def extension(self, extension_id: str) -> Any:
            raise Unreachable("닿지 못했습니다")

    offline = Services(data_dir=data_dir, client=Dead())
    path = offline.write_for(manifest(found), path=tmp_path / "run.services.json", keys=public_keys(client))
    assert path is not None
    assert set(read_directory(path).externals) == {APP}
    assert offline.problems, "받지 못한 사유는 남는다"


def test_a_revoked_definition_is_dropped(
    client: TestClient, key: Any, ocr: tuple[int, type[Ocr]], tmp_path: Path
) -> None:
    """**404는 버린다** — 철회된 정의로 돌리는 것이 모르고 멈추는 것보다 나쁘다 (C13)."""
    port, _ = ocr
    found = definition(port)
    assert register(client, found, envelope_for(key, found)).status_code == 201
    data_dir = tmp_path / "data"
    made = Services(data_dir=data_dir, client=CenterClient(base_url="http://center", api_key=TOKEN, client=client))
    made.refresh(externals=[APP])
    assert made.cached()["extensions"], "들고 있다"

    class Revoked:
        def service_apps(self) -> list[Any]:
            return []

        def extension(self, extension_id: str) -> Any:
            raise CenterProblem("없다", code="not_found", status=404)

    after = Services(data_dir=data_dir, client=Revoked())
    after.refresh(externals=[APP])
    assert after.cached()["extensions"] == []
    assert "철회됐을 수 있습니다" in " ".join(after.problems)


def test_only_what_the_manifest_asks_for_goes_in_the_file(
    client: TestClient, key: Any, ocr: tuple[int, type[Ocr]], tmp_path: Path
) -> None:
    """**필요한 것만 준다** — 다른 Bot이 쓰는 확장의 정의는 담지 않는다."""
    port, _ = ocr
    found = definition(port)
    other = definition(port, id="ext-credit", name="외부 신용")
    for one in (found, other):
        assert register(client, one, envelope_for(key, one)).status_code == 201

    made = Services(
        data_dir=tmp_path / "data",
        client=CenterClient(base_url="http://center", api_key=TOKEN, client=client),
    )
    path = made.write_for(manifest(found), path=tmp_path / "run.services.json", keys=public_keys(client))
    assert path is not None
    body = json.loads(path.read_text(encoding="utf-8"))
    assert [one["definition"]["id"] for one in body["extensions"]] == [APP]


def test_a_bot_that_calls_nothing_gets_no_file(tmp_path: Path) -> None:
    made = Services(data_dir=tmp_path / "data")
    assert made.write_for(manifest(), path=tmp_path / "run.services.json", keys=[]) is None


def test_what_the_manifest_asks_for(ocr: tuple[int, type[Ocr]]) -> None:
    """외부 확장은 `definition_hash`가 적힌 것이고, 서비스 앱은 따로 센다 (C1)."""
    port, _ = ocr
    found = manifest(
        definition(port),
        requires={
            "extensions": [
                {"id": APP, "version": "1.0.0", "definition_hash": definition_hash(definition(port))},
                {"id": "ui-automation", "version": ">=0.4,<1"},
            ],
            "service_apps": [{"app_id": "svc-erp", "operations": ["lookup"], "key_ref": "erp-key"}],
        },
    )
    assert external_ids(found) == [APP]
    assert app_ids(found) == ["svc-erp"]


# ─────────────────────────── 실행기까지 (한 바퀴) ───────────────────────────


SHELL = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:chk="urn:chaeksas:bpmn:1" id="Defs">
  <bpmn:process id="finance.invoice" name="세금계산서 처리">
    <bpmn:extensionElements><chk:process>{props}</chk:process></bpmn:extensionElements>
    <bpmn:startEvent id="Start_1"/>
    <bpmn:serviceTask id="Task_Ocr"><bpmn:extensionElements><chk:serviceCall>{call}
    </chk:serviceCall></bpmn:extensionElements></bpmn:serviceTask>
    <bpmn:endEvent id="End_1"/>
    <bpmn:sequenceFlow id="f1" sourceRef="Start_1" targetRef="Task_Ocr"/>
    <bpmn:sequenceFlow id="f2" sourceRef="Task_Ocr" targetRef="End_1"/>
  </bpmn:process>
</bpmn:definitions>
"""

PROPS = '{"service_keys": {"ext-ocr": "ocr-key"}, "inputs": [{"name": "파일", "type": "string"}]}'
CALL = (
    '{"app_id": "ext-ocr", "operation": "read_invoice", "input": {"file_url": "파일"},'
    ' "output": {"사업자번호": "biz_no"}}'
)


def package_at(folder: Path, found: dict[str, Any]) -> Path:
    """그 외부 확장을 부르는 패키지 하나를 풀어 놓은 모양으로 (C1)."""
    (folder / "process").mkdir(parents=True, exist_ok=True)
    (folder / "process" / "main.bpmn").write_text(
        SHELL.format(props=PROPS, call=CALL), encoding="utf-8"
    )
    (folder / "manifest.json").write_text(
        json.dumps(manifest(found).to_json_dict(), ensure_ascii=False, default=str), encoding="utf-8"
    )
    return folder


def services_file(path: Path, client: TestClient, key: Any, found: dict[str, Any]) -> Path:
    path.write_text(
        json.dumps(
            to_json_dict(
                addresses={}, keys=public_keys(client),
                extensions=[{"definition": found, "envelope": envelope_for(key, found).to_json_dict()}],
            )
        ),
        encoding="utf-8",
    )
    return path


def test_the_runner_calls_the_external_app_end_to_end(
    client: TestClient, key: Any, ocr: tuple[int, type[Ocr]], tmp_path: Path, monkeypatch: Any
) -> None:
    """한 바퀴 — 패키지 → 명부 검증 → 엔진 → **진짜 외부 앱** → 변수 → C3 기록."""
    from chaeksas.bot_ui.runner_main import Package, Runner, app_directory, make_env, refuse_unusable
    from chaeksas.core.engine import State
    from chaeksas.core.run_log import RunLog, log_path

    port, echo = ocr
    found = definition(port)
    package = Package.read(package_at(tmp_path / "bot", found))
    path = services_file(tmp_path / "run.services.json", client, key, found)
    # 키 값은 실행기가 OS 비밀 저장소·환경변수에서 푼다 (ADR-0013).
    monkeypatch.setenv("CHK_BOT_UI__SVC__OCR_KEY", "ocr-secret-1")

    directory = app_directory(path)
    refuse_unusable(package, directory)  # 쓸 수 있다 — 그림대로 돈다
    data_dir = tmp_path / "data"
    runner = Runner(
        run_id="run_20261008_090000_a1b2c3",
        package=package,
        data_dir=data_dir,
        inputs={"파일": "https://files.example.com/a.pdf"},
        env=make_env(
            package,
            output_dir=tmp_path / "out",
            readable=(),
            llm_model="",
            directory=directory,
        ),
    )
    assert runner.drive(deadline_s=20) is State.DONE
    assert runner.run is not None
    assert runner.run.variables["사업자번호"] == "123-45-67890"
    assert echo.seen["headers"]["authorization"] == "Bearer ocr-secret-1"

    calls = [one for one in RunLog.read(log_path(data_dir, runner.run_id)) if one.kind == "service_call"]
    assert len(calls) == 1
    assert calls[0].data["app_id"] == "ext-ocr"
    assert calls[0].data["key_ref"] == "ocr-key", "**참조 이름만** 기록에 간다 (ADR-0013)"
    assert "123-45-67890" not in json.dumps(calls[0].data, ensure_ascii=False), "업무 값은 기록에 없다"


def test_the_runner_refuses_to_start_when_the_definition_changed(
    client: TestClient, key: Any, ocr: tuple[int, type[Ocr]], tmp_path: Path
) -> None:
    """**실행 전에** 거절한다 — 중간에 알면 이미 한 일을 되돌릴 수 없다 (C1)."""
    from chaeksas.bot_ui.runner_main import Package, app_directory, refuse_unusable
    from chaeksas.core.engine import EngineError

    port, _ = ocr
    approved = definition(port)
    package = Package.read(package_at(tmp_path / "bot", approved))
    # Center에는 새 판이 올라와 있다 — 승인받은 그 정의가 아니다.
    newer = definition(port, version="1.1.0")
    path = services_file(tmp_path / "run.services.json", client, key, newer)

    with pytest.raises(EngineError) as caught:
        refuse_unusable(package, app_directory(path))
    assert caught.value.code == "extension_definition_unusable"
