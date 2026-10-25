/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * Studio 로그인 응답. **`key`는 이 응답에만 실린다** — Studio는 OS 비밀 저장소에 둔다.
 */
export interface StudioLogin {
  expires_at: string;
  key: string;
  key_id: string;
  username: string;
  [k: string]: unknown;
}
