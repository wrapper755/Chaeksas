/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `GET /api/v1/external-tasks?run_id=`의 한 줄 — 콘솔이 보는 일감 (CON-01 「외부 작업」).
 *
 * **업무 값은 없다** (원칙 6) — 입력·출력·오류 글은 싣지 않고 코드만 싣는다. 자리(`node_id`·
 * `node_instance`·`attempt`·`call_seq`)는 멱등 칸에서 온다.
 */
export interface ExternalTaskInfo {
  acked_at?: string | null;
  attempt?: number;
  call_seq?: number;
  consumers?: string[];
  created_at: string;
  deliveries?: number;
  error_code?: string | null;
  finished_at?: string | null;
  mode: string;
  node_id: string;
  node_instance?: number;
  operation: string;
  origin: string;
  outcome_unknown?: boolean;
  state: string;
  task_id: string;
  topic: string;
  [k: string]: unknown;
}
