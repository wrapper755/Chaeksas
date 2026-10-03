/* 생성 파일: packages/contracts/schemas에서 만든다. 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `GET /admin/v1/usage` (SVC-03). 최근 것부터. **입력·출력 값은 없다** (계약 원칙 6).
 */
export interface UsagePage {
  items?: UsageRecord[];
  total?: number;
  [k: string]: unknown;
}
/**
 * 사용 기록 한 줄 (앱 안, SVC-03). **입력·출력 값은 기록하지 않는다.**
 */
export interface UsageRecord {
  at: string;
  caller_type?: string | null;
  duration_ms: number;
  key_name: string;
  mode: string;
  operation: string;
  run_id?: string | null;
  status: number;
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
