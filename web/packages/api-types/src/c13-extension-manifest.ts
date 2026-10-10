/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * 확장 정의 (C13 최상위). 파일 하나 = 확장 하나.
 *
 * schema 2에서 `bot_ui.local_runtimes`의 `command`(명령 배열)가 `entry`(진입점)로 바뀌었다
 * (ADR-0024). 필드의 뜻이 바뀐 것이라 번호를 올렸다 (계약 README 원칙 2).
 */
export interface ExtensionManifest {
  api?: string | null;
  console_url?: string | null;
  contributes?: Contributes;
  description?: string | null;
  docs_url?: string | null;
  id: string;
  name: string;
  publisher: string;
  requires_keys?: KeyNeed[];
  /**
   * 이 계약의 schema 번호
   */
  schema: number;
  service?: Service | null;
  tier: string;
  version: string;
  [k: string]: unknown;
}
/**
 * 기여 지점 (ADR-0018 §2). **모르는 열쇠는 무시한다** (호환 규칙) — `extra="allow"`가 보관한다.
 */
export interface Contributes {
  agent_environments?: AgentEnvironmentContribution[];
  "bot_ui.local_runtimes"?: LocalRuntime[];
  "bot_ui.panels"?: Panel[];
  "bot_ui.utilities"?: Utility[];
  configuration?: ConfigurationItem[];
  "console.pages"?: ConsolePage[];
  preflight?: PreflightContribution[];
  resources?: ResourceContribution[];
  "studio.editors"?: StudioEditorContribution[];
  "studio.resource_views"?: ResourceView[];
  task_types?: TaskTypeContribution[];
  [k: string]: unknown;
}
/**
 * AI 태스크 한 domain의 눈과 손 (`extension_api.AgentEnvironment`, ADR-0037).
 */
export interface AgentEnvironmentContribution {
  domain: string;
  entry: string;
  [k: string]: unknown;
}
/**
 * Bot UI가 띄우고 감시하는 로컬 프로세스 (BUI-09·11).
 *
 * **명령줄은 확장이 적지 않는다** (schema 2, ADR-0024). `entry`가 런타임을 실행하는 코드를
 * 가리키고, Bot UI가 **자기 실행 파일을 자식으로 다시 띄워** 그 `entry`를 부른다 — 설치
 * 파일로 묶은 앱 안에는 콘솔 스크립트가 없기 때문이다.
 *
 * 포트를 코드에 적지 않는다 — 설정 이름(`port_setting`)과 기본값만 둔다 (CLAUDE.md §5).
 */
export interface LocalRuntime {
  default_port?: number | null;
  entry: string;
  health?: string | null;
  id: string;
  label: string;
  port_setting?: string | null;
  reserve?: RuntimeReserve | null;
  shutdown?: RuntimeCall | null;
  start?: string;
  status?: RuntimeCall | null;
  token_dir?: boolean;
  [k: string]: unknown;
}
/**
 * 실행 예약 방법 — Bot UI가 런타임의 계약을 모른 채 실행 동안 그 런타임을 묶는다 (ADR-0014 §4).
 *
 * `POST <path>` `{run_id}`로 예약하고 `DELETE <path>`로 푼다. 관리 토큰은 런타임 폴더의
 * `token_file`에서 읽어 `header`에 싣는다. 409면 다른 쪽이 쓰는 중이다 — Bot은 기다린다.
 */
export interface RuntimeReserve {
  header: string;
  path: string;
  token_file: string;
  [k: string]: unknown;
}
/**
 * 런타임에 보내는 관리 호출 하나 — `{path, header, token_file}`.
 *
 * Bot UI는 런타임의 계약(C10 등)을 **모르고** 이 선언대로만 부른다. 토큰은 런타임 폴더의
 * `token_file`에서 **부를 때마다** 읽는다 — 런타임이 다시 뜨면 토큰이 바뀐다 (ADR-0023).
 */
export interface RuntimeCall {
  header: string;
  path: string;
  token_file: string;
  [k: string]: unknown;
}
/**
 * 플랫폼 화면의 한 칸을 **확장이 그린다** (BUI-09, ADR-0042).
 *
 * 열 이름·단위가 **확장의 말**인 표가 여기로 온다 — 플랫폼이 그리면 그 확장을 알게 된다
 * (ADR-0018). `entry`는 `extension_api.BotUiPanel`이다.
 */
export interface Panel {
  entry: string;
  id: string;
  label: string;
  runtime?: string | null;
  surface: string;
  [k: string]: unknown;
}
/**
 * Bot UI 「도구」 메뉴·탭에 더하는 유틸리티 하나 (BUI-06~08).
 */
export interface Utility {
  entry: string;
  id: string;
  label: string;
  menu?: string;
  needs_runtime?: string | null;
  [k: string]: unknown;
}
/**
 * 설정 화면의 칸 하나 (BUI-03 「확장별 설정」, STU-10, 서버 실행기 설정).
 *
 * **`secret: true`인 칸은 OS 비밀 저장소에 둔다** (ADR-0013). 설정 파일·로그에 남기지 않는다.
 */
export interface ConfigurationItem {
  key: string;
  label: string;
  schema?: {
    [k: string]: unknown;
  };
  scope: string;
  secret?: boolean;
  [k: string]: unknown;
}
/**
 * 그 서비스 앱 관리 콘솔의 고유 화면 (웹 모듈, `web/apps/svc-console`이 불러 쓴다).
 */
export interface ConsolePage {
  id: string;
  label: string;
  module: string;
  [k: string]: unknown;
}
/**
 * 사전 점검 하나 (`extension_api.PreflightCheck`).
 */
