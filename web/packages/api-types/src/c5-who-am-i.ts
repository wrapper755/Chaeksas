/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `GET /auth/me` — 지금 부르는 쪽. 세션이면 계정, 토큰이면 `account`가 없다.
 */
export interface WhoAmI {
  account?: string | null;
  actor: string;
  role: string;
  [k: string]: unknown;
}
