/* 생성 파일: packages/contracts/schemas에서 만든다. 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `kind: "deployment"` — 배포.
 */
export interface DeploymentClaim {
  bpm_process_id: string;
  content_hash: string;
  deployment_id: string;
  expires_at?: string | null;
  kind: "deployment";
  max_concurrency?: number | null;
  not_before?: string | null;
  target: DeploymentTarget;
  version: string;
  [k: string]: unknown;
}
/**
 * `{type: "bot_ui" | "server_runner", id}`. 서버 배포는 `id`에 `"*"`를 쓸 수 있다.
 */
export interface DeploymentTarget {
  id: string;
  type: string;
  [k: string]: unknown;
}
