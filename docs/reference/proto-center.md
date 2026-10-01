# 프로토타입 Center

Python 3.12 고정 · FastAPI + SQLAlchemy/Alembic + Streamlit. 저장소 이름은 [대응표](README.md) 참고.
규칙: 런타임 코어를 import하지 않는다 (테스트로 강제). 계약은 공통 계약 패키지만.

## 기능

| 영역 | 내용 | 파일 |
| --- | --- | --- |
| 패키지 | 업로드(zip 안전·매니페스트·해시 재검증, 중복 409), 목록, 다운로드(`X-Content-Hash`), 서명 부착, 역의존 | `api/packages.py`, `services/packages.py`, `services/catalog.py` |
| 봇 | 등록(enroll 토큰), 하트비트 30초. 응답에 배포·관리자 키·작업·결재가 실림 | `api/bots.py` |
| 배포 | Admin 서명 봉투 검증·저장, 철회도 서명 | `api/deployments.py`, `services/signing.py` |
| 작업 | pending → dispatched → accepted/rejected | `api/jobs.py`, `services/jobs.py` |
| 결재 | 업무 층만. 봇이 올리고 사람이 답하고 봇이 확인 | `api/hitl.py`, `services/hitl.py` |
| 실행 이력 | `(run_id, seq)` 멱등, 모르는 kind도 저장, 배치 최대 2000 | `api/runs.py`, `services/runs.py` |
| 준비도 | 최근 20회 실행으로 성공률·재생률·개입률 | `services/readiness.py` |
| 웹 화면 | 읽기 전용 Streamlit (새 구조에서는 Next.js, ADR-0017). 삭제·결재는 플래그로만 허용 | `dashboard/` |

인증 3단: API 토큰(읽기·보고), 관리자 토큰(운영 쓰기), Ed25519 서명(승인·배포·철회).
DB: SQLite(WAL). 타입은 PostgreSQL 호환으로 골랐다.

## 가져올 것

- 쓰기 3단계(A 서명 / B 관리자 / C 일반) 모델.
- 트랜잭션 미들웨어: 응답 전에 커밋하고, 400 이상이면 롤백한다.
- `UTCDateTime`: naive datetime을 거부한다.
- 하트비트로 지시를 전달하는 방식 ([ADR-0007](../decisions/0007-client-initiated-communication.md)).
- `docs/center_api_phase2.md`: 106KB의 계약 협상 기록. 계약 C4~C6 초안의 출발점으로 쓴다.
- 웹 화면 구성(실행 로그 타임라인, 준비도, 봇 현황, 결재함, 작업 지시, 공통 패키지) → [../06-screens/center-console.md](../06-screens/center-console.md).

## 모자랐던 것 (새로 설계)

- 봇별 자격 증명이 없어 C 토큰만 있으면 누구나 아무 `bot_id`로 하트비트할 수 있었다.
- 리소스(서비스 앱·UI 화면·툴팩·런타임) 개념이 없었다. 있는 것은 `toolpack` 패키지 종류뿐이었다.
- 봇 capabilities, 봇 비활성화·삭제, 오프라인 감지가 없었다.
- LLM 비용: 질문 5개가 답 없이 남았다.
- 봇 상태가 닫힌 목록이라 모르는 상태를 보내면 하트비트 전체가 422로 거부된다.
- 웹 화면에서 작업을 만들 수 없었다 (CLI만).

## Windows 이식 시 걸리는 것

- `launcher.py`: `start_new_session=True`, `os.killpg`로 프로세스 그룹을 종료한다.
- `pyproject.toml`: 로컬 절대경로(`file:///home/...`)로 계약 패키지를 가져온다.
