/* 생성 파일: packages/contracts/schemas에서 만든다. 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `GET /bot-uis`의 한 줄 (CON-03).
 *
 * 상태 값은 **Bot UI가 하트비트로 보고한 그대로**다 (C4). Center가 더하는 것은 온라인
 * 판정(`online`)과 키 정보(`key`)뿐이다.
 */
export interface BotUiInfo {
  bot_ui_id: string;
  current_run?: CurrentRun | null;
  disabled?: boolean;
  extensions?: ExtensionState[];
  key?: BotUiKey | null;
  last_seen_at?: string | null;
  machine_id: string;
  name: string;
  online?: boolean;
  os: string;
  queue?: Queue | null;
  readiness?: Readiness[];
  registered_at: string;
  runtimes?: Runtimes | null;
  status?: string | null;
  versions: Versions;
  worker?: WorkerState | null;
  [k: string]: unknown;
}
/**
 * 실행 자리 1건 (ADR-0014).
 */
export interface CurrentRun {
  bpm_process_id: string;
  job_id?: string | null;
  node_id?: string | null;
  run_id: string;
  source: string;
  started_at: string;
  state: string;
  version: string;
  [k: string]: unknown;
}
/**
 * 설치된 확장 하나 (C13).
 */
export interface ExtensionState {
  definition_hash?: string | null;
  enabled?: boolean;
  id: string;
  version: string;
  [k: string]: unknown;
}
/**
 * 그 Bot UI가 쓰는 Center API 키 (C7). **원문·해시는 주지 않는다.**
 */
export interface BotUiKey {
  expires_at?: string | null;
  prefix: string;
  state: string;
  [k: string]: unknown;
}
/**
 * 대기열. `items`는 순서대로.
 */
export interface Queue {
  items?: QueueItem[];
  max: number;
  [k: string]: unknown;
}
export interface QueueItem {
  bpm_process_id: string;
  expires_at?: string | null;
  job_id?: string | null;
  queue_id: string;
  requested_at: string;
  source: string;
  version?: string | null;
  [k: string]: unknown;
}
/**
 * 설치된 Bot 하나의 준비 상태.
 */
export interface Readiness {
  blocked?: string[];
  bpm_process_id: string;
  missing_key_refs?: string[];
  ready: boolean;
  version: string;
  [k: string]: unknown;
}
export interface Runtimes {
  browsers?: string[];
  desktop_backend?: string | null;
  extensions?: ExtensionState[];
  [k: string]: unknown;
}
export interface Versions {
  bot_ui: string;
  core: string;
  worker?: string | null;
  [k: string]: unknown;
}
/**
 * Worker 프로세스 상태. `off`는 "필요할 때 시작, 아직 안 띄움".
 */
export interface WorkerState {
  reserved_for?: string | null;
  restarts?: number;
  session?: string | null;
  state: string;
  version?: string | null;
  [k: string]: unknown;
}
