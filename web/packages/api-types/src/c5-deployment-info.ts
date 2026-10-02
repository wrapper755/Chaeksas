/* 생성 파일: packages/contracts/schemas에서 만든다. 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `GET /deployments`의 한 줄. 봉투 자체가 아니라 Center가 정리한 모양이다.
 *
 * 실행하는 쪽에 내려갈 때는 **저장된 봉투 그대로** 간다 (C4 `deployments[]`).
 */
export interface DeploymentInfo {
  bpm_process_id: string;
  content_hash: string;
  deployment_id: string;
  expires_at?: string | null;
  last_result?: string | null;
  max_concurrency?: number | null;
  not_before?: string | null;
  revoked_at?: string | null;
  signed_at: string;
  signed_by: string;
  target: {
    [k: string]: unknown;
  };
  version: string;
  [k: string]: unknown;
}
