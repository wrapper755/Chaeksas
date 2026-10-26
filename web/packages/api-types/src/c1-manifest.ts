/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * 패키지 매니페스트 (C1 최상위).
 *
 * `kind="bpm_process"`이고 `run_location`이 없으면 **`server`로 채운다** (서버 우선, 호환 규칙).
 */
export interface Manifest {
  built: Built;
  content_hash: string;
  description?: string | null;
  entry?: string | null;
  human: HumanNeeds;
  id: string;
  inputs?: ManifestInput[];
  kind: "bpm_process" | "process_lib";
  name?: string | null;
  outputs?: string[];
  process_id?: string | null;
  provides?: Provides | null;
  requires: Requires;
  run_location?: ("server" | "pc") | null;
  /**
   * 이 계약의 schema 번호
   */
  schema: number;
  triggers?: Trigger[];
  version: string;
  [k: string]: unknown;
}
/**
 * 누가 언제 무엇으로 빌드했나.
 */
export interface Built {
  at: string;
  by: string;
  core: string;
  spec_version: number;
  [k: string]: unknown;
}
/**
 * 사람 개입 종류. 서버 실행 가능 여부(R2) 판정에 쓴다.
 */
export interface HumanNeeds {
  approval_center?: boolean;
  approval_field?: boolean;
  confirmation?: boolean;
  [k: string]: unknown;
}
/**
 * 진입 정의가 받는 입력 하나 — `chk:process.inputs`를 옮긴 것 (C1). 작업 지시 화면이 칸을 그린다.
 */
export interface ManifestInput {
  default?: {
    [k: string]: unknown;
  };
  description?: string | null;
  name: string;
  required?: boolean;
  source?: string | null;
  type: string;
  [k: string]: unknown;
}
export interface Provides {
  processes?: ProvidedProcess[];
  [k: string]: unknown;
}
/**
 * `process_lib`이 제공하는 공유 BPM 프로세스 하나.
 */
export interface ProvidedProcess {
  ai_tasks?: number | null;
  description?: string | null;
  file: string;
  human?: HumanNeeds | null;
  name?: string | null;
  process_id: string;
  reads?: string[];
  run_location?: ("server" | "pc") | null;
  writes?: string[];
  [k: string]: unknown;
}
/**
 * 실행에 필요한 것. 모두 선택이고, 없으면 "제한 없음"이다.
 */
export interface Requires {
  core?: string | null;
  delegations?: string[];
  domains?: string[];
  extensions?: ExtensionNeed[];
  libs?: string[];
  os?: string[];
  resources?: ResourceRef[];
  runtimes?: string[];
  service_apps?: ServiceAppNeed[];
  settings?: string[];
  task_types?: TaskTypeNeed[];
  tools?: string[];
  [k: string]: unknown;
}
/**
 * 쓰는 확장과 버전 범위 (C13). 외부 확장은 `definition_hash`로 정의를 고정한다.
 */
export interface ExtensionNeed {
  definition_hash?: string | null;
  id: string;
  version: string;
  [k: string]: unknown;
}
/**
 * 확장이 기여한 자원 중 쓰는 것 (예: `{type: "ui_page", id: "erp.order.form"}`).
 */
export interface ResourceRef {
  id: string;
  type: string;
  [k: string]: unknown;
}
/**
 * 부르는 서비스 앱과 **키 참조**. 키 값은 절대 들어가지 않는다 (R5).
 */
export interface ServiceAppNeed {
  app_id: string;
  key_ref?: string | null;
  operations: string[];
  task_key_refs?: string[];
  [k: string]: unknown;
}
/**
 * 확장이 기여한 태스크 종류와, 그 확장 정의에 적힌 실행 위치. R2 판정에 쓴다.
 */
export interface TaskTypeNeed {
  extension: string;
  id: string;
  run_locations?: string[] | null;
  [k: string]: unknown;
}
/**
 * 시작 방법 — 진입 정의의 시작 이벤트 하나를 옮긴 것.
 *
 * `kind`는 `KNOWN_TRIGGER_KINDS` 중 하나다. 타입이 아니라 **R9**가 검사한다 — 위반에
 * `unknown_trigger_kind` 코드를 붙여 Studio·Center가 같은 문구로 말하려고 (R4와 같은 결).
 *
 * **이름과 식은 다른 칸이다** — `name`은 이벤트 이름(C12 메시지 API가 이 이름으로 보낸다),
 * `expression`은 타이머 식(`timeCycle`의 cron·ISO)이다. 한 칸에 담으면 읽는 쪽이 타이머
 * 트리거의 `name`을 메시지 이름으로 읽는다.
 */
export interface Trigger {
  expression?: string | null;
  kind: string;
  name?: string | null;
  [k: string]: unknown;
}
