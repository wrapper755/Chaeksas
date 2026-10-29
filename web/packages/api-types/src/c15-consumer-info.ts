/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `GET /api/v1/consumers`의 한 줄 (CON-07 「일꾼」).
 */
export interface ConsumerInfo {
  approved_at?: string | null;
  apps?: string[];
  consumer_id: string;
  key_prefix?: string | null;
  last_fetch_at?: string | null;
  name: string;
  topics?: string[];
  [k: string]: unknown;
}
