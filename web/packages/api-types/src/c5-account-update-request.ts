/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `PUT /accounts/{username}` — 관리자만. 비운 칸은 그대로 둔다.
 *
 * `password`는 **새로 정해 주는 것**이다(지금 비밀번호를 묻지 않는다). 자기 비밀번호를 바꾸는
 * 길은 `PUT /auth/password`다.
 */
export interface AccountUpdateRequest {
  company?: string | null;
  disabled?: boolean | null;
  password?: string | null;
  role?: string | null;
  [k: string]: unknown;
}
