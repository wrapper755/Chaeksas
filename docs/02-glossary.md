# 02. 용어집

**규칙: 용어 하나에 뜻 하나.** 새 용어는 코드에 쓰기 전에 여기 먼저 추가한다.
- "화면 표기"는 사용자에게 보이는 말, "코드"는 식별자·파일 이름에 쓰는 영어 이름이다.
- 프로토타입 저장소를 읽을 때의 대응 관계는 [reference/README.md](reference/README.md)의 대응표 한 곳에만 둔다. 이 문서에는 프로토타입 이름을 쓰지 않는다.

## 0. 가장 먼저: 프로세스와 화면을 구별한다 ([ADR-0012](decisions/0012-bot-ui.md))

| 쓰는 말 | 가리키는 것 | 예 |
| --- | --- | --- |
| **BPM 프로세스** | 업무 흐름 (BPMN으로 그린 것). 설계 화면과 운영 화면이 **같은 이름**을 쓴다 (예전 운영 화면의 「Bot」, [ADR-0111](decisions/0111-bpm-process-and-pc-runner-names.md)) | 세금계산서 발행 BPM 프로세스 |
| **<이름> 프로세스** | 프로그램이 도는 단위 (OS 프로세스, 화면 없음) | 실행 프로세스 |
| **<이름> UI**, 앱 이름 | 사람이 보는 프로그램 (화면 있음) | PC 실행기, Studio, Center 콘솔 |

"프로세스"를 단독으로 쓰지 않는다. **예외 하나 — Center 콘솔의 화면 글**은 「프로세스」라고만 쓰고, PC 실행기를 **「Bot」**이라 부른다(프로그램 이름은 그대로 「PC 실행기」) ([ADR-0121](decisions/0121-center-console-says-process.md)). 그 화면에서 프로세스는 BPM 프로세스뿐이라 모호하지 않다. 문서·Studio·PC 실행기는 그대로 「BPM 프로세스」다.

## 1. 구성요소

