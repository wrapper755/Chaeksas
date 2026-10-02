/* 생성 파일: packages/contracts/schemas에서 만든다. 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `POST /v1/ops/{operation}` 응답 (200).
 */
export interface OpResponse {
  mode_used: string;
  output?: {
    [k: string]: unknown;
  };
  replayed?: boolean;
  status?: string;
  usage?: Usage | null;
  [k: string]: unknown;
}
/**
 * LLM 사용량. 이름은 C3 `llm_usage`와 같다. **금액은 넣지 않는다.**
 */
export interface Usage {
  input_tokens?: number;
  model: string;
  output_tokens?: number;
  [k: string]: unknown;
}
