/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `GET /accounts`의 한 줄. **비밀번호 해시는 나가지 않는다.**
 */
export interface AccountInfo {
  created_at: string;
  created_by: string;
  disabled_at?: string | null;
  last_login_at?: string | null;
  password_changed_at: string;
  role: string;
  state: string;
  username: string;
  [k: string]: unknown;
}
