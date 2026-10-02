"""확장 코드가 받는 바깥 세상 — 설정·비밀·기록, 그리고 태스크 한 번의 수행.

**이름은 계약과 같게 둔다** (`run_id`·`node_id`·`attempt`·`mode`는 C3·C11의 이름). 확장이
계약 문서와 코드를 오갈 때 번역하지 않도록.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from logging import Logger
from typing import Any, Protocol, runtime_checkable

from chaeksas.contracts.service_app import MODE_DETERMINISTIC, Usage

#: 수행 모드 — 값은 C11이 소유한다 (`contracts.service_app.MODES`). 받는 쪽은 바꾸지 않는다.
Mode = str

#: 실행 위치 (C1 `run_location`).
RUN_LOCATION_PC = "pc"
RUN_LOCATION_SERVER = "server"

#: 확장 코드를 돌리는 쪽 (C11 `caller.type`과 같은 값).
HOST_STUDIO = "studio"
HOST_BOT_UI = "bot_ui"
HOST_SERVER_RUNNER = "server_runner"

#: 결과를 모르는 실패를 사람에게 넘기는 방법 (C13 §4 — PC는 확인, 서버는 오류 경계).
ESCALATE_CONFIRMATION = "confirmation"


@runtime_checkable
class Settings(Protocol):
    """확장의 설정 칸 값 (C13 `configuration`). 호스트가 확장별로 나눠 둔다."""

    def get(self, key: str, default: Any = None) -> Any: ...


@runtime_checkable
class Secrets(Protocol):
    """비밀 값을 푸는 곳 — OS 비밀 저장소 (ADR-0013).

    **값을 가진 쪽은 호스트다.** 확장은 이름으로만 묻고, 받은 값을 기록·템플릿에 넣지 않는다.
    """

    def resolve(self, ref: str) -> str | None: ...


@dataclass(frozen=True)
class ExtensionContext:
    """확장 하나에 주어지는 바깥 세상. 확장 호스트가 만들어 넘긴다."""

    extension_id: str
    extension_version: str
    api_version: str
    #: 지금 이 코드를 돌리는 쪽 (HOST_STUDIO·HOST_BOT_UI·HOST_SERVER_RUNNER).
    host: str
    settings: Settings
    secrets: Secrets
    log: Logger

    def setting(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)

    def secret(self, ref: str) -> str | None:
        """비밀 칸·키 참조의 값. **없으면 `None`** — 확장이 사람에게 알릴 몫이다."""
        return self.secrets.resolve(ref)


@dataclass(frozen=True)
class TaskContext:
    """태스크 한 번의 수행. 식별자는 C3·C11과 같은 이름이다.

    `node_instance`·`attempt`는 멱등 키의 일부다 (C11) — 서비스 앱을 부를 때 그대로 싣는다.
    """

    extension: ExtensionContext
    run_id: str
    node_id: str
    node_instance: int = 1
    attempt: int = 1
    mode: Mode = MODE_DETERMINISTIC
    run_location: str = RUN_LOCATION_PC
    #: 태스크 입력 (BPM 프로세스 변수에서 꺼낸 것).
    inputs: Mapping[str, Any] = field(default_factory=dict)
    #: BPMN `chk:*` 확장 속성 (C14) — 태스크 종류가 정한 모양이다.
    properties: Mapping[str, Any] = field(default_factory=dict)
    #: UI 세션처럼 실행을 잇는 키 (C10).
    business_key: str | None = None
    #: 서비스 앱 키 **참조 이름** (ADR-0013). 값은 `extension.secret(key_ref)`로 푼다.
    key_ref: str | None = None


@dataclass(frozen=True)
class TaskOutcome:
    """태스크가 성공했을 때. `outputs`는 BPM 프로세스 변수로 들어간다."""

    outputs: Mapping[str, Any] = field(default_factory=dict)
    #: LLM을 쓴 경우만 (C3 `llm_usage`·C11과 같은 모양). **금액은 넣지 않는다.**
    usage: Usage | None = None


class TaskFailed(Exception):
    """태스크가 실패했다. 실행기가 이것을 보고 재시도·확인·오류 경계를 정한다.

    - `retryable=False`(기본)면 다시 부르지 않는다.
    - `escalate=ESCALATE_CONFIRMATION`은 "결과를 모른다 — 사람이 봐야 한다"는 뜻이다
      (C13 §4의 `idempotent: false` 처리). 서버 실행에서는 오류 경계로 간다.
    """

    def __init__(self, code: str, message: str, *, retryable: bool = False, escalate: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.escalate = escalate
