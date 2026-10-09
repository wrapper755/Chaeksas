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
  approvals?: {
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
