/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * 업무 자리 — BPM 프로세스(패키지 id)마다 하나. **회사는 적지 않는다** — 패키지의 회사다.
 */
export interface Place {
  department?: string | null;
  scope: string;
  staff?: string | null;
  [k: string]: unknown;
}
