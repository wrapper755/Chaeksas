"""외부 확장 등록 — 그 토픽을 맡은 일꾼이 올리고 Center가 서명한다 (C13·C2·C15, ADR-0090·0121).

진짜 Center를 in-process로 띄우고 **일꾼이** 정의를 올린다(`center_admin.register_extension`) — 봉투는
**Center가 짓는다**. 콘솔·API로 등록·해제하는 길은 없다.

거듭 보는 것 다섯.

1. **그 토픽의 일꾼만 올린다** — 읽기·관리자 토큰으로는 안 된다.
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


def test_only_a_worker_uploads(client: TestClient) -> None:
    found = definition()
    for headers in (READ_AUTH, ADMIN):
        answer = client.put("/api/v1/consumers/self/extension", json={"definition": found}, headers=headers)
        assert answer.status_code == 403


# ─────────────────────────── 겹침 (E4) ───────────────────────────


def test_conflicting_contributions_cannot_even_be_declared(client: TestClient) -> None:
    """**E4는 외부 확장으로 띄울 수 없다** — E1이 먼저 막는다.

    `task_types`는 코드(수행기)를 기여하는 자리이고, 외부 확장에는 코드 기여를 넣을 수 없다 (E1).
    그래서 태스크 종류가 겹치는 일은 **설치된 확장들 사이**에서만 생기고, 그것은 확장 호스트가
    본다 (Center가 아니라).
    """
    found = definition(
        contributes={"task_types": [{"id": "ocr_task", "label": "OCR", "run_locations": ["pc"]}]}
    )
    answer = register(client, found)
    assert answer.status_code == 422
    assert answer.json()["code"] == "external_code_not_allowed"


# ─────────────────────────── 철회 (C13·C2) ───────────────────────────


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
    from chaeksas.center.errors import ApiError  # noqa: PLC0415

    with pytest.raises(ApiError) as caught:
        revoke_extension(client, "없는것", "1.0.0")
    assert caught.value.status == 404


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


# ─────────── 외부 확장의 상태 (C7 — 그 토픽의 일꾼이 말한다, ADR-0102) ───────────


def extension_row(client: TestClient, extension_id: str = "ext-ocr") -> Any:
    found = client.get("/api/v1/resources?type=extension", headers=READ_AUTH).json()["items"]
    return next(one for one in found if one["id"] == extension_id)


def test_an_extension_whose_worker_never_fetched_is_not_ok(client: TestClient) -> None:
    """올린 일꾼이 아직 가져가지 않았으면 「쓸 수 없음」이다 — **Center는 외부 앱을 두드리지 않는다** (C7)."""
    found = definition()
    assert register(client, found).status_code == 201
    row = extension_row(client, found["id"])
    assert row["status"] == "unreachable"
    assert row["status_reasons"] == ["consumer_quiet"] and row.get("checked_at") is None


def test_an_extension_whose_adapter_consumer_fetches_is_ok(client: TestClient, tmp_path: Path) -> None:
    """어댑터 일꾼이 그 토픽을 가져가면 `ok`이고 본 때는 **마지막으로 가져간 때**다."""
    from consumers import enroll  # noqa: PLC0415

    found = definition()
    assert register(client, found).status_code == 201
    tokens = enroll(client, topics=[found["id"]], folder=tmp_path / "adapter")
    fetched = client.post(
        "/api/v1/consumers/fetch",
        json={"topics": [found["id"]], "wait_s": 0},
        headers={"Authorization": f"Bearer {tokens.token()}"},
    )
    assert fetched.status_code == 200, fetched.text
    row = extension_row(client, found["id"])
    assert row["status"] == "ok" and row["status_reasons"] == []
    assert row["checked_at"], "본 때가 없다"


def test_a_host_outside_allowed_hosts_never_registers(client: TestClient) -> None:
    """허용 호스트 밖은 **등록에서 막힌다** (E3) — 어댑터 일꾼이 부를 때 §4-3이 한 번 더 본다."""
    found = definition()
    found["service"]["base_url"] = "https://다른곳.example.com"
    answer = register(client, found)
    assert answer.status_code == 422
    assert any("allowed_hosts" in str(v) for v in answer.json()["detail"]["violations"])
