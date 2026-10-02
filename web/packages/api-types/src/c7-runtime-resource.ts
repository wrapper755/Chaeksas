/* 생성 파일: packages/contracts/schemas에서 만든다. 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * 실행하는 쪽이 보고한 런타임 (C4 등록·하트비트, C12).
 */
export interface RuntimeResource {
  browsers?: string[];
  desktop_backend?: string | null;
  extensions?: {
    [k: string]: unknown;
  }[];
  host: RuntimeHost;
  os?: string | null;
  versions?: {
    [k: string]: string;
  };
  [k: string]: unknown;
}
export interface RuntimeHost {
  id: string;
  name?: string | null;
  type: string;
  [k: string]: unknown;
}