| 화면 표기 | 코드 | 종류 | 뜻 |
| --- | --- | --- | --- |
| Studio | `studio` | 화면 | 설계자가 BPM 프로세스를 그리고, 시험 실행(자율 수행·재생)·학습·패키지 빌드를 하는 데스크톱 앱 |
| **PC 실행기** | `bot_ui` | 화면 (트레이 GUI) | **항상 떠 있는 트레이 기반 GUI 프로그램.** PC 한 대에 하나, Center에 등록되는 단위. BPM 프로세스를 내려받아 설치하고 하나씩 실행하며, 현장 결재·확인 창을 띄운다. 「도구」 메뉴에는 「확장...」(BUI-11)이 있다 |
| **데스크톱 앱** | — (묶는 말) | 화면 표기 | **사람이 PC에 깔아 쓰는 Chaeksas 프로그램을 묶어 부르는 말** — Studio(BPM 프로세스를 만든다)와 PC 실행기(BPM 프로세스를 돌린다). Center 콘솔에서는 줄여 「앱」이라 한다(CON-03 「앱」 — 두 프로그램의 등록 승인도 거기서 한다, [ADR-0121](decisions/0121-center-console-says-process.md)). 「PC」만으로는 사람이 무엇을 보는 화면인지 알기 어려워 이 말을 쓴다. 코드 식별자는 따로 두지 않는다(각각 `studio`·`bot_ui`) |
| (배포된) BPM 프로세스 | `bot` | 업무 | **Center에서 PC 실행기·서버 실행기로 전달되어 실행되는 BPM 프로세스.** 실행 중인 BPM 프로세스가 서비스 앱·Center를 부른다. 코드 식별자 `bot`·`bot_ui`는 옛 화면 이름(「Bot」·「Bot UI」)에서 왔고 **그대로 둔다** — 계약 칸·API 경로라 바꾸면 현장과 Center가 서로 못 알아본다 ([ADR-0111](decisions/0111-bpm-process-and-pc-runner-names.md)) |
| 실행 프로세스 | `runner` (`chk-bot-runner`) | 프로세스 | 실행 중인 BPM 프로세스 하나를 맡는 PC 실행기의 자식 프로세스. **동시에 하나만** 있다 (격리용: BPM 프로세스가 죽어도 PC 실행기는 산다). S4에서 확인 [ADR-0014](decisions/0014-one-bot-per-pc.md) |
| 서버 실행기 | `server_runner` | 프로세스 (서버, 화면 없음) | 실행 위치가 「서버」인 BPM 프로세스를 **여러 건 동시에** 실행한다. Center가 배포·작업·관리를 하고, 서버 실행기는 Center API 키로 Center에 접속한다 [ADR-0015](decisions/0015-run-location.md) |
| 실행 자리 | `run_slot` | 개념 | PC 한 대에서 BPM 프로세스가 실행될 수 있는 자리. **하나뿐**이고, 결재·확인을 기다려도 BPM 프로세스가 끝날 때까지 쥔다 [ADR-0014](decisions/0014-one-bot-per-pc.md) |
| 대기열 | `run_queue` | 개념 | 실행 자리가 차 있을 때 실행 요청(Center 작업, 수동, 감시 트리거, 일정, 메시지)이 기다리는 PC 실행기의 목록. 들어온 순서, 기본 20건 |
| Center | `center` | 서버 | 패키지·PC 실행기·배포·작업·결재·실행 이력·리소스·Center API 키를 관리 |
| Center 콘솔 | `console` | 화면 (웹) | Center의 웹 화면. 운영자·결재자가 쓴다 |
| 관리자 계정 | `account` | Center | Center 콘솔에 들어오는 아이디·비밀번호. 역할은 「관리자」(승인·배포까지 쓰기 전부)·「보기 전용」. 지우지 않고 멈춘다 [ADR-0090](decisions/0090-center-admin-accounts.md) |
| Center 서명 키 | `signing key` | Center | 승인·배포·외부 확장 봉투에 Center가 대신 서명하는 키. DB에 있고 공개키는 믿는 키 목록(`admin_keys`)으로 현장에 내려간다 [ADR-0090](decisions/0090-center-admin-accounts.md) |
| **확장** | `extension` | 묶음 | **BPM 프로세스에 공통 기능을 더하는 묶음.** 확장 정의(C13 `extension.json`)로 태스크 종류·작업·Studio 편집기 등을 **기여**한다. 등급: 내장 / 사내 / 외부. **지금 깔린 내장 확장은 없다** ([ADR-0018](decisions/0018-extensions.md), [ADR-0114](decisions/0114-remove-ui-automation.md)) |
| 확장 정의 | `extension.json` | 파일 | 확장이 무엇을 더하는지 선언 (C13) |
| 일꾼 폴더 | `consumers_dir` | Center | Center가 **뜰 때** 읽는 폴더. `<이름>.consumer.json`(이름·토픽·토큰 해시, C15 `FolderConsumer`)으로 일꾼을 들인다 — **일꾼이 들어오는 유일한 길**이고 요청 코드·승인이 없다. `CHK_CENTER__CONSUMERS_DIR`(기본 `<데이터>/consumers`). **폴더가 원본이다** — 빼면 거둔다 ([ADR-0122](decisions/0122-consumer-folder.md)). 같은 폴더의 `<이름>.key.json`(C7 `FolderKey`)은 연동용·대리 답용 키다 ([ADR-0123](decisions/0123-folder-keys.md)) |
| 기여 / 기여 지점 | `contributes` | 개념 | 확장이 플랫폼에 끼워 넣는 것 / 끼워 넣을 수 있는 자리 (VS Code의 contribution point와 같은 뜻) |
| 내장 확장 / 사내 확장 / 외부 확장 | `builtin` / `internal` / `external` | 등급 | 이 저장소에 있음 / 다른 사내 저장소 / 정의 파일만 (외부 앱). 외부 확장은 코드를 기여할 수 없다 |
| 외부 앱 | `external app` | 서버 | 이 저장소·C11 밖의 서버 앱 (흔히 "외부 LLM 앱"이라 부르는 것). 외부 확장의 서버 부분으로, 관리자가 등록한(Center가 서명한) 확장 정의의 HTTP 어댑터로만 붙는다 |
| HTTP 어댑터 | `http-adapter` | 개념 | C11을 따르지 않는 외부 앱을 템플릿만으로 부르는 방법 (C13 §4) |
| 확장 호스트 | `extension_host` | 코드 | Studio·PC 실행기·실행 프로세스·서버 실행기·어댑터 일꾼 안에서 확장을 찾아 기여를 등록하는 부분 (`core`) |
| 서비스 앱 | `service_app` | 서버 | **확장의 서버 부분. BPM 프로세스가 Center의 외부 작업으로 부르는 서버 앱** (대부분 LLM 앱). 자율·결정 수행 모드를 가진다. 앱마다 **관리 콘솔**이 있다. [ADR-0010](decisions/0010-service-apps.md), [ADR-0013](decisions/0013-api-keys.md) |
| 서비스 앱 관리 콘솔 | `svc_console` | 화면 (웹) | 서비스 앱마다 하나. 상태, API 키 발급·폐기, 사용 기록 (+ 앱 고유 화면) |
| 공통 계약 | `contracts` | 패키지 | 모든 구성요소가 주고받는 데이터 모델의 단일 원본 |
| 모의 앱 | `mock app` | 개발·시험용 | **업무 예제가 부르는 서비스 앱·외부 앱의 거짓 구현** (`samples/mock_apps`). 제품이 아니고, 답하는 값은 예제 케이스가 정한다. 개발 PC·시험망에서만 띄운다 ([samples/README.md](../samples/README.md)) |

