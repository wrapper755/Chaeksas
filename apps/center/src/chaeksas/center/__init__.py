"""Center API — 패키지 레지스트리, 배포, 작업, 결재 창구, 실행 이력, Center API 키

지금 있는 것 (M2):

| 계약 | 무엇 |
| --- | --- |
| C7 | Center API 키 발급·목록·폐기·PC 묶음 풀기 (CON-11) |
| C4 | Bot UI 등록·하트비트, 현황 목록 (CON-03) |
| C5 | 패키지 업로드·목록·정보·내려받기 (C1 검사·해시 재계산) |

아직 없는 것: 배포·작업·결재·실행 이력·리소스 목록 (M5), 서버 실행기 (M7).
**콘솔 화면은 여기 없다** — `web/apps/center-console` (ADR-0017).

자세히: docs/01-architecture.md §2.
"""

from chaeksas.center.app import create_app
from chaeksas.center.settings import Settings

__all__ = ["Settings", "create_app"]
