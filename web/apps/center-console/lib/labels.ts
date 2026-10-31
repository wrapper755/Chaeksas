/**
 * 여러 화면이 같이 쓰는 표기 — **한 자리에 둔다** (CON-01 목록과 CON-03 상세가 따로 들고 있다가
 * 목록만 `schedule`을 그대로 보였다, 09-gaps §8-3).
 *
 * 화면을 모르는 순수 함수라 vitest가 잰다 (`labels.test.ts`).
 */

/** C3·C4 `source` → 사람이 읽는 말. 값은 `contracts/events.py`의 `KNOWN_SOURCES`와 같다. */
const SOURCE: Record<string, string> = {
  job: "작업",
  manual: "수동",
  watch: "감시",
  schedule: "일정",
  message: "메시지",
  delegation: "위임",
  test: "시험",
};

/** 시작 방식. 모르는 값은 **그대로** 보인다(사라지지 않게), 없으면 「—」. */
export function sourceLabel(source: string | null | undefined): string {
  if (!source) return "—";
  return SOURCE[source] ?? source;
}

/**
 * 오프라인 PC 실행기의 실행·대기열 칸에 붙이는 한 줄 (CON-03 목록, U8) — 그 값이 지금이 아니라
 * **언제 보고한 것인지** 말한다. 온라인이거나 아직 보고가 없으면 붙이지 않는다. 시각 글은 부르는
 * 쪽이 짓는다(화면이 쓰는 `time()`과 같은 모양이어야 한다).
 */
export function lastReportNote(
  online: boolean | null | undefined,
  lastSeenAt: string | null | undefined,
  format: (value: string) => string,
): string | null {
  if (online || !lastSeenAt) return null;
  return `마지막 보고 ${format(lastSeenAt)} 기준`;
}
