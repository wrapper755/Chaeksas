/* 생성 파일: packages/contracts/schemas에서 만든다. 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `GET /center-keys`의 한 줄. **원문은 들어가지 않는다.**
 */
export interface CenterKeyInfo {
  bound_to?: BoundTo | null;
  created_at: string;
  expires_at?: string | null;
  key_id: string;
  last_used_at?: string | null;
  name: string;
  prefix: string;
  revoked_at?: string | null;
  state: string;
  type: string;
  [k: string]: unknown;
}
/**
 * 키가 묶인 곳. Bot UI용·서버 실행기용 키는 처음 등록한 PC에 묶인다 (C4).
 */
export interface BoundTo {
  first_seen?: string | null;
  id: string;
  machine_name?: string | null;
  name?: string | null;
  type: string;
  [k: string]: unknown;
}
