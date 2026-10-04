/* 생성 파일: packages/contracts/schemas에서 만든다. 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * 실행 하나의 요약 (CON-01 목록·상세). **받을 때 만들어 둔다** — 목록을 그릴 때마다
 * 이벤트를 다시 읽지 않는다.
 */
export interface RunInfo {
  bpm_process_id?: string | null;
  duration_s?: number | null;
  error_code?: string | null;
  events?: number;
  executor?: string | null;
  finished_at?: string | null;
  mode?: string | null;
  run_id: string;
  run_location?: string | null;
  source?: string | null;
  started_at?: string | null;
  status?: string;
  version?: string | null;
  [k: string]: unknown;
}
