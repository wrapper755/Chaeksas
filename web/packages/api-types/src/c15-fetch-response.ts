/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

export interface FetchResponse {
  consumer_id?: string | null;
  rotated_token?: RotatedKey | null;
  tasks?: LockedTask[];
  [k: string]: unknown;
}
/**
 * 하트비트 답의 새 키 (C4 §키 회전). 새 키로 첫 요청이 올 때까지 주기마다 실린다.
 */
export interface RotatedKey {
  expires_at?: string | null;
  sealed_key: Sealed;
  [k: string]: unknown;
}
/**
 * 받는 쪽 공개키로만 열리는 한 덩이 (C4 §봉함).
 */
export interface Sealed {
  alg?: string;
  ciphertext: string;
  epk: string;
  nonce: string;
  [k: string]: unknown;
}
/**
 * 일꾼이 받은 일감 하나.
 */
export interface LockedTask {
  business_key?: string | null;
  caller: Caller;
  deadline: string;
  delivery?: number;
  idempotency: Idempotency;
  input?: {
    [k: string]: unknown;
  };
  lock_until: string;
  mode: string;
  operation: string;
  origin: string;
  task_id: string;
  topic: string;
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
