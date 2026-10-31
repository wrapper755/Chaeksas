import { describe, expect, it } from "vitest";
import { buildAppLog } from "./app-logs";

const enrollment = (over: Record<string, unknown> = {}) => ({
  enrollment_id: "enr_1",
  type: "bot_ui",
  code: "ABCD-EFGH",
  name: "현장 PC 1",
  os: "windows",
  machine_id_prefix: "abc",
  requested_at: "2026-10-31T01:00:00+00:00",
  expires_at: "2026-11-01T01:00:00+00:00",
  state: "pending",
  ...over,
});

describe("buildAppLog", () => {
  it("요청·결정·키·배치 결정을 새 것부터 한 줄씩 모은다", () => {
    const rows = buildAppLog({
      enrollments: [enrollment({ state: "approved", decided_at: "2026-10-31T02:00:00+00:00", decided_by: "admin" })],
      keys: [
        {
          key_id: "k1",
          type: "bot_ui",
          name: "현장 PC 1",
          prefix: "chk_ctr_ab",
          created_at: "2026-10-31T02:00:00+00:00",
          revoked_at: "2026-10-31T05:00:00+00:00",
          state: "revoked",
        },
      ],
      hosts: [
        {
          kind: "bot_ui",
          name: "현장 PC 1",
          results: [
            {
              at: "2026-10-31T03:00:00+00:00",
              deployment_id: "dep_1",
              bpm_process_id: "fin.tax",
              version: "1.0.0",
              result: "rejected",
              reason: "expired",
            },
          ],
        },
      ],
    });
    expect(rows.map((one) => one.what)).toEqual(["키 폐기", "설치 거부", "키 발급", "승인", "등록 요청"]);
    expect(rows[1]?.detail).toBe("fin.tax@1.0.0 — 유효 기간 지남");
    expect(rows[3]?.who).toBe("admin");
  });

  it("들이기 비밀로 들어온 서버 실행기는 「자동 승인」이고, 결정 없이 닫힌 요청은 요청 줄에 그렇게 적는다", () => {
    const rows = buildAppLog({
      enrollments: [
        enrollment({ type: "server_runner", state: "approved", decided_at: "2026-10-31T01:00:01+00:00", decided_by: "join_token" }),
        enrollment({ enrollment_id: "enr_2", state: "expired" }),
      ],
      keys: [],
      hosts: [],
    });
    expect(rows.map((one) => one.what)).toContain("자동 승인");
    expect(rows.find((one) => one.what === "자동 승인")?.who).toBe("—");
    expect(rows.filter((one) => one.what === "등록 요청").map((one) => one.detail)).toContain(
      "요청 코드 ABCD-EFGH · 결정 없이 닫힘",
    );
    expect(rows.every((one) => one.at <= "2026-10-31T23:59:59+00:00")).toBe(true);
  });

  it("일꾼·연동용은 앱이 아니라 넣지 않는다", () => {
    const rows = buildAppLog({
      enrollments: [enrollment({ type: "consumer" })],
      keys: [{ key_id: "k", type: "integration", name: "ERP", prefix: "p", created_at: "2026-10-31T00:00:00+00:00", state: "active" }],
      hosts: [],
    });
    expect(rows).toEqual([]);
  });
});
