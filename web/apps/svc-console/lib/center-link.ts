/**
 * 「실행 id」 → CON-01 실행 상세 링크 (ADR-0075).
 *
 * **화면을 모르는 함수만** 둔다 — 페이지는 `server-only`를 끌고 와 단위 시험에서 못 부른다
 * (`pnpm test`가 이 파일을 잰다). Center 콘솔 주소는 이 콘솔의 설정이고(**브라우저가 여는** 주소)
 * 콘솔 서버는 Center를 부르지 않는다 — 주소는 링크에만 쓴다.
 */

/** C3 `run_id` — `run_<YYYYMMDD>_<HHMMSS>_<hex6>` (시험 실행은 `test_`). */
const RUN_ID = /^(?:run|test)_\d{8}_\d{6}_[0-9a-f]{6}$/;

/** 실행 id로 읽을 수 있나. 아니면 링크를 걸지 않는다. */
export function isRunId(value: string | null | undefined): value is string {
  return typeof value === "string" && RUN_ID.test(value);
}

/** CON-01 실행 상세 주소. 주소 설정이 없거나 실행 id가 아니면 `null` — **링크만 없다**. */
export function centerRunUrl(base: string | null | undefined, runId: string | null | undefined): string | null {
  const root = (base ?? "").trim().replace(/\/+$/, "");
  if (!root || !isRunId(runId)) return null;
  return `${root}/runs/${encodeURIComponent(runId)}`;
}
