"""서버 실행기가 확장을 꽂는 자리 (C13, ADR-0064).

**실행 위치를 호스트가 쥔다** — `run_locations`에 `server`를 적지 않은 태스크 종류는 기여를 내지
않으므로, 그런 BPM 프로세스는 사전 점검이 `task_types_wrong_location`으로 **시작 전에** 막는다
(`core.preflight`). 적어 둔 것만 서버에서 돈다.

확장에게 가는 것은 셋이다 — 자기 설정 칸(`scope: server_runner`인 것만, **환경변수로**),
Center 주소(`center.url`), 비밀(`call_token`은 이 실행기의 Center API 키, 나머지는 그 확장의 비밀
칸 — ADR-0102). **화면이 없어 설정 파일이
없으므로**(`docs/04-setup.md` §6) 설정은 환경변수뿐이고 이름 규칙은 **PC 실행기의 것과 같다**.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from chaeksas.contracts.extension import CALL_TOKEN_SECRET, CENTER_URL_SETTING, SCOPE_SERVER_RUNNER
from chaeksas.core.extensions import ExtensionHost, HostTasks, load_host
from chaeksas.extension_api import HOST_SERVER_RUNNER, RUN_LOCATION_SERVER, ExtensionContext
from chaeksas.server_runner.credentials import Credentials, extension_config_env


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

    `call_token`은 **이 실행기의 Center API 키**다 (서버 실행기는 제 키로 외부 작업을 올린다, C15).
    나머지는 그 확장의 비밀 설정 칸이다 — 확장마다 이름 공간이 갈라져 있어 남의 비밀을 가져갈 수 없다.
    """

    credentials: Credentials
    extension_id: str

    def resolve(self, ref: str) -> str | None:
        if ref == CALL_TOKEN_SECRET:
            return self.credentials.center_api_key()
        return self.credentials.extension_secret(self.extension_id, ref)


def settings_for(
    host: ExtensionHost,
    extension_id: str,
    *,
    center_url: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> PlainSettings:
    """그 확장의 설정 칸 + 호스트가 채우는 예약 키 (C13).

    - 칸은 `scope: server_runner`인 것만. 값은 **환경변수**(`CHK_SERVER_RUNNER__EXT__<확장>__<칸>`)
      이고 없으면 `None`이다. **비밀 칸은 넣지 않는다** — 그것은 `Secrets`가 푼다 (ADR-0013).
    - `center.url`은 이 실행기가 붙은 Center다 (C13 — 확장 클라이언트가 외부 작업을 올리는 곳).
    """
    env = environ if environ is not None else os.environ
    found = host.get(extension_id)
    values: dict[str, Any] = {}
    if found is not None:
        for item in found.manifest.contributes.configuration:
            if item.scope != SCOPE_SERVER_RUNNER or item.secret:
                continue
            values[item.key] = env.get(extension_config_env(extension_id, item.key))
        values[CENTER_URL_SETTING] = center_url
    return PlainSettings(values=values)


def tasks(
    *,
    host: ExtensionHost | None = None,
    center_url: str | None = None,
    credentials: Credentials | None = None,
) -> HostTasks:
    """엔진의 `RunEnv.extensions` — 확장 호스트를 꽂는다 (ADR-0018 — 엔진은 확장을 모른다).

    `center_url`은 이 실행기가 붙은 Center다 — 모든 실행이 함께 쓴다.
    """
    loaded = load(host=host)
    creds: Credentials = credentials if credentials is not None else Credentials()

    def make_context(extension_id: str) -> ExtensionContext:
        return loaded.context(
            extension_id,
            host=HOST_SERVER_RUNNER,
            settings=settings_for(
                loaded,
                extension_id,
                center_url=center_url,
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
