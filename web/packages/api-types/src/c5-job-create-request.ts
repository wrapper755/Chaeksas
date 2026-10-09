/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `POST /jobs`.
 *
 * `requested_by`는 **본문에서 받지 않는다.** 키 이름이나 `X-CHK-Actor` 헤더로 Center가 채운다.
 */
export interface JobCreateRequest {
  bpm_process_id: string;
  expires_at?: string | null;
  idempotency_key?: string | null;
  inputs: {
    [k: string]: unknown;
  };
  note?: string | null;
  target: JobTarget;
  version?: string | null;
  [k: string]: unknown;
}
/**
 * 작업 대상. 서버 실행기는 `id`를 비우거나 `"*"`로 두면 Center가 고른다.
 */
export interface JobTarget {
  id?: string | null;
  type: string;
  [k: string]: unknown;
}