### 역할과 관계 (확정, 2026-10-01)

| 역할 | 누구 | 한 줄 |
| --- | --- | --- |
| 지도 | BPMN (BPM 프로세스 정의) | 순서·분기·결재를 정한다 |
| 운전사 | AI | 목표에 도달하는 방법을 찾는다 |
| 실행 | 서버 실행기·PC 실행기가 BPM 프로세스를 실행 (개발 중에는 Studio) | 태스크를 차례로 수행하며 운전사·손·서비스 앱을 부른다 |
| 손 | 확장이 주는 결정적 수행기 (지금 없음) | 요청받은 일을 정해진 대로만 한다 |

```
PC 실행기 (화면, 트레이, 항상 실행)                      ── 현장 PC / 설계자 PC
 └─ 실행 ─▶ 실행 프로세스 (BPM 프로세스 하나)
              ├─ AI 태스크        → AI(LLM)
              ├─ 서비스 앱 태스크  → Center 외부 작업 (호출 토큰) ← 서비스 앱·어댑터 일꾼
              └─ 결재·확인          → Center 또는 현장 결재 창
Center ─(하트비트 응답: 배포·작업·결재 답)─▶ PC 실행기   (Center API 키로 인증)
```

- 「손」을 주는 확장은 지금 깔려 있지 않다 — 화면 조작(UI 자동화 확장)은 걷었고 다시 들인다 ([ADR-0114](decisions/0114-remove-ui-automation.md)).

## 2. BPM 프로세스와 실행

