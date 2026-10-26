/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * 하트비트 응답 — 지시는 모두 여기 실려 내려온다 (ADR-0007).
 *
 * `deployments`는 **저장된 JSON 그대로** 다룬다. C2 봉투를 모델로 바꿔 다시 직렬화하면
 * `canonical_json`이 달라져 서명이 깨지므로, 일부러 `dict`로 둔다.
 */
export interface HeartbeatResponse {
  admin_keys?: AdminKey[] | null;
  approvals?: ApprovalDispatch[];
  cancel_jobs?: string[];
  deployments?: {
    [k: string]: unknown;
  }[];
  disabled?: boolean;
  drop_service_keys?: string[];
  jobs?: JobDispatch[];
  key_expires_at?: string | null;
  next_heartbeat_s?: number;
  rotated_key?: RotatedKey | null;
  server_time: string;
  service_keys?: ServiceKeyDelivery[];
  [k: string]: unknown;
}
/**
 * Admin 공개키 하나. 철회된 키도 `revoked_at`과 함께 내려온다 (C4로 배포된다).
 */
export interface AdminKey {
  key_id: string;
  label?: string | null;
  public_key: string;
  revoked_at?: string | null;
  [k: string]: unknown;
}
/**
 * 답이 정해진 결재 (C6).
 */
export interface ApprovalDispatch {
  answer?: {
    [k: string]: unknown;
  };
  answered_at?: string | null;
  answered_by?: string | null;
  answered_via?: string | null;
  request_id: string;
  state: string;
  [k: string]: unknown;
}
/**
 * 내려온 작업 하나. ack가 올 때까지 매번 실린다.
 */
export interface JobDispatch {
  bpm_process_id: string;
  expires_at?: string | null;
  inputs?: {
    [k: string]: unknown;
  };
  job_id: string;
  note?: string | null;
  requested_at: string;
  requested_by: string;
  version?: string | null;
  virtual_worker?: VirtualWorkerIdentity | null;
  [k: string]: unknown;
}
/**
 * **가상 직원 신원** — 그 실행을 돌리는 가상 직원 (C5 §가상 직원, ADR-0098).
 *
 * Center가 서버 작업을 내려줄 때 붙인다(C12 `JobDispatch.virtual_worker`, ADR-0099). 실행하는
 * 쪽이 출처가 `virtual_worker.*`인 입력의 값으로 푼다 (`core.engine.sourced_inputs`).
 */
export interface VirtualWorkerIdentity {
  id: string;
  name: string;
  supervisors?: string[];
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
 * 하트비트 답에 실린 봉한 키 하나 (C4 §서비스 앱 키 전달).
 */
export interface ServiceKeyDelivery {
  app_id: string;
  bpm_process_id?: string | null;
  expires_at?: string | null;
  key_refs?: string[];
  purpose?: string;
  replaces?: string | null;
  sealed_key: Sealed;
  service_key_id: string;
  source?: string;
  [k: string]: unknown;
}
