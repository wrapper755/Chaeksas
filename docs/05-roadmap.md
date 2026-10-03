# 05. 로드맵

> 상태: **제안.** 날짜는 넣지 않았다. 각 단계는 완료 기준을 모두 만족해야 끝난다.
> 원칙: 한 단계가 끝날 때마다 **Windows 클라이언트 + Linux 서버** 조합에서 확인한다. "내 PC에서 된다"는 완료가 아니다.

## 단계 한눈에

| 단계 | 이름 | 핵심 산출물 | 선행 |
| --- | --- | --- | --- |
| M0 | 문서 기준선 | 이 문서 묶음, 초기 ADR, 참고 지도, 화면 설계서 | — |
| M1 | 뼈대와 스파이크 | 워크스페이스(uv + `web/` pnpm), 계약 패키지 골격, `service_kit` 골격, 디자인 토큰 생성기, CI(Win+Linux, Python+Node), Windows 스파이크 4개 | M0 |
| M2 | Center 최소 + Bot UI 연결 | Center API 키로 Bot UI 등록·하트비트, 패키지 업로드·다운로드, 콘솔 최소 | M1 |
| M3 | 실행 코어 | BPMN 실행, AI 태스크, 실행 이벤트, Studio 최소 | M1 |
| M4 | UI 자동화 | UI 자동화 앱 + Worker 프로세스 + Bot UI 셀렉터 등록 + UI 태스크 | M2, M3 |
| M5 | 배포·결재·서비스 앱 | 서명·배포, 작업 지시, 결재 창구, 리소스 목록, 서비스 앱 태스크 | M4 |
| M6 | 첫 릴리스 | 시나리오 1~4 Windows 현장 PC 통과 | M5 |
| M7 | 서버 실행 | 서버 실행기, 서버 Bot 동시 실행, 상태 저장·재개, PC 위임, CON-12 | M6 |

## M0. 문서 기준선 (지금)

- [x] 배포 단위 이름 확정: **BPM 프로세스** (운영 화면: Bot)
- [x] 포트 기본값 + 설정 변경, 환경변수 접두사 `CHK_` ([ADR-0011](decisions/0011-config-ports-env.md))
- [x] 무인 실행(Windows 서비스)은 나중에 검토로 미룸
- [x] ADR-0004~0010 결정 (0008·0009는 수정해 수락)
- [x] 서비스 앱 이름 확정, 수행 모드(자율/결정) ([ADR-0010](decisions/0010-service-apps.md))
- [x] Bot UI 하나로 구조 정리: Bot = BPM 프로세스, Worker = 서버 프로세스 ([ADR-0012](decisions/0012-bot-ui.md))
- [x] 키: Center 키는 Bot UI에, 서비스 앱 키는 앱 관리 콘솔에서 ([ADR-0013](decisions/0013-api-keys.md))
- [x] 서비스 앱 키 지정 위치 확정: BPM 프로세스 속성에 키 참조 ([ADR-0013](decisions/0013-api-keys.md) §3)
- [x] PC 한 대에 실행 중인 Bot 하나 + 대기열, 결재 대기 중에도 끝까지 ([ADR-0014](decisions/0014-one-bot-per-pc.md))
- [x] 실행 위치 PC / 서버 구분, 서버는 Center 관리·동시 실행 ([ADR-0015](decisions/0015-run-location.md))
- [x] 서버 우선(기본값 서버), 서버 Bot 이름, 상한 10/5, 서버 실행은 M7 ([ADR-0016](decisions/0016-server-first.md))
- [x] 화면 설계서(`06-screens`) 최종 검토 (독립 검토 22건 반영)
- [x] 확장 모델: 내장·사내·외부, 기여 지점, HTTP 어댑터 ([ADR-0018](decisions/0018-extensions.md), [C13](03-contracts/C13-extension-manifest.md))
- [x] 웹 화면 Next.js, 디자인 토큰 하나 ([ADR-0017](decisions/0017-web-nextjs-design-system.md)), 스타일 가이드 초안 ([07-style-guide](07-style-guide.md))
- [x] 스타일 가이드·토큰 검토 (`design/preview.html`)
- [x] 계약 초안: [C1](03-contracts/C1-package-manifest.md), [C3](03-contracts/C3-run-events.md), [C4](03-contracts/C4-bot-ui-center.md), [C11](03-contracts/C11-service-app-common.md)
- [x] 계약 C1~C6·C10·C11 독립 검토 반영 → 합의
- [x] 계약 초안: [C7](03-contracts/C7-resources-center-keys.md), [C8](03-contracts/C8-ui-automation-plan-heal-report.md), [C9](03-contracts/C9-ui-page-registry.md), [C12](03-contracts/C12-server-runner-center.md)(M7)
- [x] C7·C8·C9·C13 독립 검토 반영 → 합의 (C12는 M7 전에 검토)