| 화면 표기 | 코드 | 뜻 |
| --- | --- | --- |
| BPM 프로세스 | `bpm_process` | **사용자가 만들고 배포하는 업무 단위.** 진입 정의와 하위 정의, 학습 자료(재생 명세), 시험 케이스를 묶은 것 |
| 프로세스 정의 | `process_definition` | BPMN 2.0 파일 하나. BPM 프로세스 하나는 진입 정의 1개 + 하위 정의 0개 이상 |
| 실행 위치 | `run_location` | BPM 프로세스 속성. **서버**(`server`, **기본값**, 서버 우선 — [ADR-0016](decisions/0016-server-first.md)): / **PC**(`pc`: PC 실행기에서 하나씩, 끝날 때까지 — 현장 확인·PC 전용 자원이 필요할 때만) / 서버 쪽: 서버 실행기에서 동시 실행, 기다리는 동안 상태 저장). [ADR-0015](decisions/0015-run-location.md) |
| 서버 BPM 프로세스 | `server_bot` | 운영 화면에서 실행 위치가 「서버」인 BPM 프로세스를 부르는 이름 (확정). PC 쪽은 그냥 「BPM 프로세스」 |
| PC 위임 | `pc_delegation` | 서버 BPM 프로세스의 Call Activity가 **따로 배포된 PC BPM 프로세스**을 부르는 것 (`chk:call.delegate`). Center 작업으로 PC 실행기에 맡기고 서버 BPM 프로세스는 상태를 저장하고 기다린다. 결과는 그 BPM 프로세스가 선언한 `outputs`가 Center를 지나 돌아온다 ([ADR-0062](decisions/0062-pc-delegation.md)). **대상이 서버 BPM 프로세스이어도 같은 칸**이고 어디서 도는지는 대상 패키지의 실행 위치가 정한다 — 그래서 둘을 함께 「위임」이라고도 한다 ([ADR-0082](decisions/0082-batch-start.md)) |
| 동시 실행 상한 | `max_concurrency` | 서버 실행에만 있다. 서버 실행기 전체(기본 10) + BPM 프로세스별(배포 때, 기본 5) |
| 진입 정의 | `entry` | BPM 프로세스를 시작할 때 처음 실행하는 정의 |
| 공유 BPM 프로세스 | `process_lib` | 여러 BPM 프로세스가 Call Activity로 부르는 재사용 BPMN. 패키지에 복사되어 들어간다 |
| 패키지 | `package` | BPM 프로세스·공유 BPM 프로세스를 담은 서명 가능한 zip. 종류(`kind`)를 가진다. **비밀(키 값)은 넣지 않는다**. 도구 묶음(툴팩)은 패키지가 아니다 — 도구는 확장이 기여한다 ([ADR-0050](decisions/0050-no-toolpack-kind.md)) |
| 태스크 | `task` | BPMN 노드 하나 |
| 배포 | `deployment` | "이 PC 실행기(또는 서버 실행기)에서 이 BPM 프로세스의 이 버전을 쓴다"는 서명 봉투 — 관리자가 콘솔에서 누르면 Center가 서명한다. 서버 배포에는 동시 실행 상한이 들어간다 |
| 작업 | `job` | 배포된 BPM 프로세스를 특정 입력으로 한 번 실행하라는 Center의 지시 |
| 실행 | `run` | BPM 프로세스 실행 한 번. `run_id`로 식별 |
| 실행 이벤트 | `run_event` | 실행 중 일어난 일 하나. `(run_id, seq)`가 멱등 키 |
| 이정표 | `milestone` | 이벤트 정의가 없는 중간 던지기 이벤트. 「어디까지 왔는지」를 실행 기록에 남긴다 (C14 §이벤트) |
| 출력 폴더 | `output_dir` | 실행 하나가 파일을 쓰는 곳이자 BPM 프로세스가 적는 **상대 경로의 기준**. 쓰기는 이 안만 된다 ([ADR-0026](decisions/0026-file-paths-and-file-list-task.md)) |
| 읽기 허용 폴더 | `readable` | 파일 목록이 들여다볼 수 있는 폴더. 실행하는 쪽(PC 실행기 설정·Studio)이 정한다 ([ADR-0026](decisions/0026-file-paths-and-file-list-task.md)) |
| 시험 케이스 | `case` | 입력 + 기대 결과 + 결재 자동 응답. Studio 시험 실행의 판정 기준 |
| 사전 점검 | `preflight` | 실행 전에 각 노드를 ok / warning / blocked로 판정 (확장 태스크 종류·갖춰야 할 설정·AI 환경) |
| 재생 | `replay` | 성공한 AI 태스크의 **도구 차례**를 다시 밟는 것 (결정 수행의 한 형태). 태스크마다 `plan`(마지막 추출만 모델) / `full`(모델 0회) / `none`을 고른다 ([ADR-0028](decisions/0028-replay-memory.md)) |
| 재생 명세 | `replay_spec` | 자율 수행이 남긴 도구 차례와 마지막 답. 패키지 안 `memory/specs.json`에 들어가고 도구 인자는 `{변수}` 템플릿이다 |
| 자율 수행 | `autonomous` | 수행 모드. AI가 방법을 찾아 수행하고 결과를 학습 자료로 남긴다. **Studio에서 개발 목적으로 실행할 때** |
| 결정 수행 | `deterministic` | 수행 모드. 학습·등록된 대로 LLM 없이(또는 최소로) 수행한다. **PC 실행기에서 BPM 프로세스를 운영 실행할 때**, Studio의 재생 실행 |

### 2-1. 가상 직원과 일괄 ([ADR-0079](decisions/0079-virtual-worker-is-an-intake-bot.md))

