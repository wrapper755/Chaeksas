# 02. 용어집

**규칙: 용어 하나에 뜻 하나.** 새 용어는 코드에 쓰기 전에 여기 먼저 추가한다.
- "화면 표기"는 사용자에게 보이는 말, "코드"는 식별자·파일 이름에 쓰는 영어 이름이다.
- 프로토타입 저장소를 읽을 때의 대응 관계는 [reference/README.md](reference/README.md)의 대응표 한 곳에만 둔다. 이 문서에는 프로토타입 이름을 쓰지 않는다.

## 0. 가장 먼저: 프로세스와 화면을 구별한다 ([ADR-0012](decisions/0012-bot-ui.md))

| 쓰는 말 | 가리키는 것 | 예 |
| --- | --- | --- |
| **BPM 프로세스** / **Bot** | 업무 흐름 (BPMN으로 그린 것). 설계 화면에서는 "BPM 프로세스", 운영 화면에서는 "Bot". 같은 것이다 | 세금계산서 발행 Bot |
| **<이름> 프로세스** | 프로그램이 도는 단위 (OS 프로세스, 화면 없음) | Worker 프로세스, 실행기 프로세스 |
| **<이름> UI**, 앱 이름 | 사람이 보는 프로그램 (화면 있음) | Bot UI, Studio, Center 콘솔 |

"프로세스"를 단독으로 쓰지 않는다.

## 1. 구성요소

