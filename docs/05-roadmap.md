# 05. 로드맵

> 상태: **M0~M3·M5·M7·M9는 끝났다.** M4(UI 자동화)는 걷었고 다시 들인다(ADR-0114). M6·M8은 현장 PC에서 사람이 할 것만 남았다 (단계별 상태는 아래 표). 날짜는 넣지 않는다 — 각 단계는 완료 기준을 모두 만족해야 끝난다.
> 원칙: 한 단계가 끝날 때마다 **Windows 클라이언트 + Linux 서버** 조합에서 확인한다. "내 PC에서 된다"는 완료가 아니다.

## 단계 한눈에

**상태는 아래 각 단계의 체크 상자가 원본이다.** 이 표는 그것을 한 줄로 줄인 것이고, 상자를 켤
때 같이 고친다.

| 단계 | 이름 | 상태 | 핵심 산출물 | 선행 |
| --- | --- | --- | --- | --- |
| M0 | 문서 기준선 | **끝** | 이 문서 묶음, 초기 ADR, 참고 지도, 화면 설계서 | — |
| M1 | 뼈대와 스파이크 | **끝** | 워크스페이스(uv + `web/` pnpm), 계약 패키지 골격, `service_kit` 골격, 디자인 토큰 생성기, CI(Win+Linux, Python+Node), Windows 스파이크 4개 | M0 |
| M2 | Center 최소 + PC 실행기 연결 | **끝** | Center API 키로 PC 실행기 등록·하트비트, 패키지 업로드·다운로드, 콘솔 최소 | M1 |
| M3 | 실행 코어 | **끝** | BPMN 실행, AI 태스크, 실행 이벤트, Studio 최소 | M1 |
| M4 | UI 자동화 | **걷었다 — 다시 들인다** ([ADR-0114](decisions/0114-remove-ui-automation.md)) | (없음) | M2, M3 |
| M5 | 배포·결재·서비스 앱 | **끝** | 서명·배포, 작업 지시, 결재 창구, 리소스 목록, 서비스 앱 태스크 | M2, M3 |
| M6 | 첫 릴리스 | **진행 중** (시나리오 3은 UI 자동화를 다시 들일 때까지 멈춤, 남은 하나는 현장 PC 사람 몫) | 시나리오 3 Windows 현장 PC 통과 (1·2·4는 M7, ADR-0055) | M5 |
| M7 | 서버 실행 | **끝** | 서버 실행기, 서버 BPM 프로세스 동시 실행, 상태 저장·재개, PC 위임, CON-12 | M6 |
| M8 | 건넬 수 있게, 고칠 수 있게 | **진행 중** (남은 둘은 현장 PC 사람 몫) | Windows 설치 파일(빌드·CI 산출물·자동 시작·판 올리기), Center 저장소 옮기기 수단 | M7 |
| M9 | 바깥 기능은 Pull로 | **끝** (조각 1~6과 C14·C1의 옛 키 칸 — ADR-0102·0103) | C15 외부 작업, 일꾼이 된 서비스 앱, 어댑터 일꾼, 주소·키 칸 없는 CON-07 | M7 |

## M0. 문서 기준선

- [x] 배포 단위 이름 확정: **BPM 프로세스** (운영 화면도 — [ADR-0111](decisions/0111-bpm-process-and-pc-runner-names.md))
- [x] 포트 기본값 + 설정 변경, 환경변수 접두사 `CHK_` ([ADR-0011](decisions/0011-config-ports-env.md))
- [x] 무인 실행(Windows 서비스)은 나중에 검토로 미룸
- [x] ADR-0004~0010 결정 (0008·0009는 수정해 수락)
- [x] 서비스 앱 이름 확정, 수행 모드(자율/결정) ([ADR-0010](decisions/0010-service-apps.md))
- [x] PC 실행기 하나로 구조 정리: BPM 프로세스, Worker = 서버 프로세스 ([ADR-0012](decisions/0012-bot-ui.md) — Worker는 [ADR-0114](decisions/0114-remove-ui-automation.md)로 걷었다)
- [x] 키: Center 키는 PC 실행기에, 서비스 앱 키는 앱 관리 콘솔에서 ([ADR-0013](decisions/0013-api-keys.md) — 서비스 앱 키는 [ADR-0102](decisions/0102-calling-outside-is-pull.md)로 없어졌고 Center 키는 Center가 봉해 내려 준다, [ADR-0092](decisions/0092-keys-are-issued-and-delivered-by-center.md))
- [x] 서비스 앱 키 지정 위치 확정: BPM 프로세스 속성에 키 참조 ([ADR-0013](decisions/0013-api-keys.md) §3 — [ADR-0102](decisions/0102-calling-outside-is-pull.md)로 대체: 키 참조 칸이 없다)
- [x] PC 한 대에 실행 중인 BPM 프로세스 하나 + 대기열, 결재 대기 중에도 끝까지 ([ADR-0014](decisions/0014-one-bot-per-pc.md))
- [x] 실행 위치 PC / 서버 구분, 서버는 Center 관리·동시 실행 ([ADR-0015](decisions/0015-run-location.md))
- [x] 서버 우선(기본값 서버), 서버 BPM 프로세스 이름, 상한 10/5, 서버 실행은 M7 ([ADR-0016](decisions/0016-server-first.md))
- [x] 화면 설계서(`06-screens`) 최종 검토 (독립 검토 22건 반영)
- [x] 확장 모델: 내장·사내·외부, 기여 지점, HTTP 어댑터 ([ADR-0018](decisions/0018-extensions.md), [C13](03-contracts/C13-extension-manifest.md))
- [x] 웹 화면 Next.js, 디자인 토큰 하나 ([ADR-0017](decisions/0017-web-nextjs-design-system.md)), 스타일 가이드 초안 ([07-style-guide](07-style-guide.md))
- [x] 스타일 가이드·토큰 검토 (`design/preview.html`)
- [x] 계약 초안: [C1](03-contracts/C1-package-manifest.md), [C3](03-contracts/C3-run-events.md), [C4](03-contracts/C4-bot-ui-center.md), [C11](03-contracts/C11-service-app-common.md)
- [x] 계약 C1~C6·C10·C11 독립 검토 반영 → 합의
- [x] 계약 초안: [C7](03-contracts/C7-resources-center-keys.md), C8, C9 (둘은 [ADR-0114](decisions/0114-remove-ui-automation.md)로 지웠다), [C12](03-contracts/C12-server-runner-center.md)(M7)
- [x] C7·C8·C9·C13 독립 검토 반영 → 합의 (C12는 M7 전에 검토)

## M1. 뼈대와 스파이크

Windows에서 확신이 없는 것부터 작게 확인한다. 각 스파이크는 ADR로 끝난다.

