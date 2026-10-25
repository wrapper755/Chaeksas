/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * 케이스 파일 (`cases/*.json`).
 */
export interface CaseFile {
  cases?: Case[];
  process?: string | null;
  /**
   * 이 계약의 schema 번호
   */
  schema: number;
  [k: string]: unknown;
}
/**
 * 시험 케이스 하나. **패키지에 넣지 않는다** (Studio에서만 쓴다).
 */
export interface Case {
  answered_by?: {
    [k: string]: string;
  };
  approvals?: {
    [k: string]: {
      [k: string]: unknown;
    };
  };
  delegations?: {
    [k: string]: {
      [k: string]: unknown;
    };
  };
  description?: string | null;
  expected?: {
    [k: string]: unknown;
  };
  inputs?: {
    [k: string]: unknown;
  };
  manual?: boolean;
  messages?: CaseMessage[];
  name: string;
  virtual_worker?: VirtualWorkerIdentity | null;
  [k: string]: unknown;
}
/**
 * 시작 뒤 `after_s`초에 보내는 메시지 (Center 메시지 API와 같은 모양).
 */
export interface CaseMessage {
  after_s?: number;
  correlation?: string | null;
  name: string;
  payload?: {
    [k: string]: unknown;
  };
  [k: string]: unknown;
}
/**
 * **가상 직원 신원** — 그 실행을 돌리는 가상 직원 (C5 §가상 직원, ADR-0098).
 *
 * Center가 서버 작업을 내려줄 때 붙이고(C12 `JobDispatch.virtual_worker`) Studio는 케이스가
 * 적는다. 엔진이 `chk:process.virtual_worker_as`가 고른 변수에 넣는다.
 */
export interface VirtualWorkerIdentity {
  id: string;
  name: string;
  supervisors?: string[];
  [k: string]: unknown;
}
