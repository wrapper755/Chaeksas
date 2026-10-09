/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `GET /admin/v1/sessions?limit=` — UIA-03 한 벌 (요약 + 이력 + 폴백 분포).
 */
export interface SessionPage {
  counts?: SessionCounts;
  fallback?: FallbackSpread;
  rows?: SessionRow[];
  /**
   * 이 계약의 schema 번호
   */
  schema: number;
  [k: string]: unknown;
}
/**
 * 「최근 UI 세션」 (UIA-01)과 UIA-03 요약 — **보고가 도착한 것만** 센다.
 *
 * **「진행 중」은 없다.** C8 보고는 세션이 **끝날 때** 한 번 오므로 앱은 도는 세션을 모른다
 * (지금 무엇이 도는지는 현장의 BUI-09가 안다). 없는 수를 0으로 보이면 「아무것도 안 돈다」로
 * 읽히므로 칸 자체를 두지 않는다.
 *
 * `test`는 셀렉터 시험(BUI-08, C8 `origin: test`)이고 **나머지 수에 들어가지 않는다** —
 * 시험이 운영 통계를 흔들지 않는다 (C8·C9).
 */
export interface SessionCounts {
  escalated?: number;
  failed?: number;
  healed?: number;
  succeeded?: number;
  test?: number;
  today?: number;
  total?: number;
  [k: string]: unknown;
}
/**
 * UIA-03 「폴백 깊이 분포」 — 요소 하나를 찾기까지 사다리를 몇 칸 내려갔나.
 *
 * `attempts`에서 센다 (C8 보고). 열쇠는 깊이(글자)이고 값은 건수다 — `0`이 **1순위
 * 로케이터로 바로 성공**한 것이다.
 */
export interface FallbackSpread {
  counted?: number;
  depths?: {
    [k: string]: number;
  };
  first_hit?: number;
  [k: string]: unknown;
}
/**
 * UIA-03 「UI 세션 이력」 한 줄 — 보고 하나와 **봉투가 말해 준 것**.
 *
 * `caller`·`mode`·`bpm_process_id`·`host`는 C8 보고에 없다 — C11 호출 봉투
 * (`OpRequest.caller`·`mode`)에서 함께 적어 둔 것이다.
 */
export interface SessionRow {
  at?: string | null;
  bpm_process_id?: string | null;
  caller?: string;
  host?: string | null;
  mode?: string;
  report?: {
    [k: string]: unknown;
  };
  /**
   * 이 계약의 schema 번호
   */
  schema: number;
  [k: string]: unknown;
}