| 스파이크 | 확인할 것 | 결과 ADR |
| --- | --- | --- |
| S1 데스크톱 조작 | Windows UIA로 메모장·엑셀(또는 사내 앱)의 버튼·입력칸·셀을 찾고 조작. `pywinauto` vs `uiautomation` | 데스크톱 백엔드 선택 → `uiautomation` ([ADR-0020](decisions/0020-windows-desktop-backend.md), 수락) |
| S2 화면 캡처·DPI | 125%·150% 배율, 다중 모니터에서 캡처 좌표 = 클릭 좌표 | 캡처 방식 → Worker는 PMv2 인식 + `mss` ([ADR-0021](decisions/0021-worker-dpi-capture.md), 수락 — 다중 모니터 미확인) |
| S3 Studio 셸 | PySide6 + QtWebEngine + bpmn-js가 Windows에서 뜨고 저장·불러오기 | Studio UI 기반 → QtWebEngine + bpmn-js 배포본 + QWebChannel ([ADR-0022](decisions/0022-studio-canvas.md), 수락) |
| S4 상주·자동 시작 | PC 실행기 자동 시작, PC 실행기가 Worker 프로세스와 실행기 하나(자식 프로세스)를 띄우고 감시·재시작·강제 종료, 대기열에서 다음 BPM 프로세스로 넘어가기, 실행 중 BPM 프로세스 → Worker REST, 잠금 화면·로그오프 시 동작 | BPM 프로세스 실행 형태(자식 프로세스 여부) 확정 (ADR-0012) → 실행기 = 자식 프로세스 + Job Object, 자동 시작은 작업 스케줄러 ([ADR-0023](decisions/0023-bot-ui-process-supervision.md), 수락) |
| S5 확장 로딩 | 엔트리 포인트(`chaeksas.extensions`)로 찾은 내장 확장이 Windows 설치 파일(PyInstaller 등)로 묶인 Studio·PC 실행기에서 로드되는지, 확장의 Qt 화면·로컬 런타임 실행 파일이 함께 들어가는지 | 확장 패키징 방식 → PyInstaller onedir + 엔트리 포인트에서 옵션 계산 + 같은 실행 파일로 로컬 런타임 ([ADR-0024](decisions/0024-desktop-packaging-extensions.md), 수락 — 확장 옵션은 `core`가 주는 PyInstaller 훅이 넣는다, Linux에서 확인) |

완료 기준:
- [x] 루트에서 `uv sync`, `uv run pytest`가 Windows·Linux 모두 통과 — `.github/workflows/ci.yml`. PR마다 Linux, Windows는 주 1회(월요일, main)와 수동 실행이다 ([ADR-0108](decisions/0108-windows-ci-weekly.md))
- [x] 의존 방향 import 검사 테스트 통과 (`01-architecture` §5) — `tests/test_import_direction.py` (선언 의존 전이 + 실제 import)
- [x] 계약 패키지에서 JSON Schema가 생성됨 — `scripts/gen_schemas.py` (확장이 소유한 계약은 그 확장의 `schemas/`에 쓴다)
- [x] `service_kit`으로 만든 빈 서비스 앱이 `/healthz`, `/manifest`에 답하고, 관리 콘솔에서 발급한 API 키로만 호출되며, 허용되지 않은 모드를 거부함 (C11) — `tests/test_service_kit.py`. 관리 콘솔 화면(SVC-00~03)은 M2에서 붙었다
- [x] 스파이크 S1~S5 ADR 작성 — ADR-0020~0024 (모두 수락, 2026-10-03). 따라온 계약 변경(C8 `class_name`, C10 `session_locked`, C13 `command`→`entry`)도 계약에 들었다
- [x] `packages/extension_api`(인터페이스)와 `core` 확장 호스트 골격, 빈 내장 확장 하나가 Studio·PC 실행기에 태스크 종류·유틸리티를 기여함, 플랫폼이 특정 확장을 import하지 않음을 검사 테스트로 확인 ([ADR-0018](decisions/0018-extensions.md)) — C13 모델·검사 규칙 E1~E6(`chaeksas.contracts.extension`), 인터페이스(`TaskExecutor`·`TaskEditor`·`BotUiUtility`·`PreflightCheck`·어댑터 해석기 규격), 호스트(`chaeksas.core.extensions`: 엔트리 포인트 `chaeksas.extensions` → 기여 등록 → `entry` 해석), 내장 확장 `ui-automation`의 `extension.json`. `tests/test_extension_host.py`·`tests/test_contracts_extension.py`
- [x] `design/tokens.json` → 웹 CSS·Tailwind 테마(`@theme`)·상태 표(TS)·Qt QSS·미리보기 생성기와 명암비·간격 배수 검사, CI가 생성물 최신 여부 확인 — `scripts/gen_tokens.py`
- [x] `web/` 워크스페이스: `packages/ui`(Button·StatusBadge·DataTable·Field·Dialog·EmptyState·ErrorBanner), `api-types`가 계약 JSON Schema에서 생성됨(33묶음), Windows에서 `pnpm dev` — pnpm 워크스페이스(앱 2 + 패키지 3), Next.js 16·Tailwind 4, CI에 웹 작업 추가(Win+Linux에서 `check:api-types`·`typecheck`·`build`)
- [x] Qt 테마: 같은 토큰으로 밝게/어둡게, Pretendard 포함 — `chaeksas.qt.theme.apply_theme()`가 글꼴 등록 + 생성된 QSS + 팔레트를 함께 적용하고, 「시스템 따름」은 OS 변경을 따라간다. 글꼴은 Pretendard 1.3.9(굵기 4개 OTF)·JetBrains Mono 2.304를 저장소에 넣었다(OFL). 웹도 같은 글꼴을 가변 woff2로 자체 호스팅한다. `tests/test_qt_theme.py` 18개가 화면 없이 돈다 (CI Linux는 Qt 라이브러리를 깔고 돈다)

## M2. Center 최소 + PC 실행기 연결

