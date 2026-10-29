/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `GET /api/v1/external-tasks/{task_id}` — 결과 기다리기 (C15 §결과).
 */
export interface ExternalTaskResult {
  deliveries?: number;
  error?: TaskError | null;
  mode_used?: string | null;
  output?: {
    [k: string]: unknown;
  } | null;
  replayed?: boolean;
  state: string;
  task_id: string;
  usage?: Usage | null;
  [k: string]: unknown;
}
/**
 * 실패·만료의 사유. 코드는 C11 오류 코드 그대로 오거나 `no_consumer`·`timeout`이다.
 */
export interface TaskError {
  code: string;
  detail?: {
    [k: string]: unknown;
  } | null;
  message?: string;
  retryable?: boolean;
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
