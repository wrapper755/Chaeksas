/** UIA-02·03의 셈 (`lib/ui-automation.ts`). */
import { describe, expect, it } from "vitest";
import { attemptRows, narrowToKey, warningKey } from "./ui-automation";

describe("warningKey", () => {
  it("앱이 지은 경고 글에서 시맨틱 키를 꺼낸다", () => {
    expect(warningKey("login.submit: css|#go (최근 실패 6/10)")).toBe("login.submit");
    // 로케이터에 `": "`가 있어도 첫 자리에서 자른다.
    expect(warningKey("name: text|a: b (최근 실패 6/10)")).toBe("name");
  });

  it("모양이 아니면 null — 링크만 없다", () => {
    expect(warningKey("알 수 없는 글")).toBeNull();
    expect(warningKey(": 키 없음")).toBeNull();
  });
});

describe("narrowToKey", () => {
  it("좁히기 폼과 같은 칸으로 주소를 짓는다", () => {
    expect(narrowToKey("/ext/ui-automation/selectors", "p1", "login.submit")).toEqual({
      pathname: "/ext/ui-automation/selectors",
      query: { page: "p1", key: "login.submit" },
    });
  });
});

describe("attemptRows", () => {
  it("보낸 차례대로, 모양이 아닌 줄은 버린다", () => {
    const rows = attemptRows({
      attempts: [
        { semantic_key: "a", locator_key: "css|#a", succeeded: false, elapsed_ms: 12, matched_count: 0, failure_reason: "not_found" },
        "깨진 줄",
        { semantic_key: "a", locator_key: "role|button", succeeded: true, elapsed_ms: 5 },
      ],
    });
    expect(rows).toEqual([
      { semantic_key: "a", locator_key: "css|#a", succeeded: false, elapsed_ms: 12, matched_count: 0, failure_reason: "not_found" },
      { semantic_key: "a", locator_key: "role|button", succeeded: true, elapsed_ms: 5, matched_count: null, failure_reason: null },
    ]);
  });

  it("attempts가 없거나 목록이 아니면 빈 표", () => {
    expect(attemptRows(undefined)).toEqual([]);
    expect(attemptRows({ attempts: "x" })).toEqual([]);
  });
});
