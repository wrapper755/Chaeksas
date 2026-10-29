"""`service_kit.consumer` — 일꾼이 Center에서 일감을 가져가 수행하고 끝낸다 (C15, ADR-0102).

진짜 Center를 in-process(`TestClient`)로 띄우고 **제품의 `Enrollment`·`Consumer`**가 그것과 오간다.
스레드 없이 `run_once()`로 한 바퀴씩 민다 — 롱폴링·스레드는 `test_c15_round_trip.py`가 본다.

| 보는 것 | 왜 |
| --- | --- |
| 들이기는 요청 코드 → 승인 → 봉한 토큰을 연다, 거절되면 멈춘다 | 사람이 토큰을 옮기지 않는다 (ADR-0092) |
| 환경변수 토큰이 파일을 이긴다 | 개발·CI·컨테이너 |
| `run_once`: 가져가기 → 수행 → `complete`, 실패는 `fail`과 코드 | C15 끝내기 |
| 앞의 수행이 아직 돌면(`in_progress`) **아무것도 보내지 않는다** | 먼저 끝낸 쪽이 이긴다 |
| 끝내기가 409면(이미 끝남·거둠) 조용히 넘어간다 | 멱등이라 같은 일이다 |
| `publish`: manifest는 한 번, 카탈로그는 **`revision`이 바뀔 때만** | 같은 판을 다시 쓰면 계획 캐시가 버려진다 |
| 토큰이 없으면 Center를 부르지 않고 멈춘다 | 들이지 않은 일꾼이 두드리지 않는다 |
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from consumers import ADMIN, enroll
from fastapi.testclient import TestClient

from chaeksas.center.app import create_app as create_center
from chaeksas.center.settings import Settings as CenterSettings
from chaeksas.center.storage import Store
from chaeksas.contracts.extension import Catalog
from chaeksas.contracts.service_app import MODE_DETERMINISTIC, OpRequest, ServiceAppManifest, idempotency_key
from chaeksas.service_kit import (
    Consumer,
    Enrollment,
    OpError,
    OpResult,
    Service,
    TokenFile,
    body_hash,
    create_app,
)

TOPIC = "tax-invoice"
RUN = "test_20261029_000000_aaaaaa"


def manifest() -> ServiceAppManifest:
    return ServiceAppManifest.model_validate(
        {
            "schema": 1,
            "app_id": TOPIC,
            "name": "세금계산서 앱",
            "version": "0.1.0",
            "category": "business",
            "console_url": "http://localhost:8011",
            "extension": {"id": "tax", "version": "0.1.0"},
            "operations": [
                {"name": "issue", "modes": [MODE_DETERMINISTIC], "output_schema": {"required": ["invoice_no"]}},
                {"name": "refuse", "modes": [MODE_DETERMINISTIC]},
            ],
            "resources": [{"type": "tax_form", "catalog_url": "/v1/catalog", "label": "서식"}],
        }
    )


class Forms:
    """카탈로그를 주는 함수 — 판을 시험이 바꿔 가며 올리는지 본다."""

    def __init__(self) -> None:
        self.revision: int | None = 1
        self.name = "전자세금계산서"

    def __call__(self) -> Catalog:
        return Catalog.model_validate(
            {"schema": 1, "revision": self.revision, "items": [{"type": "tax_form", "id": "e-tax", "name": self.name}]}
        )


def issue(req: OpRequest, mode: str) -> OpResult:
    return OpResult({"invoice_no": f"INV-{req.input.get('n', 0)}"})


def refuse(req: OpRequest, mode: str) -> OpResult:
    raise OpError("input_invalid", "사업자 번호가 틀렸다", status=422)


@pytest.fixture
def center(tmp_path: Path) -> Iterator[TestClient]:
    store = Store(tmp_path / "center.sqlite3")
    settings = CenterSettings(admin_token="t-admin", package_dir=tmp_path / "pkg")
    with TestClient(create_center(settings, store=store)) as found:
        yield found
    store.close()


@pytest.fixture
def forms() -> Forms:
    return Forms()


@pytest.fixture
def service(forms: Forms) -> Service:
    made: Service = create_app(manifest(), {"issue": issue, "refuse": refuse}, catalogs={"tax_form": forms}).state.ops
    return made


@pytest.fixture
def tokens(center: TestClient, tmp_path: Path) -> TokenFile:
    found: TokenFile = enroll(
        center, topics=[TOPIC], manifests=[manifest().to_json_dict()], folder=tmp_path / "consumer"
    )
    return found


@pytest.fixture
def consumer(center: TestClient, service: Service, tokens: TokenFile) -> Consumer:
    return Consumer([service], center_url="", tokens=tokens, wait_s=0, client=center)


@pytest.fixture
def studio(center: TestClient) -> dict[str, str]:
    """시험 실행으로 일감을 올리는 쪽 — Studio 키."""
    made = center.post("/api/v1/center-keys", json={"name": "설계자", "type": "studio"}, headers=ADMIN)
    assert made.status_code == 201, made.text
    return {"Authorization": f"Bearer {made.json()['key']}"}


def post(center: TestClient, studio: dict[str, str], **over: Any) -> str:
    body: dict[str, Any] = {
        "schema": 1,
        "topic": TOPIC,
        "operation": "issue",
        "mode": MODE_DETERMINISTIC,
        "origin": "test",
        "idempotency": {"run_id": RUN, "node_id": "Task_issue", "node_instance": 1, "attempt": 1},
        "caller": {"type": "studio", "host": "설계자 PC"},
        "input": {"n": 7},
        **over,
    }
    made = center.post("/api/v1/external-tasks", json=body, headers=studio)
    assert made.status_code == 201, made.text
    return str(made.json()["task_id"])


def seen(center: TestClient, studio: dict[str, str], task_id: str) -> dict[str, Any]:
    found = center.get(f"/api/v1/external-tasks/{task_id}", headers=studio)
    assert found.status_code == 200, found.text
    return dict(found.json())


class Counting:
    """Center로 나가는 요청을 센다 — `publish`가 같은 판을 다시 올리지 않는지."""

    def __init__(self, inner: TestClient) -> None:
        self.inner = inner
        self.puts: list[str] = []

    def put(self, path: str, **kw: Any) -> Any:
        self.puts.append(path)
        return self.inner.put(path, **kw)

    def post(self, path: str, **kw: Any) -> Any:
        return self.inner.post(path, **kw)


# ─────────────────────────── 들이기 ───────────────────────────


def test_enrollment_waits_for_approval_then_opens_the_sealed_token(center: TestClient, tmp_path: Path) -> None:
    tokens = TokenFile.at(tmp_path / "c")
    step = Enrollment(
        center_url="", name="일꾼", topics=[TOPIC], manifests=[], tokens=tokens, machine_id="a" * 64, client=center
    )
    code = step.step()
    assert code, "처음에는 요청 코드를 받는다"
    assert step.step() == code, "승인 전에는 같은 코드로 기다린다"
    assert tokens.token() is None

    enrollment_id = tokens.get("enrollment_id")
    assert center.post(f"/api/v1/enrollments/{enrollment_id}/approve", json={}, headers=ADMIN).status_code == 200
    assert step.step() is None
    raw = tokens.token()
    assert raw and (tmp_path / "c" / "consumer-token.json").exists()
    assert step.step() is None, "토큰이 있으면 다시 청하지 않는다"


def test_a_rejected_enrollment_stops_and_can_ask_again(center: TestClient, tmp_path: Path) -> None:
    tokens = TokenFile.at(tmp_path / "c")
    step = Enrollment(
        center_url="", name="일꾼", topics=[TOPIC], manifests=[], tokens=tokens, machine_id="b" * 64, client=center
    )
    step.step()
    enrollment_id = tokens.get("enrollment_id")
    rejected = center.post(f"/api/v1/enrollments/{enrollment_id}/reject", json={"reason": "모르는 서버"}, headers=ADMIN)
    assert rejected.status_code == 200, rejected.text
    with pytest.raises(RuntimeError, match="rejected"):
        step.step()
    assert not tokens.get("enrollment_id"), "다음 걸음은 새로 청한다"


def test_the_environment_token_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHK_SVC_TAX__CENTER__TOKEN", "from-env")
    tokens = TokenFile.at(tmp_path, env_prefix="CHK_SVC_TAX__")
    tokens.save(token="from-file")
    assert tokens.token() == "from-env"


def test_without_a_token_the_consumer_does_not_knock(service: Service, tmp_path: Path) -> None:
    class Nobody:
        def post(self, *_a: Any, **_k: Any) -> Any:  # pragma: no cover — 불리면 안 된다
            raise AssertionError("토큰 없이 Center를 불렀다")

    lonely = Consumer([service], center_url="", tokens=TokenFile.at(tmp_path), wait_s=0, client=Nobody())
    with pytest.raises(RuntimeError, match="토큰이 없다"):
        lonely.run_once(wait_s=0)


# ─────────────────────────── 한 바퀴 ───────────────────────────


def test_run_once_fetches_executes_and_completes(
    center: TestClient, consumer: Consumer, studio: dict[str, str]
) -> None:
    assert consumer.run_once(wait_s=0) == 0, "일감이 없으면 빈손이다"
    task_id = post(center, studio)
    assert consumer.run_once(wait_s=0) == 1

    found = seen(center, studio, task_id)
    assert found["state"] == "completed" and found["output"] == {"invoice_no": "INV-7"}
    assert found["mode_used"] == MODE_DETERMINISTIC and found["replayed"] is False
    assert consumer.registration().registered and consumer.registration().last_reported_at, "SVC-01이 본다"


def test_an_operation_failure_goes_back_as_fail(center: TestClient, consumer: Consumer, studio: dict[str, str]) -> None:
    task_id = post(center, studio, operation="refuse")
    consumer.run_once(wait_s=0)
    found = seen(center, studio, task_id)
    assert found["state"] == "failed"
    assert found["error"] == {"code": "input_invalid", "message": "사업자 번호가 틀렸다", "retryable": False}


def test_a_slot_still_running_sends_nothing(
    center: TestClient, consumer: Consumer, service: Service, studio: dict[str, str]
) -> None:
    """같은 멱등 칸이 **이 앱 안에서 아직 도는 중**이면 끝내지 않는다 — 앞의 것이 끝내면 그것이 이긴다."""
    task_id = post(center, studio)
    [task] = consumer.fetch(max_tasks=1, wait_s=0)
    req = service.request_of(task)
    service.idempotency.begin(idempotency_key(task.operation, req), body=body_hash(req))

    consumer.handle(task)
    assert seen(center, studio, task_id)["state"] == "locked", "아무것도 보내지 않았다"


def test_a_409_on_finish_is_ignored(
    center: TestClient, consumer: Consumer, studio: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    """올린 쪽이 거뒀다(409 `cancelled`) — 일꾼은 경고 없이 다음 일감으로 간다."""
    task_id = post(center, studio)
    [task] = consumer.fetch(max_tasks=1, wait_s=0)
    assert center.post(f"/api/v1/external-tasks/{task_id}/cancel", headers=studio).status_code == 200

    with caplog.at_level(logging.WARNING, logger="chaeksas.service_kit.consumer"):
        consumer.handle(task)
    assert caplog.records == []
    assert seen(center, studio, task_id)["state"] == "cancelled"


def test_a_redelivered_task_is_finished_from_the_stored_result(
    center: TestClient, consumer: Consumer, studio: dict[str, str]
) -> None:
    """잠금이 지나 다시 온 일감 — 다시 수행하지 않고 **저장된 결과로** 끝낸다 (`replayed`)."""
    task_id = post(center, studio)
    [task] = consumer.fetch(max_tasks=1, wait_s=0)
    first = consumer.services[0].execute(task)
    assert first.ok  # 수행은 했는데 끝내기 전에 일꾼이 죽었다

    consumer.handle(task)
    found = seen(center, studio, task_id)
    assert found["state"] == "completed" and found["replayed"] is True


# ─────────────────────────── 올리기 ───────────────────────────


def test_publish_uploads_the_manifest_once_and_the_catalog_when_its_revision_changes(
    center: TestClient, service: Service, tokens: TokenFile, forms: Forms
) -> None:
    counting = Counting(center)
    consumer = Consumer([service], center_url="", tokens=tokens, wait_s=0, client=counting)

    consumer.publish()
    assert counting.puts == ["/api/v1/consumers/self/manifest", "/api/v1/consumers/self/catalogs/tax_form"]
    consumer.publish()
    assert len(counting.puts) == 2, "같은 판이면 다시 올리지 않는다"

    forms.revision, forms.name = 2, "전자세금계산서 (고침)"
    consumer.publish()
    assert counting.puts[2:] == ["/api/v1/consumers/self/catalogs/tax_form"], "판이 바뀌면 카탈로그만"

    consumer.publish(force=True)
    assert len(counting.puts) == 5, "`force`는 둘 다 다시 올린다"

    found = center.get("/api/v1/resources?type=contributed", headers=ADMIN).json()["items"]
    assert [(one["id"], one["name"], one["revision"], one["extension_id"]) for one in found] == [
        ("e-tax", "전자세금계산서 (고침)", 2, "tax")
    ]


def test_a_catalog_without_a_revision_is_uploaded_every_time(
    center: TestClient, service: Service, tokens: TokenFile, forms: Forms
) -> None:
    """판이 없으면 같은지 모른다 — 매번 올린다 (Center도 그때는 항목을 다시 쓴다)."""
    forms.revision = None
    counting = Counting(center)
    consumer = Consumer([service], center_url="", tokens=tokens, wait_s=0, client=counting)
    consumer.publish()
    consumer.publish()
    assert counting.puts.count("/api/v1/consumers/self/catalogs/tax_form") == 2
