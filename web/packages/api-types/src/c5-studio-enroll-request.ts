/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `POST /api/v1/studio/enroll` — Studio의 등록 요청 (C5 §Studio 등록 요청과 승인, ADR-0093).
 *
 * PC 실행기의 `EnrollRequest`와 같은 결이다 — 등록(`register`)이 없는 Studio라 그 칸만 따로 둔다.
 */
export interface StudioEnrollRequest {
  machine_id: string;
  name: string;
  os: string;
  public_key: string;
  /**
   * 이 계약의 schema 번호
   */
  schema: number;
  versions: StudioVersions;
  [k: string]: unknown;
}
/**
 * Studio의 판 (C5 §Studio 등록 요청과 승인).
 */
export interface StudioVersions {
  core: string;
  studio: string;
  [k: string]: unknown;
}
