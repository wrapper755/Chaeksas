/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `POST /api/v1/approvals/{request_id}/answer`.
 *
 * `answered_by`는 **본문에서 받지 않는다.** 콘솔 BFF가 `X-CHK-Actor` 헤더로 보낸다.
 */
export interface AnswerRequest {
  answer: {
    [k: string]: unknown;
  };
  [k: string]: unknown;
}
