# C14. BPMN 확장 속성 (BPM 프로세스 정의 파일 형식)

| 항목 | 값 |
| --- | --- |
| 상태 | 초안 (2026-10-01). **모델·BPMN 읽기·검사 B1~B14 구현됨** (2026-10-03, 예제 50개로 확인). **식 `chk-expr`·스크립트·템플릿도 구현됨** (2026-10-04, [ADR-0025](../decisions/0025-expression-language.md) — 예제의 식 자리 193곳·템플릿 자리 전부로 확인). **DMN 판정·파일 목록·파일 출력·메일/웹훅·이정표도 구현됨** (2026-10-04, [ADR-0026](../decisions/0026-file-paths-and-file-list-task.md)). **AI 태스크·서비스 앱 태스크·재생** (2026-10-04, [ADR-0027](../decisions/0027-llm-connection.md)·[ADR-0028](../decisions/0028-replay-memory.md))과 **타이머·메시지·신호·호출**도 돈다. 합의는 M3에서 엔진·Studio와 함께 |
| schema | 1 |
| 보내는 쪽 → 받는 쪽 | Studio(쓰기) → 패키지(C1 `process/*.bpmn`) → 실행기·서버 실행기(읽기·실행), Center(검사) |
| 코드 위치 | `chaeksas.contracts.bpmn_ext` — 모델·`read_process()`·`validate()`. DMN 읽기·판정은 `chaeksas.contracts.dmn`. 확장 태스크의 속 내용은 각 확장의 `contracts/` |
| 관련 ADR | [0008](../decisions/0008-map-driver-hands-boundary.md), [0013](../decisions/0013-api-keys.md), [0015](../decisions/0015-run-location.md), [0016](../decisions/0016-server-first.md), [0018](../decisions/0018-extensions.md), [0026](../decisions/0026-file-paths-and-file-list-task.md) |
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
| AI 태스크 | `serviceTask` | `chk:aiTask` | `goal`(Markdown — `## 상황`·`## 할 일`·`## 판단하지 않는 것`·`## 반환` 권장), `domain`(`llm`\|`api`\|`doc`\|`web`\|`desktop`), `tools[]`, `params`(업무 파라미터, 재생 때 그대로 쓰인다), `results`(`{이름: 타입}`), `replay`(`plan`\|`full`\|`none`, 기본 `plan` — 아래 「재생」), `limits`, `forbidden_actions[]`, `confirm_triggers[]`, `web`/`desktop`(환경 설정) |
| UI 태스크 (UI 자동화 확장) | `serviceTask` | `chk:task` `type="ui_task"` `extension="ui-automation"` | `page_id`, `start_url?`, `steps[]`(`{key, action, value?, result?, navigates?}`), `goal?`(자율 수행 전용), `heal`(기본 true), `close_browser` |
| 서비스 앱 태스크 | `serviceTask` | `chk:serviceCall` | `app_id`, `operation`, `input`(`{필드: 식}`), `output`(`{변수: 필드}`), `key_ref?`(없으면 프로세스의 `service_keys`를 상속), `timeout_s`, `retry`(`{max, on: [503, 429]}`) |
| 다른 확장 태스크 | `serviceTask` | `chk:task` `type="<확장 태스크 종류>"` `extension="<id>"` | 그 확장의 계약이 정한 JSON |
| 결재 | `userTask` | `chk:approval` | `title`, `description`, `show`(**변수 이름 배열** — 문자열 하나로 쓰면 검사 오류), `fields[]`(C6 Form과 같다: `{key, label, type: bool\|number\|text\|choice, choices?, required, default?}`), `location`(`follow`\|`center`\|`field`), `expires`(ISO 기간 또는 변수 이름) |
| 수동 작업 (사람 확인) | `manualTask` | `chk:approval` | 결재와 같은 형식. 화면에는 「확인」으로 보인다. 서버 BPM 프로세스에서는 Center 결재함으로 간다 |
| 스크립트 | `scriptTask` | 표준 `bpmn:script` (`scriptFormat="chk-expr"`) | 식 언어로 쓴 대입문. 입력은 프로세스 변수, 결과는 대입한 변수 |
| 규칙 | `businessRuleTask` | `chk:rule` | `decision`(같은 패키지의 DMN 결정 id), `input`(`{DMN 입력 식 이름: 식}`), `output`(`{변수: DMN 출력}`). DMN은 한 건을 판정한다 — 목록은 반복(아래)으로. 적중 정책 `COLLECT`면 출력이 목록이다 (맞는 줄이 없으면 빈 목록). 아래 「규칙 태스크와 DMN」 |
| 파일 목록 | `serviceTask` | `chk:fileList` | `folder`(템플릿 — 아래 「파일 경로」), `pattern`(glob 한 조각, 기본 `*`), `recursive`(기본 false), `sort`(`name`\|`modified`, 기본 `name`), `limit?`, `store_as`(**필수** — 파일 경로 목록), `count_as?`(개수). 디스크를 읽으므로 식의 도우미가 아니라 태스크다 ([ADR-0025](../decisions/0025-expression-language.md) §식에 두지 않는 것, [ADR-0026](../decisions/0026-file-paths-and-file-list-task.md)) |
| 메일 보내기 | `sendTask` | `chk:email` | `to[]`, `cc[]`, `subject`, `body`, `attachments[]`(변수 이름), `store_as?`. 아래 「보내기」 |
| 웹훅 보내기 | `sendTask` | `chk:webhook` | `url`, `method`, `body`(`all`\|`fields:[..]`\|`template:"…"`), `timeout_s`, `store_as?`. URL은 허용 호스트 규칙(C13 §4-3과 같은 해석기)을 따른다. 아래 「보내기」 |
| 메시지 받기 | `receiveTask` | 표준 `messageRef` + `chk:receive` | `correlation`(변수 이름 — 이 값이 같은 메시지만 받는다), `payload[]`(메시지 본문에서 변수로 들어오는 이름 — 검사 B11이 출처로 본다. 메시지 시작은 `chk:process.inputs`로 선언) |
| 다른 BPM 프로세스 호출 | `callActivity` | 표준 `calledElement` + `chk:call` | `input`(`{호출 대상 변수: 식}`), `output`(`{내 변수: 호출 대상 변수}`). **적은 것만 오간다.** 둘 다 비면 오가는 변수 없음 (프로토타입의 "비면 전부"는 없앴다) |

