"""Center API — 패키지 레지스트리, 배포, 작업, 결재 창구, 실행 이력, Center API 키

지금 있는 것:

| 계약 | 무엇 | 모듈 |
| --- | --- | --- |
| C7 | Center API 키 발급·목록·폐기·PC 묶음 풀기 (CON-11) | `keys.py` |
| C7 | 리소스 목록 — 서비스 앱 등록·주소·해제, 확장·툴팩·런타임 모으기, 확장 기여 카탈로그 | `api/resources.py` |
| C4 | Bot UI 등록·하트비트(배포·작업·결재·`readiness`), 현황 목록·상세 (CON-03) | `api/bot_ui.py` |
| C5 | 패키지 업로드·목록·정보·내려받기 (C1 검사·해시 재계산), 승인·철회 봉투 | `api/packages.py`, `api/signing.py` |
| C5 | 배포 — Admin 봉투를 받아 두고 하트비트로 **저장된 JSON 그대로** 내려 준다 | `api/deployments.py` |
| C5 | 작업 지시 `/jobs` — **서명이 없다**, 토큰 권한이 관문이다 | `api/jobs.py` |
| C6 | 결재 창구 — 올리기·목록·답하기·회수 (확인은 422) | `api/approvals.py` |
| C3 | 실행 기록 수집·목록·상세 (CON-01) | `api/runs.py` |

아직 없는 것: 서버 실행기 (C12, M7). 남은 공백은 `docs/09-gaps.md`에 있다 — 그중 Center 몫은
`PUT /packages/…/status`(지원 종료)·`DELETE /packages/…`·`GET …/dependents`와 외부 확장 `health`
두드리기다.
**콘솔 화면은 여기 없다** — `web/apps/center-console` (ADR-0017).

자세히: docs/01-architecture.md §2.
"""

from chaeksas.center.app import create_app
from chaeksas.center.settings import Settings

__all__ = ["Settings", "create_app"]
