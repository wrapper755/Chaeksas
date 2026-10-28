/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `GET /api/v1/external-topics`의 한 줄 (C15 「정한 것」의 제안 — CON-07 토픽 상태).
 */
export interface TopicStatus {
  consumers?: number;
  last_fetch_at?: string | null;
  oldest_waiting_since?: string | null;
  topic: string;
  waiting?: number;
  [k: string]: unknown;
}