### 반복 (다중 인스턴스)

- 표준 `bpmn:multiInstanceLoopCharacteristics`(`isSequential`)에 `chk:loop`(`collection`, `item`, `result`, `collect_into`)를 더한다. AI·UI·서비스 앱·규칙 태스크에 쓸 수 있다. `result`는 한 번 돈 결과로 쓰는 변수 이름(그 태스크의 출력 중 하나)이고, 모은 목록의 순서는 입력 순서다 (병렬이어도).
- `collect_into`는 **필수**다. 빠지면 프로토타입처럼 반복이 멈춘다.
- 병렬(`isSequential=false`)은 서버 BPM 프로세스에서만 동시에 돈다. PC에서는 차례로 돈다 (실행 자리 하나).

### 규칙 태스크와 DMN

DMN 파일은 패키지 안에 그대로 들어가고, 결정 하나(`dmn:decision`)는 **결정표**(`dmn:decisionTable`) 하나다. 읽기·판정은 `chaeksas.contracts.dmn`이 한다 (형식 해석이므로 계약 쪽이다).

- **입력 이름은 `dmn:inputExpression`의 본문**이다 (`dmn:input@label`이 아니다 — 라벨은 사람이 읽는 이름이라 「시각」과 「시」처럼 다를 수 있다). `chk:rule.input`의 열쇠가 이 이름이고, 값은 `chk-expr` 식이다.
- **값은 `typeRef`로 맞춘다.** `number`면 숫자로, `boolean`이면 참거짓으로, `string`이면 문자열로 바꾼 뒤 견준다. 이것이 없으면 `"25" > 20`이 문자열 비교가 된다.
- **입력 칸(unary test) 문법** — FEEL의 부분집합만 쓴다. 이 밖은 읽기 오류다.

  | 적는 법 | 뜻 |
  | --- | --- |
  | `-` (또는 빈 칸) | 무엇이든 맞다 |
  | `"문자열"`, `숫자`, `true`/`false` | 같다 |
  | `"ERP","HRIS"` | 쉼표는 「또는」 |
  | `< n`, `<= n`, `> n`, `>= n` | 견준다 |
  | `[a..b]` `(a..b)` `[a..b)` `(a..b]` | 범위 — 대괄호는 포함, 소괄호는 제외 |

