/* 생성 파일: packages/contracts/schemas에서 만든다. 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * 확장이 기여한 자원 하나 (C13 §5 공통 카탈로그 항목).
 */
export interface ContributedResource {
  data?: {
    [k: string]: unknown;
  };
  extension_id?: string | null;
  id: string;
  name?: string | null;
  resource_type: string;
  revision?: number | null;
  summary?: string | null;
  updated_at?: string | null;
  used_by?: string[];
  [k: string]: unknown;
}