| 화면 표기 | 코드 | 뜻 |
| --- | --- | --- |
| 가상 직원 | `virtual_worker` | **사람이 아닌 업무 주체.** Center에 등록되고(주체 이름 `vw:<id>`, C5 §가상 직원) 접수 BPM 프로세스·감독자를 갖는다. 기동해도 되는 BPM 프로세스는 따로 두지 않는다 — 접수 BPM 프로세스의 서명된 `requires.delegations`다. 그 접수 BPM 프로세스의 실행(일괄)과 자식 실행을 Center가 **읽을 때** 이어 붙인다 ([ADR-0085](decisions/0085-virtual-worker-resource.md)). **배포 단위가 아니다** — 배포 단위는 여전히 BPM 프로세스이다 (§6). 코드에서 `worker`로 줄여 쓰지 않는다 (외부 작업의 일꾼과 헷갈린다) |
| 접수 BPM 프로세스 | `intake_bot` | 가상 직원이 돌리는 **서버 BPM 프로세스**. 인입 → 항목 N건 만들기 → 일괄 결재 → 일괄 기동을 그림으로 그린 것 |
| 일괄 | `batch` | **접수 BPM 프로세스 실행 한 번.** 일괄 id는 그 실행의 `run_id`이고 항목은 그 실행의 변수(목록)다. 「묶음」이라 쓰지 않는다 (확장·시험 묶음·PC 묶음 풀기가 이미 쓴다) |
| 일괄 결재 | — | 일괄 안의 결재 하나(C6). 항목 N건을 `show`로 보이고 감독자가 한 번에 승인·반려한다. 새 결재 종류가 아니다 |
| 값 출처 | `source` | BPM 프로세스 입력 하나의 값을 **누가 넣나**. 비우면 부르는 쪽(작업·메시지·위임·케이스), `virtual_worker.id`·`.name`·`.supervisors`면 **Center**가 그 실행의 가상 직원에서 넣는다 — 부르는 쪽은 줄 수 없다. 가상 직원 정보를 따로 된 칸이 아니라 **입력 한 줄**로 받는다 ([ADR-0099](decisions/0099-input-value-source.md)) |
| 일괄 기동 | `batch_start` | 승인된 항목마다 BPM 프로세스 작업을 하나씩 내는 것 (반복 + 위임). 기동된 실행을 **자식 실행**이라 하고 `parent_run_id`가 일괄 id다 |

| 화면 표기 | 코드 | BPMN 요소 | 누가 수행 |
| --- | --- | --- | --- |
| AI 태스크 | `ai_task` | ServiceTask | AI(LLM). 목표·허용 도구·결과 필드 |
| 서비스 앱 태스크 | `service_task` | ServiceTask | 서비스 앱. 앱 + 작업 + 입력·출력 매핑 (C15 외부 작업으로 부른다 — 키는 없다) |
| 결재 | `approval` | UserTask | 사람 (Center 또는 현장 PC) |
| 파일 목록 | `file_list` | ServiceTask | 실행 엔진 내장. 폴더를 훑어 파일 경로 목록을 만든다 ([ADR-0026](decisions/0026-file-paths-and-file-list-task.md)) |
| 스크립트·규칙·메일·웹훅 | — | ScriptTask, BusinessRuleTask(DMN), SendTask, ReceiveTask | 실행 엔진 내장 |

## 3. 사람 개입

