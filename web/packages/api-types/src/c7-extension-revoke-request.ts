/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `DELETE /resources/extensions` — 관리자만 (C7·C13). 그 판을 쓰는 Bot은 실행 불가가 된다.
 */
export interface ExtensionRevokeRequest {
  id: string;
  reason?: string;
  version: string;
  [k: string]: unknown;
}
