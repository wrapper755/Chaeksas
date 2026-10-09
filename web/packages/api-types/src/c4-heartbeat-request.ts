/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `POST /api/v1/bot-ui/heartbeat` — 30초마다 (응답의 `next_heartbeat_s`를 따름).
 */
export interface HeartbeatRequest {
  approval_acks?: ApprovalAck[];
  current_run: CurrentRun | null;
  deployment_results?: DeploymentResult[];
  extensions?: ExtensionState[];
  job_acks?: JobAck[];
  queue: Queue;
  readiness?: Readiness[];
  /**
   * 이 계약의 schema 번호
   */
  schema: number;
  status: string;
  unsent_events?: number | null;
  versions?: Versions | null;
  worker: WorkerState;
  [k: string]: unknown;
}
export interface ApprovalAck {
  accepted: boolean;
  reason?: string | null;
  request_id: string;
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
 * 배포 적용 결정 (CON-03 「최근 배치 결정」). 실행이 아니므로 C3로 보내지 않는다.
 */
export interface DeploymentResult {
  at: string;
  bpm_process_id: string;
  deployment_id: string;
  reason?: string | null;
  result: string;
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
 * 이번 주기에 처리한 작업 하나.
 */
export interface JobAck {
  job_id: string;
  position?: number | null;
  reason?: string | null;
  result: string;
  run_id?: string | null;
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