| 화면 표기 | 코드 | 종류 | 뜻 |
| --- | --- | --- | --- |
| Studio | `studio` | 화면 | 설계자가 BPM 프로세스를 그리고, 시험 실행(자율 수행·재생)·학습·패키지 빌드를 하는 데스크톱 앱 |
| **Bot UI** | `bot_ui` | 화면 (트레이 GUI) | **항상 떠 있는 트레이 기반 GUI 프로그램.** PC 한 대에 하나, Center에 등록되는 단위. ① Bot 다운로드 및 실행 ② 확장의 로컬 런타임(Worker 프로세스 등) 실행 관리 ③ 확장이 더한 유틸리티(기본 제공: UI 셀렉터 등록) |
| **Bot** | `bot` | 업무 | **Center에서 Bot UI로 전달되어 실행되는 BPM 프로세스.** 실행 중인 Bot이 Worker·서비스 앱·Center를 부른다 |
| **Worker** | `worker` | 프로세스 (서버, 화면 없음) | **127.0.0.1의 REST API 서버.** Bot UI가 시작·감시·재시작·종료한다. 실행 중인 Bot(과 Studio 개발 실행)의 UI 자동화 요청을 받아 등록된 화면 요소를 로케이터 사다리로 조작하고, 실패하면 치유를 요청한다 |
| 실행기 | `runner` | 프로세스 | 실행 중인 Bot 하나를 맡는 Bot UI의 자식 프로세스. **동시에 하나만** 있다 (격리용: Bot이 죽어도 Bot UI는 산다). S4에서 확인 [ADR-0014](decisions/0014-one-bot-per-pc.md) |
| 서버 실행기 | `server_runner` | 프로세스 (서버, 화면 없음) | 실행 위치가 「서버」인 BPM 프로세스를 **여러 건 동시에** 실행한다. Center가 배포·작업·관리를 하고, 서버 실행기는 Center API 키로 Center에 접속한다 [ADR-0015](decisions/0015-run-location.md) |
| 실행 자리 | `run_slot` | 개념 | PC 한 대에서 Bot이 실행될 수 있는 자리. **하나뿐**이고, 결재·확인을 기다려도 Bot이 끝날 때까지 쥔다 [ADR-0014](decisions/0014-one-bot-per-pc.md) |
| 대기열 | `run_queue` | 개념 | 실행 자리가 차 있을 때 실행 요청(Center 작업, 수동, 감시 트리거, 일정, 메시지)이 기다리는 Bot UI의 목록. 들어온 순서, 기본 20건 |
| Center | `center` | 서버 | 패키지·Bot UI·배포·작업·결재·실행 이력·리소스·Center API 키를 관리 |
| Center 콘솔 | `console` | 화면 (웹) | Center의 웹 화면. 운영자·결재자가 쓴다 |
| Admin | `admin` | 도구 | 서명 키를 가지고 패키지 승인·배포에 서명 |
| **확장** | `extension` | 묶음 | **BPM 프로세스에 공통 기능을 더하는 묶음.** 확장 정의(C13 `extension.json`)로 태스크 종류·작업·Studio 편집기·Bot UI 유틸리티·로컬 런타임 등을 **기여**한다. 등급: 내장 / 사내 / 외부. 첫 내장 확장은 UI 자동화 [ADR-0018](decisions/0018-extensions.md) |
| 확장 정의 | `extension.json` | 파일 | 확장이 무엇을 더하는지 선언 (C13) |
| 기여 / 기여 지점 | `contributes` | 개념 | 확장이 플랫폼에 끼워 넣는 것 / 끼워 넣을 수 있는 자리 (VS Code의 contribution point와 같은 뜻) |
| 내장 확장 / 사내 확장 / 외부 확장 | `builtin` / `internal` / `external` | 등급 | 이 저장소에 있음 / 다른 사내 저장소 / 정의 파일만 (외부 앱). 외부 확장은 코드를 기여할 수 없다 |
| 외부 앱 | `external app` | 서버 | 이 저장소·C11 밖의 서버 앱 (흔히 "외부 LLM 앱"이라 부르는 것). 외부 확장의 서버 부분으로, Admin 서명된 확장 정의의 HTTP 어댑터로만 붙는다 |
| HTTP 어댑터 | `http-adapter` | 개념 | C11을 따르지 않는 외부 앱을 템플릿만으로 부르는 방법 (C13 §4) |
| 로컬 런타임 | `local_runtime` | 프로세스 | 확장이 기여하고 Bot UI가 띄워 감시하는 로컬 프로세스. 예: Worker 프로세스 |
| 확장 호스트 | `extension_host` | 코드 | Studio·Bot UI·실행기·서버 실행기 안에서 확장을 찾아 기여를 등록하는 부분 (`core`) |
| 서비스 앱 | `service_app` | 서버 | **확장의 서버 부분. BPM 프로세스가 API 키로 호출하는 서버 앱** (대부분 LLM 앱). 자율·결정 수행 모드를 가진다. 앱마다 **관리 콘솔**이 있다. [ADR-0010](decisions/0010-service-apps.md), [ADR-0013](decisions/0013-api-keys.md) |
| 서비스 앱 관리 콘솔 | `svc_console` | 화면 (웹) | 서비스 앱마다 하나. 상태, API 키 발급·폐기, 사용 기록 (+ 앱 고유 화면) |
| UI 자동화 앱 | `ui-automation` | 서버 | 첫 내장 확장 「UI 자동화」의 서버 부분(시스템). 화면·요소·로케이터 레지스트리, 실행 계획, 치유 제안. Worker가 Bot·Studio를 대신해 호출 |
| 공통 계약 | `contracts` | 패키지 | 모든 구성요소가 주고받는 데이터 모델의 단일 원본 |

### 역할과 관계 (확정, 2026-10-01)

| 역할 | 누구 | 한 줄 |
| --- | --- | --- |
| 지도 | BPMN (BPM 프로세스 정의) | 순서·분기·결재를 정한다 |
| 운전사 | AI | 목표에 도달하는 방법을 찾는다 |
| 실행 | Bot UI가 Bot을 실행 (개발 중에는 Studio) | 태스크를 차례로 수행하며 운전사·손·서비스 앱을 부른다 |
| 손 | Worker 프로세스 | 실행 중인 Bot이 REST로 요청한 화면 조작만 한다 |

