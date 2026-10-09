/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `POST /api/v1/runs/{run_id}/events`의 응답.
 */
export interface EventBatchResponse {
  accepted: number;
  duplicates?: number;
  rejected?: RejectedLine[];
  run_id: string;
  [k: string]: unknown;
}
/**
 * 받지 못한 줄 하나.
 */
export interface RejectedLine {
  code: string;
  seq: number;
  [k: string]: unknown;
}
