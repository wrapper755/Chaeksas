# C14. BPMN 확장 속성 (BPM 프로세스 정의 파일 형식)

| 항목 | 값 |
| --- | --- |
| 상태 | 초안 (2026-10-01). **모델·BPMN 읽기·검사 B1~B14 구현됨** (2026-10-03, 예제 50개로 확인). **식 `chk-expr`·스크립트·템플릿도 구현됨** (2026-10-04, [ADR-0025](../decisions/0025-expression-language.md) — 예제의 식 자리 193곳·템플릿 자리 전부로 확인). 합의는 M3에서 엔진·Studio와 함께 |
| schema | 1 |
| 보내는 쪽 → 받는 쪽 | Studio(쓰기) → 패키지(C1 `process/*.bpmn`) → 실행기·서버 실행기(읽기·실행), Center(검사) |
| 코드 위치 | `chaeksas.contracts.bpmn_ext` — 모델·`read_process()`·`validate()`. 확장 태스크의 속 내용은 각 확장의 `contracts/` |
| 관련 ADR | [0008](../decisions/0008-map-driver-hands-boundary.md), [0013](../decisions/0013-api-keys.md), [0015](../decisions/0015-run-location.md), [0016](../decisions/0016-server-first.md), [0018](../decisions/0018-extensions.md) |
| 관련 화면 | STU-04 속성 패널, STU-06, STU-07, STU-13, STU-14 |

## 목적

BPMN 2.0 파일 안에 우리 태스크의 속성을 적는 방법을 정한다. 예를 들면 AI 태스크의 목표·결과 필드, 결재 폼, 서비스 앱 호출, 확장 태스크가 여기에 들어간다. 표준 BPMN 도구(bpmn-js)로 열고 그릴 수 있어야 하고, 엔진은 이 속성만 보고 실행할 수 있어야 한다.

## 기본 규칙

1. **네임스페이스:** `xmlns:chk="urn:chaeksas:bpmn:1"`. 확장 태스크는 같은 네임스페이스의 `chk:task` 요소에 담는다.
2. **속성은 `bpmn:extensionElements` 안의 `chk:*` 요소 하나에 JSON 텍스트로** 담는다. 속성 하나는 요소 하나다. 엔진·Studio·Center가 같은 모델(`contracts.bpmn_ext`)로 검사한다. XML 속성으로 흩어 쓰지 않는다.
3. **표준 BPMN으로 표현되는 것은 표준으로 쓴다:** 흐름, 게이트웨이 조건, 타이머, 메시지, 신호, 오류, 다중 인스턴스 표시, 호출 대상(`calledElement`). 우리 속성은 표준에 없는 것만 더한다.
4. **노드 id는 읽을 수 있게 짓는다.** 예: `Task_ReadLedger`, `Gw_HasHold`, `Approve_Hold`. 시험 케이스의 결재 자동 응답이 노드 id를 키로 쓰기 때문이다. 프로토타입에서는 `Activity_0ngrasb` 같은 생성 id 때문에 케이스를 읽을 수 없었다. Studio는 새 노드에 `<종류>_<이름 영문 요약>` 형식을 제안한다.
5. **변수 이름:** 한글을 써도 된다. 공백·하이픈은 쓸 수 없고 숫자로 시작할 수 없다 (식에서 이름으로 쓰이므로). 정규식은 `^[A-Za-z가-힣_][A-Za-z0-9가-힣_]*$`.
6. **식:** 게이트웨이 조건, 호출 입력, 스크립트는 **안전한 식 언어 `chk-expr`**(Python 식 문법의 부분집합)로 쓴다. 문법·도우미 함수 목록은 [ADR-0025](../decisions/0025-expression-language.md)가 정하고, 구현은 `chaeksas.core.expr`다 (`eval`을 쓰지 않는다 — `ast`로 파싱해 허용한 노드만 걷는다). 문자열 상수는 따옴표로 감싼다 (프로토타입에서 따옴표를 빠뜨려 변수로 해석되는 실수가 많았다).
   - **점은 사전의 키를 읽는다** — `결과.지급`은 `결과['지급']`이다. 파이썬 객체의 속성은 읽을 수 없고, 밑줄로 시작하는 이름은 점·첨자 모두 막힌다.
   - 선언한 입력(`chk:process.inputs`)을 주지 않았고 기본값도 없으면 `None`이다. 그래서 `대상월 = 대상월 or 지난달()`처럼 쓸 수 있다. **선언하지 않은 변수나 아직 만들어지지 않은 변수를 읽으면 실행 오류**다 (검사 B11이 미리 잡는다).
   - 허용할 것: 목록·사전 내포(`[x for x in …]`), 조건식(`a if c else b`), 첨자·조각, f-문자열, 내장 `len`·`sum`·`min`·`max`·`round`·`abs`·`sorted`·`zip`·`dict`·`list`·`set`·`str`·`int`·`float`·`bool`. 업무 도우미는 날짜(`오늘()`·`지난달()`·`날짜더하기()`·`달더하기()`·`기간()` …), 표(`합계(목록, 열)`·`열뽑기()`·`표를사전()`·`묶기()`·`펼치기()` …), 수(`나누기()`·`비율()` — 0으로 나누면 0), 검사(`빈칸없음()`·`범위벗어남()`)다. **전체 목록은 [ADR-0025](../decisions/0025-expression-language.md) §도우미 함수** (늘릴 때 그 표와 `core.helpers.HELPERS`를 함께 고친다).
   - **식에 두지 않는 것:** 디스크·환경·네트워크를 읽는 함수 (`파일목록()`·`설정()`). 재생(결정 수행)이 같은 값을 내야 한다 — 그런 일은 태스크·프로세스 입력으로 옮긴다 (ADR-0025 §식에 두지 않는 것).
   - **스크립트**(`scriptTask`)에는 `변수 = 식`만 쓴다. 반복·분기는 BPMN으로 그린다.
