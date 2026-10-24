/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `POST /deployments` — 관리자만. **Center가 봉투를 지어 서명한다** (ADR-0090).
 *
 * `deployment_id`·`content_hash`는 Center가 채운다 (해시는 패키지의 것이다). 받아들이는 규칙은
 * 봉투로 받던 때와 **같은 함수**(`validate_deployment`)다.
 */
export interface DeploymentRequest {
  bpm_process_id: string;
  expires_at?: string | null;
  max_concurrency?: number | null;
  not_before?: string | null;
  target: {
    [k: string]: unknown;
  };
  version: string;
  [k: string]: unknown;
}
