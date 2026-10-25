/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * 승인 응답 (C5). `host_id`는 이어받았으면 그 id, 새 자리면 첫 `register`가 만들 때까지 `None`.
 */
export interface EnrollmentDecision {
  host_id?: string | null;
  key_id: string;
  replaced_key_id?: string | null;
  [k: string]: unknown;
}
