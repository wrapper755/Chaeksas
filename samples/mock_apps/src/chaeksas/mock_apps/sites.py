"""예제가 가리키는 **웹 화면** — 공급사 포털·사내 신청서·공지 (UI 태스크가 만진다).

**시험과 사람이 같은 HTML을 본다.** M4 인수 시험(`tests/test_m4_acceptance.py`)이 이 `PAGES`를
제 시험 서버로 내주고, 현장 PC의 사람은 `chk-mock-apps serve`가 `/site` 밑에 내주는 것을 연다
(예: `http://127.0.0.1:8010/site/transactions`). 두 벌이면 「시험은 되는데 현장은 안 된다」가
생긴다 (09-gaps §6 — 현장 시나리오 3(BX-04)이 열 포털이 시험 안에만 있었다).

화면은 **조회 조건을 보지 않는다** — 대상월을 넣고 「조회」를 눌러도 표는 그대로다. 예제가 보는
것은 「채우고·누르고·표를 읽는다」이고, 표의 값은 케이스가 기대하는 것과 맞춰 두었다.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

#: 사내 신청서 (인트라넷) — 이름·내용을 채우고 「상신」.
FORM = """<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>신청</title></head>
<body>
  <form id="main" action="done" method="get">
    <input id="name" name="name" aria-label="이름" />
    <textarea id="body" name="body" aria-label="내용"></textarea>
    <button id="submit" type="submit">상신</button>
  </form>
</body></html>"""

DONE = """<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>완료</title></head>
<body>
  <p id="message">접수되었습니다 (접수번호 R-2026-0042)</p>
  <p id="contact">담당자 김책사 02-1234-5678</p>
</body></html>"""

NOTICES = """<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>공지</title></head>
<body>
  <table id="notices">
    <tr><th>번호</th><th>제목</th></tr>
    <tr><td>1</td><td><a id="first" href="notice/1">정기 점검 안내</a></td></tr>
    <tr><td>2</td><td><a href="notice/2">보안 교육 일정</a></td></tr>
  </table>
</body></html>"""

#: 공급사 포털 주문 목록 (BX-14).
PORTAL = """<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>공급사 포털</title></head>
<body>
  <input id="date" aria-label="조회일" />
  <button id="search">조회</button>
  <table id="orders">
    <tr><th>주문번호</th><th>공급사</th><th>금액</th></tr>
    <tr><td>PO-1001</td><td>한빛상사</td><td>1200000</td></tr>
    <tr><td>PO-1002</td><td>가온테크</td><td>850000</td></tr>
    <tr><td>PO-1003</td><td>다래물산</td><td>430000</td></tr>
  </table>
</body></html>"""

#: BX-04의 공급사 포털 거래 내역 — 4건, 합계 251,000 (예제의 「정상 발행」·「발행 대상 없음」이 갈린다).
TRANSACTIONS = """<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>거래 내역</title></head>
<body>
  <input id="month" aria-label="대상월" />
  <button id="search">조회</button>
  <table id="transactions">
    <tr><th>번호</th><th>거래처</th><th>금액</th></tr>
    <tr><td>1</td><td>한빛상사</td><td>120,000</td></tr>
    <tr><td>2</td><td>가온테크</td><td>85,000</td></tr>
    <tr><td>3</td><td>다래물산</td><td>43,000</td></tr>
    <tr><td>4</td><td>누리상회</td><td>3,000</td></tr>
  </table>
</body></html>"""

#: 경로 → 화면. 모르는 경로는 공지 목록이다 (공지의 글 링크가 여기로 온다).
PAGES = {
    "/": FORM,
    "/form": FORM,
    "/done": DONE,
    "/notices": NOTICES,
    "/notice/1": DONE,
    "/portal": PORTAL,
    "/transactions": TRANSACTIONS,
}

#: `chk-mock-apps serve`가 이 화면들을 붙이는 자리.
MOUNT = "/site"


def page(path: str) -> str:
    """그 경로의 화면. 모르는 경로는 공지 목록 (시험 서버와 같은 규칙)."""
    return PAGES.get(path, NOTICES)


def site_app() -> FastAPI:
    """화면을 내주는 앱 — 인증이 없다. 그래서 `serve`의 기본 바인드가 127.0.0.1이다."""
    app = FastAPI(title="예제 웹 화면", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/{path:path}", response_class=HTMLResponse)
    def show(path: str) -> str:
        return page("/" + path)

    return app


__all__ = ["MOUNT", "PAGES", "page", "site_app"]