| 화면 표기 | 코드 | 뜻 |
| --- | --- | --- |
| 결재 (업무 개입) | `approval` | BPMN UserTask. 업무상 사람이 결정해야 하는 것. Center로 올려 다른 사람이 답할 수 있다 |
| 확인 (실행 개입) | `confirmation` | 실행 중 막힘(OTP, 전환, 결과를 모르는 호출). 화면 앞 사람만 답할 수 있어 Center로 올리지 않는다 |
| 전환 | `escalation` | AI 태스크·확장 태스크가 스스로 풀지 못해 사람에게 넘기는 것 (`ESCALATED`). PC 실행에서는 확인으로 이어진다 |
| 검토 자료 | `review` | 결재·확인 창(CMN-01 [R])에 보이는 값 — 이름 → 값 (C6). 결재는 폼의 「표시 변수」, 전환한 확인은 확장이 준 것이다. 값 하나가 **표 값**(`{headers, rows}`)이면 표로 그린다 ([ADR-0112](decisions/0112-escalation-review-from-extensions.md)) |
| 결재 담당자 | `assignee` | 그 결재에 답할 사람. 그림(`chk:approval.assignees`)이 이름으로 정하고 C6에 실린다. 콘솔은 거르기만 하고, 대리 답은 담당자일 때만 받는다 ([ADR-0080](decisions/0080-approval-assignees.md)) |
| 감독자 | `supervisor` | 가상 직원(§2-1)의 결재에 답하는 **사람**. 접수 BPM 프로세스의 일괄 결재 담당자가 된다 — 그림은 출처가 `virtual_worker.supervisors`인 입력(`assignees: "감독자"`)으로 가상 직원 자원의 목록을 그대로 받는다 (ADR-0099) |
| 대리 답 | `on_behalf_of` | 연동하는 쪽(예: 대화 창구)이 **사람 대신** 결재 답을 Center에 나르는 것. 답한 사람(행위자)은 그 사람이고, 지나온 길(경로)은 키 이름이다 — 둘을 따로 적는다. 「위임」(`delegate`, PC 위임)과 다른 말이다 |

> 상태: 감독자는 [ADR-0079](decisions/0079-virtual-worker-is-an-intake-bot.md), 결재 담당자는 [ADR-0080](decisions/0080-approval-assignees.md), 대리 답은 [ADR-0081](decisions/0081-answering-on-behalf.md)이 정한다. 결재 담당자·대리 답(C6)·일괄 기동(ADR-0082)·가상 직원(C5, ADR-0085)이 돈다.

## 4. 리소스 (Center가 목록으로 관리)

| 종류 | 코드 | 예 |
| --- | --- | --- |
| 확장 | `extension` | 확장 정의, 등급, 상태, 기여 요약. 서버 부분이 있으면 서비스 앱 항목과 이어짐 |
| 서비스 앱 | `service_app` | 주소·상태·작업 목록·관리 콘솔 주소 (키는 두지 않음) |
| 기여 자원 | `contributed` | 확장이 카탈로그로 올린 자원. 종류 이름은 확장이 정하고 Center는 `data`를 해석하지 않는다 |
| 런타임 | `runtime` | PC 실행기가 보고하는 실행 능력 (C4 `runtimes`의 브라우저·데스크톱 백엔드). **지금은 채우는 쪽이 없다** ([09-gaps.md](09-gaps.md)) |

## 4-1. 외부 작업 ([ADR-0102](decisions/0102-calling-outside-is-pull.md), C15)

BPM 프로세스가 네트워크 건너의 기능을 부를 때 Center에 **일감을 올려 두고, 그 기능 쪽이 가져가 끝낸 뒤 결과를 돌려준다** (Pull). 부르는 쪽이 기능의 주소·키를 알지 않는다.

| 화면 표기 | 코드 | 뜻 |
| --- | --- | --- |
| 외부 작업 | `external_task` | Center에 올린 일감 하나. 서비스 앱 태스크 호출 한 번이 하나다. 멱등 키는 C11과 같은 여섯 칸이다 |
| 토픽 | `topic` | 일감이 걸리는 이름. **앱 id**(C11 앱 id 또는 외부 확장 id)와 같다 — BPMN `chk:serviceCall.app_id`가 그대로 토픽이다 |
| 일꾼 | `consumer` | 토픽을 지켜보다 일감을 가져가(잠금) 수행하고 끝냈다고 알리는 **상시 프로세스**. 서비스 앱이 일꾼이 되고, 외부 앱은 어댑터 일꾼이 맡는다. Center가 승인해 들인다 |
| 어댑터 일꾼 | `adapter_consumer` | Chaeksas가 주는 범용 일꾼. 외부 확장 정의의 HTTP 어댑터를 읽어 외부 앱을 부른다. **외부 앱의 주소·키는 이 일꾼만 든다** — 외부 앱이 있는 망 안에 띄워도 된다 |
| 잠금 | `lock` | 일꾼이 일감을 가져가면 그 일꾼만 끝낼 수 있는 시간. 지나면 다른 일꾼에게 다시 나간다 (그래서 **최소 한 번 실행**이다) |
| 호출 토큰 | `call_token` | 실행하는 쪽(실행 프로세스)이 외부 작업을 **올리고 결과를 기다리는 데만** 쓰는 Center 토큰. PC 실행기가 제 Center API 키로 청해(24시간) 메모리에 들고 넘긴다 |

