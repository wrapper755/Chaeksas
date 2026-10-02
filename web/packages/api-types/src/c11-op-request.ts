/* 생성 파일: packages/contracts/schemas에서 만든다. 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `POST /v1/ops/{operation}` 요청.
 */
export interface OpRequest {
  attempt: number;
  business_key?: string | null;
  call_seq?: number;
  caller: Caller;
  input?: {
    [k: string]: unknown;
  };
  mode: string;
  node_id: string;
  node_instance: number;
  run_id: string;
  /**
   * 이 계약의 schema 번호
   */
  schema: number;
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
