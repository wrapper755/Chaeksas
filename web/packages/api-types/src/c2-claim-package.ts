/* 생성 파일: packages/contracts/schemas에서 만든다. 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `kind: "package"` — 패키지 승인.
 */
export interface PackageClaim {
  content_hash: string;
  id: string;
  kind: "package";
  version: string;
  [k: string]: unknown;
}
