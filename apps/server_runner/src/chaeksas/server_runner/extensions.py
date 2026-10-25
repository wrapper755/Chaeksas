"""서버 실행기가 확장을 꽂는 자리 (C13, ADR-0064).

**로컬 런타임을 띄우지 않는다.** 런타임은 Bot UI의 것이고(C13 칸 이름이 `bot_ui.local_runtimes`다)
그 예약(`reserve`)은 **PC에 하나**를 전제한 배타 잠금이다 (ADR-0014 §4) — 서버는 동시 실행이
기본이라(C12) 맞지 않는다. 그래서 예약 키 `runtime.<id>.*`를 **일부러 채우지 않는다**.

**실행 위치를 호스트가 쥔다** — `run_locations`에 `server`를 적지 않은 태스크 종류는 기여를 내지
않으므로, 그런 Bot은 사전 점검이 `task_types_wrong_location`으로 **시작 전에** 막는다
(`core.preflight`). 적어 둔 것만 서버에서 돈다.

확장에게 가는 것은 셋이다 — 자기 설정 칸(`scope: server_runner`인 것만, **환경변수로**),
서버 부분 주소(`service.base_url`), 비밀(서비스 앱 키 참조가 먼저). **화면이 없어 설정 파일이
없으므로**(`docs/04-setup.md` §6) 설정은 환경변수뿐이고 이름 규칙은 **Bot UI의 것과 같다**.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from chaeksas.contracts import SERVICE_URL_SETTING
from chaeksas.contracts.extension import SCOPE_SERVER_RUNNER
from chaeksas.core.extensions import ExtensionHost, HostTasks, load_host
from chaeksas.extension_api import HOST_SERVER_RUNNER, RUN_LOCATION_SERVER, ExtensionContext
from chaeksas.server_runner.credentials import BotCredentials, Credentials, extension_config_env


def load(*, host: ExtensionHost | None = None) -> ExtensionHost:
    """설치된 확장을 읽은 호스트 하나 — **실행 위치를 쥔다** (ADR-0064).

    **꺼 둔 확장이 없다** (`off`가 비어 있다) — 끄는 자리는 사람이 누르는 화면이고(BUI-11·STU-15,
    ADR-0043) 서버에는 그 화면이 없다. 운영자가 가진 손잡이는 배포다. 그래서 「꺼짐」 점검
    (`extension_turned_off`)은 서버에서 뜨지 않는다.
    """
    return host if host is not None else load_host(run_location=RUN_LOCATION_SERVER)


@dataclass(frozen=True)
class PlainSettings:
    """`extension_api.Settings` — 그 확장의 설정 칸 값."""

    values: Mapping[str, Any]

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)


@dataclass(frozen=True)
class RunnerSecrets:
    """`extension_api.Secrets` — 확장이 묻는 이름을 푼다 (ADR-0013).

    **서비스 앱 키 참조가 먼저**이고(BUI-10과 같은 순서) 아니면 그 확장의 비밀 설정 칸이다.
    확장마다 이름 공간이 갈라져 있어 남의 비밀을 가져갈 수 없다.
    """

    credentials: Credentials | BotCredentials
    extension_id: str

    def resolve(self, ref: str) -> str | None:
        return self.credentials.service_app_key(ref) or self.credentials.extension_secret(
            self.extension_id, ref
        )


def settings_for(
    host: ExtensionHost,
    extension_id: str,
    *,
    service_url: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> PlainSettings:
    """그 확장의 설정 칸 + 호스트가 채우는 예약 키 (C13).

    - 칸은 `scope: server_runner`인 것만. 값은 **환경변수**(`CHK_SERVER_RUNNER__EXT__<확장>__<칸>`)
      이고 없으면 `None`이다. **비밀 칸은 넣지 않는다** — 그것은 `Secrets`가 푼다 (ADR-0013).
    - `service.base_url`은 **출처가 하나다** (C13) — Center 리소스 등록이 정의의 값을 이긴다.
    - `runtime.<id>.*`는 **없다** (ADR-0064 — 서버는 런타임을 띄우지 않는다).
    """
    env = environ if environ is not None else os.environ
    found = host.get(extension_id)
    values: dict[str, Any] = {}
    if found is not None:
        for item in found.manifest.contributes.configuration:
            if item.scope != SCOPE_SERVER_RUNNER or item.secret:
                continue
            values[item.key] = env.get(extension_config_env(extension_id, item.key))
        service = found.manifest.service
        values[SERVICE_URL_SETTING] = service_url or (
            service.base_url if service is not None else None
        )
    return PlainSettings(values=values)


def tasks(
    *,
    host: ExtensionHost | None = None,
    service_url: Callable[[str], str | None] | None = None,
    credentials: Credentials | BotCredentials | None = None,
) -> HostTasks:
    """엔진의 `RunEnv.extensions` — 확장 호스트를 꽂는다 (ADR-0018 — 엔진은 확장을 모른다).

    `service_url`은 실행기가 **제 손으로 받아 둔 바깥 앱 명부**가 답한다 (C7·C13 「전송」,
    `DirectoryCache.base_url_of`) — 확장 id로 묻는 것이라 **실행마다 다르지 않아** 이 하나를
    모든 실행이 함께 쓴다. 주지 않으면 정의에 적힌 주소를 쓴다.
    """
    loaded = load(host=host)
    creds: Credentials | BotCredentials = credentials if credentials is not None else Credentials()

    def make_context(extension_id: str) -> ExtensionContext:
        return loaded.context(
            extension_id,
            host=HOST_SERVER_RUNNER,
            settings=settings_for(
                loaded,
                extension_id,
                service_url=service_url(extension_id) if service_url is not None else None,
            ),
            secrets=RunnerSecrets(credentials=creds, extension_id=extension_id),
        )

    return HostTasks(host=loaded, make_context=make_context)


def task_type_ids(host: ExtensionHost) -> Sequence[str]:
    """서버에서 수행할 수 있는 태스크 종류 — 로그 한 줄에 쓴다 (걸러진 뒤의 목록이다)."""
    return [c.value.id for c in host.task_types()]


__all__ = [
    "PlainSettings",
    "RunnerSecrets",
    "load",
    "settings_for",
    "task_type_ids",
    "tasks",
]
