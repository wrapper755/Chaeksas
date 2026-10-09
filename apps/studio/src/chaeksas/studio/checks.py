"""STU-10의 「연결 테스트」 — 화면과 떼어 둔 확인들. **결과는 사람이 읽는 한 줄**이다.

- 모델: `GET <주소>/v1/models` — 닿는지, 키가 맞는지 (ADR-0027 — OpenAI 호환).
- Center: `GET <주소>/api/v1/resources?type=service_app` — 닿는지, Studio용 키가 맞는지 (C7).
- Worker: `GET http://127.0.0.1:<포트>/v1/health` — 토큰 없이 답하는 유일한 자리 (C10).
- 서비스 앱 키: `core.key_check.key_status` — **Bot UI(BUI-10)와 같은 함수**를 쓴다. 두 화면이
  같은 말을 해야 하고, 앱끼리 import할 수 없어 `core`에 두었다.

키 값은 결과 글에 **들어가지 않는다**. `client`는 시험이 끼운다 (httpx와 같은 모양).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from chaeksas.core.key_check import key_status

#: Worker는 이 PC에만 바인드한다 (C10).
LOCAL_HOST = "127.0.0.1"
TIMEOUT_S = 5.0

#: Center에 묻는 가장 싼 자리 — 읽기 권한만 필요하고 **앱을 깨우지 않는다** (C7 `index(probe=False)`).
CENTER_PROBE_PATH = "/api/v1/resources?type=service_app"


def _get(url: str, *, headers: Mapping[str, str] | None = None, client: Any = None) -> Any:
    import httpx  # noqa: PLC0415 — 누를 때만 든다

    if client is not None:
        return client.get(url, headers=dict(headers or {}))
    with httpx.Client(timeout=TIMEOUT_S) as made:
        return made.get(url, headers=dict(headers or {}))


def _reachable(error: Exception) -> bool:
    import httpx  # noqa: PLC0415

    return not isinstance(error, httpx.HTTPError)


def llm_status(base_url: str, api_key: str | None, *, client: Any = None) -> str:
    """모델에 닿는가. 키가 없으면 키 없이 묻는다 (로컬 모델은 키가 필요 없다)."""
    if not base_url.strip():
        return "서버 주소가 없습니다."
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        answer = _get(f"{base_url.rstrip('/')}/v1/models", headers=headers, client=client)
    except Exception as e:  # noqa: BLE001 — 닿지 못한 모든 경우
        if _reachable(e):
            raise
        return f"닿지 못함 — {type(e).__name__}"
    if answer.status_code in (401, 403):
        return f"키가 거부되었습니다 ({answer.status_code})"
    if answer.status_code >= 400:
        return f"모델 서버가 {answer.status_code}로 답했습니다"
    try:
        names = [str(one.get("id")) for one in answer.json().get("data") or [] if isinstance(one, dict)]
    except ValueError:
        names = []
    shown = ", ".join(names[:3]) + (" …" if len(names) > 3 else "")
    return f"연결됨 — 모델 {len(names)}개" + (f" ({shown})" if names else "")


def center_status(base_url: str, api_key: str | None, *, client: Any = None) -> str:
    """Center에 닿는가, Studio용 키가 맞는가 (STU-10 「Center」).

    리소스 목록을 읽어 본다 — 읽기 권한만 쓰고(C5 권한표) 서비스 앱을 깨우지 않는다.
    **키 없이 묻지 않는다** — Center는 토큰 없는 요청을 401로 돌려보내므로 「키가 거부되었다」로
    읽혀 사람을 헷갈리게 한다.
    """
    if not base_url.strip():
        return "Center 주소가 없습니다."
    if not api_key:
        return "Center API 키가 없습니다."
    try:
        answer = _get(
            f"{base_url.rstrip('/')}{CENTER_PROBE_PATH}",
            headers={"Authorization": f"Bearer {api_key}"},
            client=client,
        )
    except Exception as e:  # noqa: BLE001 — 닿지 못한 모든 경우
        if _reachable(e):
            raise
        return f"닿지 못함 — {type(e).__name__}"
    if answer.status_code in (401, 403):
        return f"키가 거부되었습니다 ({answer.status_code})"
    if answer.status_code >= 400:
        return f"Center가 {answer.status_code}로 답했습니다"
    try:
        items = answer.json().get("items") or []
    except ValueError:
        items = []
    return f"연결됨 — 서비스 앱 {len(items)}개를 읽었습니다"


@dataclass(frozen=True)
class WorkerPlace:
    """Studio가 쓰는 Worker 자리 — Bot UI가 남긴 것 (`Extensions.runtime_settings`)."""

    port: int | None
    token_dir: str | None


def worker_place(values: Mapping[str, Any], runtime_id: str = "worker") -> WorkerPlace:
    port = values.get(f"runtime.{runtime_id}.port")
    token_dir = values.get(f"runtime.{runtime_id}.token_dir")
    return WorkerPlace(port=int(port) if port else None, token_dir=str(token_dir) if token_dir else None)


def worker_status(place: WorkerPlace, *, client: Any = None) -> str:
    if place.port is None:
        return "Worker를 기여한 확장이 없습니다."
    try:
        answer = _get(f"http://{LOCAL_HOST}:{place.port}/v1/health", client=client)
    except Exception as e:  # noqa: BLE001
        if _reachable(e):
            raise
        return "Bot UI가 꺼져 있거나 Worker가 떠 있지 않습니다."
    if answer.status_code >= 400:
        return f"포트 {place.port}의 무언가가 {answer.status_code}로 답했습니다 — Worker가 아닐 수 있습니다"
    try:
        body = answer.json()
    except ValueError:
        body = {}
    version = body.get("version") if isinstance(body, dict) else None
    return f"실행 중 — Worker {version}" if version else "실행 중"


def refs_in(definitions: Iterable[Any]) -> list[tuple[str, str]]:
    """그림이 쓰는 키 참조 `(참조, 서비스 앱)` — `chk:process.service_keys`와 태스크의 `key_ref`."""
    found: dict[str, str] = {}
    for definition in definitions:
        process = getattr(definition, "process", None)
        if process is None:
            continue
        for app_id, ref in process.info.service_keys.items():
            if ref:
                found.setdefault(str(ref), str(app_id))
        for node in process.all_nodes():
            call = node.prop("serviceCall")
            if call is not None and call.key_ref:
                found.setdefault(str(call.key_ref), str(call.app_id))
            task = node.prop("task")
            if task is not None and task.data.get("key_ref"):
                found.setdefault(str(task.data["key_ref"]), str(task.extension))
    return sorted(found.items())


__all__ = [
    "WorkerPlace",
    "center_status",
    "key_status",
    "llm_status",
    "refs_in",
    "worker_place",
    "worker_status",
]
