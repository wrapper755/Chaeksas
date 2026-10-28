"""C15 한 바퀴 — 부르는 쪽 → Center → 일꾼 → Center → 부르는 쪽 (ADR-0102).

조각마다 Center(`test_center_external_tasks.py`)·일꾼(`test_service_kit.py`)·호출기를 따로 보지만, **정말
맞물리는지**는 이것만 안다 — 진짜 소켓 Center, 진짜 롱폴링, 진짜 일꾼 스레드다.

| 보는 것 | 왜 |
| --- | --- |
| 서비스 태스크 호출이 **일꾼의 작업 함수**까지 가서 출력이 돌아온다 | 부르는 쪽이 앱의 주소·키를 모른다 |
| 앱이 실패하면 **그 코드 그대로** `ServiceCallError`가 된다 | 오류 경계·재시도가 코드에 걸려 있다 |
| 결과를 받으면 Center에 **값이 남지 않는다** | 원칙 6 — `ack` |
| 오래 걸리면 **기다림으로 넘기고** 나중에 결과를 묻는다 | 서버 실행기가 자리를 놓는다 (ADR-0103) |
| 받아 간 값을 잃으면 **같은 칸으로 다시 올려** 같은 결과를 받는다 | 되살린 실행 (ADR-0103 §5) |
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from consumers import ADMIN, enroll, serve, start

from chaeksas.center.app import create_app
from chaeksas.center.settings import Settings as CenterSettings
from chaeksas.center.storage import Store
from chaeksas.core.services import (
    CenterServiceCaller,
    OpCall,
    ServiceCallError,
    ServicePending,
    ServiceResultLost,
)
from chaeksas.mock_apps import catalog
from chaeksas.mock_apps.c11 import build


@pytest.fixture
def center(tmp_path: Path) -> Iterator[tuple[str, Store]]:
    store = Store(tmp_path / "center.sqlite3")
    app = create_app(CenterSettings(admin_token="t-admin", package_dir=tmp_path / "pkg"), store=store)
    url, server, thread = serve(app)
    yield url, store
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def worker(center: tuple[str, Store], tmp_path: Path) -> Iterator[Any]:
    url, _ = center
    erp = catalog.c11("erp")
    assert erp is not None
    made = build(erp)
    with httpx.Client(base_url=url, timeout=30) as http:
        tokens = enroll(http, topics=["erp"], manifests=[made.service.manifest.to_json_dict()], folder=tmp_path / "c")
    _, stop = start([made.service], center_url=url, tokens=tokens)
    yield made
    stop.set()


def studio_key(url: str) -> str:
    with httpx.Client(base_url=url) as http:
        made = http.post("/api/v1/center-keys", json={"name": "설계자", "type": "studio"}, headers=ADMIN)
        assert made.status_code == 201, made.text
        return str(made.json()["key"])


def call(**over: Any) -> OpCall:
    body: dict[str, Any] = {
        "app_id": "erp",
        "operation": "list_overdue_receivables",
        "mode": "deterministic",
        "input": {},
        "run_id": "test_20261029_000000_aaaaaa",
        "node_id": "Task_list",
        **over,
    }
    return OpCall(**body)


def test_a_service_call_goes_through_center_to_the_consumer(center: tuple[str, Store], worker: Any) -> None:
    url, store = center
    caller = CenterServiceCaller(base_url=url, token=studio_key(url), caller_type="studio")
    found = caller.call(call())
    assert "receivables" in found.output or found.output  # 모의 ERP가 짠 답을 준다
    assert found.mode_used == "deterministic"
    row = store.row("SELECT input_json, output_json, acked_at FROM external_tasks")
    assert row is not None and row["input_json"] is None and row["output_json"] is None and row["acked_at"]


def test_the_apps_failure_code_comes_back(center: tuple[str, Store], worker: Any) -> None:
    url, _ = center
    caller = CenterServiceCaller(base_url=url, token=studio_key(url), caller_type="studio")
    with pytest.raises(ServiceCallError) as caught:
        caller.call(call(operation="no_such_op"))
    assert caught.value.code == "operation_not_found"
    assert caught.value.retryable is False


def test_a_long_task_is_handed_back_and_asked_for_later(center: tuple[str, Store], tmp_path: Path) -> None:
    """일꾼이 아직 없다 → 기다림으로 넘긴다. 일꾼이 붙어 끝내면 **묻는 쪽이** 결과를 받는다."""
    url, store = center
    caller = CenterServiceCaller(base_url=url, token=studio_key(url), caller_type="studio", park_after_s=0)
    erp = catalog.c11("erp")
    assert erp is not None
    made = build(erp)
    with httpx.Client(base_url=url, timeout=30) as http:
        tokens = enroll(http, topics=["erp"], manifests=[made.service.manifest.to_json_dict()], folder=tmp_path / "c")
    with pytest.raises(ServicePending) as parked:
        caller.call(call())
    task_id = parked.value.task_id
    assert caller.result(call(), task_id) is None  # 아직이다

    _, stop = start([made.service], center_url=url, tokens=tokens)
    try:
        found = None
        for _ in range(100):
            found = caller.result(call(), task_id)
            if found is not None:
                break
            time.sleep(0.1)
        assert found is not None and found.output
        caller.ack(task_id)
        row = store.row("SELECT output_json, acked_at FROM external_tasks WHERE task_id = ?", (task_id,))
        assert row is not None and row["output_json"] is None and row["acked_at"]

        # 넣고 ack한 뒤 죽었다 — 값이 없다. **같은 칸으로 다시 올리면** 같은 결과를 받는다.
        with pytest.raises(ServiceResultLost):
            caller.result(call(), task_id)
        again = CenterServiceCaller(base_url=url, token=caller.token, caller_type="studio").call(call())
        assert dict(again.output) == dict(found.output)
    finally:
        stop.set()


def test_a_parked_task_can_be_withdrawn(center: tuple[str, Store]) -> None:
    url, store = center
    caller = CenterServiceCaller(base_url=url, token=studio_key(url), caller_type="studio", park_after_s=0)
    with pytest.raises(ServicePending) as parked:
        caller.call(call())
    caller.withdraw(parked.value.task_id)
    row = store.row("SELECT state FROM external_tasks WHERE task_id = ?", (parked.value.task_id,))
    assert row is not None and row["state"] == "cancelled"
