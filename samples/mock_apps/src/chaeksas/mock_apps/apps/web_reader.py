"""모의 웹 읽기 — 사내 확장 `web-reader`의 서버 부분. FX-10(라우팅)·FX-18(병렬 반복)이 부른다.

**정말로 주소를 부르지 않는다.** 모의 앱이 바깥으로 나가면 개발 PC에서 시험을 돌릴 때마다
남의 서버를 두드린다 (Studio가 웹훅을 쏘지 않는 것과 같은 이유다 — CLAUDE.md §5).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from chaeksas.contracts.service_app import OpRequest
from chaeksas.mock_apps.c11 import MockApp, Op, Scenario
from chaeksas.service_kit import OpError

#: 경로에 이것이 들어 있으면 404라고 답한다 — 「다 200」인 모의는 분기를 시험할 수 없다.
MISSING_MARK = "/missing"


def _checked(raw: Any) -> str:
    url = str(raw or "")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise OpError("input_invalid", "http(s) 주소가 아니다", status=422)
    return url


def head(req: OpRequest, scenario: Scenario) -> Mapping[str, Any]:
    """상태 코드만. FX-18 「5개」가 `https://example.com`을 다섯 번 주고 정상 5를 기대한다."""
    url = _checked(req.input.get("url"))
    status = 404 if MISSING_MARK in urlsplit(url).path else 200
    return {"status": status}


def summarize_url(req: OpRequest, scenario: Scenario) -> Mapping[str, Any]:
    """요약 — 모의라서 **읽은 척하지 않고** 무엇을 못 했는지 분명히 적는다."""
    url = _checked(req.input.get("url"))
    host = urlsplit(url).netloc
    return {
        "summary": f"모의 웹 읽기입니다. {host}의 내용을 실제로 가져오지 않았습니다.",
        "host": host,
    }


APP = MockApp(
    app_id="web-reader",
    name="모의 웹 읽기",
    extension="web-reader",
    category="system",
    used_by=("FX-10", "FX-18"),
    doc="주소 상태 확인·요약 (바깥으로 나가지 않는다)",
    ops=(
        Op("head", "주소 상태 코드", head),
        Op("summarize_url", "주소 요약", summarize_url),
    ),
)

__all__ = ["APP", "MISSING_MARK"]
