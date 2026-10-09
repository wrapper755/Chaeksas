/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `GET /admin/v1/pages` — 화면 고르기 목록.
 */
export interface PageListing {
  pages?: PageBriefRow[];
  /**
   * 이 계약의 schema 번호
   */
  schema: number;
  [k: string]: unknown;
}
/**
 * UIA-02 화면 고르기 한 줄 (C9 `PageBrief`와 같은 칸).
 */
export interface PageBriefRow {
  element_count?: number;
  name?: string;
  page_id: string;
  platform?: string;
  revision?: number;
  updated_at?: string | null;
  [k: string]: unknown;
}
