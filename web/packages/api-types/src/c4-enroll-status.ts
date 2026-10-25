/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `POST …/enroll`의 응답이자 `GET …/enroll/{id}`의 응답 (C4 `EnrollResponse`·`EnrollStatus`).
 */
export interface EnrollStatus {
  code: string;
  enrollment_id: string;
  expires_at: string;
  key_expires_at?: string | null;
  key_name?: string | null;
  poll_after_s?: number;
  reason?: string | null;
  sealed_key?: Sealed | null;
  state: string;
  [k: string]: unknown;
}
/**
 * 받는 쪽 공개키로만 열리는 한 덩이 (C4 §봉함).
 */
export interface Sealed {
  alg?: string;
  ciphertext: string;
  epk: string;
  nonce: string;
  [k: string]: unknown;
}
