/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `GET /admin/v1/path?start=&goal=` — UIA-02 「화면 간 경로 탐색」.
 *
 * 간선은 요소의 `navigates_to`이고 **최단 하나**를 앱이 너비 우선으로 찾는다 (ADR-0040 —
 * SQL에 밀어 넣지 않는다). 길이 없으면 `found: false`이고 **지어내지 않는다**.
 */
export interface PathResult {
  found?: boolean;
  goal: string;
  path?: string[];
  /**
   * 이 계약의 schema 번호
   */
  schema: number;
  start: string;
  [k: string]: unknown;
}
