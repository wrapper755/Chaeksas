/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `GET /packages/{id}/{version}/dependents`의 한 줄 — 이 패키지를 쓰는 패키지 하나.
 *
 * **읽을 때 센다** (참조 그래프를 저장하지 않는다 — `missing_resources`와 같은 결).
 */
export interface DependentInfo {
  id: string;
  kind: string;
  name?: string | null;
  pinned_hash?: string | null;
  relation: string;
  status: string;
  version: string;
  [k: string]: unknown;
}
