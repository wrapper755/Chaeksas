"""어댑터 일꾼 (`apps/adapter_consumer`) — 외부 확장 하나를 일꾼의 토픽으로 돌린다 (C13 §4·C15, ADR-0102).

모의 외부 앱 `ext-credit`을 **진짜 소켓**에 띄우고 `AdapterService.execute()`가 그 정의의 어댑터로 부르게
한다 (어댑터는 호스트를 IP로 풀어 그 IP로 접속하므로 ASGI로 끼울 수 없다). 설정은 환경변수 대신
`environ` 칸으로 준다 — 시험이 프로세스 환경을 더럽히지 않는다.

| 보는 것 | 왜 |
| --- | --- |
| 정의 → 일꾼 manifest (`manifest_of`) — 작업·모드가 그대로 | Center가 그것으로 작업·모드를 대조한다 (C15) |
| 일감 하나가 외부 앱까지 가서 우리 말로 돌아온다 | 어댑터 해석기가 실행하는 쪽의 것과 같다 |
| 같은 멱등 칸은 **외부 앱을 다시 부르지 않는다** (`replayed`) | 잠금이 지나 다시 온 일감 (최소 한 번) |
| 시험 일감(`origin: test`)은 `TEST_BASE_URL`·`TEST_KEY`로, 비면 운영 쪽 | ADR-0102 §6 — 운영 앱을 건드리지 않는다 |
| 사설망은 **정의와 일꾼 설정이 둘 다 열어야** 나간다 | 기본 닫힘 (C13 「어댑터 일꾼」) |
| 키가 없으면 `key_missing`, 업무 실패는 다시 해 볼 만하지 않다 | 오류 경계·재시도가 코드에 걸려 있다 |
| 실패는 멱등 자리를 비운다 | 같은 시도로 다시 받을 수 있어야 한다 |
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from consumers import serve

from chaeksas.adapter_consumer.adapter import ENV_PREFIX, AdapterService, ext_env, manifest_of
from chaeksas.contracts.extension import ExtensionManifest
from chaeksas.contracts.external_task import LockedTask
from chaeksas.mock_apps.external import apps as external_apps
from chaeksas.mock_apps.external import definitions

APP = "ext-credit"
KEY = "ext-secret-1"
DEAD = "http://127.0.0.1:9"  # 아무도 듣지 않는 포트


@pytest.fixture(scope="module")
def credit() -> Iterator[str]:
    url, server, thread = serve(external_apps.BUILDERS[APP]())
    yield url
    server.should_exit = True
    thread.join(timeout=10)


class Hits:
    """외부 앱으로 나간 요청 — 어느 주소로, 몇 번 (값은 담지 않는다)."""

    def __init__(self) -> None:
        self.urls: list[str] = []
        self.client = httpx.Client(event_hooks={"request": [self._seen]})

    def _seen(self, request: httpx.Request) -> None:
        self.urls.append(str(request.url))


@pytest.fixture
def hits() -> Iterator[Hits]:
    found = Hits()
    yield found
    found.client.close()


def definition(base: str) -> ExtensionManifest:
    return ExtensionManifest.model_validate(definitions.BUILDERS[APP](base))


def service(base: str, hits: Hits, **settings: str) -> AdapterService:
    environ = {f"{ENV_PREFIX}ALLOW_PRIVATE_NETWORK": "1", ext_env(APP, "BASE_URL"): base, ext_env(APP, "KEY"): KEY}
    environ.update({ext_env(APP, name): value for name, value in settings.items()})
    if settings.get("OPEN") == "0":
        environ.pop(f"{ENV_PREFIX}ALLOW_PRIVATE_NETWORK")
    return AdapterService(
        definition=definition(base), environ=environ, client=hits.client, resolver=lambda host: ["127.0.0.1"]
    )


def task(**over: Any) -> LockedTask:
    slot = {"run_id": "run_20261029_090000_a1b2c3", "node_id": "Task_credit", "node_instance": 1, "attempt": 1}
    slot.update({k: over.pop(k) for k in list(over) if k in slot})
    body: dict[str, Any] = {
        "task_id": "et_credit",
        "topic": APP,
        "operation": "lookup",
        "mode": "deterministic",
        "origin": "run",
        "idempotency": slot,
        "caller": {"type": "server_runner", "host": "srv_01", "bpm_process_id": "fin.credit", "version": "1.0.0"},
        "input": {"biz_no": "123-45-67890"},
        "lock_until": "2026-10-29T09:10:00+09:00",
        "deadline": "2026-10-29T09:10:00+09:00",
        **over,
    }
    return LockedTask.model_validate(body)


# ─────────────────────────── manifest ───────────────────────────


def test_the_definition_becomes_the_consumers_manifest() -> None:
    found = definition("http://127.0.0.1:8150")
    made = manifest_of(found)
    assert made.app_id == APP and made.version == found.version
    adapter = found.service.adapter if found.service else None
    assert adapter is not None
    assert [(one.name, sorted(one.modes)) for one in made.operations] == [
        (one.name, sorted(one.modes)) for one in adapter.operations
    ]
    assert made.extension is None, "외부 확장은 등록된 정의가 원본이다 — 일꾼이 확장을 자처하지 않는다"


def test_the_topic_is_the_extension_id(credit: str, hits: Hits) -> None:
    one = service(credit, hits)
    assert one.app_id == APP and one.manifest.app_id == APP
    assert one.catalogs == {}, "`ext-credit`은 카탈로그를 선언하지 않는다"


# ─────────────────────────── 수행 ───────────────────────────


def test_a_task_reaches_the_external_app_and_comes_back(credit: str, hits: Hits) -> None:
    """FX-20 「모의 서버」가 `결과 = {"score": 780}`를 기대한다 — 정의가 우리 말로 옮긴다."""
    done = service(credit, hits).execute(task())
    assert done.ok, done.fail_body()
    body = done.complete_body()
    assert body["output"]["result"]["score"] == 780
    assert body["replayed"] is False and body["mode_used"] == "deterministic"
    assert len(hits.urls) == 1 and hits.urls[0].startswith(credit)


def test_the_same_slot_does_not_call_the_app_again(credit: str, hits: Hits) -> None:
    one = service(credit, hits)
    first = one.execute(task())
    again = one.execute(task(task_id="et_credit", delivery=2))
    assert again.ok and again.complete_body()["replayed"] is True
    assert again.complete_body()["output"] == first.complete_body()["output"]
    assert len(hits.urls) == 1, "외부 앱을 다시 부르지 않았다"

    other = one.execute(task(attempt=2))
    assert other.complete_body()["replayed"] is False and len(hits.urls) == 2


def test_the_same_slot_with_another_body_conflicts(credit: str, hits: Hits) -> None:
    one = service(credit, hits)
    one.execute(task())
    done = one.execute(task(input={"biz_no": "234-56-78901"}))
    assert done.code == "idempotency_conflict"


def test_a_slot_still_running_is_skipped(credit: str, hits: Hits) -> None:
    one = service(credit, hits)
    from chaeksas.adapter_consumer.adapter import body_hash_of  # noqa: PLC0415

    found = task()
    slot = found.idempotency
    key = ("adapter", found.operation, slot.run_id, slot.node_id, slot.node_instance, slot.attempt, slot.call_seq)
    one.idempotency.begin(key, body=body_hash_of(found))
    assert one.execute(found).skip
    assert hits.urls == []


# ─────────────────────────── 운영·시험 ───────────────────────────


def test_a_test_task_goes_to_the_test_address(credit: str, hits: Hits) -> None:
    """시험 일감은 `TEST_BASE_URL`로 — 운영 주소가 죽어 있어도 시험은 돈다."""
    one = service(DEAD, hits, TEST_BASE_URL=credit, TEST_KEY=KEY)
    trial = one.execute(task(origin="test", run_id="test_aaaaaa"))
    assert trial.ok, trial.fail_body()
    assert hits.urls[-1].startswith(credit)

    field = one.execute(task())
    assert (field.code, field.retryable) == ("unreachable", True), "운영 일감은 운영 주소로 갔다 — 닿지 못했다"
    assert hits.urls[-1].startswith(DEAD)


def test_a_test_task_falls_back_to_the_field_settings(credit: str, hits: Hits) -> None:
    """시험 칸이 비면 운영 쪽을 쓴다 (ADR-0102 §6)."""
    done = service(credit, hits).execute(task(origin="test", run_id="test_bbbbbb"))
    assert done.ok and hits.urls[-1].startswith(credit)


def test_the_test_key_is_used_for_test_tasks(credit: str, hits: Hits) -> None:
    one = service(credit, hits, KEY="", TEST_KEY=KEY)
    assert one.execute(task(origin="test", run_id="test_cccccc")).ok
    assert one.execute(task()).code == "key_missing", "운영 키가 없으면 시험 키로 대신하지 않는다"


# ─────────────────────────── 막는 것 ───────────────────────────


def test_the_private_network_is_closed_unless_the_consumer_opens_it(credit: str, hits: Hits) -> None:
    """정의가 127.0.0.1을 허용해도 **일꾼 설정이 열지 않으면** 나가지 않는다."""
    closed = service(credit, hits, OPEN="0").execute(task())
    assert (closed.code, closed.retryable) == ("host_not_allowed", False), closed.fail_body()
    assert hits.urls == [], "나가기 전에 막았다"

    assert service(credit, hits).execute(task()).ok, "열면 나간다"


def test_without_a_key_it_stops_before_going_out(credit: str, hits: Hits) -> None:
    done = service(credit, hits, KEY="").execute(task())
    assert (done.code, done.retryable) == ("key_missing", False)
    assert hits.urls == []


def test_a_business_failure_frees_the_slot(credit: str, hits: Hits) -> None:
    """모의 앱은 200에 `status: "not_found"`로 답한다 — `error_when`이 실패로 바꾼다."""
    one = service(credit, hits)
    missing = task(input={"biz_no": "000-00-00000"})
    first = one.execute(missing)
    assert (first.code, first.retryable) == ("operation_failed", False)
    again = one.execute(missing)
    assert again.code == "operation_failed" and len(hits.urls) == 2, "자리를 비웠으니 다시 불렀다"
