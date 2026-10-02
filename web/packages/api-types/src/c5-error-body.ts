/* 생성 파일: packages/contracts/schemas에서 만든다. 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * 오류 응답 본문. C11과 같은 형식이다.
 */
export interface ErrorBody {
  code: string;
  detail?: {
    [k: string]: unknown;
  };
  message: string;
  [k: string]: unknown;
}
