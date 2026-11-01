/** 키 줄 동작 (`lib/center-keys.ts`) — 폐기·묶음 풀기가 **그 줄의 키에만** 걸리는가. */
import { describe, expect, it } from "vitest";
import { currentKey, keyActions } from "./center-keys";

const pc = { id: "bui_1", type: "bot_ui", name: "재무팀 PC-03" };

describe("keyActions", () => {
  it("사용 중이고 묶이지 않은 키는 폐기만", () => {
    expect(keyActions({ state: "active", bound_to: null })).toEqual({ actions: ["revoke"] });
  });

  it("자동화로 발급해 PC에 묶인 키는 묶음 풀기도", () => {
    expect(keyActions({ state: "active", bound_to: pc }).actions).toEqual(["revoke", "unbind"]);
  });

  it("승인이 만든 키는 묶여 있어도 묶음 풀기가 없다", () => {
    expect(keyActions({ state: "active", bound_to: pc, enrollment_id: "enr_1" }).actions).toEqual(["revoke"]);
  });

  it("폐기된 키는 삭제만 — 되살리지 않는다 (폐기 → 삭제)", () => {
    expect(keyActions({ state: "revoked", bound_to: pc }).actions).toEqual(["delete"]);
  });

  it("만료된 키는 폐기부터 — Center는 폐기된 키만 지운다", () => {
    expect(keyActions({ state: "expired", bound_to: pc }).actions).toEqual(["revoke"]);
  });
});

const key = (name: string, type: string, state: string, created_at: string, prefix = "") => ({
  name,
  type,
  state,
  created_at,
  prefix,
});

describe("currentKey", () => {
  it("사용 중인 것이 이긴다", () => {
    const rows = [key("a", "relay", "revoked", "2026-11-02"), key("a", "relay", "active", "2026-11-01")];
    expect(currentKey(rows)?.state).toBe("active");
  });

  it("다 폐기됐으면 가장 최근 것", () => {
    const rows = [key("a", "relay", "revoked", "2026-10-01"), key("a", "relay", "revoked", "2026-10-31")];
    expect(currentKey(rows)?.created_at).toBe("2026-10-31");
    expect(currentKey([])).toBeNull();
  });
});
