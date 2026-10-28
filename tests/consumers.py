"""시험이 **일꾼**을 Center에 들이고 돌리는 길 — 자리가 하나다 (C15, ADR-0102).

**이것은 제품 코드가 아니다.** 사람은 Center 콘솔 「일꾼 승인 대기」에서 요청 코드를 맞춰 누르고, 시험은
관리자 토큰으로 같은 승인 API를 부른다. 토큰은 **봉해서** 받는다 — 제품과 같은 `Enrollment`가 연다.

`client`는 `TestClient`(in-process)든 진짜 소켓의 `httpx.Client`든 된다. 일꾼을 **스레드에서** 오래
돌리려면(롱폴링) 진짜 소켓 Center를 쓴다 — `serve()`가 띄운다.
"""

from __future__ import annotations

import tempfile
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import uvicorn

from chaeksas.service_kit import Consumer, Enrollment, TokenFile, TopicService

ADMIN = {"Authorization": "Bearer t-admin"}


def serve(app: Any) -> tuple[str, Any, threading.Thread]:
    """ASGI 앱 하나를 127.0.0.1의 빈 포트에 띄운다 → `(주소, 서버, 스레드)`."""
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started, "앱이 뜨지 않았다"
    return f"http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}", server, thread


def enroll(
    client: Any,
    *,
    topics: Sequence[str],
    manifests: Sequence[dict[str, Any]] = (),
    name: str = "시험 일꾼",
    folder: Path | None = None,
    machine: str | None = None,
    headers: dict[str, str] = ADMIN,
) -> TokenFile:
    """일꾼 하나를 들인다 — 요청 → 관리자 승인 → 봉한 토큰을 연다. 돌려주는 것은 토큰 자리다."""
    where = folder or Path(tempfile.mkdtemp(prefix="consumer-"))
    tokens = TokenFile.at(where)
    step = Enrollment(
        center_url="",
        name=name,
        topics=list(topics),
        manifests=list(manifests),
        tokens=tokens,
        machine_id=machine or ("e" * 48 + format(abs(hash(where)) % 16**16, "016x")),
        client=client,
    )
    code = step.step()
    assert code, "들이기 요청이 요청 코드를 받지 못했다"
    enrollment_id = tokens.get("enrollment_id")
    approved = client.post(f"/api/v1/enrollments/{enrollment_id}/approve", json={}, headers=headers)
    assert approved.status_code == 200, approved.text
    assert step.step() is None
    assert tokens.token(), "승인했는데 토큰을 열지 못했다"
    return tokens


def start(
    services: Sequence[TopicService],
    *,
    center_url: str,
    tokens: TokenFile,
    publish: bool = True,
    wait_s: int = 2,
) -> tuple[Consumer, threading.Event]:
    """일꾼을 데몬 스레드에서 돌린다 → `(일꾼, 멈추는 이벤트)`. 시험이 끝나면 `stop.set()`."""
    consumer = Consumer(list(services), center_url=center_url, tokens=tokens, wait_s=wait_s)
    if publish:
        consumer.publish(force=True)
    stop = threading.Event()
    threading.Thread(target=consumer.run, args=(stop,), name="test-consumer", daemon=True).start()
    return consumer, stop


def mock_fleet(
    http: Any,
    *,
    center_url: str,
    built: Sequence[Any],
    external_ids: Sequence[str] = (),
    folder: Path,
) -> list[threading.Event]:
    """업무 예제가 부르는 모의 앱을 **일꾼으로** 붙인다 (C15) — 묶음 시험이 함께 쓴다.

    - C11 모의 앱들(`built` — `mock_apps.c11.Built`)은 **일꾼 하나**가 토픽 여럿을 맡는다 (`chk-mock-apps`와 같다).
    - 외부 모의 앱(`external_ids`)은 **어댑터 일꾼**이 맡는다 — 정의는 이미 Center에 등록돼 있어야 한다.
      127.0.0.1을 부르므로 사설망을 열고, 키는 아무 글이나 받는 모의라 `dev-key`를 준다.

    돌려주는 것은 멈추는 이벤트들이다 — 시험이 끝나면 모두 `set()`.
    """
    from chaeksas.adapter_consumer.adapter import AdapterService, ext_env  # noqa: PLC0415
    from chaeksas.adapter_consumer.main import load_definitions  # noqa: PLC0415

    stops: list[threading.Event] = []
    services = [one.service for one in built]
    if services:
        tokens = enroll(
            http,
            topics=[one.app_id for one in services],
            manifests=[one.manifest.to_json_dict() for one in services],
            name="모의 앱",
            folder=folder / "mock-apps",
        )
        stops.append(start(services, center_url=center_url, tokens=tokens)[1])
    if external_ids:
        tokens = enroll(http, topics=list(external_ids), name="어댑터 일꾼", folder=folder / "adapter")
        environ = {"CHK_ADAPTER__ALLOW_PRIVATE_NETWORK": "1"}
        environ |= {ext_env(one, "KEY"): "dev-key" for one in external_ids}
        loaded = load_definitions(center_url, str(tokens.token()), list(external_ids), client=http)
        assert {one.app_id for one in loaded} == set(external_ids), "외부 정의를 다 받지 못했다"
        adapters = [AdapterService(definition=one.definition, environ=environ) for one in loaded]
        stops.append(start(adapters, center_url=center_url, tokens=tokens)[1])
    return stops


__all__ = ["ADMIN", "enroll", "mock_fleet", "serve", "start"]
