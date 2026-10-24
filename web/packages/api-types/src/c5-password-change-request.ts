/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `PUT /auth/password` — 자기 비밀번호. 지금 비밀번호가 맞아야 한다.
 */
export interface PasswordChangeRequest {
  current_password: string;
  new_password: string;
  [k: string]: unknown;
}
