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

## M0. 문서 기준선

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

- [x] Linux 서버에 Center가 뜨고, 콘솔에서 발급한 Center API 키를 Windows Bot UI에 넣으면 등록 → 하트비트 (C4, CON-11, BUI-03) — **Windows 11 실기에서 확인했다** (일반 권한, 한국어, 확인 목록은 [이슈 #3](https://github.com/wrapper755/Chaeksas/issues/3)). 트레이·메뉴·설정 창, 자격 증명 관리자, 작업 스케줄러 자동 시작(로그오프→로그인), Job Object로 손자까지 종료, 잠금 중 하트비트 유지, 로그오프 94초 뒤 Center에서 오프라인까지 봤다. 실기에서 나온 결함 9건은 [#4](https://github.com/wrapper755/Chaeksas/pull/4)·[#5](https://github.com/wrapper755/Chaeksas/pull/5)에서 고치고 같은 PC에서 다시 확인했다 — 일반 권한 자동 시작(작업 XML), 글꼴 힌팅, QSS 그룹 상자·숫자 칸, 150% 배율 창 크기, Center 응답 charset, 시험 격리
- [x] Bot UI별 Center API 키로 다른 Bot UI를 사칭할 수 없음 — 키는 처음 등록한 PC(`machine_id`)에 묶이고 다른 PC에서 쓰면 409 `machine_mismatch`. 운영자가 「PC 묶음 풀기」로 되돌린다
- [x] 패키지 업로드·목록·다운로드, 해시 검증 (C1, C5 일부) — **보낸 해시를 믿지 않고 파일에서 다시 계산해** 매니페스트와 대조한다 (R6). zip 경로 탈출·크기도 Center가 먼저 막는다
- [x] Center 콘솔(Next.js): 공통 틀(CON-00), 관리자 로그인 세션(BFF), Bot UI 현황(CON-03), Center API 키(CON-11) — 토큰은 암호화된 httpOnly 쿠키에 담겨 **브라우저에 내려가지 않는다**(HTML에 새지 않는 것을 확인). 실제로 띄운 Center에 붙여 두 화면이 실 데이터를 그리는 것까지 봤다. 아직 없는 화면은 탐색에서 끄고 이유를 보인다
- [x] 서비스 앱 관리 콘솔(Next.js): SVC-00~03 + `service_kit`의 관리 API(`/admin/v1/status`·`keys`·`usage`, C11) — 콘솔 **한 벌**이 모든 서비스 앱을 그린다(`CHK_SVC_CONSOLE__APP_URL`로 어느 앱인지 정하고, 고유 메뉴는 `app_id`로 고른다). 관리 API는 **관리자 토큰으로만** 열리고 업무 키로는 403, 토큰을 설정하지 않으면 경로 전체가 503이다. 발급 원문은 한 번만 보이고 목록에는 앞자리 16자만 남는다. 실제로 띄운 앱(UI 자동화 데모)에 붙여 세 화면이 실 데이터를 그리는 것과, 토큰·업무 값이 HTML에 새지 않는 것을 봤다. 좁히기·「키별 합계」와 UIA 고유 화면은 M4
- [x] 서버 구성 `docker compose` 한 번으로 기동 — Center API(8800) + Center 콘솔(8501)이 같은 compose로 뜨고, 콘솔이 `http://center:8800`으로 Center를 부르고, 볼륨에 데이터가 남는 것(컨테이너를 다시 띄워도 키가 남는다)까지 봤다. 둘 다 비관리자로 돈다. 콘솔 이미지는 `Dockerfile.console` 하나로 만들고 어느 콘솔인지는 빌드 인자 `APP`이 정한다. `svc-console`은 서비스 앱마다 하나라서 첫 서비스 앱과 함께 M4에 더한다

## M3. 실행 코어

- [ ] BPMN 실행: 시작·종료, AI 태스크, 배타 게이트웨이, 결재(로컬) — **Bot UI가 Bot을 실행한다** (조각 4a): 패키지를 설치하고(해시를 다시 계산해 대조), 대기열에서 꺼내 **자식 프로세스(실행기)**로 돌리고, 결재를 받아 답하고, 중지하면 `cancelled`로 끝난다. 주고받는 길은 파일 한 벌이다 ([ADR-0031](decisions/0031-runner-control-file.md)) — 올라오는 것은 실행 기록(C3), 내려가는 것은 제어 파일. **BUI-04 화면과 결재 창(CMN-01)도 돈다** (조각 4b): 설치된 Bot 목록·「지금 실행...」·「중지」·「결재 창 열기」가 있고, CMN-01은 `packages/qt`에 두어 **Studio와 Bot UI가 같은 창**을 쓴다. **엔진 뼈대가 돈다** (`core.engine`: 시작·종료·스크립트·게이트웨이·하위 프로세스·반복·오류 경계·결재/확인 대기·C3 기록). 예제 50개를 모두 돌려 멈추는 이유가 아는 것뿐임을 확인했다 — 지금 **끝까지 가는 예제 20개, 사람·메시지·타이머를 기다리는 예제 9개** — 50개 중 **29개**가 사람이나 끝까지 간다 (조각 2: 3·1 → 3b: 11·2 → 3c: 19·6 → 3d: 20·9)
- [x] **식 `chk-expr`·스크립트·템플릿** — 문법·도우미 목록 확정, `eval` 없이 AST를 걸어 값을 낸다 ([ADR-0025](decisions/0025-expression-language.md), 스파이크 [S6](../spikes/s6-expr/README.md)). 업무 예제 50개의 식 자리 193곳과 템플릿 자리 전부가 통과한다. 점은 사전 키를 읽고, 위험한 것 11가지는 막힌다
- [x] **흐름 요소**: 병렬·포함 게이트웨이(갈라기·합류), 하위 프로세스, 차례 반복(다중 인스턴스), 오류 경계, **타이머·메시지·신호·호출** — 엔진이 다룬다 (`core.engine`의 토큰 모형 + 기다림 등록부). 엔진은 스레드를 만들지 않는다 — 시간은 `RunEnv.clock`이 주고 부르는 쪽이 `tick()`을, 메시지는 `deliver()`를 부른다. 경계는 **멈춰 있는 동안에만** 울리고 중단·비중단을 가른다. 호출은 같은 `run_id`로 안쪽 실행을 띄운다
- [ ] C14 요소 전부: 규칙(DMN, 반복 포함), 포함·병렬 게이트웨이, 차례·병렬 반복, 하위 프로세스, 호출(매핑), 타이머(시작·중간·경계), 메시지 시작·받기·경계(상관 키), 신호(실행 안), 메일·웹훅, 파일 출력, 이정표 — **규칙(DMN)·파일 목록·파일 출력·메일/웹훅·이정표는 된다** (조각 3b). DMN은 결정표를 직접 읽고 판정한다(`contracts.dmn`, FEEL의 입력 칸 문법만). 파일은 **실행 폴더**로 묶었고 ([ADR-0026](decisions/0026-file-paths-and-file-list-task.md)), ADR-0025가 식에서 뺀 `파일목록()`은 **파일 목록 태스크**(`chk:fileList`)가 되었다. 보내기는 어댑터 뒤에 있고 어댑터가 없으면 **보내지 않고 실패**한다. 남은 것은 Studio(조각 3e)와 예제 수정(3f)이다
- [ ] AI 태스크: LLM 호출, 도구 화이트리스트, 결과 필드 검증 — **돈다** (`core.agent`·`core.llm`). OpenAI 호환 HTTP를 **우리 루프로** 부른다 ([ADR-0027](decisions/0027-llm-connection.md), 스파이크 [S7](../spikes/s7-llm/NOTES.md)) — 의존성을 늘리지 않고(프레임워크는 63~219 MB였다) 도구 선택·허용 목록·궤적 기록을 우리가 쥔다. 허용 밖 도구는 실행 오류, 결과 필드가 틀리면 업무 실패(경계가 받는다). **도구 넷도 돈다** — `pdf_text_tool`·`excel_parser_tool`·`csv_parser_tool`·`http_request_tool`이 `core.tools`에 있고, 도구가 **자기 설명과 인자 모양을 들고 다닌다**(이름만 주면 모델이 인자를 지어낸다). 파일 도구는 실행 폴더 안만 보고, HTTP 도구는 **읽기만** 한다 ([ADR-0030](decisions/0030-ai-task-tools.md), 스파이크 [S8](../spikes/s8-doc-tools/NOTES.md)). OCR·엑셀 쓰기는 만들지 않았다
- [ ] 서비스 앱 태스크를 Bot이 부른다 (C11 — 멱등 키·재시도·`service_call` 기록). `core.services`가 어댑터 뒤에서 부르고, 주소·키 값은 실행하는 쪽만 안다 (ADR-0013). Studio 편집기(STU-14)와 실제 앱은 M5
- [ ] 결정 수행 재생 — **돈다** ([ADR-0028](decisions/0028-replay-memory.md)). 재생 명세는 패키지 안 `memory/specs.json`이고 배포된 Bot은 읽기만 한다. 태스크마다 `replay: plan|full|none`을 고르고, 도구 인자는 `{변수}` 템플릿이라 입력이 달라져도 같은 명세가 맞는다. 재생이 깨지면 몰래 자율로 넘어가지 않고 오류 경계로 간다. Studio가 배운 것을 패키지에 적는 것은 조각 3e
- [x] 실행 이벤트가 로컬 큐 → Center로 전송, 콘솔 실행 로그(CON-01)에서 타임라인 조회 (C3) — **돈다** (조각 3g). **파일이 원본이다**: `runs/<run_id>.jsonl`에 먼저 쓰고, 하트비트가 끝난 뒤 큐를 비운다 (`core.run_shipping`). Center가 꺼져 있어도 실행은 돈다 (ADR-0007) — 남은 줄 수는 `unsent_events`로 알린다 (C4). **멱등이라** 실패하면 같은 배치를 그대로 다시 보내고(`(run_id, seq)`), 보낸 자리는 `.sent`에 남는다. **거부된 줄에서 멈추지 않는다** — 한 줄이 그 실행의 기록을 영원히 막는 일이 프로토타입에서 있었다. **모르는 `kind`도 저장만 한다**. `run_id`는 처음 보낸 키의 것이라 남의 기록을 덮지 못한다. 콘솔 CON-01은 목록(상태·Bot 좁히기)과 상세(요약·노드 타임라인·AI 단계·사람 개입·로그·원본 이벤트)를 그린다 — UI 태스크 섹션은 M4, 이어 돈 기록은 M7
- [ ] Studio: 메인 창(STU-01), BPM 프로세스 탐색기, 속성 패널, 시험 실행 (Windows) — **셸과 캔버스가 돈다** (조각 3e-1): STU-01 뼈대·STU-02 탐색기·STU-05 새 BPM 프로세스·예제 가져오기·열기/저장. 캔버스는 QtWebEngine 안의 bpmn-js이고 ([ADR-0022](decisions/0022-studio-canvas.md)), 배포본은 `web/`에서 버전을 고정해 복사한다 ([ADR-0029](decisions/0029-bpmn-js-vendoring.md)). 예제 4개가 **캔버스를 왕복해도 `chk:*`가 살아남는** 것을 시험이 지킨다. **속성 패널과 실행 전 검사도 돈다** (3e-2): STU-04의 「폼」 탭(이름·설명·조건식·스크립트)과 「JSON」 탭(`chk:*`를 **C14 모델로 검증**하며 고친다), 「적용」은 bpmn-js `modeling`을 거쳐 실행 취소·「저장 안 한 변경」과 함께 움직인다. 아래 탭 「검사」가 B1~B14를 보이고 줄을 더블클릭하면 캔버스가 그 노드를 고른다. 요소별 전용 폼(AI 태스크 재생 명세·허용 도구, 결재 칸 표, DMN 격자)은 툴팩·리소스 목록이 생긴 뒤다. **시험 실행도 돈다** (3e-3): STU-08 실행 대화상자(케이스·수행 모드, 고를 수 없는 것은 끄고 이유를 보인다)와 STU-09(캔버스 노드 색·상태 줄·로그·변수 탭). 케이스의 `approvals`·`messages`·`$now_plus`·`$test_receiver`를 다루고, C14 비교 규칙으로 판정하며, **자율 수행이 배운 재생 명세를 패키지에 적는다** (ADR-0028의 남은 반쪽). Studio는 **바깥으로 웹훅을 쏘지 않는다** — 시험 수신기로만 간다. **케이스 편집기와 패키지 내보내기도 돈다** (3e-4): STU-07은 JSON 글상자 대신 표로 받고(값마다 타입, 비교 콤보, 결재 칸은 그 폼의 키), 「저장」은 창을 닫지 않고 **엔진과 같은 `validate_answer`로 모든 케이스를 검증한다** — 폼에 안 맞는 답을 돌려 보기 전에 잡는다. 패키지 내보내기는 **매니페스트를 그림에서 모아**(도구·영역·서비스 앱 키 참조·결재 종류·트리거·실행 위치) C1 zip 하나를 만들고, `content_hash`는 받는 쪽이 다시 계산하는 규칙(C2) 그대로다. **시험 케이스는 패키지에 넣지 않는다**
- [ ] 패키지 매니페스트에 `run_location`이 처음부터 들어가고, Studio 「실행 전 검사」가 서버 불가 태스크를 잡고 「실행 위치를 PC로 바꾸기」를 제안 (C1, 기본값 서버, 서버 실행은 M7)
- [ ] BPMN 확장 속성(C14)을 읽고 **쓰며**, 실행 전 검사 B1~B14가 화면에 보임 — 계약 쪽(모델·`read_process()`·`validate()`)은 M1에서 만들어 예제 50개로 확인했다 (`chaeksas.contracts.bpmn_ext`). 남은 것은 Studio가 쓰기·보이기다 (식 도우미 목록은 ADR-0025로 정했다)
- [x] **인수 시험:** [업무 예제](08-business-examples/README.md#마일스톤별-인수-시험-묶음)의 M3 묶음이 Studio 시험 실행에서 케이스 모두 통과 (AI 태스크는 자율 수행 → 결정 수행 재생 둘 다) — **24개 모두 통과한다** (`tests/test_m3_acceptance.py`, 조각 3f). 모델은 127.0.0.1에 띄운 OpenAI 호환 스텁이고 표본 파일(PDF·엑셀·CSV)은 시험이 그 자리에서 만든다 — **바깥에 나가지 않고 저장소에 이진 파일을 두지 않는다**. 답은 모델이 아니라 **시험이 정한다** (예제가 그 값이어야 뜻이 통하는 자리는 짜 넣었다) — 시험하는 것은 모델의 똑똑함이 아니라 **엔진·케이스·기대값이 한 줄로 맞물리는가**다. **재생(결정 수행)도 돈다** — AI 태스크가 있는 예제마다 자율 수행으로 배운 뒤 결정 수행으로 다시 돌려, **판정이 같은 것**과 **정말 되밟은 것**(C3 `node_state: replayed`)을 함께 본다. 되밟았는지를 안 보면 「재생이 안 되고 그냥 또 자율로 돌았다」를 통과로 읽는다
- 인수 시험이 **제품 결함 여섯**을 찾았다: ① 키 없는 모델에 `Authorization: Bearer `를 보내 **모든 AI 태스크가 막혔다**(로컬 Ollama·vLLM이 그 자리다), ② Studio 예제 가져오기가 **호출 대상 BPM 프로세스**를 안 가져왔다, ③ 시험 실행이 케이스 메시지를 **진짜 초로 기다려** 아무도 안 밀면 거기서 끝났다(타이머와 한 줄로 세워 이른 것부터 민다), ④ **AI 태스크가 목표에서 가리키는 값이 모델에 가지 않았다** — C14에 「AI 태스크가 보는 값」을 적고 엔진이 보낸다, ⑤ 병렬 가지를 **번갈아 밀지 않아** 한 가지가 끝까지 달렸다 — 다른 가지가 경계를 켜기 전에 신호가 지나가 사라졌다, ⑥ **재생의 마지막 값 추출이 그 값들 없이 물었다** — 같은 입력인데 재생만 다른 답을 냈다 (④와 같은 자리를 `finish_from`에서도 고쳤다)
- 인수 시험이 **예제 결함 넷**도 찾았다: BX-02가 `범위벗어남`에 사전을 넘김, BX-05가 선택 칸(`메모`)을 파일 출력에 씀, BX-11이 `기간()`의 `{from,to}`를 타이머 기한으로 씀(고정 시각으로 바꿨다), BX-11 「공고 취소」가 거치지 않는 길의 변수를 기대함

## M4. UI 자동화 (지금)

- [ ] UI 자동화를 **내장 확장**(`extensions/ui_automation/`)으로 구현: 서비스 앱·Worker·UI 태스크 수행기·STU-13·BUI-06~08·UIA 콘솔 화면이 모두 확장 기여로 붙음
- [ ] Bot UI의 UI 셀렉터 등록(BUI-06)으로 화면 하나 등록 (C9) — **레지스트리와 승격이 돈다** (조각 5): 화면·요소·사다리를 등록하고(**사다리 없는 정보는 거부**, 등록은 **더하기**), 보고로 통계를 갱신해 **세 번 연속 성공한 `unverified`를 `active`로** 올린다. 치유로 찾은 것은 사다리에 `unverified`로 더해져 바로 쓰인다. **자동 강등은 없다**(경고만). 공개 카탈로그에 **셀렉터가 없다**. 남은 것은 **화면**(BUI-06~08)과 서비스 앱 붙이기(M5)다. **분석·검증(Worker 쪽)도 돈다** (조각 6, C10 §5): 열린 화면에서 요소 후보를 모아 **시맨틱 키를 제안**하고(`test_id` → `id` → `name` → 영문 이름 → 역할, **한글 이름은 음역하지 않는다**), 후보 하나로 사다리를 만들고, **지금 열린 화면에서** 사다리 칸마다 시험한다. **범위가 비면 전체로 몰래 넓히지 않고**, **잘리면 잘렸다고 말한다**. 검증은 **하나에 맞아야** 통과이고 결과가 등록을 **막지는 않는다**(사람이 정한다). 등록 세션이 아니면 403이라 실행 중인 Bot의 화면을 헤집지 못한다. 진짜 Chromium으로 확인했다. 남은 것은 **직접 고르기**(`pick`)다. **화면도 절반 돈다** (조각 7): Bot UI가 **확장을 싣고** 「도구」 메뉴에 유틸리티를 띄우며, `needs_runtime`인 유틸리티를 열 때 **로컬 런타임(Worker)을 자식으로 띄우고 `health`가 답할 때까지 기다린다** (못 띄우면 창을 열지 않는다). BUI-06은 브라우저 열기·분석·시맨틱 키 고치기·검증까지 돈다. **서버 부분도 돈다** (조각 8): UI 자동화 앱(`service/app.py`)이 C9의 네 작업과 공개 카탈로그를 `service_kit` 위에서 제공하고 SQLite 한 파일에 남긴다 — **다시 띄워도 레지스트리가 남는다**. 셀렉터가 나가는 작업은 `registry_write` 키만 부를 수 있고(작업이 `required_scopes`로 선언하고 뼈대가 건다, C11), **공개 카탈로그에는 셀렉터가 없다**. 보고 세 번이면 승격까지 간다. `docker compose`에 앱과 그 관리 콘솔이 들어갔다. 남은 것은 **「직접 고르기」·화면의 「등록」·BUI-07·BUI-08**과 계획 생성(C8 `plan`·`heal`)이다
- [ ] Studio UI 태스크 편집기(STU-13)에서 등록된 화면·시맨틱 키를 골라 태스크 작성
- [ ] Bot UI가 Worker 프로세스를 띄우고, 실행 중 Bot → Worker REST → 로케이터 사다리 실행 (C10) — **로컬 API 뼈대가 돈다** (조각 1): `extensions/ui_automation/worker`가 127.0.0.1에만 뜨고(토큰 둘은 파일로, 다시 띄우면 바뀐다), 세션 열기·스텝·상태·관리(예약·강제 닫기)가 C10대로 답한다. **세션은 한 번에 하나**이고 세션 비밀이 있어야 만진다. 유휴 세션은 Worker가 닫는다. **화면을 만지는 일은 `Backend`가** 하고 아직 없다 — 세션을 열면 503 `browser_unavailable`이다 (「없는데 된 척」하지 않는다). 남은 것은 **실제 백엔드**(Windows UIA·브라우저)와 로케이터 사다리(C8)다
- [ ] 셀렉터를 일부러 깨뜨리면 치유 → 3회 성공 후 승격 (C8) — **사다리와 치유가 돈다** (조각 2): Worker가 계획을 들고 **로컬에서** 탄다 (폴백 도중 네트워크를 타지 않는다). 안정한 것부터, `deprecated`는 건너뛰고, **정확히 하나**에 맞아야 쓴다. 다 실패해야 치유를 한 번 부르고 **제안도 확인한 뒤에** 쓴다. 한도를 넘으면 전환이다. 스냅샷은 **값을 가려서** 보낸다 (원칙 6). 브라우저 백엔드는 Playwright로 얇게 붙였고 **진짜 Chromium으로 확인했다** (CI는 바이너리를 내려받지 않아 건너뛴다 — 규칙 시험은 브라우저 없이 돈다). **계획·보고도 돈다** (조각 3): 세션을 열 때 계획을 받아 오고(닿지 못하면 캐시 — C10 `plan_source`), 스텝이 그 사다리를 타고, 닫을 때 보고를 보낸다. 보고는 **먼저 디스크에 쓰고** 보내며 **4xx는 다시 보내지 않는다**(큐가 막힌다). 보고에 **읽은 값은 들어가지 않는다**(원칙 6). 남은 것은 **승격 통계**(서버 쪽)와 UI 태스크 수행기다
- [ ] UI 세션 보고에 `page_id`·`outputs`·`escalation`·`business_key`가 채워짐 — **수행기가 돈다** (조각 4): 실행기가 Worker에 세션을 열고 스텝을 보내고 닫으면서 요약을 받는다. **읽은 값은 BPM 프로세스 변수로** 가고 보고에는 **들어가지 않는다** (원칙 6 — 프로토타입의 `outputs`는 없앴다). **전환은 확인으로** 넘어가고, **Worker가 다시 떴을 때는 조작한 적이 있으면 다시 하지 않는다** (C10 §3). 시험이 **진짜 Worker를 띄워** 토큰·세션 비밀·사다리까지 한 줄로 본다
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