## M1. 뼈대와 스파이크

Windows에서 확신이 없는 것부터 작게 확인한다. 각 스파이크는 ADR로 끝난다.

| 스파이크 | 확인할 것 | 결과 ADR |
| --- | --- | --- |
| S1 데스크톱 조작 | Windows UIA로 메모장·엑셀(또는 사내 앱)의 버튼·입력칸·셀을 찾고 조작. `pywinauto` vs `uiautomation` | 데스크톱 백엔드 선택 → `uiautomation` ([ADR-0020](decisions/0020-windows-desktop-backend.md), 수락) |
| S2 화면 캡처·DPI | 125%·150% 배율, 다중 모니터에서 캡처 좌표 = 클릭 좌표 | 캡처 방식 → Worker는 PMv2 인식 + `mss` ([ADR-0021](decisions/0021-worker-dpi-capture.md), 수락 — 다중 모니터 미확인) |
| S3 Studio 셸 | PySide6 + QtWebEngine + bpmn-js가 Windows에서 뜨고 저장·불러오기 | Studio UI 기반 → QtWebEngine + bpmn-js 배포본 + QWebChannel ([ADR-0022](decisions/0022-studio-canvas.md), 수락) |
| S4 상주·자동 시작 | Bot UI 자동 시작, Bot UI가 Worker 프로세스와 실행기 하나(자식 프로세스)를 띄우고 감시·재시작·강제 종료, 대기열에서 다음 Bot으로 넘어가기, 실행 중 Bot → Worker REST, 잠금 화면·로그오프 시 동작 | Bot 실행 형태(자식 프로세스 여부) 확정 (ADR-0012) → 실행기 = 자식 프로세스 + Job Object, 자동 시작은 작업 스케줄러 ([ADR-0023](decisions/0023-bot-ui-process-supervision.md), 수락) |
| S5 확장 로딩 | 엔트리 포인트(`chaeksas.extensions`)로 찾은 내장 확장이 Windows 설치 파일(PyInstaller 등)로 묶인 Studio·Bot UI에서 로드되는지, 확장의 Qt 화면·로컬 런타임 실행 파일이 함께 들어가는지 | 확장 패키징 방식 → PyInstaller onedir + 엔트리 포인트에서 옵션 계산 + 같은 실행 파일로 로컬 런타임 ([ADR-0024](decisions/0024-desktop-packaging-extensions.md), 수락 — 확장 옵션은 `core`가 주는 PyInstaller 훅이 넣는다, Linux에서 확인) |

완료 기준:
- [x] 루트에서 `uv sync`, `uv run pytest`가 Windows·Linux 모두 통과 (CI 두 개) — `.github/workflows/ci.yml`, `windows-latest` + `ubuntu-latest` 매트릭스
- [x] 의존 방향 import 검사 테스트 통과 (`01-architecture` §5) — `tests/test_import_direction.py` (선언 의존 전이 + 실제 import)
- [x] 계약 패키지에서 JSON Schema가 생성됨 — `scripts/gen_schemas.py` (C1~C7·C11·C13 모델 33개. 나머지는 그 단계에서)
- [x] `service_kit`으로 만든 빈 서비스 앱이 `/healthz`, `/manifest`에 답하고, 관리 콘솔에서 발급한 API 키로만 호출되며, 허용되지 않은 모드를 거부함 (C11) — `tests/test_service_kit.py` 28개. **관리 콘솔 화면(SVC-00~03)은 `web/`이라 아직 없다**
- [x] 스파이크 S1~S5 ADR 작성 — ADR-0020~0024 (모두 수락, 2026-10-03). 따라올 계약 변경(C8 `class_name`, C10 `session_locked`, C13 `command`→`entry`)은 아직 안 고쳤다
- [x] `packages/extension_api`(인터페이스)와 `core` 확장 호스트 골격, 빈 내장 확장 하나가 Studio·Bot UI에 태스크 종류·유틸리티를 기여함, 플랫폼이 특정 확장을 import하지 않음을 검사 테스트로 확인 ([ADR-0018](decisions/0018-extensions.md)) — C13 모델·검사 규칙 E1~E6(`chaeksas.contracts.extension`), 인터페이스(`TaskExecutor`·`TaskEditor`·`BotUiUtility`·`PreflightCheck`·어댑터 해석기 규격), 호스트(`chaeksas.core.extensions`: 엔트리 포인트 `chaeksas.extensions` → 기여 등록 → `entry` 해석), 내장 확장 `ui-automation`의 `extension.json`. `tests/test_extension_host.py`·`tests/test_contracts_extension.py`. **화면·수행은 뼈대뿐이다** (UI 태스크 수행·셀렉터 등록 화면은 M4)
- [x] `design/tokens.json` → 웹 CSS·Tailwind 테마(`@theme`)·상태 표(TS)·Qt QSS·미리보기 생성기와 명암비·간격 배수 검사, CI가 생성물 최신 여부 확인 — `scripts/gen_tokens.py`
- [x] `web/` 워크스페이스: `packages/ui`(Button·StatusBadge·DataTable·Field·Dialog·EmptyState·ErrorBanner), `api-types`가 계약 JSON Schema에서 생성됨(33묶음), Windows에서 `pnpm dev` — pnpm 워크스페이스(앱 2 + 패키지 3), Next.js 16·Tailwind 4, CI에 웹 작업 추가(Win+Linux에서 `check:api-types`·`typecheck`·`build`). **실제 화면(CON-*·SVC-*)은 M2다** — 지금 페이지는 토큰·구성요소·타입이 이어졌는지 보는 뼈대다
- [x] Qt 테마: 같은 토큰으로 밝게/어둡게, Pretendard 포함 — `chaeksas.qt.theme.apply_theme()`가 글꼴 등록 + 생성된 QSS + 팔레트를 함께 적용하고, 「시스템 따름」은 OS 변경을 따라간다. 글꼴은 Pretendard 1.3.9(굵기 4개 OTF)·JetBrains Mono 2.304를 저장소에 넣었다(OFL). 웹도 같은 글꼴을 가변 woff2로 자체 호스팅한다. `tests/test_qt_theme.py` 18개가 화면 없이 돈다 (CI Linux는 Qt 라이브러리를 깔고 돈다)

