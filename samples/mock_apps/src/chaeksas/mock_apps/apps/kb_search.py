"""모의 사내 지식 검색 — 사내 확장 `kb-search`의 서버 부분. BX-32(고객 문의)가 부른다."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from chaeksas.contracts.service_app import OpRequest
from chaeksas.mock_apps.c11 import MockApp, Op, Scenario

#: 거짓 FAQ. `말` 하나라도 질문에 들어 있으면 맞는 것으로 본다 — 모의 검색이라 점수도
#: 맞은 말의 수로 센다. BX-32 「배송 문의」의 본문 「주문한 지 5일 지났어요」가
#: 첫 줄의 「주문」·두 번째 줄의 「배송」에 걸려 근거가 비지 않는다.
FAQ = (
    {
        "id": "FAQ-001",
        "제목": "주문 후 배송까지 걸리는 기간",
        "본문": "결제 확인 뒤 영업일 2~3일 안에 출고되고, 출고 뒤 1~2일 안에 받습니다.",
        "출처": "고객센터 FAQ",
        "말": ("주문", "배송", "출고", "며칠", "언제"),
    },
    {
        "id": "FAQ-002",
        "제목": "배송 조회 방법",
        "본문": "주문 내역에서 운송장 번호를 눌러 조회합니다.",
        "출처": "고객센터 FAQ",
        "말": ("배송", "조회", "운송장"),
    },
    {
        "id": "FAQ-003",
        "제목": "반품·교환 기준",
        "본문": "받은 날로부터 7일 안에 신청할 수 있고, 단순 변심은 왕복 배송비가 듭니다.",
        "출처": "고객센터 FAQ",
        "말": ("반품", "교환", "환불", "변심"),
    },
    {
        "id": "FAQ-004",
        "제목": "배송 지연 안내",
        "본문": "주문이 몰리는 기간에는 출고가 하루 이틀 늦어질 수 있습니다.",
        "출처": "공지사항",
        "말": ("배송", "지연", "늦", "주문"),
    },
)

#: `top_k`를 비워 보내면 쓰는 값.
DEFAULT_TOP_K = 5


def search(req: OpRequest, scenario: Scenario) -> Mapping[str, Any]:
    """맞은 말이 많은 것부터 `top_k`개. 맞는 것이 없으면 **빈 목록**이다 (지어내지 않는다)."""
    query = str(req.input.get("query") or "")
    raw = req.input.get("top_k")
    top_k = int(raw) if raw is not None else DEFAULT_TOP_K

    scored = []
    for one in FAQ:
        hit = sum(1 for word in one["말"] if word in query)
        if hit:
            scored.append((hit, one))
    scored.sort(key=lambda pair: (-pair[0], str(pair[1]["id"])))
    hits = [
        {"id": one["id"], "제목": one["제목"], "본문": one["본문"], "출처": one["출처"], "점수": hit}
        for hit, one in scored[:top_k]
    ]
    return {"hits": hits}


APP = MockApp(
    app_id="kb-search",
    name="모의 사내 지식 검색",
    extension="kb-search",
    used_by=("BX-32",),
    doc="FAQ·공지 검색",
    ops=(Op("search", "지식 검색", search),),
)

__all__ = ["APP", "DEFAULT_TOP_K", "FAQ"]
