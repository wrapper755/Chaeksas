"""외부 확장 등록 — 서명 봉투로만 (C13·C2, M5 조각 9).

진짜 Center를 in-process로 띄우고 **진짜 `chk-admin`으로** 정의에 서명한다.

거듭 보는 것 다섯.

1. **서명이 관문이다** — 관리자 토큰만으로는 등록되지 않는다 (C2).
2. **봉투는 그 정의에 대한 것이어야 한다** — 한 글자만 고쳐도 `hash_mismatch`다 (E6).
3. **외부 확장에 코드 기여를 넣을 수 없다** (E1) — 내장·사내는 등록할 수 없다 (E2).
4. **어댑터 선언이 안전해야 한다** (E3) — http, 허용 호스트 밖, 금지 헤더, 모르는 템플릿 변수.
5. **철회된 판은 되살아나지 않는다**. 정의와 봉투는 **그대로** 남아 실행하는 쪽이 다시 검증한다.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from chaeksas.admin import keys as keystore
from chaeksas.admin.cli import main as admin_main
from chaeksas.center.api.signing import bootstrap_key
from chaeksas.center.app import create_app
from chaeksas.center.settings import Settings
from chaeksas.center.storage import Store
from chaeksas.contracts.extension import definition_hash
from chaeksas.contracts.signing import sign

TOKEN = "t-admin"
READ = "t-read"
ADMIN = {"Authorization": f"Bearer {TOKEN}"}
READ_AUTH = {"Authorization": f"Bearer {READ}"}
PASS = "열쇠말"
AT = "2026-10-07T09:00:00+09:00"


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
        read_token=READ,
    )
    with TestClient(create_app(settings, store=store)) as found:
        yield found


@pytest.fixture
def key(store: Store) -> Any:
    made = keystore.create(label="첫 키")
    bootstrap_key(store, public_key=made.public_bytes(), label="첫 키")
    return made


def definition(**over: Any) -> dict[str, Any]:
    """C13 §예시의 외부 확장 (OCR)."""
    base: dict[str, Any] = {
        "schema": 2,
        "id": "ext-ocr",
        "version": "1.0.0",
        "name": "외부 OCR",
        "publisher": "외부 업체",
        "tier": "external",
        "service": {
            "protocol": "http-adapter",
            "base_url": "https://ocr.example.com",
            "adapter": {
                "allowed_hosts": ["ocr.example.com"],
                "auth": {"type": "bearer"},
                "limits": {"timeout_s": 30, "max_response_kb": 512},
                "health": {"path": "/health", "expect_status": 200},
                "operations": [
                    {
                        "name": "read_invoice",
                        "description": "세금계산서 이미지에서 항목 추출",
                        "modes": ["autonomous", "deterministic"],
                        "idempotent": False,
                        "retry_on": [429, 503],
                        "input_schema": {
                            "type": "object",
                            "required": ["file_url"],
                            "properties": {"file_url": {"type": "string"}},
                        },
                        "output_schema": {
                            "type": "object",
                            "properties": {"biz_no": {"type": "string"}},
                        },
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


# ─────────────────────────── 등록 (C13 E1~E6) ───────────────────────────


def test_a_signed_definition_registers(client: TestClient, key: Any) -> None:
    """한 바퀴 — 서명 → 등록 → 확장 목록에 뜬다."""
    found = definition()
    answer = register(client, found, envelope_for(key, found))
    assert answer.status_code == 201, answer.text
    info = answer.json()
    assert info["id"] == "ext-ocr" and info["tier"] == "external"
    assert info["name"] == "외부 OCR" and info["publisher"] == "외부 업체"
    assert info["protocol"] == "http-adapter"
    assert info["definition_hash"] == definition_hash(found)
    assert info["installed_on"] == {"hosts": 0, "by_version": {}}, "아직 깔린 PC가 없다"

    [listed] = client.get("/api/v1/resources?type=extension", headers=READ_AUTH).json()["items"]
    assert listed["id"] == "ext-ocr"


def test_the_definition_and_envelope_are_kept_as_is(client: TestClient, key: Any) -> None:
    """실행하는 쪽이 **받아서 다시 검증한다** (C13 전송·E6) — 그대로 남아야 한다."""
    found = definition()
    made = envelope_for(key, found)
    register(client, found, made)

    info = client.get("/api/v1/resources/extensions/ext-ocr", headers=READ_AUTH).json()
    assert info["envelope"]["sig"] == made.sig, "봉투 바이트가 그대로다"
    assert info["definition"]["service"]["adapter"]["allowed_hosts"] == ["ocr.example.com"]


def test_a_token_alone_registers_nothing(client: TestClient) -> None:
    """**서명이 관문이다** (C2) — Admin 키가 없으면 등록되지 않는다."""
    found = definition()
    # 키를 등록하지 않은 Center — 어떤 봉투도 모르는 키다.
    made = keystore.create(label="아무 키")
    answer = register(client, found, envelope_for(made, found))
    assert answer.status_code == 400 and answer.json()["code"] == "bad_envelope"


def test_an_envelope_for_another_definition_is_refused(client: TestClient, key: Any) -> None:
    """한 글자만 고쳐도 `hash_mismatch`다 (E6)."""
    found = definition()
    made = envelope_for(key, found)
    tampered = definition(name="바꾼 이름")
    answer = register(client, tampered, made)
    assert answer.status_code == 400
    assert answer.json()["code"] == "hash_mismatch"


def test_an_envelope_for_another_extension_is_refused(client: TestClient, key: Any) -> None:
    """해시는 맞아도 **봉투가 다른 확장을 가리키면** 거부한다 (E6)."""
    found = definition()
    answer = register(client, found, envelope_for(key, found, id="딴것"))
    assert answer.status_code == 400 and answer.json()["code"] == "bad_envelope"


def test_external_code_contributions_are_refused(client: TestClient, key: Any) -> None:
    """**외부 확장에 코드 기여를 넣을 수 없다** (E1) — 설치 파일에 없는 코드를 부를 수 없다."""
    found = definition(
        contributes={
            "task_types": [
                {"id": "ocr_task", "label": "OCR", "bpmn": "serviceTask",
                 "executor": {"entry": "x:Y"}, "run_locations": ["pc"]}
            ]
        }
    )
    answer = register(client, found, envelope_for(key, found))
    assert answer.status_code == 422
    assert answer.json()["code"] == "external_code_not_allowed"


def test_a_builtin_tier_cannot_be_registered(client: TestClient, key: Any) -> None:
    """내장·사내는 **설치 파일에 든 것만** 쓴다 (E2)."""
    # 내장·사내는 `api`(필요한 `extension_api` 범위)가 필수다 — 그것까지 채워 E2를 띄운다.
    found = definition(tier="builtin", api=">=1,<2")
    answer = register(client, found, envelope_for(key, found))
    assert answer.status_code == 422 and answer.json()["code"] == "id_conflict"


def test_a_plain_http_adapter_is_refused(client: TestClient, key: Any) -> None:
    """**https만** 쓴다 (E3·§4-3) — 사설망 허용이 아니면 http는 안 된다."""
    found = definition()
    found["service"]["base_url"] = "http://ocr.example.com"
    answer = register(client, found, envelope_for(key, found))
    assert answer.status_code == 422 and answer.json()["code"] == "adapter_invalid"


def test_a_host_outside_allowed_hosts_is_refused(client: TestClient, key: Any) -> None:
    found = definition()
    found["service"]["adapter"]["allowed_hosts"] = ["other.example.com"]
    answer = register(client, found, envelope_for(key, found))
    assert answer.status_code == 422 and answer.json()["code"] == "adapter_invalid"


def test_an_unknown_template_variable_is_refused(client: TestClient, key: Any) -> None:
    """쓸 수 있는 변수는 `input.*`·`run_id`·`node_id`·`idempotency_key`뿐이다 (§4-2)."""
    found = definition()
    found["service"]["adapter"]["operations"][0]["request"]["body"] = {"url": "{{비밀}}"}
    answer = register(client, found, envelope_for(key, found))
    assert answer.status_code == 422 and answer.json()["code"] == "adapter_invalid"


def test_a_forbidden_header_template_is_refused(client: TestClient, key: Any) -> None:
    """`Authorization`은 템플릿으로 못 쓴다 (§4-2) — 키가 거기로 새면 안 된다."""
    found = definition()
    found["service"]["adapter"]["operations"][0]["request"]["headers"] = {
        "Authorization": "{{input.file_url}}"
    }
    answer = register(client, found, envelope_for(key, found))
    assert answer.status_code == 422 and answer.json()["code"] == "adapter_invalid"


def test_the_same_definition_twice_is_idempotent(client: TestClient, key: Any) -> None:
    found = definition()
    made = envelope_for(key, found)
    assert register(client, found, made).status_code == 201
    assert register(client, found, made).status_code == 200
    assert len(client.get("/api/v1/resources?type=extension", headers=READ_AUTH).json()["items"]) == 1


def test_a_read_token_cannot_register(client: TestClient, key: Any) -> None:
    found = definition()
    answer = client.post(
        "/api/v1/resources/extensions",
        json={"definition": found, "envelope": envelope_for(key, found).to_json_dict()},
        headers=READ_AUTH,
    )
    assert answer.status_code == 403


# ─────────────────────────── 겹침 (E4·E8) ───────────────────────────


def test_conflicting_contributions_cannot_even_be_declared(client: TestClient, key: Any) -> None:
    """**E4·E8은 외부 확장으로 띄울 수 없다** — E1이 먼저 막는다.

    `task_types`·`agent_environments`는 `entry`(코드)를 요구하고, 외부 확장에는 코드 기여를
    넣을 수 없다 (E1). 그래서 태스크 종류·AI 환경이 겹치는 일은 **설치된 확장들 사이**에서만
    생기고, 그것은 확장 호스트가 본다 (Center가 아니라).
    """
    found = definition(
        contributes={"agent_environments": [{"domain": "web", "entry": "x:Y"}]}
    )
    answer = register(client, found, envelope_for(key, found))
    assert answer.status_code == 422
    assert answer.json()["code"] == "external_code_not_allowed"


# ─────────────────────────── 철회 (C13·C2) ───────────────────────────


def revoke_envelope(key: Any, *, id: str = "ext-ocr", version: str = "1.0.0") -> Any:
    return sign(
        {
            "kind": "extension_revoke",
            "id": id,
            "version": version,
            "reason": "정의 결함",
            "revoked_at": AT,
        },
        keystore.load(key, passphrase=PASS),
        signed_at=AT,
    )


def test_revoking_needs_an_envelope_too(client: TestClient, key: Any) -> None:
    found = definition()
    register(client, found, envelope_for(key, found))
    # 봉투 없이 — 토큰만으로는 철회되지 않는다.
    assert client.request("DELETE", "/api/v1/resources/extensions", json={}, headers=ADMIN).status_code == 400


def test_a_revoked_extension_drops_out_of_the_list(client: TestClient, key: Any) -> None:
    found = definition()
    register(client, found, envelope_for(key, found))
    answer = client.request(
        "DELETE",
        "/api/v1/resources/extensions",
        json=revoke_envelope(key).to_json_dict(),
        headers=ADMIN,
    )
    assert answer.status_code == 200, answer.text
    assert client.get("/api/v1/resources?type=extension", headers=READ_AUTH).json()["items"] == []


def test_a_revoked_version_never_comes_back(client: TestClient, key: Any) -> None:
    """**되살아나지 않는다** (배포·패키지와 같은 규칙, C2)."""
    found = definition()
    made = envelope_for(key, found)
    register(client, found, made)
    client.request(
        "DELETE",
        "/api/v1/resources/extensions",
        json=revoke_envelope(key).to_json_dict(),
        headers=ADMIN,
    )
    again = register(client, found, made)
    assert again.status_code == 409 and again.json()["code"] == "extension_revoked"


def test_revoking_something_unregistered_is_404(client: TestClient, key: Any) -> None:
    answer = client.request(
        "DELETE",
        "/api/v1/resources/extensions",
        json=revoke_envelope(key, id="없는것").to_json_dict(),
        headers=ADMIN,
    )
    assert answer.status_code == 404


# ─────────────────────────── 보고와 합쳐지는가 (C7) ───────────────────────────


def test_a_registered_definition_wins_over_reports(client: TestClient, key: Any, store: Store) -> None:
    """등록된 정의가 **이름·등급·연결 방식의 원본**이고, 「몇 대에 깔렸나」는 보고에서 온다."""
    import hashlib

    found = definition()
    register(client, found, envelope_for(key, found))

    raw = client.post(
        "/api/v1/center-keys", json={"name": "PC 키", "type": "bot_ui"}, headers=ADMIN
    ).json()["key"]
    client.post(
        "/api/v1/bot-ui/register",
        json={
            "schema": 1,
            "machine_id": hashlib.sha256(b"pc1").hexdigest(),
            "name": "현장 PC 1",
            "os": "windows-11-23H2",
            "versions": {"bot_ui": "0.1.0", "core": "0.1.0"},
            "runtimes": {"extensions": [{"id": "ext-ocr", "version": "1.0.0", "enabled": True}]},
        },
        headers={"Authorization": f"Bearer {raw}"},
    )

    [one] = client.get("/api/v1/resources?type=extension", headers=READ_AUTH).json()["items"]
    assert one["tier"] == "external", "정의가 원본이다 (보고만 있으면 builtin으로 봤을 것)"
    assert one["installed_on"] == {"hosts": 1, "by_version": {"1.0.0": 1}}


# ─────────────────────────── 명령줄 (ADM-04) ───────────────────────────


def test_the_command_signs_to_a_file(tmp_path: Path, key: Any, capsys: Any) -> None:
    """**봉투를 파일로 쓴다** — Center로 바로 보내지 않는다 (운영자가 콘솔에 올린다)."""
    from chaeksas.admin.client import Center

    source = tmp_path / "extension.json"
    source.write_text(json.dumps(definition(), ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "e.json"
    code = admin_main(
        ["-y", "sign-extension", str(source), "--out", str(out)], center=Center()
    )
    assert code == 0
    printed = capsys.readouterr().out
    assert "ocr.example.com" in printed, "허용 호스트를 보여 준다"
    assert "autonomous, deterministic" in printed, "결정 수행 허용을 보여 준다"
    assert out.is_file()
    assert json.loads(out.read_text(encoding="utf-8"))["payload"]["kind"] == "extension"


def test_the_command_refuses_a_bad_definition(tmp_path: Path, key: Any, capsys: Any) -> None:
    """**E1·E3을 먼저 로컬에서 돌려 본다** — 서명한 뒤에 Center가 거부하면 늦다."""
    from chaeksas.admin.client import Center

    found = definition()
    found["service"]["base_url"] = "http://ocr.example.com"
    source = tmp_path / "extension.json"
    source.write_text(json.dumps(found, ensure_ascii=False), encoding="utf-8")

    assert admin_main(["-y", "sign-extension", str(source)], center=Center()) == 2
    assert "서명하지 않았습니다" in capsys.readouterr().out


def test_the_signed_envelope_is_accepted_by_center(
    client: TestClient, tmp_path: Path, key: Any
) -> None:
    """명령이 쓴 봉투를 Center가 받는다 — 한 바퀴가 이어진다."""
    from chaeksas.admin.client import Center

    found = definition()
    source = tmp_path / "extension.json"
    source.write_text(json.dumps(found, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "e.json"
    admin_main(["-y", "sign-extension", str(source), "--out", str(out)], center=Center())

    answer = client.post(
        "/api/v1/resources/extensions",
        json={
            "definition": json.loads(source.read_text(encoding="utf-8")),
            "envelope": json.loads(out.read_text(encoding="utf-8")),
        },
        headers=ADMIN,
    )
    assert answer.status_code == 201, answer.text


def test_the_revoke_command_writes_an_envelope(tmp_path: Path, key: Any, capsys: Any) -> None:
    from chaeksas.admin.client import Center

    out = tmp_path / "r.json"
    code = admin_main(
        ["-y", "revoke-extension", "ext-ocr", "1.0.0", "--out", str(out)], center=Center()
    )
    assert code == 0
    assert json.loads(out.read_text(encoding="utf-8"))["payload"]["kind"] == "extension_revoke"


# ─────────── 외부 확장의 상태 (C7 — 어댑터 `health`, 09-gaps §3-7) ───────────


class _HealthServer:
    """`health.path`에 정해진 코드를 돌려주는 작은 서버. **몇 번 두드렸는지 센다.**"""

    def __init__(self, *, code: int = 200, path: str = "/health") -> None:
        import http.server  # noqa: PLC0415
        import threading  # noqa: PLC0415

        self.hits = 0
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 — http.server의 이름이다
                if self.path != path:
                    self.send_response(404)
                    self.end_headers()
                    return
                outer.hits += 1
                self.send_response(code)
                self.end_headers()

            def log_message(self, *args: Any) -> None:
                pass  # 시험 출력에 접근 기록을 찍지 않는다

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


@pytest.fixture
def health_server() -> Iterator[_HealthServer]:
    made = _HealthServer()
    yield made
    made.close()


def local_definition(port: int, **adapter_over: Any) -> dict[str, Any]:
    """127.0.0.1에 뜬 서버를 가리키는 외부 확장 정의.

    사설 주소라 **`allow_private_network`를 켜야** 관문을 지난다 (C13 §4-3) — 그 규칙이
    Center에도 그대로 적용된다는 것을 시험이 본다.
    """
    found = definition()
    adapter = found["service"]["adapter"]
    found["service"]["base_url"] = f"http://127.0.0.1:{port}"
    adapter["allowed_hosts"] = ["127.0.0.1"]
    adapter["allow_private_network"] = True
    adapter.update(adapter_over)
    return found


def extension_row(client: TestClient, extension_id: str = "ext-ocr") -> Any:
    answer = client.get(f"/api/v1/resources/extensions/{extension_id}", headers=READ_AUTH)
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_an_extension_without_health_stays_unchecked(client: TestClient, key: Any) -> None:
    """선언이 없으면 **두드리지 않는다** — 「확인 전」이지 「응답 없음」이 아니다 (C7).

    C11의 `/healthz`를 외부 앱에 들이대지 않는다 — 어디를 봐야 하는지는 정의가 말한다.
    """
    found = definition()
    del found["service"]["adapter"]["health"]
    assert register(client, found, envelope_for(key, found)).status_code == 201

    row = extension_row(client)
    assert row["status"] == "unknown"
    assert row["status_reasons"] == [] and row["checked_at"] is None


def test_a_declared_health_is_probed(client: TestClient, key: Any, health_server: Any) -> None:
    """선언된 경로·기대 코드로 두드린다. 맞으면 `ok`이고 본 때가 남는다."""
    found = local_definition(health_server.port)
    assert register(client, found, envelope_for(key, found)).status_code == 201

    row = extension_row(client)
    assert row["status"] == "ok" and row["status_reasons"] == []
    assert row["checked_at"], "본 때가 없다"
    assert health_server.hits == 1


def test_a_different_status_code_is_unreachable(client: TestClient, key: Any) -> None:
    """**기대 코드와 다르면** 응답 없음이다 — 200이라고 넘겨짚지 않는다 (C13 `expect_status`)."""
    server = _HealthServer(code=500)
    try:
        found = local_definition(server.port)
        assert register(client, found, envelope_for(key, found)).status_code == 201
        row = extension_row(client)
        assert row["status"] == "unreachable"
        assert row["status_reasons"] == ["health_500"]
    finally:
        server.close()


def test_a_host_outside_allowed_hosts_never_registers(client: TestClient, key: Any) -> None:
    """허용 호스트 밖은 **등록에서 막힌다** (E3) — 상태 점검까지 갈 일이 없다.

    관문이 둘인 셈이다: 선언이 들어올 때 E3가 보고, 나갈 때 §4-3이 본다.
    """
    found = definition()
    found["service"]["base_url"] = "https://다른곳.example.com"
    answer = register(client, found, envelope_for(key, found))
    assert answer.status_code == 422
    assert any("allowed_hosts" in str(v) for v in answer.json()["detail"]["violations"])


def test_an_allowed_name_that_resolves_private_is_refused(
    client: TestClient, key: Any, health_server: Any
) -> None:
    """**허용된 이름이 사설 IP로 풀리면 나가지 않는다** (C13 §4-3 4번).

    E3는 이것을 못 본다 — 이름만 보고 어디로 풀리는지는 모른다. 이 관문이 없으면 서명된
    정의 하나로 Center가 내부망·메타데이터 주소를 두드리게 된다. `https`라서 E3의 스킴
    검사도 지나간다.
    """
    found = local_definition(health_server.port, allow_private_network=False)
    found["service"]["base_url"] = f"https://127.0.0.1:{health_server.port}"
    assert register(client, found, envelope_for(key, found)).status_code == 201

    row = extension_row(client)
    assert row["status"] == "unreachable"
    assert row["status_reasons"] == ["host_not_allowed"]
    assert health_server.hits == 0, "관문에 걸렸는데 두드렸다"


def test_the_probe_keeps_its_interval(client: TestClient, key: Any, health_server: Any) -> None:
    """목록을 읽을 때마다 바깥으로 나가지 않는다 — 서비스 앱과 **같은 간격**이다 (C7 60초)."""
    found = local_definition(health_server.port)
    assert register(client, found, envelope_for(key, found)).status_code == 201

    for _ in range(3):
        assert client.get("/api/v1/resources?type=extension", headers=READ_AUTH).status_code == 200
    assert health_server.hits == 1, f"간격을 지키지 않았다 ({health_server.hits}번)"


def test_refresh_ignores_the_interval(client: TestClient, key: Any, health_server: Any) -> None:
    """「새로 고침」만 간격을 무시한다 (C7)."""
    found = local_definition(health_server.port)
    assert register(client, found, envelope_for(key, found)).status_code == 201
    extension_row(client)
    before = health_server.hits

    assert client.post("/api/v1/resources/refresh", json={}, headers=ADMIN).status_code == 200
    assert health_server.hits == before + 1
