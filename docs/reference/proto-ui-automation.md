# 프로토타입 UI 자동화 서버 (→ 새 UI 자동화 앱)

`requires-python >=3.11`(실사용 3.14) · FastAPI + Neo4j 5 + Ollama + Streamlit. 저장소 이름은 [대응표](README.md) 참고.
최상위 패키지 이름이 `src`다 (프로토타입 Worker와 충돌).

## 기능

- **레지스트리:** 화면(Page) → 요소(Element, `page_id::semantic_key`) → 로케이터(Locator) 구조다. YAML(`configs/registry/`) 또는 Neo4j에 저장한다.
- **그래프:** 노드는 `Page`, `Element`, `Locator`, `Concept`, `Intent`. 관계는 `CONTAINS`, `HAS_LOCATOR{priority}`, `MAPS_TO`, `TRIGGERS`, `DEPENDS_ON`, `RESOLVES_TO`. 화면 간 경로는 `shortestPath`로 찾는다.
- **계획:** 우선순위는 명시 스텝 > 인텐트 캐시 > Navigator LLM 순이다. 요소마다 로케이터 사다리 전체를 넘긴다.
- **치유 제안:** 입력은 ARIA 스냅샷과 잘라 낸 DOM이다. LLM이 제안을 만들고, 제안이 없으면 `locator: null`을 돌려준다.
- **보고 반영:**
  - 새 로케이터는 `unverified`, 우선순위 0으로 등록한다.
  - 3회 연속 성공하면 `active`로 올리고, 대체된 로케이터는 `deprecated`로 내린다.
- **전환:** 치유 3회 실패 → 사람 작업을 만든다. 웹훅 또는 폴링 방식.
- **웹 화면 (Streamlit — 새 구조에서는 Next.js, ADR-0017):** 개요, 셀렉터 인벤토리, 모니터링 → [../06-screens/service-app-console.md](../06-screens/service-app-console.md)의 UIA-01~03 (UI 자동화 앱 관리 콘솔).

## API (`src/main.py`)

- `/v1/goals`, `/v1/jobs`
- `/v1/worker/{lease,plan,heal,report}`
- `/v1/registry/pages` (CRUD), `/v1/registry/intents`
- `/v1/escalations`, `/healthz`

인증은 Bearer 토큰 하나다.

## 가져올 것

- `knowledge_graph/schema.py`, `queries.py`의 그래프 모델과 제약 조건.
- 승격 규칙: 임계값 3, 치유 로케이터 우선순위 0.
- 등록은 기존 데이터를 지우지 않고 사다리를 늘리는 방식. 삭제는 잘못 만든 것에만 쓴다.
- 인텐트 캐시에 업무 값을 넣지 않는 원칙.
- `docs/registry-*.md`, `read-actions.md`: 동작 8종(fill, click, press, read, read_table, read_options, read_selection, select)의 정의.

## 버릴 것

- `/v1/worker/lease`와 메모리 작업 큐. 작업 배분은 Center가 맡는다 ([ADR-0007](../decisions/0007-client-initiated-communication.md)).
- 제품을 가리지 않는 전환 웹훅. 새 구조에서는 Bot이 확인(실행 개입)으로 받는다.
- 쓰지 않는 `langgraph` 의존성, 서버가 무시하는 브라우저 설정.
- 서버 전용 웹 화면(별도 포트). Center 콘솔의 한 영역으로 합친다.

## 열린 채 남은 문제

- 잘못 넣은 catalog 관계를 지우는 방법이 없다.
- `depends_on` 순환 검사가 요청 하나 안에서만 이뤄진다.
- `unverified` 로케이터의 만료 정책이 없다.
- 인텐트 캐시가 잘못된 첫 해석을 굳힐 수 있다.
- 데스크톱 실행기가 없다. 어휘(`automation_id`, `control_name`)만 있다.
