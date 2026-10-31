/** CON-05 「새 작업」의 서버 대상·「취소」/「중지」 단추 (`lib/jobs.ts`, ADR-0063). */
import { describe, expect, it } from "vitest";
import type { DeploymentInfo } from "@chaeksas/api-types/c5-deployment-info";
import { cancelControl, runsOnServer, serverLimit, serverVersions } from "./jobs";

function deployment(
  bot: string,
  version: string,
  target: { type: string; id: string },
  max_concurrency: number | null = null,
): DeploymentInfo {
  return { bpm_process_id: bot, version, target, max_concurrency } as unknown as DeploymentInfo;
}

const ALL = [
  deployment("정산", "1.0.0", { type: "server_runner", id: "*" }, 3),
  deployment("정산", "1.1.0", { type: "server_runner", id: "srv_a" }),
  deployment("정산", "1.1.0", { type: "server_runner", id: "srv_b" }, 2),
  deployment("발주", "1.0.0", { type: "bot_ui", id: "pc_1" }),
];

describe("runsOnServer", () => {
  it("서버 실행기에 배포된 프로세스만 서버다", () => {
    expect(runsOnServer(ALL, "정산")).toBe(true);
    expect(runsOnServer(ALL, "발주")).toBe(false);
    expect(runsOnServer(ALL, "없음")).toBe(false);
  });
});

describe("serverVersions", () => {
  it("어느 실행기든 배포된 판을 겹치지 않게 센다", () => {
    expect(serverVersions(ALL, "정산")).toEqual(["1.0.0", "1.1.0"]);
    expect(serverVersions(ALL, "발주")).toEqual([]);
  });
});

describe("serverLimit", () => {
  it("적은 상한은 수, 적지 않은 것은 「기본」이다", () => {
    expect(serverLimit(ALL, "정산", "1.0.0")).toBe("3");
  });
  it("실행기마다 다르면 모두 보인다", () => {
    expect(serverLimit(ALL, "정산", "1.1.0")).toBe("기본 / 2");
  });
});

describe("cancelControl", () => {
  const server = { type: "server_runner", id: "*" };
  const pc = { type: "bot_ui", id: "pc_1" };
  it("시작 전이면 대상과 상관없이 「취소」", () => {
    for (const state of ["pending", "dispatched", "queued"]) {
      expect(cancelControl({ state, target: server, cancel_requested: false })).toBe("cancel");
      expect(cancelControl({ state, target: pc, cancel_requested: false })).toBe("cancel");
    }
  });
  it("도는 서버 실행은 「중지」, 도는 PC 실행은 끈 단추", () => {
    expect(cancelControl({ state: "accepted", target: server, cancel_requested: false })).toBe("stop");
    expect(cancelControl({ state: "accepted", target: pc, cancel_requested: false })).toBe("pc_running");
  });
  it("이미 요청했거나 끝났으면 단추가 없다", () => {
    expect(cancelControl({ state: "accepted", target: server, cancel_requested: true })).toBeNull();
    expect(cancelControl({ state: "cancelled", target: server, cancel_requested: true })).toBeNull();
    expect(cancelControl({ state: "rejected", target: pc, cancel_requested: false })).toBeNull();
  });
});