```
Bot UI (화면, 트레이, 항상 실행)                      ── 현장 PC / 설계자 PC
 ├─ 실행 ─▶ Bot = BPM 프로세스 (실행 중)
 │            ├─ AI 태스크        → AI(LLM)
 │            ├─ UI 태스크        → Worker 프로세스 (REST, 127.0.0.1)
 │            │                       └─ Worker → UI 자동화 앱 (서버)
 │            ├─ 서비스 앱 태스크  → 서비스 앱 (REST, 서비스 앱 API 키)
 │            └─ 결재              → Center
 ├─ 시작·감시 ─▶ Worker 프로세스
 └─ 유틸리티: UI 셀렉터 등록 ─▶ Worker API + UI 자동화 앱
Center ─(하트비트 응답: 배포·작업·결재 답)─▶ Bot UI   (Center API 키로 인증)
```

- Bot(BPM 프로세스)은 Worker를 띄우지 않는다. Worker 기동·종료는 Bot UI의 일이다.
- Worker는 업무를 모른다. "어느 화면의 어느 요소에 무엇을 하라"(시맨틱 키 + 동작)만 받는다.
- Studio의 개발 실행도 같은 PC의 Bot UI가 관리하는 Worker에 요청한다. 설계자 PC에도 Bot UI를 설치한다.

## 2. BPM 프로세스와 실행

| 화면 표기 | 코드 | 뜻 |
| --- | --- | --- |
| BPM 프로세스 (운영 화면: Bot) | `bpm_process` | **사용자가 만들고 배포하는 업무 단위.** 진입 정의와 하위 정의, 학습 자료(재생 명세), 시험 케이스, 서비스 앱 키 참조를 묶은 것 |
| 프로세스 정의 | `process_definition` | BPMN 2.0 파일 하나. BPM 프로세스 하나는 진입 정의 1개 + 하위 정의 0개 이상 |
| 실행 위치 | `run_location` | BPM 프로세스 속성. **서버**(`server`, **기본값**, 서버 우선 — [ADR-0016](decisions/0016-server-first.md)): / **PC**(`pc`: Bot UI에서 하나씩, 끝날 때까지 — UI 조작·현장 확인·PC 전용 자원이 필요할 때만) / 서버 쪽: 서버 실행기에서 동시 실행, 기다리는 동안 상태 저장). [ADR-0015](decisions/0015-run-location.md) |
| 서버 Bot | `server_bot` | 운영 화면에서 실행 위치가 「서버」인 BPM 프로세스를 부르는 이름 (확정). PC 쪽은 그냥 「Bot」 |
| PC 위임 | `pc_delegation` | 서버 Bot의 Call Activity가 실행 위치 「PC」인 BPM 프로세스를 부르는 것. Center 작업으로 Bot UI에 맡기고 서버 Bot은 상태를 저장하고 기다린다 (제안, [ADR-0016](decisions/0016-server-first.md) §3) |
| 동시 실행 상한 | `max_concurrency` | 서버 실행에만 있다. 서버 실행기 전체(기본 10) + BPM 프로세스별(배포 때, 기본 5) |
| 진입 정의 | `entry` | BPM 프로세스를 시작할 때 처음 실행하는 정의 |
| 공유 BPM 프로세스 | `process_lib` | 여러 BPM 프로세스가 Call Activity로 부르는 재사용 BPMN. 패키지에 복사되어 들어간다 |
| 툴팩 | `toolpack` | 코드 없이 선언한 도구 묶음(MCP 서버, HTTP 템플릿). 비밀은 이름만 |
| 패키지 | `package` | BPM 프로세스·공유 BPM 프로세스·툴팩을 담은 서명 가능한 zip. 종류(`kind`)를 가진다. **비밀(키 값)은 넣지 않는다** |
| 태스크 | `task` | BPMN 노드 하나 |
| 배포 | `deployment` | "이 Bot UI(또는 서버 실행기)에서 이 BPM 프로세스의 이 버전을 쓴다"는 Admin 서명 봉투. 서버 배포에는 동시 실행 상한이 들어간다 |
| 작업 | `job` | 배포된 Bot을 특정 입력으로 한 번 실행하라는 Center의 지시 |
| 실행 | `run` | Bot 실행 한 번. `run_id`로 식별 |
| 실행 이벤트 | `run_event` | 실행 중 일어난 일 하나. `(run_id, seq)`가 멱등 키 |
| 시험 케이스 | `case` | 입력 + 기대 결과 + 결재 자동 응답. Studio 시험 실행의 판정 기준 |
| 사전 점검 | `preflight` | 실행 전에 각 노드를 ok / warning / blocked로 판정 (서비스 앱 키 참조가 이 PC에 있는지도 포함) |
| 재생 | `replay` | 성공한 AI 태스크의 도구 순서를 LLM 없이 다시 실행 (결정 수행의 한 형태) |
| 자율 수행 | `autonomous` | 수행 모드. AI가 방법을 찾아 수행하고 결과를 학습 자료로 남긴다. **Studio에서 개발 목적으로 실행할 때** |
| 결정 수행 | `deterministic` | 수행 모드. 학습·등록된 대로 LLM 없이(또는 최소로) 수행한다. **Bot UI에서 Bot을 운영 실행할 때**, Studio의 재생 실행 |

