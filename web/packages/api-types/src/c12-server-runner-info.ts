/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `GET /api/v1/server-runners` 한 줄 (CON-12).
 *
 * `queued`는 **Center의 대기열**이다 — 실행기가 보내는 값이 아니라 Center가 센 것이다
 * (C12 — 서버 쪽 대기열은 Center가 가진다).
 */
export interface ServerRunnerInfo {
  capacity: Capacity;
  key_expires_at?: string | null;
  last_heartbeat_at?: string | null;
  name: string;
  online: boolean;
  os: string;
  paused?: boolean;
  queued?: number;
  registered_at?: string | null;
  running?: RunningRun[];
  server_runner_id: string;
  status: string;
  unsent_events?: number | null;
  versions?: RunnerVersions | null;
  waiting?: WaitingRun[];
  [k: string]: unknown;
}
/**
 * 자리 셈. **`running`은 기다리는 실행을 뺀 수**다 (ADR-0054 §5).
 *
 * Center가 빈자리를 `max - running`으로 계산한다 (C12 §Center가 작업을 나누는 규칙).
 */
export interface Capacity {
  max: number;
  running: number;
  [k: string]: unknown;
}
/**
 * 지금 도는 실행 하나 — 스레드를 쥐고 있다.
 */
export interface RunningRun {
  bpm_process_id: string;
  job_id?: string | null;
  node_id?: string | null;
  run_id: string;
  started_at: string;
  version: string;
  [k: string]: unknown;
}
/**
 * C4 `Versions`와 **칸이 다르다** — 서버에는 Worker가 없다.
 */
export interface RunnerVersions {
  core: string;
  server_runner: string;
  [k: string]: unknown;
}
/**
 * 상태만 남고 **일꾼을 놓은** 실행 (ADR-0054 §1·§3).
 *
 * `waiting_for`에 따라 **짝이 되는 칸이 있어야 한다** — 결재는 `request_id`, 메시지는
 * `message_name`, 타이머는 `until`. `validate_heartbeat()`가 그것을 본다.
 */
export interface WaitingRun {
  bpm_process_id: string;
  correlation?: {
    [k: string]: unknown;
  };
  message_name?: string | null;
  request_id?: string | null;
  run_id: string;
  since: string;
  until?: string | null;
  version: string;
  waiting_for: string;
  [k: string]: unknown;
}
