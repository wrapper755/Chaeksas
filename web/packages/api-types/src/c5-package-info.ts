/* 생성 파일: packages/contracts/schemas에서 만든다. 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `GET /packages`의 한 줄, `POST /packages`의 응답.
 */
export interface PackageInfo {
  content_hash: string;
  id: string;
  kind: string;
  manifest?: Manifest | null;
  missing_resources?: MissingResource[];
  name?: string | null;
  preflight?: PreflightSummary;
  run_location?: string | null;
  signed_at?: string | null;
  signed_by?: string | null;
  status: string;
  uploaded_at: string;
  uploaded_by: string;
  version: string;
  [k: string]: unknown;
}
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
  kind: "bpm_process" | "process_lib" | "toolpack";
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
export interface Provides {
  processes?: ProvidedProcess[];
  tools?: ProvidedTool[];
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
 * 툴팩이 제공하는 도구 하나. `args`는 JSON Schema.
 */
export interface ProvidedTool {
  args?: {
    [k: string]: unknown;
  };
  description?: string | null;
  domain: string;
  name: string;
  [k: string]: unknown;
}
/**
 * 실행에 필요한 것. 모두 선택이고, 없으면 "제한 없음"이다.
 */
export interface Requires {
  core?: string | null;
  domains?: string[];
  extensions?: ExtensionNeed[];
  libs?: string[];
  os?: string[];
  resources?: ResourceRef[];
  runtimes?: string[];
  secrets?: string[];
  service_apps?: ServiceAppNeed[];
  settings?: string[];
  task_types?: TaskTypeNeed[];
  toolpacks?: ToolpackRef[];
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
  key_ref: string;
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
  run_locations: string[];
  [k: string]: unknown;
}
/**
 * 쓰는 툴팩. 해시로 고정한다 (R7).
 */
export interface ToolpackRef {
  content_hash: string;
  id: string;
  version: string;
  [k: string]: unknown;
}
/**
 * 시작 방법. `kind`는 열린 문자열 (알려진 값은 `KNOWN_TRIGGER_KINDS`).
 */
export interface Trigger {
  kind: string;
  name?: string | null;
  [k: string]: unknown;
}
/**
 * 패키지가 쓰는데 Center 리소스 목록에 없는(또는 맞지 않는) 것 하나.
 *
 * C5 `PackageInfo.missing_resources`에 실린다.
 */
export interface MissingResource {
  id: string;
  reason: string;
  type: string;
  [k: string]: unknown;
}
/**
 * Studio가 계산한 사전 점검 요약. 값은 코드 목록이다 (C4 `Readiness.blocked`와 같은 결).
 */
export interface PreflightSummary {
  blocked?: string[];
  warnings?: string[];
  [k: string]: unknown;
}
