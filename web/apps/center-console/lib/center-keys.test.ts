/** CON-11 줄 동작 (`lib/center-keys.ts`) — 폐기·묶음 풀기가 **그 줄의 키에만** 걸리는가. */
import { describe, expect, it } from "vitest";
import { keyActions } from "./center-keys";

const pc = { id: "bui_1", type: "bot_ui", name: "재무팀 PC-03" };

describe("keyActions", () => {
  it("사용 중이고 묶이지 않은 키는 폐기만", () => {
    expect(keyActions({ state: "active", bound_to: null })).toEqual({ actions: ["revoke"], reason: null });
  });

  it("자동화로 발급해 PC에 묶인 키는 묶음 풀기도", () => {
    expect(keyActions({ state: "active", bound_to: pc }).actions).toEqual(["revoke", "unbind"]);
  });

  it("승인이 만든 키는 묶여 있어도 묶음 풀기가 없다", () => {
    expect(keyActions({ state: "active", bound_to: pc, enrollment_id: "enr_1" }).actions).toEqual(["revoke"]);
  });

  it("폐기·만료된 키는 할 것이 없고 까닭을 말한다", () => {
    expect(keyActions({ state: "revoked", bound_to: pc })).toEqual({ actions: [], reason: "폐기된 키입니다." });
    const expired = keyActions({ state: "expired", bound_to: pc });
    expect(expired.actions).toEqual([]);
    expect(expired.reason).toContain("만료");
  });
});
