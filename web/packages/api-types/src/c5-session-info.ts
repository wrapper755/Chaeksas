/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * 로그인 응답. **`token`은 이 응답에만 실린다** — 콘솔 서버가 쿠키에 담고 브라우저에 내려 주지 않는다.
 */
export interface SessionInfo {
  expires_at: string;
  role: string;
  token: string;
  username: string;
  [k: string]: unknown;
}
