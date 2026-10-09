/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `GET /jobs/{id}` — 만들 때 받은 것 + Center가 아는 것.
 *
 * 취소(`DELETE /jobs/{id}`)도 이 모양으로 답한다. 202일 때는 `cancel_requested=true`이고,
 * 결과는 다음 하트비트의 ack로 `cancel_result`에 적힌다.
 */
export interface JobInfo {
  bpm_process_id: string;
  cancel_requested?: boolean;
  cancel_result?: string | null;
  dispatched_at?: string | null;
  expires_at?: string | null;
  idempotency_key?: string | null;
  inputs: {
    [k: string]: unknown;
  };
  job_id: string;
  note?: string | null;
  queue_position?: number | null;
  requested_at: string;
  requested_by: string;
  run_id?: string | null;
  run_status?: string | null;
  state: string;
  state_reason?: string | null;
  target: JobTarget;
  version?: string | null;
  [k: string]: unknown;
}
/**
 * 작업 대상. 서버 실행기는 `id`를 비우거나 `"*"`로 두면 Center가 고른다.
 */
export interface JobTarget {
  id?: string | null;
  type: string;
  [k: string]: unknown;
}