7. **템플릿:** 파일 경로·메일 제목·본문·`dataOutput.template`은 식이 아니라 **텍스트에 `{변수}`를 끼운 것**이다. 중괄호 안에는 **변수 이름 하나만** 올 수 있고 식은 쓸 수 없다. `{{`·`}}`는 중괄호 한 개다. 값이 `None`이면 빈 칸으로 들어가고, 모르는 이름은 실행 오류다 (ADR-0025 §1).
8. **비밀·키 값은 넣지 않는다.** 서비스 앱 키는 참조 이름만 쓴다 (C1·ADR-0013).
9. **엔진이 늘 주는 변수**가 있다. 선언하지 않아도 식·템플릿에서 쓸 수 있고, 검사 B11이 「출처 없음」으로 보지 않는다.

   | 이름 | 값 |
   | --- | --- |
   | `오늘` | 실행을 시작한 날짜 (`YYYY-MM-DD`). 파일 이름에 자주 쓴다 — `일일/{오늘}.md` |
   | `지금` | 실행을 시작한 시각 (ISO 8601 + 시간대) |
   | `run_id` | 그 실행의 id (C3와 같은 값) |

   늘어나면 이 표와 `contracts.bpmn_ext.BUILTIN_VARS`를 함께 고친다.

## 프로세스 수준

`bpmn:process` 의 `extensionElements`에 다음을 둔다.

| 요소 | JSON 필드 | 뜻 |
| --- | --- | --- |
| `chk:process` | `run_location`(`server`\|`pc`), `service_keys`(`{app_id: key_ref}`), `extensions`(`[{id, version}]`), `inputs`(`[{name, type, required, description, default?}]` — 메시지 본문으로 들어오는 값도 여기에 선언), `outputs`(`[name]`) | BPM 프로세스 정보 (STU-06). 패키지 매니페스트(C1)는 빌드 때 이것을 모아 만든다 |
| `chk:defaults` | `limits`(`{timeout_s, max_steps}`), `forbidden_actions[]`, `confirm_triggers[]`, `web`(`{profile, session}`), `desktop`(`{app}` — 띄울 앱 이름) | 모든 AI·UI 태스크의 기본값. 태스크에 적은 값이 이긴다 |

## 태스크 종류와 속성

