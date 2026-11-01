/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `POST /api/v1/messages` — 연동용 키 또는 관리자 토큰.
 *
 * `correlation`이 없으면 **메시지 시작만** 된다 (기다리는 실행을 찾을 열쇠가 없다).
 */
export interface MessageRequest {
  correlation?: {
    [k: string]: unknown;
  };
  idempotency_key?: string | null;
  name: string;
  payload?: {
    [k: string]: unknown;
  };
  /**
   * 이 계약의 schema 번호
   */
  schema: number;
  [k: string]: unknown;
}
