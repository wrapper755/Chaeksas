/* 생성 파일: packages/contracts/schemas에서 만든다. 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * 키 하나 (SVC-02). `ServiceAppKey`에서 **`hash`를 뺀 것** + `state`.
 */
export interface AdminKeyInfo {
  allowed_modes?: string[];
  allowed_operations?: string[];
  created_at?: string | null;
  expires_at?: string | null;
  extra_scopes?: string[];
  last_used_at?: string | null;
  name: string;
  prefix: string;
  revoked_at?: string | null;
  state: string;
  [k: string]: unknown;
}
