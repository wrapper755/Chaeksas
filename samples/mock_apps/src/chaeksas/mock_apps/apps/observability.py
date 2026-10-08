"""모의 모니터링 — 최근 로그. 사내 확장 `observability`의 서버 부분. BX-34(장애 알림)가 부른다."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from chaeksas.contracts.service_app import OpRequest
from chaeksas.mock_apps.c11 import MockApp, Op, Scenario

#: 서비스 이름 → 거짓 로그. BX-34의 입력이 `payment-api`다.
LOGS: dict[str, tuple[str, ...]] = {
    "payment-api": (
        "ERROR upstream card-gateway timeout after 3000ms (attempt 1/3)",
        "ERROR upstream card-gateway timeout after 3000ms (attempt 2/3)",
        "WARN  circuit breaker half-open for card-gateway",
        "ERROR POST /v1/charges -> 502 (upstream_unavailable)",
        "INFO  retry budget exhausted, shedding 12% of traffic",
    ),
}

#: 모르는 서비스에도 답한다 — 모니터링은 「그 서비스 로그가 없다」가 정상 답이다.
EMPTY: tuple[str, ...] = ()

#: `minutes`를 비워 보내면 쓰는 값.
DEFAULT_MINUTES = 15


def recent_logs(req: OpRequest, scenario: Scenario) -> Mapping[str, Any]:
    service = str(req.input.get("service") or "")
    raw = req.input.get("minutes")
    minutes = int(raw) if raw is not None else DEFAULT_MINUTES
    return {"lines": list(LOGS.get(service, EMPTY)), "minutes": minutes}


APP = MockApp(
    app_id="observability",
    name="모의 모니터링",
    extension="observability",
    category="system",
    used_by=("BX-34",),
    doc="최근 로그 조회",
    ops=(Op("recent_logs", "최근 로그", recent_logs),),
)

__all__ = ["APP", "DEFAULT_MINUTES", "LOGS"]
