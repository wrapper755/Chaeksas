/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `POST /staff`·`PUT /staff/{id}` — 업무의 주체. 사람인지 가상인지 가르지 않는다.
 */
export interface StaffRequest {
  company: string;
  department?: string | null;
  id: string;
  name: string;
  state?: string;
  [k: string]: unknown;
}
