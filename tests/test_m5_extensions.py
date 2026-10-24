"""외부 확장 등록 — 관리자가 올리고 Center가 서명한다 (C13·C2, M5 조각 9, ADR-0090).

진짜 Center를 in-process로 띄우고 관리자로 정의를 올린다 — 봉투는 **Center가 짓는다**.

거듭 보는 것 다섯.

1. **관리자만 등록한다** — 읽기 토큰으로는 안 된다.
2. **봉투는 그 정의에 대한 것이다** — 실행하는 쪽이 같은 검증(E6)으로 다시 본다. 같은 판에 다른
   정의가 오면 `id_conflict`다.
3. **외부 확장에 코드 기여를 넣을 수 없다** (E1) — 내장·사내는 등록할 수 없다 (E2).
4. **어댑터 선언이 안전해야 한다** (E3) — http, 허용 호스트 밖, 금지 헤더, 모르는 템플릿 변수.
5. **철회된 판은 되살아나지 않는다**. 정의와 봉투는 **그대로** 남아 실행하는 쪽이 다시 검증한다.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from center_admin import register_extension, revoke_extension
from fastapi.testclient import TestClient

from chaeksas.center import signer as center_signer
from chaeksas.center.app import create_app
from chaeksas.center.settings import Settings
from chaeksas.center.storage import Store
from chaeksas.contracts.extension import definition_hash, verify_external
from chaeksas.contracts.signing import AdminKey

TOKEN = "t-admin"
READ = "t-read"
ADMIN = {"Authorization": f"Bearer {TOKEN}"}
READ_AUTH = {"Authorization": f"Bearer {READ}"}
AT = "2026-10-07T09:00:00+09:00"


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


def register(client: TestClient, found: dict[str, Any]) -> Any:
    """정의만 올린다 — 봉투는 Center가 짓는다 (ADR-0090). 응답을 그대로 돌려준다."""
    return register_extension(client, found, expect=None)


# ─────────────────────────── 등록 (C13 E1~E6) ───────────────────────────


def test_a_signed_definition_registers(client: TestClient) -> None:
    """한 바퀴 — 서명 → 등록 → 확장 목록에 뜬다."""
    found = definition()
    answer = register(client, found)
    assert answer.status_code == 201, answer.text
    info = answer.json()
    assert info["id"] == "ext-ocr" and info["tier"] == "external"
    assert info["name"] == "외부 OCR" and info["publisher"] == "외부 업체"
    assert info["protocol"] == "http-adapter"
    assert info["definition_hash"] == definition_hash(found)
    assert info["installed_on"] == {"hosts": 0, "by_version": {}}, "아직 깔린 PC가 없다"

    [listed] = client.get("/api/v1/resources?type=extension", headers=READ_AUTH).json()["items"]
    assert listed["id"] == "ext-ocr"


def test_the_definition_and_envelope_are_kept_as_is(client: TestClient, store: Store) -> None:
    """실행하는 쪽이 **받아서 다시 검증한다** (C13 전송·E6) — Center 키로 서명한 봉투가 남는다."""
    from chaeksas.contracts.signing import Envelope  # noqa: PLC0415

    found = definition()
    register(client, found)

    info = client.get("/api/v1/resources/extensions/ext-ocr", headers=READ_AUTH).json()
    assert info["envelope"]["key_id"] == center_signer.current_key_id(store)
    assert info["definition"]["service"]["adapter"]["allowed_hosts"] == ["ocr.example.com"]
    # 현장이 하는 검증 그대로 — 하트비트가 내려 주는 믿는 키로 통과한다.
    keys = [AdminKey.model_validate(one) for one in client.get("/api/v1/admin-keys", headers=ADMIN).json()]
    envelope = Envelope.model_validate(info["envelope"])
    assert verify_external(info["definition"], envelope, keys=keys) == []
    # 한 글자만 고쳐도 현장이 거부한다 (E6 `hash_mismatch`).
    tampered = {**info["definition"], "name": "바꾼 이름"}
    assert "hash_mismatch" in [v.code for v in verify_external(tampered, envelope, keys=keys)]


def test_another_definition_on_the_same_version_is_refused(client: TestClient) -> None:
    """같은 판(`id@version`)에 **다른 정의**가 오면 409다 — 판을 올려야 한다."""
    assert register(client, definition()).status_code == 201
    answer = register(client, definition(name="바꾼 이름"))
    assert answer.status_code == 409 and answer.json()["code"] == "id_conflict"


def test_external_code_contributions_are_refused(client: TestClient) -> None:
    """**외부 확장에 코드 기여를 넣을 수 없다** (E1) — 설치 파일에 없는 코드를 부를 수 없다."""
    found = definition(
        contributes={
            "task_types": [
                {"id": "ocr_task", "label": "OCR", "bpmn": "serviceTask",
                 "executor": {"entry": "x:Y"}, "run_locations": ["pc"]}
            ]
        }
    )
    answer = register(client, found)
    assert answer.status_code == 422
    assert answer.json()["code"] == "external_code_not_allowed"


def test_a_builtin_tier_cannot_be_registered(client: TestClient) -> None:
    """내장·사내는 **설치 파일에 든 것만** 쓴다 (E2)."""
    # 내장·사내는 `api`(필요한 `extension_api` 범위)가 필수다 — 그것까지 채워 E2를 띄운다.
    found = definition(tier="builtin", api=">=1,<2")
    answer = register(client, found)
    assert answer.status_code == 422 and answer.json()["code"] == "id_conflict"


def test_a_plain_http_adapter_is_refused(client: TestClient) -> None:
    """**https만** 쓴다 (E3·§4-3) — 사설망 허용이 아니면 http는 안 된다."""
    found = definition()
    found["service"]["base_url"] = "http://ocr.example.com"
    answer = register(client, found)
    assert answer.status_code == 422 and answer.json()["code"] == "adapter_invalid"


def test_a_host_outside_allowed_hosts_is_refused(client: TestClient) -> None:
    found = definition()
    found["service"]["adapter"]["allowed_hosts"] = ["other.example.com"]
    answer = register(client, found)
    assert answer.status_code == 422 and answer.json()["code"] == "adapter_invalid"


def test_an_unknown_template_variable_is_refused(client: TestClient) -> None:
    """쓸 수 있는 변수는 `input.*`·`run_id`·`node_id`·`idempotency_key`뿐이다 (§4-2)."""
    found = definition()
    found["service"]["adapter"]["operations"][0]["request"]["body"] = {"url": "{{비밀}}"}
    answer = register(client, found)
    assert answer.status_code == 422 and answer.json()["code"] == "adapter_invalid"


def test_a_forbidden_header_template_is_refused(client: TestClient) -> None:
    """`Authorization`은 템플릿으로 못 쓴다 (§4-2) — 키가 거기로 새면 안 된다."""
    found = definition()
    found["service"]["adapter"]["operations"][0]["request"]["headers"] = {
        "Authorization": "{{input.file_url}}"
    }
    answer = register(client, found)
    assert answer.status_code == 422 and answer.json()["code"] == "adapter_invalid"


def test_the_same_definition_twice_is_idempotent(client: TestClient) -> None:
    found = definition()
    assert register(client, found).status_code == 201
    assert register(client, found).status_code == 200
    assert len(client.get("/api/v1/resources?type=extension", headers=READ_AUTH).json()["items"]) == 1


def test_a_read_token_cannot_register(client: TestClient) -> None:
    found = definition()
    answer = client.post(
        "/api/v1/resources/extensions",
        json={"definition": found},
        headers=READ_AUTH,
    )
    assert answer.status_code == 403


# ─────────────────────────── 겹침 (E4·E8) ───────────────────────────


def test_conflicting_contributions_cannot_even_be_declared(client: TestClient) -> None:
    """**E4·E8은 외부 확장으로 띄울 수 없다** — E1이 먼저 막는다.

    `task_types`·`agent_environments`는 `entry`(코드)를 요구하고, 외부 확장에는 코드 기여를
    넣을 수 없다 (E1). 그래서 태스크 종류·AI 환경이 겹치는 일은 **설치된 확장들 사이**에서만
    생기고, 그것은 확장 호스트가 본다 (Center가 아니라).
    """
    found = definition(
        contributes={"agent_environments": [{"domain": "web", "entry": "x:Y"}]}
    )
    answer = register(client, found)
    assert answer.status_code == 422
    assert answer.json()["code"] == "external_code_not_allowed"


# ─────────────────────────── 철회 (C13·C2) ───────────────────────────


def test_revoking_names_the_version(client: TestClient) -> None:
    """무엇을 거두는지 **판까지** 적어야 한다 — 비우면 422다."""
    register(client, definition())
    answer = client.request("DELETE", "/api/v1/resources/extensions", json={}, headers=ADMIN)
    assert answer.status_code == 422 and answer.json()["code"] == "input_invalid"


def test_a_read_token_cannot_revoke(client: TestClient) -> None:
    register(client, definition())
    revoke_extension(client, "ext-ocr", "1.0.0", headers=READ_AUTH, expect=403)


def test_a_revoked_extension_drops_out_of_the_list(client: TestClient) -> None:
    found = definition()
    register(client, found)
    revoke_extension(client, "ext-ocr", "1.0.0", reason="정의 결함")
    assert client.get("/api/v1/resources?type=extension", headers=READ_AUTH).json()["items"] == []


def test_a_revoked_version_never_comes_back(client: TestClient) -> None:
    """**되살아나지 않는다** (배포·패키지와 같은 규칙, C2)."""
    found = definition()
    register(client, found)
    revoke_extension(client, "ext-ocr", "1.0.0", reason="정의 결함")
    again = register(client, found)
    assert again.status_code == 409 and again.json()["code"] == "extension_revoked"


def test_revoking_something_unregistered_is_404(client: TestClient) -> None:
    revoke_extension(client, "없는것", "1.0.0", expect=404)


# ─────────────────────────── 보고와 합쳐지는가 (C7) ───────────────────────────


def test_a_registered_definition_wins_over_reports(client: TestClient) -> None:
    """등록된 정의가 **이름·등급·연결 방식의 원본**이고, 「몇 대에 깔렸나」는 보고에서 온다."""
    import hashlib

    found = definition()
    register(client, found)

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


def test_an_extension_without_health_stays_unchecked(client: TestClient) -> None:
    """선언이 없으면 **두드리지 않는다** — 「확인 전」이지 「응답 없음」이 아니다 (C7).

    C11의 `/healthz`를 외부 앱에 들이대지 않는다 — 어디를 봐야 하는지는 정의가 말한다.
    """
    found = definition()
    del found["service"]["adapter"]["health"]
    assert register(client, found).status_code == 201

    row = extension_row(client)
    assert row["status"] == "unknown"
    assert row["status_reasons"] == [] and row["checked_at"] is None


def test_a_declared_health_is_probed(client: TestClient, health_server: Any) -> None:
    """선언된 경로·기대 코드로 두드린다. 맞으면 `ok`이고 본 때가 남는다."""
    found = local_definition(health_server.port)
    assert register(client, found).status_code == 201

    row = extension_row(client)
    assert row["status"] == "ok" and row["status_reasons"] == []
    assert row["checked_at"], "본 때가 없다"
    assert health_server.hits == 1


def test_a_different_status_code_is_unreachable(client: TestClient) -> None:
    """**기대 코드와 다르면** 응답 없음이다 — 200이라고 넘겨짚지 않는다 (C13 `expect_status`)."""
    server = _HealthServer(code=500)
    try:
        found = local_definition(server.port)
        assert register(client, found).status_code == 201
        row = extension_row(client)
        assert row["status"] == "unreachable"
        assert row["status_reasons"] == ["health_500"]
    finally:
        server.close()


def test_a_host_outside_allowed_hosts_never_registers(client: TestClient) -> None:
    """허용 호스트 밖은 **등록에서 막힌다** (E3) — 상태 점검까지 갈 일이 없다.

    관문이 둘인 셈이다: 선언이 들어올 때 E3가 보고, 나갈 때 §4-3이 본다.
    """
    found = definition()
    found["service"]["base_url"] = "https://다른곳.example.com"
    answer = register(client, found)
    assert answer.status_code == 422
    assert any("allowed_hosts" in str(v) for v in answer.json()["detail"]["violations"])


def test_an_allowed_name_that_resolves_private_is_refused(
    client: TestClient, health_server: Any
) -> None:
    """**허용된 이름이 사설 IP로 풀리면 나가지 않는다** (C13 §4-3 4번).

    E3는 이것을 못 본다 — 이름만 보고 어디로 풀리는지는 모른다. 이 관문이 없으면 서명된
    정의 하나로 Center가 내부망·메타데이터 주소를 두드리게 된다. `https`라서 E3의 스킴
    검사도 지나간다.
    """
    found = local_definition(health_server.port, allow_private_network=False)
    found["service"]["base_url"] = f"https://127.0.0.1:{health_server.port}"
    assert register(client, found).status_code == 201

    row = extension_row(client)
    assert row["status"] == "unreachable"
    assert row["status_reasons"] == ["host_not_allowed"]
    assert health_server.hits == 0, "관문에 걸렸는데 두드렸다"


def test_the_probe_keeps_its_interval(client: TestClient, health_server: Any) -> None:
    """목록을 읽을 때마다 바깥으로 나가지 않는다 — 서비스 앱과 **같은 간격**이다 (C7 60초)."""
    found = local_definition(health_server.port)
    assert register(client, found).status_code == 201

    for _ in range(3):
        assert client.get("/api/v1/resources?type=extension", headers=READ_AUTH).status_code == 200
    assert health_server.hits == 1, f"간격을 지키지 않았다 ({health_server.hits}번)"


def test_refresh_ignores_the_interval(client: TestClient, health_server: Any) -> None:
    """「새로 고침」만 간격을 무시한다 (C7)."""
    found = local_definition(health_server.port)
    assert register(client, found).status_code == 201
    extension_row(client)
    before = health_server.hits

    assert client.post("/api/v1/resources/refresh", json={}, headers=ADMIN).status_code == 200
    assert health_server.hits == before + 1
