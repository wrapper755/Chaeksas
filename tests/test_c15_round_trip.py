"""C15 한 바퀴 — 부르는 쪽 → Center → 일꾼 → Center → 부르는 쪽 (ADR-0102).

조각마다 Center(`test_center_external_tasks.py`)·일꾼(`test_service_kit.py`)·호출기를 따로 보지만, **정말
맞물리는지**는 이것만 안다 — 진짜 소켓 Center, 진짜 롱폴링, 진짜 일꾼 스레드다.

| 보는 것 | 왜 |
| --- | --- |
| 서비스 태스크 호출이 **일꾼의 작업 함수**까지 가서 출력이 돌아온다 | 부르는 쪽이 앱의 주소·키를 모른다 |
| 앱이 실패하면 **그 코드 그대로** `ServiceCallError`가 된다 | 오류 경계·재시도가 코드에 걸려 있다 |
| 결과를 받으면 Center에 **값이 남지 않는다** | 원칙 6 — `ack` |
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from consumers import ADMIN, enroll, serve, start

from chaeksas.center.app import create_app
from chaeksas.center.settings import Settings as CenterSettings
from chaeksas.center.storage import Store
from chaeksas.core.services import CenterServiceCaller, OpCall, ServiceCallError
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
