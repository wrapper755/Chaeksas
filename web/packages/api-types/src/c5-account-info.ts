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
  permissions?: string[];
  role: string;
  state: string;
  studio_logins?: StudioLoginInfo[];
  username: string;
  [k: string]: unknown;
}
/**
 * 그 계정이 로그인해 있는 Studio 하나 — 살아 있는 Studio 키 (CON-14 「Studio 로그인」).
 */
export interface StudioLoginInfo {
  created_at: string;
  expires_at?: string | null;
  key_id: string;
  last_used_at?: string | null;
  machine_name: string;
  [k: string]: unknown;
}
