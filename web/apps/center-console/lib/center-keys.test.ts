/** 키 줄 동작 (`lib/center-keys.ts`) — 폐기·묶음 풀기가 **그 줄의 키에만** 걸리는가. */
import { describe, expect, it } from "vitest";
import { consoleIssuedKeys, currentKey, folderKey, keyActions } from "./center-keys";

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

describe("folderKey", () => {
  const keys = [
    key("worker", "consumer", "revoked", "2026-10-30"),
    key("worker", "consumer", "active", "2026-10-31"),
    key("nowview-relay", "relay", "active", "2026-10-31"),
    // 같은 이름이라도 앞자리가 있으면 콘솔에서 발급한 것 — 폴더 줄과 잇지 않는다.
    key("nowview-relay", "relay", "active", "2026-11-01", "bpm_ctr_abcd1234"),
  ];

  it("일꾼 줄은 일꾼용 키, 키 줄은 연동용·대리 답용 키", () => {
    expect(folderKey({ kind: "consumer", id: "worker" }, keys)?.created_at).toBe("2026-10-31");
    expect(folderKey({ kind: "key", id: "nowview-relay" }, keys)?.prefix).toBe("");
  });

  it("키가 없는 줄은 null — 거둔 확장·읽지 못한 파일", () => {
    expect(folderKey({ kind: "extension", id: "ext-credit" }, keys)).toBeNull();
    expect(folderKey({ kind: "consumer", id: null }, keys)).toBeNull();
    expect(folderKey({ kind: "key", id: "worker" }, keys)).toBeNull();
  });
});

describe("consoleIssuedKeys", () => {
  it("앞자리가 있는 연동용·대리 답용만", () => {
    const keys = [
      key("test1", "integration", "active", "2026-10-31", "bpm_ctr_1"),
      key("nowview-integration", "integration", "active", "2026-10-31"),
      key("pc", "bot_ui", "active", "2026-10-31", "bpm_ctr_2"),
    ];
    expect(consoleIssuedKeys(keys).map((row) => row.name)).toEqual(["test1"]);
  });
});