### 태스크 종류

| 화면 표기 | 코드 | BPMN 요소 | 누가 수행 |
| --- | --- | --- | --- |
| AI 태스크 | `ai_task` | ServiceTask | AI(LLM). 목표·허용 도구·결과 필드 |
| UI 태스크 | `ui_task` | ServiceTask | Worker 프로세스 (REST 요청). 화면 + 시맨틱 키 + 동작 목록 |
| 서비스 앱 태스크 | `service_task` | ServiceTask | 서비스 앱. 앱 + 작업 + 입력·출력 매핑 (키는 BPM 프로세스의 키 참조를 상속) |
| 결재 | `approval` | UserTask | 사람 (Center 또는 현장 PC) |
| 스크립트·규칙·메일·웹훅 | — | ScriptTask, BusinessRuleTask(DMN), SendTask, ReceiveTask | 실행 엔진 내장 |

## 3. 사람 개입

| 화면 표기 | 코드 | 뜻 |
| --- | --- | --- |
| 결재 (업무 개입) | `approval` | BPMN UserTask. 업무상 사람이 결정해야 하는 것. Center로 올려 다른 사람이 답할 수 있다 |
| 확인 (실행 개입) | `confirmation` | 실행 중 막힘(OTP, 애매한 클릭, Worker 응답 없음). 화면 앞 사람만 답할 수 있어 Center로 올리지 않는다 |
| 전환 | `escalation` | 자동 치유가 한도를 넘어 사람에게 넘기는 것. 확인으로 이어진다 |

## 4. UI 자동화

| 화면 표기 | 코드 | 뜻 |
| --- | --- | --- |
| 화면 | `page` | 자동화 대상 화면 하나. `page_id`로 식별, URL 패턴 또는 창 식별자를 가진다 |
| 요소 | `element` | 화면 안의 조작 대상. `page_id::semantic_key`로 식별 |
| 시맨틱 키 | `semantic_key` | 요소의 업무 이름 (`submit_button`). BPMN·AI는 셀렉터 대신 이것을 쓴다 |
| 로케이터 | `locator` | 요소를 찾는 방법 하나 (role, test_id, css, xpath, automation_id, class_name, control_name) |
| 사다리 | `ladder` | 한 요소의 로케이터들을 우선순위대로 늘어놓은 것. 앞에서부터 시도 |
| 동작 | `action` | 요소에 하는 일 8종: fill, click, press, read, read_table, read_options, read_selection, select |
| UI 셀렉터 등록 | `selector_registry` (기능) | UI 자동화 확장이 Bot UI에 기여하는 유틸리티 (기본 제공). 화면 요소를 담아 검증하고 UI 자동화 앱에 등록·삭제 |
| 치유 | `healing` | 사다리가 모두 실패했을 때 새 로케이터를 제안받아 로컬에서 검증하는 것 |
| 승격 | `promotion` | 치유된 로케이터가 연속 3회 성공해 `unverified` → `active`가 되는 것 |
| 인텐트 | `intent` | 자연어 지시 → 스텝 목록 해석 결과의 캐시 |
| UI 세션 | `ui_session` | UI 태스크 하나가 Worker에 연 브라우저·창 조작 묶음. 끝날 때 보고 한 건 |

