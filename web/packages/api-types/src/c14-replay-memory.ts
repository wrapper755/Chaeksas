/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `memory/specs.json` 한 벌.
 */
export interface ReplayMemory {
  /**
   * 이 계약의 schema 번호
   */
  schema: number;
  specs?: ReplaySpec[];
  [k: string]: unknown;
}
/**
 * AI 태스크 하나의 재생 명세.
 */
export interface ReplaySpec {
  answer?: string;
  bpm_process_id: string;
  model?: string;
  node_id: string;
  steps?: ReplayStep[];
  version?: string;
  [k: string]: unknown;
}
/**
 * 되밟을 도구 호출 하나.
 */
export interface ReplayStep {
  arguments?: {
    [k: string]: unknown;
  };
  tool: string;
  [k: string]: unknown;
}