| 태스크 종류 (화면) | BPMN 요소 | 속성 요소 | 필드 |
| --- | --- | --- | --- |
| AI 태스크 | `serviceTask` | `chk:aiTask` | `goal`(Markdown — `## 상황`·`## 할 일`·`## 판단하지 않는 것`·`## 반환` 권장), `domain`(`llm`\|`api`\|`doc`\|`web`\|`desktop`), `tools[]`, `params`(업무 파라미터, 재생 때 `$param`), `results`(`{이름: 타입}`), `limits`, `forbidden_actions[]`, `confirm_triggers[]`, `web`/`desktop`(환경 설정) |
| UI 태스크 (UI 자동화 확장) | `serviceTask` | `chk:task` `type="ui_task"` `extension="ui-automation"` | `page_id`, `start_url?`, `steps[]`(`{key, action, value?, result?, navigates?}`), `goal?`(자율 수행 전용), `heal`(기본 true), `close_browser` |
| 서비스 앱 태스크 | `serviceTask` | `chk:serviceCall` | `app_id`, `operation`, `input`(`{필드: 식}`), `output`(`{변수: 필드}`), `key_ref?`(없으면 프로세스의 `service_keys`를 상속), `timeout_s`, `retry`(`{max, on: [503, 429]}`) |
| 다른 확장 태스크 | `serviceTask` | `chk:task` `type="<확장 태스크 종류>"` `extension="<id>"` | 그 확장의 계약이 정한 JSON |
| 결재 | `userTask` | `chk:approval` | `title`, `description`, `show`(**변수 이름 배열** — 문자열 하나로 쓰면 검사 오류), `fields[]`(C6 Form과 같다: `{key, label, type: bool\|number\|text\|choice, choices?, required, default?}`), `location`(`follow`\|`center`\|`field`), `expires`(ISO 기간 또는 변수 이름) |
| 수동 작업 (사람 확인) | `manualTask` | `chk:approval` | 결재와 같은 형식. 화면에는 「확인」으로 보인다. 서버 BPM 프로세스에서는 Center 결재함으로 간다 |
| 스크립트 | `scriptTask` | 표준 `bpmn:script` (`scriptFormat="chk-expr"`) | 식 언어로 쓴 대입문. 입력은 프로세스 변수, 결과는 대입한 변수 |
| 규칙 | `businessRuleTask` | `chk:rule` | `decision`(같은 패키지의 DMN 결정 id), `input`(`{DMN 입력 식 이름: 식}`), `output`(`{변수: DMN 출력}`). DMN은 한 건을 판정한다 — 목록은 반복(아래)으로. 적중 정책 `COLLECT`면 출력이 목록이다 (맞는 줄이 없으면 빈 목록) |
| 메일 보내기 | `sendTask` | `chk:email` | `to[]`, `cc[]`, `subject`, `body`, `attachments[]`(변수 이름), `store_as?` |
| 웹훅 보내기 | `sendTask` | `chk:webhook` | `url`, `method`, `body`(`all`\|`fields:[..]`\|`template:"…"`), `timeout_s`, `store_as?`. URL은 허용 호스트 규칙(C13 §4-3과 같은 해석기)을 따른다 |
| 메시지 받기 | `receiveTask` | 표준 `messageRef` + `chk:receive` | `correlation`(변수 이름 — 이 값이 같은 메시지만 받는다), `payload[]`(메시지 본문에서 변수로 들어오는 이름 — 검사 B11이 출처로 본다. 메시지 시작은 `chk:process.inputs`로 선언) |
| 다른 BPM 프로세스 호출 | `callActivity` | 표준 `calledElement` + `chk:call` | `input`(`{호출 대상 변수: 식}`), `output`(`{내 변수: 호출 대상 변수}`). **적은 것만 오간다.** 둘 다 비면 오가는 변수 없음 (프로토타입의 "비면 전부"는 없앴다) |

### 반복 (다중 인스턴스)

- 표준 `bpmn:multiInstanceLoopCharacteristics`(`isSequential`)에 `chk:loop`(`collection`, `item`, `result`, `collect_into`)를 더한다. AI·UI·서비스 앱·규칙 태스크에 쓸 수 있다. `result`는 한 번 돈 결과로 쓰는 변수 이름(그 태스크의 출력 중 하나)이고, 모은 목록의 순서는 입력 순서다 (병렬이어도).
- `collect_into`는 **필수**다. 빠지면 프로토타입처럼 반복이 멈춘다.
- 병렬(`isSequential=false`)은 서버 BPM 프로세스에서만 동시에 돈다. PC에서는 차례로 돈다 (실행 자리 하나).

