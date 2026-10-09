/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * 실행 하나의 요약 (CON-01 목록·상세). **받을 때 만들어 둔다** — 목록을 그릴 때마다
 * 이벤트를 다시 읽지 않는다.
 */
export interface RunInfo {
  ai_tasks?: number | null;
  bpm_process_id?: string | null;
  duration_s?: number | null;
  error_code?: string | null;
  events?: number;
  executor?: string | null;
  finished_at?: string | null;
  human_requests?: number | null;
  mode?: string | null;
  replayed_tasks?: number | null;
  run_id: string;
  run_location?: string | null;
  service_calls?: number | null;
  source?: string | null;
  started_at?: string | null;
  status?: string;
  ui_tasks?: number | null;
  version?: string | null;
  [k: string]: unknown;
}
