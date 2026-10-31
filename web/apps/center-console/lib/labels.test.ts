/** 화면이 같이 쓰는 표기 (`lib/labels.ts`) — CON-01 「시작 방식」, CON-03 「마지막 보고 기준」. */
import { describe, expect, it } from "vitest";
import { lastReportNote, sourceLabel } from "./labels";

describe("sourceLabel", () => {
  it("C3 시작 출처를 모두 사람 말로 옮긴다", () => {
    // contracts/events.py `KNOWN_SOURCES` — 늘면 여기도 는다.
    const known = ["job", "manual", "watch", "schedule", "message", "delegation", "test"];
    for (const one of known) expect(sourceLabel(one)).not.toBe(one);
    expect(sourceLabel("schedule")).toBe("일정");
    expect(sourceLabel("job")).toBe("작업");
  });

  it("모르는 값은 그대로, 없으면 「—」", () => {
    expect(sourceLabel("later_kind")).toBe("later_kind");
    expect(sourceLabel(null)).toBe("—");
    expect(sourceLabel(undefined)).toBe("—");
    expect(sourceLabel("")).toBe("—");
  });
});

describe("lastReportNote", () => {
  const format = (value: string) => `<${value}>`;

  it("오프라인이면 마지막 보고 시각을 붙인다", () => {
    expect(lastReportNote(false, "2026-10-31T09:00:00Z", format)).toBe("마지막 보고 <2026-10-31T09:00:00Z> 기준");
  });

  it("온라인이거나 보고가 없으면 붙이지 않는다", () => {
    expect(lastReportNote(true, "2026-10-31T09:00:00Z", format)).toBeNull();
    expect(lastReportNote(false, null, format)).toBeNull();
    expect(lastReportNote(false, undefined, format)).toBeNull();
  });
});