export interface PreflightContribution {
  entry: string;
  id: string;
  [k: string]: unknown;
}
/**
 * Center 리소스 목록(C7)에 올릴 자원 갈래. 응답은 §5 공통 카탈로그 형식이다.
 */
export interface ResourceContribution {
  catalog_url: string;
  label: string;
  type: string;
  [k: string]: unknown;
}
/**
 * Studio 속성 패널의 태스크 편집기 (태스크 종류와 따로 더할 때).
 */
export interface StudioEditorContribution {
  entry: string;
  task_type: string;
  [k: string]: unknown;
}
/**
 * Studio 리소스 탐색기(STU-03)의 한 갈래. **선언뿐이라 외부 확장도 쓸 수 있다.**
 */
export interface ResourceView {
  creates_task_field?: string | null;
  creates_task_type?: string | null;
  id: string;
  label: string;
  resource_type: string;
  [k: string]: unknown;
}
/**
 * Studio 팔레트·속성 편집기에 더하는 태스크 종류 하나 (실행기가 수행한다).
 */
export interface TaskTypeContribution {
  bpmn?: string;
  editor?: Editor | null;
  executor?: Executor | null;
  icon?: string | null;
  id: string;
  label: string;
  run_locations?: string[];
  [k: string]: unknown;
}
/**
 * 태스크 편집기. `kind="schema"`면 입력 JSON Schema로 자동 폼을 만든다 (STU-14 방식).
 */
export interface Editor {
  entry?: string | null;
  kind: string;
  [k: string]: unknown;
}
/**
 * `extension_api.TaskExecutor`를 구현한 객체를 가리킨다.
 */
export interface Executor {
  entry: string;
  [k: string]: unknown;
}
/**
 * 이 확장이 쓰는 서비스 앱 키 하나.
 *
 * - `run`: BPM 프로세스가 작업을 부를 때. BPM 프로세스의 키 참조로 지정한다.
 * - `utility`: Bot UI 유틸리티가 쓸 때. `configuration`의 `secret` 칸으로 받는다.
 */
export interface KeyNeed {
  config_key?: string | null;
  extra_scopes?: string[];
  purpose: string;
  [k: string]: unknown;
}
/**
 * 서버 부분. **주소의 출처는 하나다** — Center 리소스 등록(C7)의 `base_url`이 있으면
 * 그것을, 없으면 이 값을 쓴다. 클라이언트 설정에 따로 두지 않는다.
 */
export interface Service {
  adapter?: HttpAdapter | null;
  base_url?: string | null;
  protocol: string;
  [k: string]: unknown;
}
/**
 * C11을 따르지 않는 외부 앱을 **코드 없이** 붙이는 선언 (§4).
 *
 * 해석기는 `chaeksas.core`에 하나뿐이고, 안전 규칙(https만·리다이렉트 금지·사설망 차단·
 * DNS 고정·크기 상한)을 그 해석기가 지킨다.
 */
export interface HttpAdapter {
  allow_private_network?: boolean;
  allowed_hosts?: string[];
  auth?: AdapterAuth | null;
  health?: AdapterHealth | null;
  limits?: AdapterLimits;
  operations?: AdapterOperation[];
  [k: string]: unknown;
}
/**
 * 어느 헤더에 키 참조로 푼 값을 넣나. **쿼리 문자열 인증은 없다** (주소·로그에 키가 남는다).
 */
export interface AdapterAuth {
  name?: string | null;
  type: string;
  [k: string]: unknown;
}
/**
 * 없으면 Center는 상태를 「확인 전」으로 둔다.
 */
export interface AdapterHealth {
  expect_status?: number;
  path: string;
  [k: string]: unknown;
}
export interface AdapterLimits {
  max_response_kb?: number;
  timeout_s?: number;
  [k: string]: unknown;
}
/**
 * 외부 앱의 작업 하나. 기본값이 보수적이다 — 자율 수행만, 멱등 아님.
 *
 * `idempotent: false`인 작업이 결과를 모르는 실패(시간 초과·연결 끊김)를 만나면 자동으로
 * 다시 부르지 않는다. PC는 확인으로 넘기고, 서버는 실행 실패·오류 경계로 보낸다.
 */
export interface AdapterOperation {
  description?: string | null;
  idempotent?: boolean;
  input_schema?: {
    [k: string]: unknown;
  } | null;
  modes?: string[];
  name: string;
  output_schema?: {
    [k: string]: unknown;
  } | null;
  request: AdapterRequest;
  response?: AdapterResponse;
  retry_on?: number[];
  server_ok?: boolean;
  [k: string]: unknown;
}
/**
 * 요청 템플릿. 값은 위치별로 인코딩한다 (§4-2).
 */
export interface AdapterRequest {
  body?: unknown;
  headers?: {
    [k: string]: string;
  };
  method: string;
  path: string;
  query?: {
    [k: string]: string;
  };
  [k: string]: unknown;
}
/**
 * 어디서 출력 필드를 꺼내나. 값은 제한된 JSONPath다.
 */
export interface AdapterResponse {
  error_when?: ErrorWhen | null;
  output?: {
    [k: string]: string;
  };
  [k: string]: unknown;
}
/**
 * 응답이 실패를 뜻하는 조건. `equals`·`not_equals`·`exists` 중 하나만 쓴다.
 */
export interface ErrorWhen {
  equals?: unknown;
  exists?: boolean | null;
  not_equals?: unknown;
  path: string;
  [k: string]: unknown;
}
