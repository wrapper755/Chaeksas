/** 업무 자리 글 (`lib/organization.ts`) — CON-02 승인 창이 보이는 것 (ADR-0127). */
import { describe, expect, it } from "vitest";
import {
  REMOVE_BLOCKED,
  namesOf,
  orgTree,
  parseNode,
  placeLine,
  removeBlocked,
  triggersLabel,
  workPlaceLabel,
} from "./organization";

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

describe("CON-13 나무", () => {
  it("?node=는 종류와 id — 모르는 모양은 null", () => {
    expect(parseNode("department:purchasing")).toEqual({ kind: "department", id: "purchasing" });
    expect(parseNode("staff:a:b")).toEqual({ kind: "staff", id: "a:b" });
    expect(parseNode("purchasing")).toBeNull();
    expect(parseNode("team:x")).toBeNull();
    expect(parseNode(undefined)).toBeNull();
  });

  it("회사 > 부서 > 직원, 부서 없는 직원은 회사 바로 아래", () => {
    const tree = orgTree(
      [{ id: "c2", name: "회사2" }, { id: "default", name: "기본 회사" }],
      [{ id: "sales", company: "default", name: "영업팀" }, { id: "buy", company: "default", name: "구매팀" }],
      [
        { id: "kim", company: "default", department: "buy", name: "김구매" },
        { id: "boss", company: "default", department: null, name: "대표" },
        { id: "lee", company: "c2", name: "이" },
      ],
    );
    expect(tree.map((one) => one.company.id)).toEqual(["default", "c2"]);
    const [first, second] = tree;
    expect(first?.departments.map((one) => one.department.id)).toEqual(["buy", "sales"]);
    expect(first?.departments[0]?.staff.map((one) => one.id)).toEqual(["kim"]);
    expect(first?.staff.map((one) => one.id)).toEqual(["boss"]);
    expect(second?.staff.map((one) => one.id)).toEqual(["lee"]);
  });

  it("가리키는 것이 있으면 등록 해제를 끈다", () => {
    expect(removeBlocked({ staff: 0, work: [], recent_runs: [] })).toBeNull();
    expect(removeBlocked({ staff: 2 })).toBe(REMOVE_BLOCKED);
    expect(removeBlocked({ work: [{}] })).toBe(REMOVE_BLOCKED);
  });

  it("시작 방법 — 매니페스트 triggers", () => {
    expect(triggersLabel([{ kind: "timer", expression: "0 8 * * 1-5" }, { kind: "message", name: "주문" }])).toBe(
      "일정 0 8 * * 1-5, 메시지 주문",
    );
    expect(triggersLabel([{ kind: "none" }])).toBe("—");
    expect(triggersLabel(undefined)).toBe("—");
  });
});
