/** 업무 자리 글 (`lib/organization.ts`) — CON-02 승인 창이 보이는 것 (ADR-0127). */
import { describe, expect, it } from "vitest";
import { namesOf, placeLine, workPlaceLabel } from "./organization";

describe("workPlaceLabel", () => {
  const names = { departments: namesOf([{ id: "purchasing", name: "구매팀" }]), staff: { kim: "김구매" } };

  it("자리가 없으면 회사 공통이다", () => {
    expect(workPlaceLabel(null)).toBe("회사 공통");
    expect(workPlaceLabel({ scope: "company" })).toBe("회사 공통");
  });

  it("부서·직원은 이름으로, 모르면 id 그대로", () => {
    expect(workPlaceLabel({ scope: "department", department: "purchasing" }, names)).toBe("부서: 구매팀");
    expect(workPlaceLabel({ scope: "staff", staff: "kim" }, names)).toBe("직원: 김구매");
    expect(workPlaceLabel({ scope: "staff", staff: "lee" }, names)).toBe("직원: lee");
  });

  it("승인 창 한 줄", () => {
    expect(placeLine("기본 회사", "부서: 구매팀")).toBe("회사: 기본 회사 · 업무 자리: 부서: 구매팀");
  });
});
