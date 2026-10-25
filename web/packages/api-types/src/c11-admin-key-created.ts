/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * 발급 응답. **원문 `key`는 이 응답에만 실린다** (SVC-02 — 다시 볼 수 없다).
 */
export interface AdminKeyCreated {
  allowed_modes?: string[];
  allowed_operations?: string[];
  center_key_id?: string | null;
  created_at?: string | null;
  expires_at?: string | null;
  extra_scopes?: string[];
  issued_by?: string | null;
  issued_for?: IssuedFor | null;
  key: string;
  last_used_at?: string | null;
  name: string;
  prefix: string;
  revoked_at?: string | null;
  state: string;
  [k: string]: unknown;
}
/**
 * 누구를 위해 지은 키인가 (C11 키 레코드). SVC-02 「발급」 열이 이것을 읽는다.
 */
export interface IssuedFor {
  bpm_process_id?: string | null;
  center_key?: {
    [k: string]: string;
  } | null;
  deployment_id?: string | null;
  kind: string;
  target?: ServiceKeyTarget | null;
  [k: string]: unknown;
}
/**
 * 키를 받는 쪽 — 배포 대상 하나. `name`은 SVC-02에 보일 이름이다 (앱은 PC 이름을 모른다).
 */
export interface ServiceKeyTarget {
  id: string;
  name?: string | null;
  type: string;
  [k: string]: unknown;
}
