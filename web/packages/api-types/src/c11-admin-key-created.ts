/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * 발급 응답. **원문 `key`는 이 응답에만 실린다** (SVC-02 — 다시 볼 수 없다).
 */
export interface AdminKeyCreated {
  allowed_modes?: string[];
  allowed_operations?: string[];
  created_at?: string | null;
  expires_at?: string | null;
  extra_scopes?: string[];
  key: string;
  last_used_at?: string | null;
  name: string;
  prefix: string;
  revoked_at?: string | null;
  state: string;
  [k: string]: unknown;
}