## M2. Center 최소 + Bot UI 연결

- [ ] Linux 서버에 Center가 뜨고, 콘솔에서 발급한 Center API 키를 Windows Bot UI에 넣으면 등록 → 하트비트 (C4, CON-11, BUI-03)
- [ ] Bot UI별 Center API 키로 다른 Bot UI를 사칭할 수 없음
- [ ] 패키지 업로드·목록·다운로드, 해시 검증 (C1, C5 일부)
- [ ] Center 콘솔(Next.js): 공통 틀(CON-00), 관리자 로그인 세션(BFF), Bot UI 현황(CON-03), Center API 키(CON-11)
- [ ] 서비스 앱 관리 콘솔(Next.js): SVC-00~02
- [ ] 서버 구성 `docker compose` 한 번으로 기동

## M3. 실행 코어

- [ ] BPMN 실행: 시작·종료, AI 태스크, 배타 게이트웨이, 결재(로컬)
- [ ] C14 요소 전부: 스크립트(식 언어·도우미 목록 확정), 규칙(DMN, 반복 포함), 포함·병렬 게이트웨이, 차례·병렬 반복, 하위 프로세스, 호출(매핑), 타이머(시작·중간·경계), 메시지 시작·받기·경계(상관 키), 신호(실행 안), 메일·웹훅, 파일 출력, 이정표
- [ ] AI 태스크: LLM 호출, 도구 화이트리스트, 결과 필드 검증
- [ ] 실행 이벤트가 로컬 큐 → Center로 전송, 콘솔 실행 로그(CON-01)에서 타임라인 조회 (C3)
- [ ] Studio: 메인 창(STU-01), BPM 프로세스 탐색기, 속성 패널, 시험 실행 (Windows)
- [ ] 패키지 매니페스트에 `run_location`이 처음부터 들어가고, Studio 「실행 전 검사」가 서버 불가 태스크를 잡고 「실행 위치를 PC로 바꾸기」를 제안 (C1, 기본값 서버, 서버 실행은 M7)
- [ ] BPMN 확장 속성(C14)을 읽고 **쓰며**, 실행 전 검사 B1~B14가 화면에 보임 — 계약 쪽(모델·`read_process()`·`validate()`)은 M1에서 만들어 예제 50개로 확인했다 (`chaeksas.contracts.bpmn_ext`). 남은 것은 Studio가 쓰기·보이기, 그리고 식 도우미 함수 목록 확정
- [ ] **인수 시험:** [업무 예제](08-business-examples/README.md#마일스톤별-인수-시험-묶음)의 M3 묶음이 Studio 시험 실행에서 케이스 모두 통과 (AI 태스크는 자율 수행 → 결정 수행 재생 둘 다)

## M4. UI 자동화

- [ ] UI 자동화를 **내장 확장**(`extensions/ui_automation/`)으로 구현: 서비스 앱·Worker·UI 태스크 수행기·STU-13·BUI-06~08·UIA 콘솔 화면이 모두 확장 기여로 붙음
- [ ] Bot UI의 UI 셀렉터 등록(BUI-06)으로 화면 하나 등록 (C9)
- [ ] Studio UI 태스크 편집기(STU-13)에서 등록된 화면·시맨틱 키를 골라 태스크 작성
- [ ] Bot UI가 Worker 프로세스를 띄우고, 실행 중 Bot → Worker REST → 로케이터 사다리 실행 (C10)
- [ ] 셀렉터를 일부러 깨뜨리면 치유 → 3회 성공 후 승격 (C8)
- [ ] UI 세션 보고에 `page_id`·`outputs`·`escalation`·`business_key`가 채워짐
- [ ] 데스크톱 조작(S1 결과)으로 Windows 앱 한 개 조작
- [ ] **인수 시험:** 업무 예제 M4 묶음 (BX-04·BX-14·BX-17, FX-05·FX-15·FX-16) 통과, M3 묶음 회귀

## M5. 배포·결재·서비스 앱

- [ ] Admin 서명 → 배포 → Bot UI가 Bot 설치, 서명 없는 패키지 거부 (C2, C5)
- [ ] Center 작업 지시 → Bot UI가 Bot 실행 → 결과
- [ ] 결재를 콘솔 결재함(CON-04)에서 답하고 Bot이 이어서 진행 (C6)
- [ ] 리소스 목록(CON-07): 서비스 앱·UI 화면·툴팩·런타임, 배포 전 누락 경고 (C7)
- [ ] 서비스 앱 태스크(STU-14): Studio에서 앱·작업을 골라 만들고, Studio는 자율 수행·Bot은 결정 수행으로 호출 (C11)
- [ ] 외부 확장 하나(시험용 외부 앱)를 정의 파일만으로 Center에 등록하고, 서비스 앱 태스크(STU-14)로 HTTP 어댑터를 통해 부름 (C13 §4)
- [ ] 서비스 앱 관리 콘솔(SVC-02)에서 키 발급 → Bot UI(BUI-10)·Studio에 키 참조로 등록 → 사전 점검이 빠진 키를 잡음
- [ ] 예제가 쓰는 모의 서비스 앱(ERP·디렉터리·신용·헬프데스크 등)을 `samples/mock-*`로 만든다
- [ ] **인수 시험:** 업무 예제 M5 묶음 통과, PC 예제는 Center 배포 → Bot UI 실행으로 다시 통과

## M6. 첫 릴리스

- [ ] 시나리오 1~4(`00-vision`)가 Windows 현장 PC에서 Center 배포를 거쳐 통과
- [ ] 새 개발자가 `04-setup`만 보고 1시간 안에 환경 구성 (실제로 한 번 해 본다)
- [ ] 모든 계약 문서 상태가 "구현됨", 모든 화면이 `06-screens`와 일치

## M7. 서버 실행

> 업무 대부분이 서버 Bot으로 돈다 (서버 우선, [ADR-0016](decisions/0016-server-first.md)). M6 진행을 보고 앞당길지 다시 판단한다.

- [ ] 서버 실행기가 Center API 키(서버 실행기용)로 등록·하트비트 (C12, CON-11)
- [ ] 실행 위치 「서버」 BPM 프로세스를 서버 실행기에 배포하고, 작업 여러 건이 동시에 돈다 (상한 초과는 Center 대기열)
- [ ] 결재를 기다리는 실행이 상태를 저장하고 일꾼을 놓았다가, 결재함 답으로 이어 간다. 서버 실행기를 재시작해도 이어 간다
- [ ] PC 위임(제안 확정 시): 서버 Bot의 Call Activity가 PC BPM 프로세스를 부르면 Bot UI에서 실행되고 결과로 이어 감
- [ ] 콘솔 「서버 실행」(CON-12)에서 실행 중·기다리는 실행·대기열을 본다
- [ ] **인수 시험:** 실행 위치 서버인 업무·기능 예제 전부가 서버 실행기에서 통과. BX-03(며칠 대기)은 서버 실행기 재시작을 끼워 넣어 통과

## 나중에 (범위 밖, 기록만)

PostgreSQL 전환, 서버 실행의 헤드리스 웹 조작, OIDC 로그인, LLM 비용 집계, 실행 기록 보존 정책, 무인 실행(Windows 서비스 모드, S4 결과에 따라), Admin 데스크톱 창, 멀티 테넌시.
