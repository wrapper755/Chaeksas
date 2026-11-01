/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `GET /companies…` — 셈은 읽을 때 센다.
 */
export interface CompanyInfo {
  bot_uis?: number;
  created_at: string;
  departments?: number;
  id: string;
  name: string;
  processes?: number;
  recent_runs?: RecentRun[];
  staff?: number;
  state?: string;
  studios?: number;
  updated_at: string;
  work?: WorkItem[];
  [k: string]: unknown;
}
export interface RecentRun {
  bpm_process_id?: string | null;
  requested_by?: string | null;
  run_id: string;
  started_at?: string | null;
  status?: string | null;
  [k: string]: unknown;
}
/**
 * 그 자리에 놓인 업무 하나 — 상세가 읽을 때 모은다.
 */
export interface WorkItem {
  bpm_process_id: string;
  triggers?: {
    [k: string]: string;
  }[];
  versions?: string[];
  [k: string]: unknown;
}
