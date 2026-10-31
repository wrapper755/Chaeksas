/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `POST /api/v1/approvals/{request_id}/answer`.
 *
 * `answered_by`는 **본문에서 받지 않는다.** 콘솔 BFF가 `X-BPM-Actor` 헤더로 보내고,
 * 대리 답용 키는 `X-BPM-On-Behalf-Of`로 보낸다 (ADR-0081 — 그 사람이 담당자일 때만 받는다).
 */
export interface AnswerRequest {
  answer: {
    [k: string]: unknown;
  };
  if_review_digest?: string | null;
  [k: string]: unknown;
}
