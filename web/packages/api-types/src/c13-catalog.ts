/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `resources[].catalog_url`의 응답 (§5).
 *
 * **비밀·셀렉터·업무 값을 넣지 않는다.** 카탈로그는 서버망 안에서만 연다.
 */
export interface Catalog {
  items?: CatalogItem[];
  revision?: number | null;
  /**
   * 이 계약의 schema 번호
   */
  schema: number;
  [k: string]: unknown;
}
/**
 * 공통 카탈로그 항목 (§5). `data`의 모양은 확장이 정하고, Center는 해석하지 않는다.
 */
export interface CatalogItem {
  data?: {
    [k: string]: unknown;
  };
  id: string;
  name?: string | null;
  summary?: string | null;
  type: string;
  updated_at?: string | null;
  [k: string]: unknown;
}