### 파일 출력

- `bpmn:dataObjectReference`에 `chk:dataOutput`(`path`, `format: md|xlsx|json|txt|csv`, `template?`, `variables?`, `sheet?`, `append`, `store_as`)를 둔다.
- 쓰는 시점은 `dataOutputAssociation`으로 연결된 태스크가 끝날 때다.
- `path`는 출력 폴더 기준 상대 경로이고, 앞에 `outputs/`를 붙이지 않는다.
- `template`가 비면 `variables`의 표를 만든다. 둘 다 비면 검사 오류다. 프로토타입에서는 이때 모든 변수가 쏟아졌다.
- **`store_as`는 필수다.** 첨부·후속 태스크가 파일 경로를 받는 유일한 길이다.

### 이벤트 (표준)

| 종류 | 쓰는 법 | 비고 |
| --- | --- | --- |
| 타이머 시작 | `timeCycle` — 5필드 cron(`0 9 * * 1-5`) 또는 ISO `R/…` | 서버 실행기·Bot UI의 일정이 이것을 읽는다 |
| 타이머 경계·중간 | `timeDuration`(ISO `PT30M`, `P3D`) 또는 **변수 이름** | 경계는 `cancelActivity="false"`로 비중단. 경계의 반복(`timeCycle`)은 schema 1에서 지원하지 않는다 |
| 메시지 시작·받기·경계·중간 받기 | `messageRef` → `bpmn:message name`. 받기 태스크 외의 받기(경계·중간 받기)도 상관 키는 `chk:receive{correlation}`로 둔다 | 외부 시스템이 Center 메시지 API로 보낸다 (C12, PC는 Bot UI 메시지 수신). 상관 키가 없으면 메시지 시작만 깨운다 |
| 신호 | `signalRef` | 한 실행 안의 가지 사이에서만 |
| 오류 경계 | `errorRef` → `bpmn:error errorCode` | 표준 코드: `TASK_FAILED`(AI·UI·서비스 앱 태스크 실패), `SEND_FAILED`(메일·웹훅), `ESCALATED`(UI 태스크 전환을 사람 확인 대신 흐름으로 받을 때), `DELEGATION_FAILED`(예약). 오류 경로에는 `error_code`, `error_message`, `failed_task` 변수가 생긴다 |
| 조건 시작 | `conditionalEventDefinition` | **schema 1에서 쓰지 않는다** (프로토타입의 폴더 감시). 외부 시스템 메시지나 타이머로 바꾼다 |

## 시험 케이스 형식 (Studio, 패키지에 넣지 않음)

예제 묶음과 Studio의 시험 케이스는 다음 JSON을 쓴다 (STU-07).

```json
{
  "schema": 1,
  "cases": [{
    "name": "8월 정상",
    "description": "보류 5건, 지급 2건",
    "inputs": {"대상월": "2026-08"},
    "expected": {"지급합계": 6358000, "보류건수": 5},
    "approvals": {"Approve_Hold": {"지급진행": "지급 대상대로 진행", "의견": "보류 5건 공급사에 확인 요청"}},
    "messages": [{"after_s": 5, "name": "return_arrived", "correlation": "RT-01", "payload": {"검수통과": true}}],
    "manual": false
  }]
}
```

- `process`(선택): 이 케이스 파일이 시험하는 BPM 프로세스 id (`Proc_<파일>`). Studio는 정의 옆에 두므로 비워도 된다.
- `messages`(선택): 시작 뒤 `after_s`초에 보내는 메시지. Center 메시지 API(C12)와 같은 모양(`name`, `correlation`, `payload`)이다. 받기 태스크·경계·중간 받기를 시험할 때 쓴다. 받을 곳이 없으면 `no_receiver`로 기록만 하고 케이스를 실패시키지 않는다.

- `approvals`는 노드 id → 폼 응답이다.
- `manual: true`인 케이스는 자동 응답이 있어도 쓰지 않고 실제 창을 띄운다. 폼을 사람이 보는지 확인하는 용도다.
- 수동이 아닌 케이스에서 자동 응답이 없는 결재는 **답하지 않은 채 기다린다** — 타이머 경계(기한 초과)를 시험하는 방법이다. 케이스 전체 시간 제한(Studio 설정, 기본 300초)을 넘으면 그 케이스는 실패다.
- `expected`가 비면 「비교 안 함」으로 판정한다 (U6).

