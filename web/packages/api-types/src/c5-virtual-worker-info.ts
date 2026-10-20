/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `GET /virtual-workers…` — 등록 + 최근 일괄(하나를 읽을 때만).
 */
export interface VirtualWorkerInfo {
  batches?: VirtualWorkerBatch[];
  created_at: string;
  id: string;
  intake: string;
  name: string;
  state?: string;
  supervisors?: string[];
  updated_at: string;
  [k: string]: unknown;
}
/**
 * 일괄 하나 = 접수 Bot 실행 하나 (ADR-0079). **읽을 때** 모은다 — 저장하지 않는다.
 */
export interface VirtualWorkerBatch {
  children?: number;
  children_by_status?: {
    [k: string]: number;
  };
  open_approvals?: string[];
  run_id: string;
  started_at?: string | null;
  status?: string | null;
  [k: string]: unknown;
}
