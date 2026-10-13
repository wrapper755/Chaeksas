/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * 지시는 모두 여기 실려 내려온다 (ADR-0007).
 *
 * `deployments`는 **저장된 JSON 그대로** 다룬다 — C2 봉투를 모델로 바꿔 다시 직렬화하면
 * 서명이 깨진다 (C4와 같은 이유로 `dict`다).
 *
 * `jobs`는 **빈자리만큼만** 실린다 (C12 §Center가 작업을 나누는 규칙).
 */
export interface ServerRunnerHeartbeatResponse {
  admin_keys?: AdminKey[] | null;
  approvals?: ApprovalDispatch[];
  cancel_jobs?: string[];
  deployments?: {
    [k: string]: unknown;
  }[];
  jobs?: JobDispatch[];
  key_expires_at?: string | null;
  messages?: MessageDispatch[];
  next_heartbeat_s?: number;
  paused?: boolean;
  server_time: string;
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
  [k: string]: unknown;
}
/**
 * 내려온 메시지 하나 — 기다리는 실행을 깨우거나 메시지 시작으로 새 실행을 만든다.
 */
export interface MessageDispatch {
  correlation?: {
    [k: string]: unknown;
  };
  message_id: string;
  name: string;
  payload?: {
    [k: string]: unknown;
  };
  received_at: string;
  [k: string]: unknown;
}