- **출력 칸은 값 하나**다 (`"높음"`, `0.05`, `true`). 식은 쓸 수 없다.
- **적중 정책:** `FIRST`(처음 맞는 줄), `UNIQUE`(맞는 줄이 하나여야 한다 — 둘 이상이면 실행 오류), `ANY`(여럿 맞아도 되지만 결과가 달라지면 실행 오류), `COLLECT`(맞는 줄을 모두 모아 **출력이 목록**이 된다). 그 밖의 정책은 schema 1에서 쓰지 않는다.
- **맞는 줄이 없으면** `COLLECT`는 빈 목록, 나머지는 출력이 모두 `None`이다 (실패가 아니다 — 게이트웨이로 가른다).
- 판정은 **순수하다** — 같은 입력이면 같은 결과다. 그래서 결정 수행(재생)에서도 다시 판정한다.

### 파일 경로

파일을 읽고 쓰는 자리(`chk:fileList`, `chk:dataOutput`)는 **실행 폴더** 둘로 묶는다 ([ADR-0026](../decisions/0026-file-paths-and-file-list-task.md)). 실행하는 쪽(Bot UI·Studio 시험 실행·서버 실행기)이 정해서 준다.

| 폴더 | 무엇 |
| --- | --- |
| **출력 폴더** | 실행 하나가 파일을 쓰는 곳. 상대 경로의 기준이기도 하다 |
| **읽기 허용 폴더** | 파일 목록이 들여다볼 수 있는 곳 (여러 개). 주지 않으면 출력 폴더만 읽을 수 있다 |

