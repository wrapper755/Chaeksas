import { describe, expect, it } from "vitest";
import { centerRunUrl, isRunId } from "./center-link";

const RUN = "run_20261018_093000_abc123";

describe("「실행 id」 → CON-01 (ADR-0075)", () => {
  it("C3 run_id 모양만 실행 id로 본다", () => {
    expect(isRunId(RUN)).toBe(true);
    expect(isRunId("test_20261018_093000_00ff00")).toBe(true);
    expect(isRunId("reg_1a2b3c4d")).toBe(false);
    expect(isRunId("")).toBe(false);
    expect(isRunId(null)).toBe(false);
  });

  it("주소가 없으면 링크만 없다", () => {
    expect(centerRunUrl("http://localhost:8501/", RUN)).toBe(`http://localhost:8501/runs/${RUN}`);
    expect(centerRunUrl("", RUN)).toBeNull();
    expect(centerRunUrl(undefined, RUN)).toBeNull();
    expect(centerRunUrl("http://c", "reg_1")).toBeNull();
  });
});
