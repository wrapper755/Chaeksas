/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * 패키지 승인 철회(`POST /packages/{id}/{version}/revoke`)의 본문 — 관리자만.
 */
export interface RevokeRequest {
  reason?: string;
  [k: string]: unknown;
}
