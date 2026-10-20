/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `POST /virtual-workers`·`PUT /virtual-workers/{id}` — 사람이 아닌 업무 주체 (ADR-0085).
 *
 * **기동 허용 목록은 없다** — 접수 Bot의 서명된 `requires.delegations`가 그것이다 (ADR-0079).
 */
export interface VirtualWorkerRequest {
  id: string;
  intake: string;
  name: string;
  state?: string;
  supervisors?: string[];
  [k: string]: unknown;
}
