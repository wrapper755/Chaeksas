/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `GET /enrollments`의 한 줄 (C5 §등록 승인, CON-03·CON-12 「승인 대기」).
 */
export interface EnrollmentInfo {
  code: string;
  decided_at?: string | null;
  decided_by?: string | null;
  enrollment_id: string;
  existing?: ExistingHost | null;
  expires_at: string;
  key_id?: string | null;
  machine_id_prefix: string;
  name: string;
  os: string;
  reason?: string | null;
  remote_addr?: string | null;
  requested_at: string;
  state: string;
  topics?: string[];
  type: string;
  versions?: {
    [k: string]: unknown;
  };
  [k: string]: unknown;
}
/**
 * 그 기계가 이미 등록돼 있으면 — 승인하면 이 자리를 이어받고 그 키는 폐기된다 (C5).
 */
export interface ExistingHost {
  id: string;
  key_prefix?: string | null;
  last_seen?: string | null;
  name: string;
  [k: string]: unknown;
}