**기대 결과 비교 규칙** (AI 결과는 매번 조금씩 달라서 정확히 같음만으로는 시험할 수 없다):

| `expected` 값 | 통과 조건 |
| --- | --- |
| 숫자·문자열·참거짓 | 같다 |
| `"*"` | 변수가 있고 비어 있지 않다 |
| `{"$gt"\|"$gte"\|"$lt"\|"$lte": n}` | 비교가 맞다 |
| `{"$contains": "문구"}` | 문자열이 문구를 포함하거나, 목록이 그 값을 가진다 |
| 그 밖의 객체 | **부분 일치** — 적은 키만 같은 규칙으로 비교한다 |
| 목록 | 길이가 같고 각 원소가 같은 규칙으로 맞는다 |

`$`로 시작하는 키는 연산자로 예약한다 (변수 이름 규칙상 `$`는 쓰이지 않는다).

**케이스 입력 연산자:**

| 값 | 바뀌는 것 |
| --- | --- |
| `{"$now_plus": "PT20S"}` | 케이스를 돌리는 순간 + 기간의 ISO 시각. 마감 시각을 받는 BPM 프로세스 시험용 (BX-11) |
| `{"$test_receiver": "reply"}` | Studio 시험 수신기의 주소(`reply`는 이름). 웹훅 회신을 받아 실행 기록에 남긴다. **Studio 시험 실행에서만** 웹훅 허용 호스트 규칙(https·사설망 차단)의 예외다. 배포된 Bot에서는 쓸 수 없다 |

## 검사 규칙 (Studio 「실행 전 검사」·Center 업로드)

| # | 규칙 | 위반 |
| --- | --- | --- |
| B1 | `chk:*` JSON이 모델과 맞는다 | 오류 |
| B2 | `show`는 배열이고 각 이름이 변수 규칙에 맞는다 | 오류 |
| B3 | 배타·포함 게이트웨이의 나가는 흐름 중 조건 없는 것은 `default`로 지정된다. 포함 분기는 포함 합류로 닫는다 | 오류 |
| B4 | 반복에 `collect_into`가 있다 | 오류 |
| B5 | 파일 출력에 `store_as`가 있고 `template`·`variables` 중 하나가 있다 | 오류 |
| B6 | 실행 위치가 `server`면 UI 태스크·`web`/`desktop` 도메인 AI 태스크·`location: field` 결재가 없다 (C1 R2) | 오류 |
| B7 | 서비스 앱 태스크의 `app_id`에 키 참조가 있다 (자기 것 또는 프로세스 `service_keys`) | 오류 |
| B8 | 결과 필드 타입이 `string`·`int`·`number`·`bool`·`list`·`dict`·`date` 중 하나다. 번호처럼 보이는 문자열(예: 발주번호 `PO-2608-001`)을 `int`로 두면 경고 | 오류 / 경고 |
| B9 | 연결되지 않은 노드가 없다 (들어오는 흐름·나가는 흐름) | 오류 |
| B10 | 노드 id가 생성형(`Activity_[0-9a-z]{7}`)이면 경고 | 경고 |
| B11 | 어떤 경로로는 만들어지지 않는 변수를 읽는다 (예: 한 가지에서만 생기는 결재 칸을 합류 뒤에 읽음, 프로세스 `inputs`에 없는 메시지 본문 변수) | 경고 |
| B12 | 결재 칸 `type`이 C6의 `bool`·`number`·`text`·`choice` 중 하나이고, `choice`에는 `choices`가 있다. UI 태스크 스텝 `action`이 C10 동작 목록 안에 있다. 경계 이벤트는 태스크·하위 프로세스에만 붙는다 | 오류 |
| B13 | 웹훅 `body: all` (비밀이 섞일 수 있음), `location: field` 결재에 하루 넘는 시간 제한 | 경고 |
| B14 | 병렬 분기와 합류의 가지 수가 맞다 (오류 경계의 대체 흐름을 병렬 합류에 바로 이으면 합류가 영원히 기다린다). 규칙 태스크의 `input`·`output`이 DMN 입력·출력 이름과 맞다. 호출의 `output`이 호출 대상의 `outputs`에 있다. 타이머로 시작하는 BPM 프로세스에 기본값 없는 필수 입력이 없다 | 오류 |

