/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `GET /packages/{id}/place` — 지금 자리와 그 회사, 누가 언제 바꿨나.
 */
export interface PlaceInfo {
  bpm_process_id: string;
  company: string;
  department?: string | null;
  scope: string;
  staff?: string | null;
  updated_at: string;
  updated_by: string;
  [k: string]: unknown;
}
