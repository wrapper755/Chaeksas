/**
 * UI 자동화 화면(UIA-02·03)이 쓰는 셈 — **화면을 모른다** (vitest가 부른다).
 */

/**
 * UIA-02 실패율 경고 한 줄 → 그 요소의 시맨틱 키.
 *
 * 경고는 앱이 지은 글이다 (C9 `PageDetail.warnings` — `"<시맨틱 키>: <로케이터> (최근 실패 a/b)"`).
 * 키는 **첫 `": "` 앞**이다. 그 모양이 아니면 `null` — 글은 보이고 링크만 없다.
 */
export function warningKey(text: string): string | null {
  const at = text.indexOf(": ");
  return at > 0 ? text.slice(0, at) : null;
}

/**
 * UIA-02 「좁히기 · 시맨틱 키」가 걸린 주소 (GET 폼과 같은 칸 — JS 없이 돈다). `<Link href>`가
 * 받는 모양(`pathname`·`query`)이다 — 경로 타입 검사가 글자 주소를 받지 않는다.
 */
export function narrowToKey<P extends string>(
  here: P,
  pageId: string,
  key: string,
): { pathname: P; query: { page: string; key: string } } {
  return { pathname: here, query: { page: pageId, key } };
}

/** UIA-03 「시도한 로케이터」 한 줄 (C8 `AttemptReport`). */
export interface AttemptRow {
  semantic_key: string;
  locator_key: string;
  succeeded: boolean;
  elapsed_ms: number | null;
  matched_count: number | null;
  failure_reason: string | null;
}

const num = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

/**
 * 보고 원문(`SessionRow.report`) → 「시도한 로케이터」 표. **보낸 차례 그대로**다.
 *
 * 보고는 `dict`로 온다 (C9 — 앱이 받은 것을 그대로 담는다). 모양이 아닌 줄은 버린다.
 */
export function attemptRows(report: Record<string, unknown> | undefined): AttemptRow[] {
  const raw = report?.attempts;
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((one): one is Record<string, unknown> => typeof one === "object" && one !== null)
    .map((one) => ({
      semantic_key: String(one.semantic_key ?? ""),
      locator_key: String(one.locator_key ?? ""),
      succeeded: one.succeeded === true,
      elapsed_ms: num(one.elapsed_ms),
      matched_count: num(one.matched_count),
      failure_reason: one.failure_reason ? String(one.failure_reason) : null,
    }));
}