- **상대 경로는 출력 폴더 기준**이다. 앞에 `outputs/`를 붙이지 않는다.
- **쓰기는 출력 폴더 안만** 된다. **읽기는 출력 폴더와 읽기 허용 폴더 안만** 된다.
- `..`·절대 경로·심볼릭 링크로 그 밖을 가리키면 **실행 오류**다 (`path_denied`). 그림·설정이 잘못된 것이라서 **오류 경계로 받지 않는다**.
- `pattern`에는 경로 구분자(`/`·`\`)를 쓸 수 없다 — 폴더는 `folder`로만 정한다.
- 경로를 만들 때 `{변수}` 템플릿을 쓴다 (기본 규칙 7). 경로 구분자는 `/`로 적고, 실행하는 쪽이 그 OS의 구분자로 바꾼다.
- **변수에 들어가는 경로는 BPM 프로세스가 적은 그대로**다 — 파일 목록(`store_as`)은 `folder`에 이어 붙인 것, 파일 출력(`store_as`)은 채운 `path` 그대로. 실행한 PC의 절대 경로를 엔진이 새로 만들어 섞지 않는다.
- **실행 기록에는 경로를 남기지 않는다** (원칙 6 — 파일 이름에 거래처·사람 이름이 들어간다). 개수·형식·크기만 남는다.
- 폴더가 없거나 읽을 수 없으면 **업무 실패**(`TASK_FAILED`)다 — 오류 경계로 받을 수 있다. 맞는 파일이 없으면 빈 목록이고 실패가 아니다.

### 파일 출력

- `bpmn:dataObjectReference`에 `chk:dataOutput`(`path`, `format: md|xlsx|json|txt|csv`, `template?`, `variables?`, `sheet?`, `append`, `store_as`)를 둔다.
- 쓰는 시점은 `dataOutputAssociation`으로 연결된 태스크가 끝날 때다. 그 태스크가 만든 변수는 이미 있다 (결재 폼의 칸을 그 결재의 출력 파일에 넣는 것이 흔하다).
- `path`는 「파일 경로」 규칙을 따른다.
- `template`가 비면 `variables`의 표를 만든다. 둘 다 비면 검사 오류다. 프로토타입에서는 이때 모든 변수가 쏟아졌다.
- **`store_as`는 필수다.** 첨부·후속 태스크가 파일 경로를 받는 유일한 길이다. 들어가는 값은 **출력 폴더 기준 상대 경로**다 (실행하는 PC의 절대 경로를 업무 값에 섞지 않는다).
- **형식마다 무엇을 쓰나** — `variables`의 값이 **사전 목록**이면 표로 본다 (열은 사전 열쇠의 합집합, 처음 나온 순서).

  | `format` | `template`가 있으면 | `variables`만 있으면 |
  | --- | --- | --- |
  | `md`·`txt` | 채운 텍스트 그대로 | 이름마다 한 토막 — 표면 표(`md`)·`열: 값` 줄(`txt`), 아니면 `이름: 값` |
  | `csv` | 채운 텍스트 그대로 | **이름 하나**만 쓸 수 있다. 표면 그 표, 아니면 `이름,값` 두 줄 |
  | `json` | 채운 텍스트가 JSON이어야 한다 | `{이름: 값}` 객체 |
  | `xlsx` | 쓸 수 없다 (검사 오류) | **이름마다 시트 하나.** 시트 이름은 `sheet`(이름이 하나일 때만) 또는 변수 이름 |

- `append: true`는 `md`·`txt`·`csv`만 된다 (`json`·`xlsx`는 이어 붙일 수 없다 — 검사 오류). `csv`를 이어 쓸 때는 열 이름 줄을 다시 쓰지 않는다.
- 파일은 **UTF-8**로 쓴다 (`csv`는 Excel이 바로 열 수 있게 BOM을 붙인다). 줄 끝은 `\n`이다.

### 재생 (결정 수행)

**자율 수행**(Studio 개발 실행)은 AI 태스크가 한 일을 **재생 명세**로 적어 둔다. **결정 수행**(Bot UI 운영 실행)은 그것을 되밟아 모델을 덜 부르거나 아예 부르지 않는다 ([ADR-0010](../decisions/0010-service-apps.md) §2, [ADR-0028](../decisions/0028-replay-memory.md)).

- 재생 명세는 **패키지 안 `memory/specs.json`**에 들어간다 (C1 패키지 구성). 배포된 Bot은 **읽기만** 한다 — 현장 PC마다 다르게 학습되지 않고, 서명으로 무결성이 보장되며, 「어느 판이 무엇을 재생하는가」가 분명하다.
- 명세 하나의 열쇠는 **`(BPM 프로세스 정의 id, 노드 id)`**다. 한 노드에 하나뿐이라, 같은 노드가 한 실행에서 여러 번 돌아도(반복·BX-37) 같은 명세를 쓴다.
- **도구 인자는 값이 아니라 템플릿으로 적는다.** 기록할 때 인자 값이 그 시점 프로세스 변수의 값과 같으면 `{변수}`로 바꿔 둔다 (기본 규칙 7의 템플릿과 같은 모양). 그래야 입력이 달라져도 같은 명세가 맞는다 — 종류에 따라 달라지는 값을 목표 문장에 넣지 말고 입력·업무 파라미터로 받으라는 것이 이 때문이다.

| `replay` | 결정 수행에서 | 언제 쓰나 |
| --- | --- | --- |
| `plan` (**기본**) | 적어 둔 **도구 차례**를 템플릿으로 다시 채워 밟고, **마지막 값 추출만 모델에게 한 번** | 도구가 **읽어 오고** 모델이 판단하는 태스크 |
| `full` | 도구 차례를 밟고 **마지막 답도 기억에서 쓴다** — 모델을 **한 번도 부르지 않는다** | 도구가 **일을 하는** 태스크 (입력·발행·쓰기). 답은 요약이라 재사용해도 된다 |
| `none` | 기억을 쓰지 않고 그냥 돈다 (모델을 부른다) | 매번 판단이 달라지는 태스크 |

- **도구가 없는 AI 태스크에 `full`을 쓸 수 없다** (검사 오류 B12). 아무것도 확인하지 않고 답만 복사하는 꼴이기 때문이다.
- **명세가 없으면 `plan`·`full`도 그냥 돈다** (모델을 부른다). 없다고 실패시키지 않는다 — 처음 배포한 Bot이 멈추면 안 된다.
- **재생이 맞지 않으면 몰래 자율 수행으로 넘어가지 않는다** ([ADR-0010](../decisions/0010-service-apps.md)). 기억에 적힌 도구가 이 PC에 없거나 도구가 실패하면 `TASK_FAILED`로 올려 **오류 경계가 받게** 한다.
- 재생한 노드는 실행 기록에 `node_state: replayed`로 남는다 (C3 — `run_finished.replayed_tasks`가 이것을 센다).

### 보내기 (메일·웹훅)

- **실제로 보내는 일은 실행하는 쪽이 주는 「보내기 어댑터」가 한다.** 엔진은 받는 사람·제목·본문·본문 묶음을 만들어 넘기기만 한다. 어댑터를 주지 않으면 **보내지 않고 실패**한다 (`SEND_FAILED`) — 조용히 삼키지 않는다. Studio 시험 실행은 시험용 어댑터를 끼운다.
- `to`·`cc`·`subject`·`body`·`url`은 템플릿(`{변수}`)이다. `attachments`는 **변수 이름**이고, 그 값은 파일 경로(대개 `dataOutput.store_as`)다.
- `webhook.body`: `all`(변수 전부 — B13 경고), `fields:[이름, 이름]`(적은 변수만), `template:"…"`(채운 텍스트). 본문은 JSON으로 보낸다.
- 보내기가 실패하면 `TaskFailed`로 올라가 **오류 경계가 받는다** (`SEND_FAILED`). 경계가 없으면 실행이 실패한다.
- `store_as`가 있으면 **보낸 결과 요약**이 그 변수에 들어간다 — 메일은 `{"ok": true, "to": 받는 사람 수, "id": 보낸 쪽 id 또는 null}`, 웹훅은 `{"ok": true, "status": 200, "body": 응답 본문}`. 본문·받는 사람 같은 업무 값은 실행 기록에 남지 않는다 (원칙 6).

### 이벤트 (표준)

| 종류 | 쓰는 법 | 비고 |
| --- | --- | --- |
| 타이머 시작 | `timeCycle` — 5필드 cron(`0 9 * * 1-5`) 또는 ISO `R/…` | 서버 실행기·Bot UI의 일정이 이것을 읽는다 |
| 타이머 경계·중간 | `timeDuration`(ISO `PT30M`, `P3D`) 또는 **변수 이름** | 경계는 `cancelActivity="false"`로 비중단. 경계의 반복(`timeCycle`)은 schema 1에서 지원하지 않는다 |
| 메시지 시작·받기·경계·중간 받기 | `messageRef` → `bpmn:message name`. 받기 태스크 외의 받기(경계·중간 받기)도 상관 키는 `chk:receive{correlation}`로 둔다 | 외부 시스템이 Center 메시지 API로 보낸다 (C12, PC는 Bot UI 메시지 수신). 상관 키가 없으면 메시지 시작만 깨운다 |
| 신호 | `signalRef` | 한 실행 안의 가지 사이에서만 |
| 이정표 | `intermediateThrowEvent`에 **이벤트 정의를 두지 않는다** | 지나가기만 하면서 실행 기록에 `node_state`(`task_type: milestone`)를 남긴다. 「어디까지 왔는지」를 콘솔·Studio가 이것으로 보인다. 노드 `name`이 이정표 이름이다 (id 접두어 `Ms_`) |
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
| B5 | 파일 출력에 `store_as`가 있고 `template`·`variables` 중 하나가 있다. `xlsx`에 `template`를 쓰지 않고, `csv`의 `variables`는 이름 하나이며, `append`는 `md`·`txt`·`csv`에만 있다. 파일 목록에 `store_as`가 있고 `pattern`에 경로 구분자가 없다 | 오류 |
| B6 | 실행 위치가 `server`면 UI 태스크·`web`/`desktop` 도메인 AI 태스크·`location: field` 결재가 없다 (C1 R2) | 오류 |
| B7 | 서비스 앱 태스크의 `app_id`에 키 참조가 있다 (자기 것 또는 프로세스 `service_keys`) | 오류 |
| B8 | 결과 필드 타입이 `string`·`int`·`number`·`bool`·`list`·`dict`·`date` 중 하나다. 번호처럼 보이는 문자열(예: 발주번호 `PO-2608-001`)을 `int`로 두면 경고 | 오류 / 경고 |
| B9 | 연결되지 않은 노드가 없다 (들어오는 흐름·나가는 흐름) | 오류 |
| B10 | 노드 id가 생성형(`Activity_[0-9a-z]{7}`)이면 경고 | 경고 |
| B11 | 어떤 경로로는 만들어지지 않는 변수를 읽는다 (예: 한 가지에서만 생기는 결재 칸을 합류 뒤에 읽음, 프로세스 `inputs`에 없는 메시지 본문 변수) | 경고 |
| B12 | 결재 칸 `type`이 C6의 `bool`·`number`·`text`·`choice` 중 하나이고, `choice`에는 `choices`가 있다. UI 태스크 스텝 `action`이 C10 동작 목록 안에 있다. 경계 이벤트는 태스크·하위 프로세스에만 붙는다. 파일 출력 `format`·파일 목록 `sort`·AI 태스크 `replay`가 아는 값이고, **도구 없는 AI 태스크에 `replay: full`이 없다** | 오류 |
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
| 2026-10-04 | 1 | 읽기가 타이머 본문(`timeDate`·`timeDuration`·`timeCycle`)·`signalRef`·`cancelActivity`·정의 수준 `bpmn:signal`을 들고 온다 — §이벤트가 글로만 적어 둔 것을 엔진이 쓸 수 있게 했다 (`Node.timer`·`signal_ref`·`cancel_activity`, `BpmnProcess.signals`) | — |
| 2026-10-04 | 1 | **AI 태스크에 `replay` 추가**(`plan`\|`full`\|`none`)와 「재생」 절 — 재생 명세는 패키지 안 `memory/specs.json`이고, 도구 인자는 **값이 아니라 `{변수}` 템플릿**으로 적는다. B12를 늘림 | [0028](../decisions/0028-replay-memory.md) |
| 2026-10-04 | 1 | **파일 목록 태스크(`chk:fileList`) 추가** — ADR-0025가 식에서 뺀 `파일목록()`의 자리. 「파일 경로」 절(출력 폴더·읽기 허용 폴더)을 새로 두고 파일 출력도 그것을 따르게 함. DMN 판정 규칙(입력 이름은 `inputExpression`, 입력 칸 문법, 적중 정책), 보내기 어댑터, 이정표(`intermediateThrowEvent`)를 적음. B5·B12를 늘림 | [0026](../decisions/0026-file-paths-and-file-list-task.md) |
| 2026-10-01 | 1 | 업무 예제 작업 반영: `inputs[].default`, `chk:receive.payload`, 경계·중간 받기의 상관 키, 케이스 `messages`·`process`·입력 연산자(`$now_plus`, `$test_receiver`), 자동 응답 없는 결재, 기대 결과 비교 규칙, 결재 칸을 C6에 맞춤(`choices`, `date` 없음), `defaults.desktop`, 식의 None·허용 목록, 검사 B11~B14 ([08-business-examples](../08-business-examples/README.md)) | — |
