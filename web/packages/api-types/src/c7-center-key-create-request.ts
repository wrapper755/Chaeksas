/* 생성 파일: packages/contracts/schemas에서 만든다. 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `POST /center-keys` — 관리자 토큰으로만.
 */
export interface CenterKeyCreateRequest {
  expires_at?: string | null;
  name: string;
  type: string;
  [k: string]: unknown;
}
