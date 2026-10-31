"""외부 확장 정의 — 받아서 **다시 검증하고** 대조한다, 그리고 어댑터 일꾼까지 한 바퀴 (C13 「전송」·C15).

진짜 Center를 띄우고, **Center의 서명 키**로 서명하고(ADR-0090), **진짜 외부 앱**을 127.0.0.1에 띄워
실행기 → Center → **어댑터 일꾼** → 외부 앱까지 한 바퀴를 본다 (ADR-0102 — 실행하는 쪽은 외부 앱을
부르지 않는다).

거듭 보는 것 다섯.

1. **봉투가 관문이다** — 손댄 정의·모르는 키·봉투 없는 정의는 쓰지 않는다 (C2 V1~V3, E6).
2. **패키지가 고정한 해시여야 한다** (C1) — 정의가 바뀌면 실행 **전에** 거절한다.
3. **닿지 못하면 들고 있던 것을 쓴다** (ADR-0007). **404는 버린다** (철회는 보안 동작이다).
4. **외부 앱의 키는 어댑터 일꾼만 안다** — 실행하는 쪽·Center·실행 기록 어디에도 없다.
5. **그 BPM 프로세스가 쓰는 것만** 파일에 담는다.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from center_admin import register_extension
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from chaeksas.bot_ui.center_client import CenterClient, CenterProblem, Unreachable
from chaeksas.center import signer as center_signer
from chaeksas.center.app import create_app
from chaeksas.center.settings import Settings
from chaeksas.center.storage import Store
from chaeksas.contracts.extension import definition_hash
from chaeksas.contracts.manifest import Manifest
from chaeksas.contracts.signing import sign
from chaeksas.core.app_directory import (
    DirectoryCache,
    build,
    extension_ids,
    external_ids,
    read_directory,
    to_json_dict,
)
from chaeksas.core.services import OpCall

TOKEN = "t-admin"
ADMIN = {"Authorization": f"Bearer {TOKEN}"}
AT = "2026-10-08T09:00:00+09:00"
APP = "ext-ocr"


# ─────────────────────────── 거리 ───────────────────────────


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
    """Center가 서명하는 키 — 공개키는 하트비트의 `admin_keys`로 현장에 간다 (ADR-0090 §5).

    정의를 손대거나 봉투를 따로 지어 보는 시험이 이 키로 직접 서명한다.
    """
    return center_signer.active(store)


def public_keys(client: TestClient) -> list[Any]:
    """Center가 믿는 공개키(Center 키) — PC 실행기는 하트비트로 받는다 (C4 `admin_keys`)."""
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
    return sign(claim, key, signed_at=AT)


def register(client: Any, found: dict[str, Any]) -> Any:
    """관리자가 정의를 올린다 — 봉투는 Center가 짓는다 (ADR-0090)."""
    return register_extension(client, found, expect=None)


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

    def do_GET(self) -> None:  # noqa: N802 — 어댑터 `health` (C13 §4-1)
        self.send_response(200 if self.path == "/health" else 404)
        self.send_header("Content-Length", "0")
        self.end_headers()

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
            keys=public_keys(client),
            extensions=[{"definition": tampered, "envelope": envelope.to_json_dict()}],
        )
    )
    assert made.externals == {}
    assert "hash_mismatch" in made.problems[APP]


def test_an_unknown_key_is_refused(ocr: tuple[int, type[Ocr]]) -> None:
    """Center에 등록되지 않은 키로 서명한 정의는 쓰지 않는다 (V2)."""
    port, _ = ocr
    found = definition(port)
    stranger = Ed25519PrivateKey.generate()
    made = build(
        to_json_dict(
            keys=[],
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
    """정의가 바뀌었으면 그 BPM 프로세스는 **승인·배포를 다시 받아야 한다** — 몰래 새 정의로 돌지 않는다."""
    port, _ = ocr
    approved = definition(port)  # 패키지가 승인받을 때 본 정의
    newer = definition(port, version="1.1.0")  # Center에 올라온 새 판
    made = build(
        to_json_dict(
            keys=public_keys(client),
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


# ─────────────────────────── PC 실행기가 받아 온다 (C7) ───────────────────────────


def test_bot_ui_fetches_and_writes_what_the_bot_uses(
    client: TestClient, ocr: tuple[int, type[Ocr]], tmp_path: Path
) -> None:
    port, _ = ocr
    found = definition(port)
    assert register(client, found).status_code == 201

    made = DirectoryCache.using(
        tmp_path / "data", CenterClient(base_url="http://center", api_key=TOKEN, client=client)
    )
    path = made.write_for(manifest(found), path=tmp_path / "run.services.json", keys=public_keys(client))

    assert path is not None
    body = json.loads(path.read_text(encoding="utf-8"))
    assert [one["definition"]["id"] for one in body["extensions"]] == [APP]
    assert body["keys"], "Admin 공개키가 함께 간다 (실행기가 다시 검증한다)"
    # 파일 그대로 실행기가 읽어 검증한다.
    assert set(read_directory(path).externals) == {APP}


def test_an_unreachable_center_uses_what_we_held(
    client: TestClient, ocr: tuple[int, type[Ocr]], tmp_path: Path
) -> None:
    """**Center가 꺼졌다고 업무가 멈추지 않는다** (ADR-0007) — 들고 있던 정의를 쓴다."""
    port, _ = ocr
    found = definition(port)
    assert register(client, found).status_code == 201
    data_dir = tmp_path / "data"
    good = DirectoryCache.using(
        data_dir, CenterClient(base_url="http://center", api_key=TOKEN, client=client)
    )
    good.refresh(externals=[APP])

    class Dead:
        def extension(self, extension_id: str) -> Any:
            raise Unreachable("닿지 못했습니다")

    offline = DirectoryCache.using(data_dir, Dead())
    path = offline.write_for(manifest(found), path=tmp_path / "run.services.json", keys=public_keys(client))
    assert path is not None
    assert set(read_directory(path).externals) == {APP}
    assert offline.problems, "받지 못한 사유는 남는다"


def test_a_revoked_definition_is_dropped(
    client: TestClient, ocr: tuple[int, type[Ocr]], tmp_path: Path
) -> None:
    """**404는 버린다** — 철회된 정의로 돌리는 것이 모르고 멈추는 것보다 나쁘다 (C13)."""
    port, _ = ocr
    found = definition(port)
    assert register(client, found).status_code == 201
    data_dir = tmp_path / "data"
    made = DirectoryCache.using(
        data_dir, CenterClient(base_url="http://center", api_key=TOKEN, client=client)
    )
    made.refresh(externals=[APP])
    assert made.cached()["extensions"], "들고 있다"

    class Revoked:
        def extension(self, extension_id: str) -> Any:
            raise CenterProblem("없다", code="not_found", status=404)

    after = DirectoryCache.using(data_dir, Revoked())
    after.refresh(externals=[APP])
    assert after.cached()["extensions"] == []
    assert "철회됐을 수 있습니다" in " ".join(after.problems)


def test_only_what_the_manifest_asks_for_goes_in_the_file(
    client: TestClient, ocr: tuple[int, type[Ocr]], tmp_path: Path
) -> None:
    """**필요한 것만 준다** — 다른 BPM 프로세스가 쓰는 확장의 정의는 담지 않는다."""
    port, _ = ocr
    found = definition(port)
    other = definition(port, id="ext-credit", name="외부 신용")
    for one in (found, other):
        assert register(client, one).status_code == 201

    made = DirectoryCache.using(
        tmp_path / "data", CenterClient(base_url="http://center", api_key=TOKEN, client=client)
    )
    path = made.write_for(manifest(found), path=tmp_path / "run.services.json", keys=public_keys(client))
    assert path is not None
    body = json.loads(path.read_text(encoding="utf-8"))
    assert [one["definition"]["id"] for one in body["extensions"]] == [APP]


def test_a_bot_that_calls_nothing_gets_no_file(tmp_path: Path) -> None:
    made = DirectoryCache(data_dir=tmp_path / "data")
    assert made.write_for(manifest(), path=tmp_path / "run.services.json", keys=[]) is None


def test_what_the_manifest_asks_for(ocr: tuple[int, type[Ocr]]) -> None:
    """외부 확장은 `definition_hash`가 적힌 것이다 (C1)."""
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
    # **정의를 받아 볼 대상은 전부다** — 지금 내보내기는 `definition_hash`를 적지 않으므로
    # 고정된 것만 물으면 외부 앱을 하나도 부를 수 없다. 어느 것이 외부인가는 Center의 답이
    # 말해 준다 (내장·사내는 정의 없이 와서 담기지 않는다).
    assert extension_ids(found) == sorted([APP, "ui-automation"])


def test_an_unpinned_external_is_still_fetched_and_verified(
    client: TestClient, ocr: tuple[int, type[Ocr]], tmp_path: Path
) -> None:
    """**고정하지 않은 외부 확장도 부를 수 있어야 한다** (지금 Studio가 해시를 적지 않는다).

    담긴 정의는 **그대로 봉투 검증을 거친다** — 고정이 없다고 관문이 느슨해지지 않는다.
    """
    port, _ = ocr
    found = definition(port)
    assert register(client, found).status_code == 201
    unpinned = manifest(requires={"extensions": [{"id": APP, "version": "1.0.0"}]})

    made = DirectoryCache.using(
        tmp_path / "data", CenterClient(base_url="http://center", api_key=TOKEN, client=client)
    )
    directory = made.directory_for(unpinned, keys=public_keys(client))
    assert set(directory.externals) == {APP}
    # 고정하지 않았으니 **대조할 것이 없다** (C1 — `unusable`은 고정된 것만 본다).
    assert directory.unusable(unpinned.requires.extensions) == []


def test_the_server_runner_builds_the_directory_without_a_file(
    client: TestClient, ocr: tuple[int, type[Ocr]], tmp_path: Path
) -> None:
    """서버 실행기는 **파일을 거치지 않는다** — 그래도 봉투 검증은 같은 자리에서 한다 (C13 E6).

    공개키를 주지 않으면 **어느 봉투도 검증되지 않는다** — 받아도 쓰지 못하고 사유가 남는다.
    """
    port, _ = ocr
    found = definition(port)
    assert register(client, found).status_code == 201
    asked = manifest(found)
    made = DirectoryCache.using(
        tmp_path / "data", CenterClient(base_url="http://center", api_key=TOKEN, client=client)
    )

    good = made.directory_for(asked, keys=public_keys(client))
    assert set(good.externals) == {APP}

    without_keys = made.directory_for(asked, keys=[])
    assert without_keys.externals == {}
    assert APP in without_keys.problems, "쓰지 못한 정의는 사유와 함께 남는다"


# ─────────────────────────── 실행기까지 (한 바퀴) ───────────────────────────


SHELL = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:bpm="urn:chaeksas:bpmn:1" id="Defs">
  <bpmn:process id="finance.invoice" name="세금계산서 처리">
    <bpmn:extensionElements><bpm:process>{props}</bpm:process></bpmn:extensionElements>
    <bpmn:startEvent id="Start_1"/>
    <bpmn:serviceTask id="Task_Ocr"><bpmn:extensionElements><bpm:serviceCall>{call}
    </bpm:serviceCall></bpmn:extensionElements></bpmn:serviceTask>
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
                keys=public_keys(client),
                extensions=[{"definition": found, "envelope": envelope_for(key, found).to_json_dict()}],
            )
        ),
        encoding="utf-8",
    )
    return path


def test_the_runner_calls_the_external_app_through_the_adapter_consumer(
    ocr: tuple[int, type[Ocr]], tmp_path: Path
) -> None:
    """한 바퀴 — 패키지 → 엔진 → **Center(C15)** → 어댑터 일꾼 → **진짜 외부 앱** → 변수 → C3 기록.

    실행하는 쪽(Studio 키, `test_…` 실행)은 외부 앱의 주소도 키도 모른다. 키는 **어댑터 일꾼의
    설정**(`BPM_ADAPTER__EXT__EXT_OCR__KEY`)에만 있고, 외부 앱이 받은 `Authorization`이 그것이다.
    """
    import httpx  # noqa: PLC0415
    from consumers import enroll, serve, start  # noqa: PLC0415

    from chaeksas.adapter_consumer.adapter import ext_env  # noqa: PLC0415
    from chaeksas.adapter_consumer.main import service_of  # noqa: PLC0415
    from chaeksas.bot_ui.runner_main import Runner  # noqa: PLC0415
    from chaeksas.core.engine import State  # noqa: PLC0415
    from chaeksas.core.packages import InstalledBot  # noqa: PLC0415
    from chaeksas.core.run_env import make_env  # noqa: PLC0415
    from chaeksas.core.run_log import RunLog, log_path  # noqa: PLC0415
    from chaeksas.core.services import CenterServiceCaller  # noqa: PLC0415

    port, echo = ocr
    found = definition(port)
    store = Store(tmp_path / "center.sqlite3")
    app = create_app(
        Settings(db_path=tmp_path / "center.sqlite3", package_dir=tmp_path / "pkg", admin_token=TOKEN), store=store
    )
    url, server, thread = serve(app)
    try:
        with httpx.Client(base_url=url, timeout=30) as http:
            tokens = enroll(http, topics=[APP], folder=tmp_path / "adapter")
            studio = http.post("/api/v1/center-keys", json={"name": "설계자", "type": "studio"}, headers=ADMIN)
            studio_key = str(studio.json()["key"])
        # 어댑터 일꾼이 **제 정의를 들고 있다가** 뜰 때 올린다 (ADR-0122) — `start()`의 `publish`가 올린다.
        service = service_of(
            found, environ={ext_env(APP, "KEY"): "ocr-secret-1", "BPM_ADAPTER__ALLOW_PRIVATE_NETWORK": "1"}
        )
        _, stop = start([service], center_url=url, tokens=tokens)
        try:
            package = InstalledBot.read(package_at(tmp_path / "bot", found))
            data_dir = tmp_path / "data"
            runner = Runner(
                run_id="test_20261008_090000_a1b2c3",
                package=package,
                data_dir=data_dir,
                inputs={"파일": "https://files.example.com/a.pdf"},
                env=make_env(
                    package,
                    output_dir=tmp_path / "out",
                    readable=(),
                    llm_model="",
                    services=CenterServiceCaller(base_url=url, token=studio_key, caller_type="studio"),
                ),
            )
            assert runner.drive(deadline_s=30) is State.DONE
        finally:
            stop.set()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
    assert runner.run is not None
    assert runner.run.variables["사업자번호"] == "123-45-67890"
    assert echo.seen["headers"]["authorization"] == "Bearer ocr-secret-1", "키는 어댑터 일꾼의 설정에서 왔다"

    calls = [one for one in RunLog.read(log_path(data_dir, runner.run_id)) if one.kind == "service_call"]
    assert len(calls) == 1
    assert calls[0].data["app_id"] == "ext-ocr"
    assert calls[0].data["key_ref"] == "", "키가 없다 — 참조 이름도 기록에 가지 않는다 (ADR-0102)"
    assert "123-45-67890" not in json.dumps(calls[0].data, ensure_ascii=False), "업무 값은 기록에 없다"


def test_the_runner_refuses_to_start_when_the_definition_changed(
    client: TestClient, key: Any, ocr: tuple[int, type[Ocr]], tmp_path: Path
) -> None:
    """**실행 전에** 거절한다 — 중간에 알면 이미 한 일을 되돌릴 수 없다 (C1)."""
    from chaeksas.bot_ui.runner_main import app_directory, refuse_unusable
    from chaeksas.core.engine import EngineError
    from chaeksas.core.packages import InstalledBot

    port, _ = ocr
    approved = definition(port)
    package = InstalledBot.read(package_at(tmp_path / "bot", approved))
    # Center에는 새 판이 올라와 있다 — 승인받은 그 정의가 아니다.
    newer = definition(port, version="1.1.0")
    path = services_file(tmp_path / "run.services.json", client, key, newer)

    with pytest.raises(EngineError) as caught:
        refuse_unusable(package, app_directory(path))
    assert caught.value.code == "extension_definition_unusable"


# ─────────────────────────── 외부 확장 주소·키 — Center에 없다 (ADR-0102) ───────────────────────────


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("PUT", "/api/v1/resources/extensions/ext-ocr/address"),
        ("PUT", "/api/v1/resources/extensions/ext-ocr/app-key"),
        ("PUT", "/api/v1/resources/extensions/ext-ocr/app-key/test"),
        ("POST", "/api/v1/resources/service-apps"),
    ],
)
def test_center_has_no_place_for_outside_addresses_or_keys(client: TestClient, method: str, path: str) -> None:
    """주소·키는 **어댑터 일꾼의 설정에만** 있다 — Center에 넣는 길이 없다 (C7)."""
    answer = client.request(method, path, json={"base_url": "https://x", "key": "k"}, headers=ADMIN)
    assert answer.status_code in (404, 405)
