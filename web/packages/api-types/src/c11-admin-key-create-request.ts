/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `POST /admin/v1/keys`. 기본 권한은 **결정 수행만**이다 (운영 키가 자율 수행을 못 하게).
 */
export interface AdminKeyCreateRequest {
  allowed_modes?: string[];
  allowed_operations?: string[];
  expires_at?: string | null;
  extra_scopes?: string[];
  name: string;
  note?: string | null;
  [k: string]: unknown;
}