## 5. 리소스 (Center가 목록으로 관리)

| 종류 | 코드 | 예 |
| --- | --- | --- |
| 확장 | `extension` | 확장 정의, 등급, 상태, 기여 요약. 서버 부분이 있으면 서비스 앱 항목과 이어짐 |
| 서비스 앱 | `service_app` | 주소·상태·작업 목록·관리 콘솔 주소 (키는 두지 않음) |
| UI 화면 | `ui_page` | UI 자동화 앱에 등록된 화면 |
| 툴팩 | `toolpack` | 사내 API 도구 묶음 |
| 런타임 | `runtime` | Bot UI가 가진 실행 능력 (Worker 버전, 브라우저, 데스크톱 백엔드) |

## 6. 키와 설정 ([ADR-0013](decisions/0013-api-keys.md))

| 화면 표기 | 코드 | 뜻 |
| --- | --- | --- |
| 연동용 키 | `integration_key` | Center API 키의 한 종류. 외부 시스템이 작업을 만들 때 쓴다 (C5) |
| Center API 키 | `center_api_key` | Center 콘솔에서 발급. **Bot UI 설정에 등록**해 Center 등록·하트비트·다운로드에 쓴다 (Studio용도 따로 발급). 키가 곧 그 Bot UI의 신원 |
| 서비스 앱 API 키 | `service_api_key` | **각 서비스 앱의 관리 콘솔에서 발급.** 허용 작업·허용 수행 모드·만료를 가진다. Center는 발급·저장하지 않는다 |
| 키 참조 | `key_ref` | BPM 프로세스 속성에 적는 키의 이름 (예: `finance-invoice`). 값은 Bot UI·Studio의 비밀 저장소에 있다 (확정, ADR-0013 §3) |
| 환경변수 접두사 | — | `CHK_` 하나. 중첩은 `__` (예: `CHK_CENTER__PORT`) |
| 포트 | — | 구성요소마다 기본값이 있고, 설정 파일 또는 환경변수로 바꾼다 ([04-setup.md](04-setup.md) §6) |

## 7. 쓰지 않는 말

| 말 | 이유 | 대신 |
| --- | --- | --- |
| 프로세스 (단독) | BPM 프로세스인지 OS 프로세스인지 모호 | BPM 프로세스 / Bot / <이름> 프로세스 |
| Bot (프로그램을 가리켜) | Bot은 업무(BPM 프로세스)다 | Bot UI |
| Worker 앱, Worker 창, Worker 트레이 | Worker는 화면이 없다 | Worker 프로세스. 화면 기능은 Bot UI의 「UI 셀렉터 등록」 |
| 직원, Employee, 에이전트(배포 단위로서) | 배포 단위는 BPM 프로세스(Bot)다 | BPM 프로세스 / Bot |
| 에이전트(화면에서) | LLM이 태스크를 수행하는 내부 구성만 뜻한다 | AI 태스크 |
| RPA 봇, BPM 봇 | 모호 | Bot |
| LLM 앱 (분류 이름으로) | 서비스 앱 중 LLM을 안 쓰는 것도 있다 | 서비스 앱 |
| 셀렉터 서버, UI 서버 | 서비스 앱 체계 밖의 이름 | UI 자동화 앱 |
| 플러그인, 애드온, 모듈(기능 묶음을 가리켜) | 한 개념에 한 단어 | 확장 |
| HITL (화면에서) | 두 층을 구분하지 못한다 | 결재 / 확인 |
| lease, dispatcher | 서버가 작업을 배분하던 옛 구조 | Center 작업(`job`) + UI 세션 |
| 대시보드 | 읽기 전용이던 옛 구조 | Center 콘솔 |
| 등록 토큰 | Center API 키로 바뀜 | Center API 키 |