## 5. 키와 설정 ([ADR-0013](decisions/0013-api-keys.md))

| 화면 표기 | 코드 | 뜻 |
| --- | --- | --- |
| 연동용 키 | `integration_key` | Center API 키의 한 종류. 외부 시스템이 작업을 만들 때 쓴다 (C5) |
| 대리 답용 키 | `relay_key` | Center API 키의 한 종류 (`type: relay`). 연동하는 쪽이 **사람 대신 결재에 답할 때만** 쓴다 — 결재 읽기·답뿐이고, 그 사람(`X-CHK-On-Behalf-Of`)이 결재 담당자일 때만 받는다 ([ADR-0081](decisions/0081-answering-on-behalf.md)) |
| Center API 키 | `center_api_key` | Center 콘솔에서 발급. **PC 실행기 설정에 등록**해 Center 등록·하트비트·다운로드에 쓴다 (Studio용도 따로 발급). 키가 곧 그 PC 실행기의 신원 |
| 서비스 앱 API 키 | `service_api_key` | **각 서비스 앱의 관리 콘솔에서 발급.** 허용 작업·허용 수행 모드·만료를 가진다. Center는 발급·저장하지 않는다 |
| 키 참조 | `key_ref` | BPM 프로세스 속성에 적던 키의 이름. **없어졌다** — 서비스 앱 키가 없다 ([ADR-0102](decisions/0102-calling-outside-is-pull.md)). 옛 그림·패키지에 적혀 있으면 모르는 칸으로 읽고 보지 않는다 (C14 B7이 경고한다). C3 `service_call.key_ref`는 늘 빈 글이다 |
| 환경변수 접두사 | — | `CHK_` 하나. 중첩은 `__` (예: `CHK_CENTER__PORT`) |
| 포트 | — | 구성요소마다 기본값이 있고, 설정 파일 또는 환경변수로 바꾼다 ([04-setup.md](04-setup.md) §6) |

## 6. 쓰지 않는 말

| 말 | 이유 | 대신 |
| --- | --- | --- |
| 프로세스 (단독) | BPM 프로세스인지 OS 프로세스인지 모호 | BPM 프로세스 / <이름> 프로세스 |
| BPM 프로세스 (프로그램을 가리켜) | BPM 프로세스는 업무(BPM 프로세스)다 | PC 실행기 |
| 직원, Employee, 에이전트(배포 단위로서) | 배포 단위는 BPM 프로세스다. 「가상 직원」(§2-1)은 배포 단위가 아니라 **업무 주체**라 이 금지에 걸리지 않는다 — 「직원」만 단독으로 쓰지 않는다 | BPM 프로세스 |
| 묶음 (일괄을 가리켜) | 확장·시험 묶음·PC 묶음 풀기가 이미 쓴다 | 일괄 |
| `worker` (가상 직원을 가리켜, 경로·칸 이름에서) | 일꾼(`consumer`)과 헷갈린다 | `virtual_worker` |
| 에이전트(화면에서) | LLM이 태스크를 수행하는 내부 구성만 뜻한다 | AI 태스크 |
| RPA 봇, BPM 봇 | 모호 | BPM 프로세스 |
| LLM 앱 (분류 이름으로) | 서비스 앱 중 LLM을 안 쓰는 것도 있다 | 서비스 앱 |
| 플러그인, 애드온, 모듈(기능 묶음을 가리켜) | 한 개념에 한 단어 | 확장 |
| HITL (화면에서) | 두 층을 구분하지 못한다 | 결재 / 확인 |
| lease, dispatcher | 서버가 작업을 배분하던 옛 구조 | Center 작업(`job`) |
| 대시보드 | 읽기 전용이던 옛 구조 | Center 콘솔 |
| 등록 토큰 | Center API 키로 바뀜 | Center API 키 |
| Worker·워커 (외부 작업을 가져가는 쪽을 가리켜) | 한 개념에 한 단어 — 그 쪽은 일꾼이다 | 일꾼 (`consumer`) |
| External Task Worker, 작업 게시판 | 제품 이름·비유 | 외부 작업 · 토픽 · 일꾼 |
