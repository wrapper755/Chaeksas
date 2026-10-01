# 프로토타입 Worker

`requires-python >=3.11`(실사용 3.14) · Playwright + PySide6/qasync + FastAPI. 저장소 이름은 [대응표](README.md) 참고.
최상위 패키지 이름이 `src`다 (프로토타입 UI 자동화 서버와 충돌).

## 기능

- **로컬 API (`src/local_api/`, 127.0.0.1:8899, 선택 토큰 헤더):**
  - `POST /v1/sessions`로 브라우저 세션을 연다.
  - `POST /v1/sessions/{id}/steps`로 스텝을 실행한다. 시맨틱 키 또는 자연어 지시 중 하나를 받는다.
  - `POST /v1/sessions/{id}/goto`로 페이지를 이동한다.
  - `DELETE /v1/sessions/{id}`로 세션을 닫는다. 이때 보고 한 건이 서버로 간다.
- **실행기 (`src/executor/`):**
  - 로케이터를 우선순위대로 시도한다. 로케이터당 2초.
  - 모두 실패하면 서버에 치유를 요청한다.
  - 제안을 로컬에서 검증한다. 요소가 정확히 하나여야 하고 역할이 맞아야 한다.
  - 치유 한도를 넘으면 전환한다.
- **오프라인 (`src/client/cache.py`):** 계획 캐시, 등록 대기 큐, 보고 대기 큐(JSONL, 순서 보장).
- **GUI (`src/gui/`):** 트레이 앱, 화면 등록 탭, 실행/테스트 탭 → [../06-screens/worker.md](../06-screens/worker.md).

## 가져올 것

- 로케이터 모델과 플랫폼 검증. 웹 로케이터 타입과 데스크톱 로케이터 타입을 섞지 못하게 막는다.
- 오프라인 큐·캐시 설계.
- 요소 선택기(`executor/picker.py`)의 폴링 방식. `expose_function`을 쓰지 않는다.
- GUI 스레딩 규칙: qasync 루프 하나, Qt 슬롯에서 동기 I/O 금지, 정해진 종료 순서 (stop → 최대 20초 대기 → cancel → quit).

## 모자랐던 것 (새 계약에서 막을 것)

`local_api/session.py`의 세션 종료 보고에 문제가 있다.
- `page_id`, `outputs`, `escalation`이 빠져 있다.
- 상태는 SUCCEEDED와 FAILED 두 가지뿐이다.

그래서 Bot 경로에서는 승격 통계와 전환이 끊긴다. 또한 세션 요청에 `business_key`가 없다.

## Windows 관련 메모

- Windows 실기 검증 이력은 없다.
- 열린 문제: "Windows 서비스는 UI를 띄울 수 없으므로 GUI와 루프를 언젠가 갈라야 한다." → 새 로드맵 M1 스파이크 S4, [ADR-0009](../decisions/0009-worker-deployment-form.md).