- [x] Linux 서버에 Center가 뜨고, Windows PC 실행기가 Center API 키로 등록 → 하트비트 (C4, CON-11, BUI-03) — 지금 키는 사람이 넣지 않는다: PC 실행기가 요청 코드로 청하고 관리자가 CON-03 「승인 대기」에서 승인하면 Center가 봉해 내려 준다 ([ADR-0092](decisions/0092-keys-are-issued-and-delivered-by-center.md)). **Windows 11 실기에서 확인했다** (일반 권한, 한국어, 확인 목록은 [이슈 #3](https://github.com/wrapper755/Chaeksas/issues/3)). 트레이·메뉴·설정 창, 자격 증명 관리자, 작업 스케줄러 자동 시작(로그오프→로그인), Job Object로 손자까지 종료, 잠금 중 하트비트 유지, 로그오프 94초 뒤 Center에서 오프라인까지 봤다. 실기에서 나온 결함 9건은 [#4](https://github.com/wrapper755/Chaeksas/pull/4)·[#5](https://github.com/wrapper755/Chaeksas/pull/5)에서 고치고 같은 PC에서 다시 확인했다 — 일반 권한 자동 시작(작업 XML), 글꼴 힌팅, QSS 그룹 상자·숫자 칸, 150% 배율 창 크기, Center 응답 charset, 시험 격리
- [x] PC 실행기별 Center API 키로 다른 PC 실행기를 사칭할 수 없음 — 키는 처음 등록한 PC(`machine_id`)에 묶이고 다른 PC에서 쓰면 409 `machine_mismatch`. **거꾸로도 하나다** — 같은 PC를 다른 키가 등록하면 409 `machine_already_registered`라서 PC 하나에 PC 실행기 행이 둘 생기지 않는다 (C4 「키 묶기」). 운영자가 「PC 묶음 풀기」로 되돌리고, 풀린 자리는 새 키가 이어받는다
- [x] 패키지 업로드·목록·다운로드, 해시 검증 (C1, C5 일부) — **보낸 해시를 믿지 않고 파일에서 다시 계산해** 매니페스트와 대조한다 (R6). zip 경로 탈출·크기도 Center가 먼저 막는다
- [x] Center 콘솔(Next.js): 공통 틀(CON-00), 관리자 로그인 세션(BFF — 지금은 관리자 계정, [ADR-0090](decisions/0090-center-admin-accounts.md)), PC 실행기 현황(CON-03), Center API 키(CON-11) — 세션은 암호화된 httpOnly 쿠키에 담겨 **브라우저에 내려가지 않는다**(HTML에 새지 않는 것을 확인). 실제로 띄운 Center에 붙여 두 화면이 실 데이터를 그리는 것까지 봤다
- [x] 서비스 앱 관리 콘솔(Next.js): SVC-00~03 + `service_kit`의 관리 API(`/admin/v1/status`·`keys`·`usage`, C11) — 콘솔 **한 벌**이 모든 서비스 앱을 그린다(`CHK_SVC_CONSOLE__APP_URL`로 어느 앱인지 정하고, 고유 메뉴는 `app_id`로 고른다). 관리 API는 **관리자 토큰으로만** 열리고 업무 키로는 403, 토큰을 설정하지 않으면 경로 전체가 503이다. 발급 원문은 한 번만 보이고 목록에는 앞자리 16자만 남는다. 실제로 띄운 앱(UI 자동화 데모)에 붙여 세 화면이 실 데이터를 그리는 것과, 토큰·업무 값이 HTML에 새지 않는 것을 봤다. 좁히기·「키별 합계」와 UIA 고유 화면은 M4
- [x] 서버 구성 `docker compose` 한 번으로 기동 — `deploy/compose.yaml`로 Center API(8800) + Center 콘솔(8501) + 서버 실행기가 뜨고(실행기 키는 비밀 볼륨 — [ADR-0100](decisions/0100-server-runner-secrets-dir.md)), 콘솔이 `http://center:8800`으로 Center를 부르고, 볼륨에 데이터가 남는 것(컨테이너를 다시 띄워도 키가 남는다)까지 봤다. 둘 다 비관리자로 돈다. 콘솔 이미지는 `Dockerfile.console` 하나로 만들고 어느 콘솔인지는 빌드 인자 `APP`이 정한다. `svc-console`은 서비스 앱마다 하나다

## M3. 실행 코어

> 상태: **끝.**

- [x] BPMN 실행: 시작·종료, AI 태스크, 배타 게이트웨이, 결재(로컬) — 엔진은 `core.engine`이고 **한 걸음씩** 돌며 스레드를 만들지 않는다. PC 실행기가 패키지를 설치해(해시를 다시 계산해 대조) 대기열에서 꺼내 **자식 프로세스(실행기)**로 돌린다. 오가는 길은 실행 기록(C3)과 제어 파일 하나다 ([ADR-0031](decisions/0031-runner-control-file.md)). 결재 창 CMN-01은 `packages/qt`에 있어 **Studio와 PC 실행기가 같은 창**을 쓴다
- [x] **식 `chk-expr`·스크립트·템플릿** — `eval` 없이 허용한 AST 노드만 걷는다 ([ADR-0025](decisions/0025-expression-language.md), 스파이크 [S6](../spikes/s6-expr/README.md)). 도우미 호출은 값 없이 미리 본다(C14 B15)
- [x] **흐름 요소**: 병렬·포함 게이트웨이(갈라기·합류), 하위 프로세스, 차례 반복(다중 인스턴스), 오류 경계, **타이머·메시지·신호·호출** — 시간은 `RunEnv.clock`이 주고 부르는 쪽이 `tick()`·`deliver()`·`signal()`을 부른다. 경계는 **멈춰 있는 동안에만** 켜지고 중단·비중단을 가른다. 호출은 같은 `run_id`로 안쪽 실행을 띄우고, 병렬 가지는 번갈아 민다
- [x] C14 요소 전부: 규칙(DMN, 반복 포함), 포함·병렬 게이트웨이, 차례·병렬 반복, 하위 프로세스, 호출(매핑), 타이머(시작·중간·경계), 메시지 시작·받기·경계(상관 키), 신호(실행 안), 메일·웹훅, 파일 출력, 이정표 — DMN은 `contracts.dmn`이 결정표를 직접 읽고 판정한다(FEEL은 C14에 적은 입력 칸 문법만). 파일은 출력 폴더와 허용 폴더 안만 ([ADR-0026](decisions/0026-file-paths-and-file-list-task.md)·[ADR-0032](decisions/0032-writable-dirs.md)), 보내기는 `RunEnv`의 어댑터 뒤에 있다 ([ADR-0059](decisions/0059-sending-mail-and-webhooks.md))
- [x] AI 태스크: LLM 호출, 도구 화이트리스트, 결과 필드 검증 — `core.agent`가 OpenAI 호환 HTTP를 **우리 루프로** 부른다 ([ADR-0027](decisions/0027-llm-connection.md), 스파이크 [S7](../spikes/s7-llm/NOTES.md)). 허용 밖 도구는 실행 오류, 결과 필드가 틀리면 업무 실패다. 내장 도구(PDF·엑셀·CSV·HTTP 읽기, 엑셀 덧붙이기)는 `core.tools`이고 자기 설명과 인자 모양을 들고 다닌다 ([ADR-0030](decisions/0030-ai-task-tools.md), 스파이크 [S8](../spikes/s8-doc-tools/NOTES.md)). 한도·지시문은 [ADR-0105](decisions/0105-ai-task-limits-and-instructions.md)
- [x] 서비스 앱 태스크를 BPM 프로세스가 부른다 (멱등 키·재시도·`service_call` 기록) — **C15 외부 작업으로** 부른다 ([ADR-0102](decisions/0102-calling-outside-is-pull.md)): `core.services.CenterServiceCaller`가 Center에 일감을 올리고 일꾼이 가져간다. 주소·키는 일꾼만 안다
- [x] 결정 수행 재생 ([ADR-0028](decisions/0028-replay-memory.md)) — 재생 명세는 패키지 안 `memory/specs.json`이고 배포된 BPM 프로세스는 읽기만 한다. 태스크마다 `replay: plan|full|none`을 고르고 도구 인자는 `{변수}` 템플릿이다. 재생이 깨지면 몰래 자율로 넘어가지 않고 오류 경계로 간다
- [x] 실행 이벤트가 로컬 큐 → Center로 전송, 콘솔 실행 로그(CON-01)에서 타임라인 조회 (C3) — **파일이 원본이다**: `runs/<run_id>.jsonl`에 먼저 쓰고 하트비트 뒤에 `core.run_shipping`이 보낸다. Center가 꺼져 있어도 실행은 돈다 (ADR-0007). 멱등(`(run_id, seq)`)이고 거부된 줄에서 멈추지 않는다. CON-01은 목록·상세(노드 타임라인·AI 단계·사람 개입·UI 태스크·이어 돈 기록·원본 이벤트)다
- [x] Studio: 메인 창(STU-01), BPM 프로세스 탐색기, 속성 패널, 시험 실행 (Windows) — 캔버스는 QtWebEngine 안의 bpmn-js이고 배포본은 `web/`에서 판을 고정해 복사한다 ([ADR-0022](decisions/0022-studio-canvas.md)·[ADR-0029](decisions/0029-bpmn-js-vendoring.md)). 속성 패널(STU-04)은 요소별 폼과 C14 모델로 검증하는 「JSON」 탭이고 「적용」은 캔버스를 거친다. 아래 탭 「검사」가 B1~B16을 보인다. 시험 실행(STU-08·09)은 케이스의 결재·메시지·위임·`$now_plus`·`$test_receiver`를 다루고 **자율 수행이 배운 재생 명세를 패키지에 적는다**. 바깥으로 웹훅을 쏘지 않는다. 케이스 편집기(STU-07)는 엔진과 같은 `validate_answer`로 검증하고, 패키지 내보내기는 매니페스트를 그림에서 모은다(시험 케이스는 넣지 않는다)
- [x] 패키지 매니페스트에 `run_location`이 처음부터 들어가고, Studio 「실행 전 검사」가 서버 불가 태스크를 잡고 「실행 위치를 PC로 바꾸기」를 제안 (C1, 기본값 서버, 서버 실행은 M7) — 매니페스트의 `run_location`(없으면 **서버**)과 B6은 `contracts.bpmn_ext`에 있고 검사 탭이 보인다. 제안 단추는 화면 설계서대로 **STU-06**에 있다(`process_dialog.py` — 검사 탭에는 쓰기 단추를 두지 않는다). 세는 함수는 B6과 하나(`contracts.server_blockers`)다
- [x] BPMN 확장 속성(C14)을 읽고 **쓰며**, 실행 전 검사가 화면에 보임 — 계약 쪽은 `contracts.bpmn_ext`(B1~B16), 식 자리 검사(B15)는 `core.expr_check`, 쓰기는 속성 패널이 캔버스를 거쳐 한다
- [x] **인수 시험:** [업무 예제](08-business-examples/README.md#마일스톤별-인수-시험-묶음)의 M3 묶음이 Studio 시험 실행에서 케이스 모두 통과 (AI 태스크는 자율 수행 → 결정 수행 재생 둘 다) — **29개 모두 통과한다** (`tests/test_m3_acceptance.py`, `REMAINING`이 비었다). 모델은 127.0.0.1에 띄운 OpenAI 호환 스텁이고 답은 시험이 정한다(`tests/canned_answers.py`), 표본 파일은 시험이 그 자리에서 만든다(`tests/sample_files.py`). 재생은 **판정이 같은 것**과 **정말 되밟은 것**(C3 `node_state: replayed`)을 함께 본다

## M4. UI 자동화

> 상태: **걷었다 — 다시 들인다** ([ADR-0114](decisions/0114-remove-ui-automation.md)). M4가 만든 것(UI 자동화
> 확장 — 서비스 앱·Worker 프로세스·UI 태스크·셀렉터 등록 도구, 그것만 쓰던 Tool UI·로컬 런타임 감독·C8~C10)은
> 코드·계약·화면에서 빠졌고, 그 예제 일곱(BX-04·BX-14·BX-17·BX-36·FX-05·FX-15·FX-16)과 M4 인수 묶음도 없다.
> 다시 들일 때는 기여 지점·장치를 **필요한 것만** 새 ADR로 정하고 완료 기준을 그때 새로 적는다.
> 걷은 장치의 결정(ADR-0020·0021·0033·0035~0037·0040·0072·0074·0077)은 본문이 남아 출발점이 된다.

## M5. 배포·결재·서비스 앱

> 상태: **끝.**

- [x] 승인·배포 서명 → 배포 → PC 실행기가 BPM 프로세스 설치, 서명 없는 패키지 거부 (C2, C5) — 관리자가 Center 콘솔에 **계정으로** 들어와 승인(CON-02·06)·배포(CON-15)하면 **Center가 서버의 키로 봉투를 대신 서명한다** ([ADR-0090](decisions/0090-center-admin-accounts.md) — `center/signer.py`, 교체는 `chk-center signing-key`). 하트비트가 **저장된 JSON 그대로** 내려 주고 PC 실행기가 V1~V7을 보고 설치하거나 **사유와 함께 거부한다**(서명 없는 패키지 V7, 남의 배포 V6, 예약은 거부가 아니라 기다림). 승인·배포 철회는 되살아나지 않는다
- [x] Center 작업 지시 → PC 실행기가 BPM 프로세스 실행 → 결과 — `/jobs`에는 **서명이 없다**(「언제 돌려라」라서 토큰 권한이 관문이다, C5 권한표). 배포되지 않은 것은 돌릴 수 없고(`no_deployment`), ack가 올 때까지 매번 다시 싣고, 실행의 성패는 `run_status`에만 적는다. 시작된 작업의 취소는 대상 종류가 가른다 ([ADR-0063](decisions/0063-stopping-a-running-server-run.md) — PC는 거절)
- [x] 콘솔 운영 화면 CON-03·04·05 — CON-03은 목록과 상세(대기열·배포·확장·최근 배치 결정·준비), CON-04는 결재함, CON-05는 작업(목록에는 입력의 **키만**, 「새 작업」은 매니페스트의 `inputs`로 칸을 그린다)이다
- [x] 결재를 콘솔 결재함(CON-04)에서 답하고 BPM 프로세스가 이어서 진행 (C6) — `center/api/approvals.py`: 확인은 올라오지 않고(422), 답은 올린 키에게만 가고, 거절은 되돌림이며, 실행이 끝나거나 대기열을 잃으면 자동으로 회수한다. 현장은 요청 파일 → 하트비트 → 제어 파일로 잇는다 ([ADR-0038](decisions/0038-approval-request-channel.md)). 서버 실행기도 같은 결재함을 쓴다
- [x] 리소스 목록(CON-07): 확장·서비스 앱·확장 기여 자원·런타임, 배포 전 누락 경고 (C7) — **따로 등록받지 않는다**: 런타임은 C4 보고, 서비스 앱은 일꾼이 올린 manifest, 확장은 둘을 합친 것이다. 주소·키 칸이 없고 상태는 토픽(붙은 일꾼·밀린 일감)에서 온다 ([ADR-0102](decisions/0102-calling-outside-is-pull.md)). 누락은 읽을 때 세고, 배포를 막는 것은 확장 누락·해시 불일치·R8뿐이다. 기여 자원은 일꾼이 올린 카탈로그다
- [x] 서비스 앱 태스크(STU-14): Studio에서 앱·작업을 골라 만들고, Studio는 자율 수행·BPM 프로세스는 결정 수행으로 호출 (C11) — `service_editor.py`: 고를 거리는 C7 리소스 목록에서 오고 **C11 앱과 외부 확장의 어댑터 작업이 같은 모양**이다. 입력·출력 표는 스키마에서 짓고 필수 입력이 비면 「적용」을 막는다. 키 칸은 없다(C15). Studio 시험 실행은 시험 일감(`origin: test`)으로 진짜 앱을 부른다
- [x] 외부 확장 하나(시험용 외부 앱)를 정의 파일만으로 Center에 등록하고, 서비스 앱 태스크(STU-14)로 HTTP 어댑터를 통해 부름 (C13 §4) — 관리자가 CON-07에서 정의를 올리면 E1~E8을 지난 뒤 **Center가 서명한다**(E6, ADR-0090). 어댑터는 **어댑터 일꾼**(`apps/adapter_consumer`)이 `core.http_adapter.AdapterCaller`로 돌리고 주소·키는 그 일꾼의 환경변수에만 있다. 실행하는 쪽은 `core.app_directory`로 봉투를 다시 검증하고, 고정한 `definition_hash`와 다르면 시작조차 하지 않는다 ([ADR-0060](decisions/0060-pinning-external-definitions.md))
- [x] 사전 점검이 BPM 프로세스에 빠진 것을 잡고 Center가 그것을 안다 (C4 `readiness`) — 처음 기준이었던 서비스 앱 키는 [ADR-0102](decisions/0102-calling-outside-is-pull.md)로 없어졌다. `core.preflight`가 갖춰야 할 설정(`requires.settings`)·꺼 둔 확장·확장 태스크 종류·`web`·`desktop` AI 환경을 보고 하트비트 `readiness`로 올린다. **점검이 실행을 막지 않고**(터진 것만 빼고 사유를 남긴다) 준비되지 않은 BPM 프로세스는 띄우지 않는다(`not_ready`)
- [x] 예제가 쓰는 모의 서비스 앱(ERP·디렉터리·신용·헬프데스크 등)을 `samples/`로 만든다 — `samples/mock_apps`: C11 앱 열셋은 `chk-mock-apps serve`의 **일꾼 하나**가 Center에서 가져가고, 외부 앱 둘(`ext-credit`·`ext-helpdesk`)은 `service_kit`을 쓰지 않아 어댑터 일꾼이 부른다. 거짓 데이터의 값은 케이스가 정하고 시험이 예제의 DMN을 실제로 돌려 대조한다. 부르는 예제가 없는 앱은 두지 않는다
- [x] **인수 시험:** 업무 예제 M5 묶음 통과, PC 예제는 Center 배포 → PC 실행기 실행으로 다시 통과 — **19개** (`tests/test_m5_acceptance.py`), **BX-33은 일부러 실패하는 교육 예제**라 그 의도한 실패를 따로 본다 ([ADR-0039](decisions/0039-optional-variables-and-b11.md)). 모의 앱은 진짜 소켓에 뜨고 일꾼이 Center에서 일감을 가져가며, 외부 확장 둘은 서명 봉투로 등록된다. BX-16은 PC 위임이라 결과를 케이스가 적는다(C14 `delegations`). **PC 예제 재통과**는 `tests/test_m5_pc_rerun.py`다 — 그림에서 읽은 PC 예제(지금은 FX-19 하나)가 승인·배포 → 하트비트 설치 → Center 작업 지시 → 진짜 실행 프로세스로 끝까지 돈다. 업무 값은 C3에 없어 결과가 맞는지는 Studio 시험 실행이 본다

## M6. 첫 릴리스 (지금)

> 상태: **진행 중.** 셋째(계약·화면이 코드와 맞는다)는 닫혔다. 첫째(시나리오 3)는 화면 조작이 있어야 하므로
> **UI 자동화를 다시 들일 때까지 멈춘다** ([ADR-0114](decisions/0114-remove-ui-automation.md)). 둘째는 **Windows 현장 PC와
> 사람의 시간**이 있어야 하고, M8 A의 설치 파일로 하면 개발 체크아웃을 세우지 않아도 된다
> (M8의 마지막 상자).

- [ ] **시나리오 3**(`00-vision`)이 Windows 현장 PC에서 Center 배포를 거쳐 통과 — **1·2·4는 서버 BPM 프로세스**(BX-10·BX-20·BX-30)이라 M7 인수 시험이 덮는다 ([ADR-0055](decisions/0055-m6-field-scenario-is-scenario-3.md)). 시나리오 3의 예제(BX-04)는 UI 자동화와 함께 걷었다 — 다시 들일 때 예제와 이 기준을 함께 되살린다 ([ADR-0114](decisions/0114-remove-ui-automation.md))
- [ ] 새 개발자가 `04-setup`만 보고 1시간 안에 환경 구성 (실제로 한 번 해 본다) — **Windows 11에서 문서만 따라 해 23분쯤** 걸렸다 ([04-setup §8 실행 기록](04-setup.md)). 따라 한 것이 사람이 아니라 Claude라 **사람이 한 번 더** 해 봐야 닫는다
- [x] 계약 문서 상태가 "구현됨", 모든 화면이 `06-screens`와 일치 — 계약 **열다섯이 모두 「구현됨」**이다(상태 셋의 뜻은 [03-contracts/README](03-contracts/README.md) §상태). 화면 문서가 약속한 것은 돈다 — 대조 기록과 조건이 서야 생기는 자리는 [09-gaps](09-gaps.md)에 있다

## M7. 서버 실행

> 상태: **끝.** 업무 대부분이 서버 BPM 프로세스로 돈다 (서버 우선,
> [ADR-0016](decisions/0016-server-first.md)). 모양은 결정 셋이 정했다 — 상태 저장·재개와 동시
> 실행 [ADR-0054](decisions/0054-server-run-state-and-concurrency.md), PC 위임
> [ADR-0062](decisions/0062-pc-delegation.md), 서버의 확장 태스크
> [ADR-0064](decisions/0064-extension-tasks-on-the-server.md).

- **상태 저장·재개와 동시 실행** (스파이크 [s10](../spikes/s10-server-runner-state/NOTES.md) → ADR-0054): 기다리는 실행은 `Run`을 **JSON 한 덩이로** 담아(`core.run_snapshot` — 칸을 셋으로 가르고 칸이 늘면 시험이 묻는다) 실행기의 SQLite(`server_runner/store.py`)에 넣고 자리를 놓는다. 실행 하나는 **스레드 하나**다. 기록은 파일에서 줄과 보낸 자리를 함께 읽어 되살린다
- [x] 서버 실행기가 Center API 키(서버 실행기용)로 등록·하트비트 (C12, CON-11) — `apps/server_runner`. 키는 요청 코드를 관리자가 CON-12 「승인 대기」에서 승인하면 Center가 봉해 내려 준다 ([ADR-0092](decisions/0092-keys-are-issued-and-delivered-by-center.md)). 키 묶기는 C4와 한 코드(`center/host_keys.py`)이고, 「유실 처리」는 오프라인인 실행기만이다(409 `runner_online`)
- [x] 실행 위치 「서버」 BPM 프로세스를 서버 실행기에 배포하고, 작업 여러 건이 동시에 돈다 (상한 초과는 Center 대기열) — 설치·`RunEnv`·패키지 읽기·바깥 앱 명부는 **PC 실행기와 같은 코드**다(`core.packages`·`core.deploy`·`core.run_env`·`core.app_directory`). 작업은 `free_slots()`·`pick_jobs()`로 **빈자리만큼만** 싣고 BPM 프로세스별 상한에 걸린 것은 건너뛴다. 기록은 하트비트 **뒤에** 보낸다
- [x] 결재를 기다리는 실행이 상태를 저장하고 일꾼을 놓았다가, 결재함 답으로 이어 간다. 서버 실행기를 재시작해도 이어 간다 — 결재 답·메시지(C12 §메시지)·타이머(`wake_due()`, [ADR-0061](decisions/0061-waking-runs-whose-timer-is-due.md))·위임 결과·긴 외부 작업([ADR-0103](decisions/0103-long-external-tasks.md))이 깨운다. 「이미 봤다」는 `core.seen`이고([ADR-0056](decisions/0056-bounded-seen-maps.md)·[ADR-0057](decisions/0057-shared-seen-map.md)) 빨아들인 메시지는 스냅샷과 한 커밋에 적는다([ADR-0058](decisions/0058-absorbed-messages-travel-with-the-snapshot.md)). 기다림은 C3 `run_waiting`·`run_resumed`로 실행 기록에도 남는다. 도는 서버 실행은 Center에서 취소할 수 있다 ([ADR-0063](decisions/0063-stopping-a-running-server-run.md))
- [x] PC 위임: 서버 BPM 프로세스의 Call Activity가 **배포된 PC BPM 프로세스**을 부르면 PC 실행기에서 실행되고 결과로 이어 감 — ADR-0062의 「증명할 다섯」이 다 찼다. 그림은 `chk:call.delegate`, 엔진은 네 번째 기다림(`WAIT_DELEGATION`), 실행기는 `CenterDelegator`, Center는 배포된·활성인·대기열이 짧은 PC를 고르고(`center/api/delegations.py`), 결과는 PC의 작업 ack `outputs`로 올라온다. Studio 시험 실행은 케이스의 `delegations`로 끝낸다(`CaseDelegator`). **PC 실행기는 일부러 꽂지 않는다**. 업무 예제 BX-16이 FX-19를 맡긴다
- **서버의 확장 태스크** (ADR-0064): `run_locations`에 `server`를 적은 종류만 수행기를 낸다. 적지 않은 것은 사전 점검이 시작 전에 막는다(`task_types_wrong_location`)
- [x] 콘솔 「서버 실행」(CON-12)에서 실행 중·기다리는 실행·대기열을 본다 — 목록(`/server-runners`)과 상세(`/server-runners/<id>`)다. 「실행 중」·「기다리는 실행」·「BPM 프로세스별 상한」은 실행기 하나의 것이라 상세에, 「대기열」은 목록 쪽에 있다
- [x] **인수 시험:** 실행 위치 서버인 업무·기능 예제 전부가 서버 실행기에서 통과 — `tests/test_m7_server_rerun.py`가 실행 위치 `server`인 예제 **47개를 그림에서 읽어** 배포·설치는 전부 보고, 끝까지 도는 것은 **묶음 44개 + 전용 시험 둘**이다(`ELSEWHERE` — BX-16은 PC 위임, FX-24는 일괄 기동이라 발판이 더 필요하다). **BX-33은 일부러 실패하는** 교육 예제라(ADR-0039) 의도한 실패를 따로 본다. 갈래 셋을 합쳐 47개와 맞춰 보므로 조용히 빠지는 일이 없다. 결재는 Center 결재함(C6), 메시지는 Center 메시지 API(C12)에 넣는다. BX-03(며칠 대기)은 `tests/test_server_runner_resume.py`가 재시작을 끼워 넣어 보고, 시나리오 1·2·4(BX-10·BX-20·BX-30)가 여기 든다 ([ADR-0055](decisions/0055-m6-field-scenario-is-scenario-3.md))

## M8. 건넬 수 있게, 고칠 수 있게

> 상태: **진행 중** — 코드로 할 것은 다 했다. 남은 둘은 **현장 PC에서 사람이** 한다(설치한 PC 실행기의
> 자동 시작 확인, 설치 파일로 M6의 「1시간 환경 구성」 다시 하기). 거리 둘을 **A → B 순서**로 두었다.

**A. Windows 설치 파일** — 묶는 방법은 [ADR-0024](decisions/0024-desktop-packaging-extensions.md)가
정했고 `core`가 PyInstaller 훅까지 준다(빌드 인자를 적지 않는다). 제품 쪽 빌드는 `packaging/build.py`다.

- [x] 제품 쪽 빌드 하나로 Studio·PC 실행기 실행 파일이 나온다 (깔린 확장·`extension.json`이 함께 들어간다 — S5가 본 것) — **된다** (`packaging/build.py`, 조각 1): PyInstaller onedir 둘, **확장 인자 0개**(`core`의 훅이 엔트리 포인트를 훑는다 — 지금은 깔린 확장이 없어 `--selftest`가 확장 0개를 정상으로 본다, ADR-0114), Windows에서만 매니페스트(DPI Per-Monitor v2). 개발 PC(Linux aarch64)에서 PC 실행기 356MB·62초, Studio 1008MB·81초
- [x] CI가 **Windows 산출물을 만든다** — `.github/workflows/desktop.yml`(「데스크톱 산출물」)이 **수동 실행·`v*` 태그에만** 돈다 (푸시마다 묶지 않는다). Windows·Linux 둘을 묶고 `--selftest`로 검사한 뒤 산출물을 올린다. **Windows 묶음을 정말 확인했다** (런 38873092925 — PC 실행기 160MB·86초, Studio 598MB·109초, 셀프테스트 통과). 그 전에 **Windows 전용 흠 둘**이 드러났다: 빌드 자신의 한글 `print`, 그리고 **PyInstaller 자식 안**의 훅이 찍는 한글 — 둘 다 이제 Linux에서 잡히는 시험이 막는다
- [x] **설치 파일이 나온다** — **된다** ([ADR-0068](decisions/0068-installer-inno-setup-per-user.md)): Inno Setup, **사용자별**(관리자 권한 없이 `%LOCALAPPDATA%\Programs\Chaeksas\<앱>`), Studio·PC 실행기 둘, 서명 없음. 스크립트는 `packaging/installer/chaeksas.iss` 하나이고 앱마다 다른 값은 `build.py --installer`가 넘긴다. 덮어쓸 때 옛 `_internal`을 먼저 지운다. **산출물 워크플로가 조용히 설치 → 설치된 앱으로 `--selftest`(판·확장) → 조용히 제거까지 해 본다** — 첫 시도에 통과했다 (런 39004329132): 설치 파일 **PC 실행기 63MB·Studio 205MB**, 설치 → 검사 → 제거 7.8초·16.7초. Inno Setup은 러너에 이미 있었다
- [ ] 설치한 PC 실행기가 **자동 시작**으로 뜬다 — 거는 것은 앱(BUI-03 토글 → 작업 스케줄러)이고 설치 파일은 **제거할 때 지운다**(`autostart.TASK_NAME`). 설치한 실행 파일 자리로 등록되는지는 **현장 PC에서** 본다 (사람 몫과 함께)
- [x] **「판 올리기」를 정한다** — **정했다** ([ADR-0069](decisions/0069-upgrading-by-reinstall.md)): **사람이 설치 파일로 다시 깐다**(Studio·PC 실행기). Center는 PC마다 판을 보여 줄 뿐 프로그램을 내려 주지 않고, 그래서 서명 봉투도 두지 않는다. 언제(도는 BPM 프로세스·대기열이 빈 때 — CON-03 「비활성화」로 만든다)와 실패 때 되돌리기(옛 설치 파일)는 사람이 정한다. 순서는 `docs/04-setup.md` §6-3
- [x] 산출물에 **판이 찍혀** 있고 C4·C12 `versions`가 그것을 올린다 — **된다** ([ADR-0067](decisions/0067-build-stamp.md)): 판은 **빌드가 정한다**(`--version` > `v*` 태그 > `<core 판>+g<커밋>[.dirty]`)이고 실행 파일 옆 `chaeksas-build.json`에 찍혀 `core.build_info`가 읽는다. C4 `versions.build`(`{commit, built_at}`)가 있으면 묶은 것, 없으면 체크아웃이다 — CON-03이 그것을 보인다. **고치다가 흠 둘이 드러났다**: 묶은 PC 실행기가 `bot_ui`·`core`를 `0.0.0`으로 올리고 있었고(dist-info가 안 들어갔다), 서버 실행기는 판이 코드에 적혀 있었다. 빌드가 **되읽어** 판과 `core`의 판을 확인한다
- [ ] 사람이 그 설치 파일로 **현장 PC에 넣어** M6의 「1시간 환경 구성」을 다시 해 본다 (시나리오 3은 UI 자동화를 다시 들인 뒤)

**B. 저장소 옮기기 수단** — Center 저장소의 표·열을 고치는 길은 `center/migrations.py` 하나다
([ADR-0065](decisions/0065-center-schema-migrations.md)).

- [x] 저장소에 **판 번호**가 있고, 뜰 때 필요한 옮기기 단계를 돌린다 (뒤로 가는 길은 두지 않는다 — 결정으로 적는다) — **된다** ([ADR-0065](decisions/0065-center-schema-migrations.md), `center/migrations.py`): 오늘의 `SCHEMA`가 **1판 기준선이고 얼었다**(SQL의 지문을 시험이 지킨다 — 주석은 고쳐도 된다). 판 표가 없는 옛 DB는 기준선을 `IF NOT EXISTS`로 다시 돌려 1판으로 적는다(오늘 하던 일 그대로 — 새 DB와 같은 길이다). **DB 판이 코드보다 높으면 뜨지 않는다**
- [x] 옮기기가 **멱등이고 중간에 죽어도 안전하다** (한 걸음씩, 한 트랜잭션에) — **된다**: 단계의 문과 판 기록이 **한 트랜잭션**이고(`BEGIN IMMEDIATE` — 파이썬 `sqlite3`는 DDL 앞에서 트랜잭션을 열지 않아 우리가 적는다, `executescript`는 먼저 커밋해 버려 쓰지 않는다) **잠금을 잡은 뒤 판을 다시 읽어** 넷이 동시에 떠도 한 번만 옮긴다. 그 시험이 **이 결정 전부터 있던 흠**을 잡았다 — 동시에 뜨면 `PRAGMA journal_mode=WAL`에서 한쪽이 기다리지 않고 죽었다(이미 WAL이면 바꾸지 않고 잠겼으면 다시 한다)
- [x] 미뤄 둔 빚 하나를 **실제로 고쳐** 수단이 도는 것을 보인다 — **2판이 `deployment_results.bot_ui_id` → `host_id`**다 (그 칸은 PC와 서버 실행기를 함께 담는데 이름을 못 고쳐 부르는 쪽이 바꿔 부르고 있었다). **데이터가 든 옛 DB를 옮기는 것**까지 시험이 본다(새로 만든 DB와 옮긴 DB의 표·열이 같다)
- [x] **키 묶기를 DB도 지킨다** ([ADR-0066](decisions/0066-migration-guards.md), 3판) — `bot_uis`·`server_runners`의 `key_id`·`machine_id`에 UNIQUE 넷. 겹친 옛 행(2026-10-08 전에 생길 수 있었다)은 **짐작해 고치지 않는다**(#57) — 단계의 **지킴 질의**가 걸리면 문을 하나도 돌리지 않고 무엇이 겹쳤는지와 고치는 길을 말한다. 고르는 것은 사람이고 `chk-center hosts duplicates`·`retire <id>`가 **옮기기를 돌리지 않고** DB를 연다(은퇴는 지우지 않는다 — 이력이 그 id를 가리킨다). 판정은 그대로 `host_keys.py`에 있다(사람에게 할 말은 그쪽이 안다)
- [x] **CON-06 「내려받은 횟수」** — **된다** (4판, C5 `download_count`·`last_downloaded_at`): 계약과 화면을 먼저 고치고 열 둘을 더했다. **관문을 지나 파일을 내어 줄 때만** 센다(막힌 요청은 세지 않는다)
- [x] PostgreSQL 전환은 **그다음이고 이 단계에서 정한다** — **정했다** ([ADR-0070](decisions/0070-center-stays-on-sqlite.md)): **옮기지 않는다** — Center는 SQLite로 남고, 옮길 조건 셋(Center 여러 대·쓰기 잠금 관측·회사 요구)을 적었다. 옮기기 수단은 둘을 받을 수 있게 **SQL을 이식할 모양으로만** 적고 그것을 `tests/test_center_sql_portable.py`가 지킨다(실제 PostgreSQL에서 돌려 보지는 않는다). 백업은 `docs/04-setup.md` §6-4

**선행은 M7이다.** 다만 A는 **M6의 사람 몫 둘을 쉽게 만든다** — 현장 PC에 개발 체크아웃을
세우지 않아도 되므로, 순서상 M6보다 늦지만 **M6를 돕는다**.


## M9. 바깥 기능은 Pull로

> 상태: **끝났다** — 조각 1~6과 옛 키 칸 걷기 (긴 작업은 [ADR-0103](decisions/0103-long-external-tasks.md), [ADR-0102](decisions/0102-calling-outside-is-pull.md), 계약 [C15](03-contracts/C15-external-tasks.md) 구현됨) — Center가 일감을 받고 일꾼을 들이며, 부르는 쪽(서버 실행기·실행 프로세스·Studio)과 일꾼(서비스 앱·모의 앱·어댑터 일꾼)이 붙었다. 옛 Push 길은 걷었다. 그림·매니페스트의 키 참조 칸(C14 `key_ref`·`service_keys`, C1 `key_ref`·`task_key_refs`·R4)도 걷었다.
> BPM 프로세스가 네트워크 건너 바깥 기능을 부르는 길을 모두 Center의 외부 작업으로 바꾼다 — 부르는 쪽은 올리고
> 기다리고, 일꾼이 가져가 끝낸다. Center 콘솔에서 바깥 기능의 주소·키를 넣는 칸이 없어지는 것이 끝이다.
> 한 조각이 끝날 때마다 옛 길을 **그 조각에서 걷는다** (두 길을 나란히 두지 않는다).

- [x] 조각 1 — **C15 합의**: 계약 모델(`contracts.external_task`), Center 외부 작업 표(15판)·API·롱폴링(새 일감·끝내기가 종을 울린다, 상한 200), 일꾼 승인(요청 코드 → 토큰을 봉해 내려 준다, 토픽은 승인할 때) — `tests/test_center_external_tasks.py`
- [x] 조각 2 — **서비스 앱**: `service_kit` 가져가기 루프, 모의 앱 13개, 부르는 쪽 셋(서버 실행기·실행 프로세스·Studio)의 `ServiceCaller`. C11 `/v1/ops`·서비스 앱 키 배달(ADR-0094)을 걷는다. M3·M5·M7 묶음이 초록 — **됐다**: `service_kit.consumer`(`Consumer`·`Enrollment`·`TokenFile`), `chk-mock-apps serve`가 열셋을 일꾼 하나로, 부르는 쪽은 `core.services.CenterServiceCaller` 하나(실행 프로세스는 PC 실행기가 청한 호출 토큰 — `POST /call-tokens`). 서비스 앱 키·Studio 개발 키·BUI-05 키 알림·사전 점검의 키 점검을 걷었다 — `tests/test_service_kit_consumer.py`·`test_c15_round_trip.py`
- [x] 조각 3 — **어댑터 일꾼** (`chk-adapter-consumer`): 외부 앱 둘(모의), Center의 외부 앱 키·외부 확장 주소 덮어쓰기를 걷는다 — **됐다**: `apps/adapter_consumer`, 주소·키는 `CHK_ADAPTER__EXT__<확장>__*`에만, 사설망은 `CHK_ADAPTER__ALLOW_PRIVATE_NETWORK`로 연다 — `tests/test_adapter_consumer.py`
- [x] 조각 4 — **UI 자동화**: 그 확장의 계획·치유·보고·등록을 외부 작업으로 옮겼다 — 확장은 뒤에 [ADR-0114](decisions/0114-remove-ui-automation.md)로 걷었다
- [x] 조각 5 — **화면**: CON-07(주소·키 칸 → 일꾼 승인·토픽 상태), STU-10 — 화면 문서를 먼저 고친다 — **된다**: CON-07은 기능 목록·일꾼 승인 대기·토픽 표, STU-10에 서비스 앱 키 칸이 없고, CON-02의 「서비스 앱 키 참조」 열도 걷었다
- [x] 조각 6 — **긴 작업**: 서버 실행기가 외부 작업을 기다리는 동안 스레드를 놓는다 (다섯째 기다림) — **돈다** ([ADR-0103](decisions/0103-long-external-tasks.md)): 한 번 기다려 끝나지 않으면 `external_task`로 멈추고 결과는 하트비트 주기마다 묻는다. M7 묶음이 서비스 호출 예제 넷을 **모든 호출을 넘긴 채로** 끝까지 돌린다
- [x] 옛 키 칸 — C14 `chk:serviceCall.key_ref`·`chk:process.service_keys`, C1 `requires.service_apps[].key_ref`·`task_key_refs`·R4를 걷었다. 예제 생성기가 더 적지 않고(`key_ref`를 적으면 거부한다), 옛 파일은 모르는 칸으로 읽어 **B7이 경고 한 줄**로 말한다. 판은 올리지 않았다(선택 칸 — 원칙 3) — `tests/test_contracts_bpmn_ext.py`·`test_contracts.py`

## 나중에 (범위 밖, 기록만)

UI 자동화 확장 다시 들이기([ADR-0114](decisions/0114-remove-ui-automation.md) — M4 자리), 서버 실행의 헤드리스 웹 조작, OIDC 로그인, LLM 비용 집계, 실행 기록 보존 정책, 무인 실행(Windows 서비스 모드, S4 결과에 따라), 멀티 테넌시.

**PostgreSQL 전환은 M8에서 「옮기지 않는다」로 정했다** ([ADR-0070](decisions/0070-center-stays-on-sqlite.md) — 옮길 조건 셋을 적어 두었다).
**헤드리스 웹 조작은 더 멀어졌다** — [ADR-0064](decisions/0064-extension-tasks-on-the-server.md)가
「서버는 로컬 런타임을 띄우지 않는다」로 정했으므로, 열려면 **사이드카 같은 새 결정**부터
필요하다. 그 수요는 **PC 위임**(ADR-0062)이 받고 있다.
