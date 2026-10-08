"""모의 앱 하나를 C11 서비스 앱으로 만드는 공통 자리.

앱 모듈은 **작업 함수만** 쓴다 (`Op`). 키 검증·권한·멱등·오류 형식·사용 기록·관리 API는
`service_kit`이 계약대로 준다 (CLAUDE.md §5 — 직접 FastAPI를 쓰지 않는다).

여기서 더하는 것은 두 가지뿐이다.

- **설정을 환경변수에서 읽는 자리** — 앱마다 `CHK_SVC_<앱 id>__*`다 (`docs/04-setup.md` §6).
  `app_id`의 `-`는 `_`로 바꾼다 (`kb-search` → `CHK_SVC_KB_SEARCH__`).
- **시나리오 제어(`/mock/v1/scenario`)** — 같은 입력에 다른 답이 필요한 케이스가 있다.
  예제 케이스가 그렇게 적어 두었다: BX-08은 「평소」와 「모의 서버에 95일 연체 1건 추가」가
  둘 다 입력이 비어 있다. 시험이 케이스마다 이 자리를 바꾼다.

  **C11에는 이런 길이 없다.** 그래서 경로를 `/mock/`으로 떼어 두었다 — 모의 앱만의
  것이고, 진짜 서비스 앱이 이것을 흉내 내서는 안 된다. 인증이 없으므로 이 앱들은
  **개발 PC·시험망에서만** 띄운다 (`samples/README.md`).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from chaeksas.contracts.service_app import (
    MODE_AUTONOMOUS,
    MODE_DETERMINISTIC,
    ExtensionRef,
    Operation,
    OpRequest,
    ServiceAppKey,
    ServiceAppManifest,
    prefix_of,
)
from chaeksas.service_kit import InMemoryKeyStore, OpError, create_app, hash_key, issue

log = logging.getLogger(__name__)

#: 기본 시나리오 이름. 앱은 이 이름의 거짓 데이터로 답한다.
DEFAULT_SCENARIO = "기본"

#: 모의 제어 경로 (C11이 아니다 — 위 설명).
SCENARIO_PATH = "/mock/v1/scenario"

#: 모든 앱이 두 수행 모드를 받는다 — Bot은 결정 수행, Studio 시험 실행은 자율 수행이다.
BOTH_MODES = (MODE_DETERMINISTIC, MODE_AUTONOMOUS)

#: 앱 열여섯 개에 키를 하나씩 심는 것은 개발에서 쓸 수 없다. 이 환경변수 하나를 주면
#: **모든 모의 앱이 그 키를 받는다**. 앱마다 다르게 하려면 `CHK_SVC_<앱>__DEV_KEY`가 이긴다.
SHARED_KEY_ENV = "CHK_MOCK_APPS__DEV_KEY"


class Scenario:
    """어느 거짓 데이터로 답할지. 앱 하나에 하나이고, 시험이 바꾼다."""

    def __init__(self, name: str = DEFAULT_SCENARIO, allowed: Sequence[str] = (DEFAULT_SCENARIO,)):
        self.allowed = tuple(allowed)
        self.name = name

    def set(self, name: str) -> None:
        if name not in self.allowed:
            raise ValueError(f"모르는 시나리오다: {name} (있는 것: {', '.join(self.allowed)})")
        self.name = name

    def is_(self, name: str) -> bool:
        return self.name == name


#: 작업 함수 — 요청과 시나리오를 받고 C11 `output`에 들어갈 것을 돌려준다.
#: 실패는 `service_kit`의 `OpError`로 올린다 (C11 오류 표의 코드를 쓴다).
Answer = Callable[[OpRequest, Scenario], Mapping[str, Any]]


@dataclass(frozen=True)
class Op:
    """작업 하나 — C11 `Operation` 선언 + 모의 구현."""

    name: str
    description: str
    answer: Answer
    modes: tuple[str, ...] = BOTH_MODES
    server_ok: bool = True

    def declared(self) -> Operation:
        return Operation(
            name=self.name,
            description=self.description,
            modes=list(self.modes),
            server_ok=self.server_ok,
        )


@dataclass(frozen=True)
class MockApp:
    """모의 앱 하나.

    `app_id`는 **예제 BPMN의 `chk:serviceCall.app_id` 그대로**여야 한다 — 그렇지 않으면
    예제가 부를 수 없다. `tests/test_mock_apps.py`가 예제에서 읽어 대조한다.
    """

    app_id: str
    name: str
    ops: tuple[Op, ...]
    #: 이 앱을 서버 부분으로 가진 확장의 id·판. 내장·사내 확장의 정의는 Center에 없으므로
    #: **manifest의 이 칸이 C7 「확장」 목록의 출처다** (C7 §확장, 조각 10).
    extension: str | None = None
    category: str = "business"
    version: str = "1.0.0"
    scenarios: tuple[str, ...] = (DEFAULT_SCENARIO,)
    #: 사람이 읽을 설명 — 어느 예제가 이 앱을 부르는가.
    used_by: tuple[str, ...] = ()
    doc: str = ""

    def op(self, name: str) -> Op | None:
        return next((one for one in self.ops if one.name == name), None)

    @property
    def env_prefix(self) -> str:
        return "CHK_SVC_" + self.app_id.replace("-", "_").upper() + "__"

    def env(self, name: str, default: str | None = None) -> str | None:
        return os.environ.get(self.env_prefix + name, default)

    def manifest(self, *, console_url: str = "") -> ServiceAppManifest:
        return ServiceAppManifest(
            schema=1,
            app_id=self.app_id,
            name=self.name,
            version=self.version,
            category=self.category,
            console_url=console_url or self.env("CONSOLE_URL") or "",
            operations=[one.declared() for one in self.ops],
            extension=ExtensionRef(id=self.extension, version=self.version) if self.extension else None,
        )


@dataclass
class Built:
    """띄울 준비가 된 앱 하나."""

    mock: MockApp
    app: FastAPI
    scenario: Scenario
    #: 발급한 키 원문. 환경변수로 받은 것이면 그 값이고, 만든 것이면 새 값이다.
    #: **기록·응답에 넣지 않는다** — 띄운 사람에게 한 번 보여 주려고만 들고 있다.
    key: str = field(repr=False, default="")
    #: 환경변수로 받은 키인가. 받은 것이면 띄울 때 되읊지 않는다 (사람이 이미 안다).
    key_from_env: bool = False


def build(mock: MockApp, *, console_url: str = "", admin_token: str | None = None) -> Built:
    """모의 앱 하나를 만든다.

    키는 `CHK_SVC_<앱>__DEV_KEY` → `CHK_MOCK_APPS__DEV_KEY` 순으로 받고, 둘 다 없으면
    **그 자리에서 하나 만든다** (개발 편의). 만든 값은 띄운 사람에게 한 번 보여 준다 —
    비밀 저장소가 아니라 개발용이다.
    """
    scenario = Scenario(allowed=mock.scenarios)
    keys = InMemoryKeyStore()
    given = (mock.env("DEV_KEY") or os.environ.get(SHARED_KEY_ENV, "")).strip()
    if given:
        raw = given
        record = ServiceAppKey(
            name="dev", hash=hash_key(raw), prefix=prefix_of(raw), allowed_modes=list(BOTH_MODES)
        )
    else:
        raw, record = issue("dev", allowed_modes=list(BOTH_MODES))
    keys.add(record)

    handlers = {one.name: _handler(one, scenario) for one in mock.ops}
    app = create_app(
        mock.manifest(console_url=console_url),
        handlers,
        keys=keys,
        admin_token=admin_token or mock.env("ADMIN_TOKEN"),
    )
    _mount_scenario(app, scenario)
    return Built(mock=mock, app=app, scenario=scenario, key=raw, key_from_env=bool(given))


def _handler(op: Op, scenario: Scenario) -> Callable[[OpRequest, str], Mapping[str, Any]]:
    def run(req: OpRequest, mode_used: str) -> Mapping[str, Any]:
        try:
            return op.answer(req, scenario)
        except KeyError as e:
            # 모의 데이터에 없는 것을 물었다 — 업무 입력이 틀렸다는 뜻이다.
            raise OpError("input_invalid", f"{op.name}: 모의 데이터에 {e} 가 없다", status=422) from e

    return run


def _mount_scenario(app: FastAPI, scenario: Scenario) -> None:
    """`/mock/v1/scenario` — 어느 거짓 데이터로 답할지 고른다 (모의 앱만의 길)."""

    @app.get(SCENARIO_PATH)
    def read() -> dict[str, Any]:
        return {"name": scenario.name, "allowed": list(scenario.allowed)}

    @app.post(SCENARIO_PATH)
    def write(body: dict[str, Any]) -> Any:
        try:
            scenario.set(str(body.get("name") or ""))
        except ValueError as e:
            return JSONResponse(status_code=422, content={"code": "input_invalid", "message": str(e), "detail": {}})
        return {"name": scenario.name, "allowed": list(scenario.allowed)}


__all__ = [
    "BOTH_MODES",
    "DEFAULT_SCENARIO",
    "SCENARIO_PATH",
    "Answer",
    "Built",
    "MockApp",
    "Op",
    "Scenario",
    "build",
]
