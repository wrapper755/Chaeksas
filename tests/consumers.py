"""시험이 **일꾼**을 Center에 들이고 돌리는 길 — 자리가 하나다 (C15, ADR-0102).

**이것은 제품 코드가 아니다.** 사람은 Center의 일꾼 폴더에 `<이름>.consumer.json`(토큰 해시)을 두고 Center를
다시 띄운다 (ADR-0122). 시험은 Center를 다시 띄우지 않고 **폴더가 쓰는 함수 그대로**(`consumer_folder.admit`)로
들인다 — 토큰 원문은 시험이 지어 `TokenFile`에 둔다.

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

from chaeksas.center.consumer_folder import admit, new_token, token_sha256
from chaeksas.center.storage import Store
from chaeksas.contracts.external_task import FolderConsumer
from chaeksas.service_kit import Consumer, TokenFile, TopicService

ADMIN = {"Authorization": "Bearer t-admin"}


#: `serve()`가 띄운 앱 — 주소로 그 Center의 저장소를 찾는다 (`store_of`).
_SERVED: dict[str, Any] = {}


def store_of(client: Any) -> Store:
    """그 Center의 저장소 — `TestClient`면 앱에서, 진짜 소켓이면 `serve()`가 적어 둔 앱에서."""
    app = getattr(client, "app", None)
    if app is None or not hasattr(app, "state"):
        app = _SERVED[str(client.base_url).rstrip("/")]
    store: Store = app.state.store
    return store


def serve(app: Any) -> tuple[str, Any, threading.Thread]:
    """ASGI 앱 하나를 127.0.0.1의 빈 포트에 띄운다 → `(주소, 서버, 스레드)`."""
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started, "앱이 뜨지 않았다"
    url = f"http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}"
    _SERVED[url] = app
    return url, server, thread


def enroll(
    client: Any,
    *,
    topics: Sequence[str],
    manifests: Sequence[dict[str, Any]] = (),
    name: str = "시험 일꾼",
    folder: Path | None = None,
    machine: str | None = None,
    headers: dict[str, str] = ADMIN,  # noqa: ARG001 — 옛 부르는 꼴을 받는다 (승인이 없어졌다, ADR-0122)
) -> TokenFile:
    """일꾼 하나를 들인다 — 일꾼 폴더가 하는 일 그대로. 돌려주는 것은 토큰 자리다."""
    where = folder or Path(tempfile.mkdtemp(prefix="consumer-"))
    tokens = TokenFile.at(where)
    raw = new_token()
    spec = FolderConsumer.model_validate(
        {"name": name, "topics": list(topics), "token_sha256": token_sha256(raw), "manifests": list(manifests)}
    )
    stem = machine or f"test-{format(abs(hash(where.resolve().as_posix())) % 16**12, '012x')}"
    got = admit(store_of(client), stem, spec)
    assert got.outcome in ("registered", "unchanged"), got
    tokens.save(token=raw)
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
    definitions: Sequence[dict[str, Any]] = (),
    folder: Path,
) -> list[threading.Event]:
    """업무 예제가 부르는 모의 앱을 **일꾼으로** 붙인다 (C15) — 묶음 시험이 함께 쓴다.

    - C11 모의 앱들(`built` — `mock_apps.c11.Built`)은 **일꾼 하나**가 토픽 여럿을 맡는다 (`bpm-mock-apps`와 같다).
    - 외부 모의 앱(`external_ids`)은 **어댑터 일꾼**이 맡고 **제 정의를 올린다**(ADR-0122) — `definitions`가
      그 정의들이다. 127.0.0.1을 부르므로 사설망을 열고, 키는 아무 글이나 받는 모의라 `dev-key`를 준다.

    돌려주는 것은 멈추는 이벤트들이다 — 시험이 끝나면 모두 `set()`.
    """
    from chaeksas.adapter_consumer.adapter import ext_env  # noqa: PLC0415
    from chaeksas.adapter_consumer.main import service_of  # noqa: PLC0415

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
        environ = {"BPM_ADAPTER__ALLOW_PRIVATE_NETWORK": "1"}
        environ |= {ext_env(one, "KEY"): "dev-key" for one in external_ids}
        adapters = [service_of(one, environ=environ) for one in definitions]
        assert {one.app_id for one in adapters} == set(external_ids), "외부 정의가 맡은 토픽과 다르다"
        stops.append(start(adapters, center_url=center_url, tokens=tokens)[1])
    return stops


__all__ = ["ADMIN", "enroll", "mock_fleet", "serve", "start", "store_of"]
