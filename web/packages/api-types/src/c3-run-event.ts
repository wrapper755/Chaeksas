/* 생성 파일: packages/contracts/schemas에서 만든다. 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * 실행 이벤트 한 줄. 로컬 `runs/<run_id>.jsonl`의 한 줄이자 전송 단위.
 *
 * `data`에는 **업무 값·결재 답·비밀·스크린샷을 넣지 않는다** (README 원칙 6).
 */
export interface RunEvent {
  data?: {
    [k: string]: unknown;
  };
  /**
   * 열린 문자열 — 모르는 종류도 저장한다
   */
  kind: string;
  node_id?: string | null;
  run_id: string;
  /**
   * 이 계약의 schema 번호
   */
  schema: number;
  /**
   * 실행 안에서 1부터 단조 증가
   */
  seq: number;
  ts: string;
  [k: string]: unknown;
}
