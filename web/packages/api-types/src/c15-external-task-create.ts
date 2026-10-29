/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `POST /api/v1/external-tasks` — 일감 올리기 (C15 §올리기).
 */
export interface ExternalTaskCreate {
  business_key?: string | null;
  caller: Caller;
  idempotency: Idempotency;
  input?: {
    [k: string]: unknown;
  };
  mode: string;
  operation: string;
  origin?: string;
  /**
   * 이 계약의 schema 번호
   */
  schema: number;
  timeout_s?: number | null;
  topic: string;
  want_result?: boolean;
  [k: string]: unknown;
}
/**
 * 누가 부르는가. `type`은 열린 문자열 (KNOWN_CALLER_TYPES).
 */
export interface Caller {
  bpm_process_id?: string | null;
  host?: string | null;
  type: string;
  version?: string | null;
  [k: string]: unknown;
}
/**
 * C11 멱등 키에서 `operation`을 뺀 다섯 칸 (`operation`은 일감에 따로 있다).
 */
export interface Idempotency {
  attempt: number;
  call_seq?: number;
  node_id: string;
  node_instance: number;
  run_id: string;
  [k: string]: unknown;
}
