"""키가 없을 때 — 등록 요청 → 승인 → 키 받기 (C12 §등록 요청과 승인, ADR-0092).

서버 실행기에는 화면이 없다. 그래서 **요청 코드를 로그 한 줄로** 찍고, 관리자는 Center 콘솔
「서버 실행」의 「승인 대기」에서 같은 코드를 보고 승인한다. 승인되면 받은 키를 비밀 저장소에 두고
평소처럼 등록한다.

- **환경변수로 키가 오면** 여기에 오지 않는다 (컨테이너·CI의 길).
- **비밀 저장소가 없으면 요청하지 않는다** — 받은 키를 둘 곳이 없다. 평문 파일로 흘리지 않는다.
- 보낸 요청은 데이터 폴더의 `enrollment.json`에 둔다 — 다시 떠도 같은 요청을 묻는다. 그 파일에는
  키도 봉함도 없다(요청 id·코드·상태뿐이다).
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from chaeksas.contracts.enrollment import (
    EnrollStatus,
    SealError,
    new_keypair,
    open_sealed,
    public_of,
    request_code,
)
from chaeksas.contracts.server_runner import ServerRunnerEnrollRequest
from chaeksas.server_runner.agent import Agent
from chaeksas.server_runner.center_client import CenterProblem, Unreachable
from chaeksas.server_runner.credentials import ENV_CENTER_API_KEY, SecretsUnavailable
from chaeksas.server_runner.secret_file import ENV_SECRETS_DIR

log = logging.getLogger(__name__)

STATE_FILE = "enrollment.json"

NO_SECRETS = (
    "Center API 키가 없고 OS 비밀 저장소도 없습니다 — 받은 키를 둘 곳이 없어 등록 요청을 보내지 "
    f"않습니다. 비밀 폴더를 {ENV_SECRETS_DIR}로 적어 주거나(컨테이너는 볼륨) "
    f"환경변수 {ENV_CENTER_API_KEY}로 「서버 실행기용」 키를 주세요"
)


def _state_path(agent: Agent) -> Path:
    return agent.settings.data_path / STATE_FILE


def _load(agent: Agent) -> EnrollStatus | None:
    path = _state_path(agent)
    if not path.exists():
        return None
    try:
        return EnrollStatus.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as e:
        log.warning("등록 요청 기록을 읽지 못해 새로 요청한다 (%s): %s", path, e)
        return None


def _save(agent: Agent, found: EnrollStatus | None) -> None:
    path = _state_path(agent)
    if found is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    kept = found.model_copy(update={"sealed_key": None}).to_json_dict()
    path.write_text(json.dumps(kept, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def _secret(agent: Agent) -> str:
    found = agent.credentials.enroll_secret()
    if found:
        return found
    private, _ = new_keypair()
    agent.credentials.set_enroll_secret(private)
    return private


def _ask(agent: Agent, secret: str) -> EnrollStatus:
    public = public_of(secret)
    request = ServerRunnerEnrollRequest(**agent.register_fields(), public_key=public)
    found = agent.client.enroll(request)
    if found.code != request_code(public, found.enrollment_id):
        raise CenterProblem("Center가 준 요청 코드가 이 서버가 계산한 것과 다릅니다 — Center 주소를 확인하세요")
    _save(agent, found)
    log.info(
        "Center에 등록 요청을 보냈습니다. 요청 코드 %s — Center 콘솔 「서버 실행」에서 승인하세요 (%s까지)",
        found.code,
        found.expires_at,
    )
    return found


def step(agent: Agent) -> str | None:
    """한 걸음. 키를 받았으면 그 키, 아직이면 `None`. 거절되면 `CenterProblem`(사람의 일)."""
    secret = _secret(agent)
    current = _load(agent)
    if current is None or current.state == "expired":
        _ask(agent, secret)
        return None
    try:
        found = agent.client.enroll_status(current.enrollment_id)
    except CenterProblem as e:
        if e.status == 404:
            _save(agent, None)  # Center가 모르는 요청 — 다음 걸음에 새로 보낸다
            return None
        raise
    if found.state == "rejected":
        _save(agent, None)  # 다시 띄우면 새로 요청한다
        reason = f": {found.reason}" if found.reason else ""
        raise CenterProblem(f"등록 요청이 거절되었습니다{reason} — 다시 요청하려면 실행기를 다시 띄우세요")
    if found.state == "approved" and found.sealed_key is not None:
        try:
            key = open_sealed(secret, found.sealed_key, salt=found.enrollment_id)
        except SealError as e:
            _save(agent, None)
            raise CenterProblem(f"받은 키를 열지 못했습니다 — {e}") from e
        agent.credentials.set_center_api_key(key)
        _save(agent, None)
        log.info("등록 요청이 승인되어 Center API 키를 받았다")
        return key
    _save(agent, found)
    if found.state == "pending":
        log.info("승인을 기다린다 — 요청 코드 %s", found.code)
    return None


def obtain_key(agent: Agent, *, once: bool, stop: threading.Event | None = None) -> str | None:
    """키를 받을 때까지 묻는다. `once`면 한 걸음만 (`--once` — 설치 확인).

    비밀 저장소가 없으면 `SecretsUnavailable`을 그대로 올린다 — 부르는 쪽이 `NO_SECRETS`를 찍는다.
    """
    if not agent.credentials.available:
        raise SecretsUnavailable(NO_SECRETS)
    waiting = stop or threading.Event()
    while not waiting.is_set():
        try:
            key = step(agent)
        except Unreachable as e:
            log.warning("%s", e)
            key = None
        if key or once:
            return key
        current = _load(agent)
        waiting.wait(current.poll_after_s if current is not None else agent.settings.retry_s)
    return None


__all__ = ["NO_SECRETS", "STATE_FILE", "obtain_key", "step"]
