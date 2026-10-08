"""어떤 모의 앱이 있는가 — 한 자리에 모아 둔다.

`app_id`는 **업무 예제의 `chk:serviceCall.app_id` 그대로**다. 예제가 부르는 것이 여기
없으면 M5 인수 시험을 돌릴 수 없으므로, `tests/test_mock_apps.py`가 예제 BPMN에서
읽어 이 표와 대조한다 — 손으로 맞춘 목록이 아니다.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

from chaeksas.mock_apps.apps import (
    center_jobs,
    compliance,
    crm,
    directory,
    erp,
    hris,
    kb_search,
    lms,
    mailer,
    observability,
    shop,
    ticketing,
    web_reader,
    wms,
)
from chaeksas.mock_apps.c11 import MockApp
from chaeksas.mock_apps.external import definitions

#: C11 서비스 앱 (사내 확장의 서버 부분). 순서가 기본 포트를 정한다 — 아래 `port_of`.
C11_APPS: tuple[MockApp, ...] = (
    erp.APP,
    directory.APP,
    hris.APP,
    crm.APP,
    compliance.APP,
    shop.APP,
    wms.APP,
    lms.APP,
    mailer.APP,
    ticketing.APP,
    kb_search.APP,
    observability.APP,
    web_reader.APP,
    center_jobs.APP,
)

#: 외부 앱 (C11이 아니다 — HTTP 어댑터로 붙는다, C13 §4).
EXTERNAL_IDS: tuple[str, ...] = tuple(definitions.BUILDERS)

#: 기본 포트 — `docs/04-setup.md` §6의 「다음 서비스 앱: 8010부터 10씩」을 따른다.
PORT_BASE = 8010
PORT_STEP = 10

#: 한 포트에 다 띄울 때 쓰는 포트 (`chk-mock-apps serve`의 기본). 앱은 `/<app_id>`에 붙는다.
ALL_IN_ONE_PORT = 8010


def c11(app_id: str) -> MockApp | None:
    return next((one for one in C11_APPS if one.app_id == app_id), None)


def ids() -> tuple[str, ...]:
    """모의 앱 전부 (C11 + 외부)."""
    return tuple(one.app_id for one in C11_APPS) + EXTERNAL_IDS


def operations() -> dict[str, tuple[str, ...]]:
    """`app_id` → 작업 이름들. 외부 앱은 정의의 어댑터 작업에서 읽는다."""
    found = {one.app_id: tuple(op.name for op in one.ops) for one in C11_APPS}
    for app_id, make in definitions.BUILDERS.items():
        # 주소는 아무것이나 — 작업 이름만 본다.
        adapter = make("https://example.com")["service"]["adapter"]
        found[app_id] = tuple(str(op["name"]) for op in adapter["operations"])
    return found


def port_of(app_id: str) -> int:
    """그 앱의 기본 포트. `CHK_SVC_<앱>__PORT`가 있으면 그 값이다.

    포트 숫자를 코드에 흩어 적지 않는다 — 이 함수가 유일한 자리다 (ADR-0011).
    """
    order = ids()
    if app_id not in order:
        raise KeyError(app_id)
    env = "CHK_SVC_" + app_id.replace("-", "_").upper() + "__PORT"
    given = os.environ.get(env, "").strip()
    if given:
        return int(given)
    return PORT_BASE + PORT_STEP * order.index(app_id)


def rows() -> Iterator[tuple[str, str, int, str]]:
    """`--list`가 찍는 표: (app_id, 종류, 기본 포트, 어느 예제가 쓰나)."""
    for one in C11_APPS:
        yield one.app_id, "C11", port_of(one.app_id), ", ".join(one.used_by)
    uses = {"ext-credit": "BX-06, BX-10, FX-20", "ext-helpdesk": "BX-32, BX-35"}
    for app_id in EXTERNAL_IDS:
        yield app_id, "외부", port_of(app_id), uses.get(app_id, "")


__all__ = [
    "ALL_IN_ONE_PORT",
    "C11_APPS",
    "EXTERNAL_IDS",
    "PORT_BASE",
    "PORT_STEP",
    "c11",
    "ids",
    "operations",
    "port_of",
    "rows",
]