`validate()`는 오류와 경고를 **함께** 돌려준다 (`Violation.severity`). Studio 「실행 전 검사」는 오류만으로 실행을 막고(`blocking()`), 경고는 보여 주고 사람이 판단한다.

**혼자서는 할 수 없는 검사는 인자로 받는다.** 주지 않으면 그 부분을 건너뛴다 (C1 `validate()`와 같은 태도).

| 인자 | 없으면 | 주는 쪽 |
| --- | --- | --- |
| `task_type_locations` | B6에서 확장 태스크를 건너뛴다 | 확장 호스트 (C13 `task_types[].run_locations`) |
| `dmn_decisions` | B14의 DMN 대조를 건너뛴다 | 패키지의 DMN 파일 |
| `called_processes` | B14의 호출 대조를 건너뛴다 | 패키지의 다른 BPM 프로세스 |
| `extension_task_vars` | **확장 태스크 뒤에서는 B11이 입을 닫는다** | 확장 (그 태스크가 만드는 변수) |

**플랫폼은 확장 태스크의 속을 검사하지 않는다** (ADR-0018). 예를 들어 UI 태스크 스텝의 `action`이 C10 동작 목록에 있는지는 UI 자동화 확장이 본다 — B12의 그 줄은 확장의 몫이다.

B11은 **어림**이다. 식에서 변수를 이름으로 뽑되 문자열 상수·함수 호출·키워드 인자·내포 변수는 뺀다. 도우미 함수 목록은 정해졌지만(ADR-0025) 검사는 계약 쪽에 있고 도우미 구현은 `core`에 있어 이름을 아직 대조하지 않는다 — 그래서 여전히 경고다.

## 프로토타입과 달라진 것

| 프로토타입 | 여기 |
| --- | --- |
| `agentworks:payload`, `agentworks:form` … | `chk:aiTask`, `chk:approval` … |
| `target_domain` `LLM/API/WEB/DOCUMENT/DESKTOP/HYBRID` | `domain` `llm/api/doc/web/desktop` (HYBRID 없음 — 웹 표 읽기는 UI 태스크, 데스크톱 조작은 UI 태스크 또는 `desktop` AI 태스크로 나눈다) |
| 웹 조작을 AI 태스크(WEB)로 | 등록된 화면이면 UI 태스크(UI 자동화 확장), 등록 전 탐색만 AI 태스크 `web` |
| `hitl_answers` | `approvals` + `manual` 케이스 |
| 호출 매핑 비면 전부 전달 | 적은 것만 |
| 조건 시작(폴더 감시) | 쓰지 않음 |
| `AGENT_FAILED` | `TASK_FAILED` |

## 변경 이력

| 날짜 | schema | 바뀐 것 | ADR |
| --- | --- | --- | --- |
| 2026-10-01 | 1 | 초안 (프로토타입 확장 속성을 새 용어·확장 모델로 옮김) | 0018 |
| 2026-10-03 | 1 | 구현하며 명시한 것: 엔진이 늘 주는 변수(`오늘`·`지금`·`run_id`) 표, `validate()`가 받는 인자와 건너뛰는 검사, 확장 태스크의 속은 확장이 검사한다(B12), B11이 어림인 이유, B13·B14 순서 | 0018 |
| 2026-10-04 | 1 | 식 `chk-expr`의 문법·도우미 목록 확정, 템플릿(`{변수}`)을 식과 가름, 점이 사전 키를 읽는다고 명시, 흐름 조건식 본문을 reader가 들고 온다 ([ADR-0025](../decisions/0025-expression-language.md)) | — |
| 2026-10-01 | 1 | 업무 예제 작업 반영: `inputs[].default`, `chk:receive.payload`, 경계·중간 받기의 상관 키, 케이스 `messages`·`process`·입력 연산자(`$now_plus`, `$test_receiver`), 자동 응답 없는 결재, 기대 결과 비교 규칙, 결재 칸을 C6에 맞춤(`choices`, `date` 없음), `defaults.desktop`, 식의 None·허용 목록, 검사 B11~B14 ([08-business-examples](../08-business-examples/README.md)) | — |
