/* 생성 파일: packages/contracts/schemas에서 만든다. 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * 서명 봉투. `payload`는 **받은 그대로** 둔다.
 */
export interface Envelope {
  alg: "ed25519";
  key_id: string;
  payload: {
    [k: string]: unknown;
  };
  /**
   * 이 계약의 schema 번호
   */
  schema: number;
  sig: string;
  signed_at: string;
  [k: string]: unknown;
}
