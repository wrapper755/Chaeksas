/** CON-02가 세는 일 (`lib/summary.ts`) — **셈을 글이 아니라 숫자로** 본다.
 *
 * 09-gaps §4-9: 이 셈은 TypeScript라 `pnpm typecheck`·`pnpm build`로는 **틀려도 잡히지 않았다**.
 * 파이썬 쪽 시험(`tests/test_console_bot_status.py`)은 **재료가 오는가**와 **같은 흠이 다시
 * 들어오는가**(글)만 본다 — 여기서 재는 것은 **값**이다.
 *
 * 거듭 보는 것 넷.
 *
 * 1. **끝난 실행만** 센다 (C3 — 도는 중인 실행의 셈 칸은 비어 있다).
 * 2. **버전마다 최근 20회만** (목록은 새것부터 온다).
 * 3. **확인률의 분모는 그 칸을 보낸 실행뿐**이다 — 0으로 세면 조용히 낮아진다.
 * 4. **세는 쪽은 제가 세지 않은 칸을 들고 다니지 않는다** (`RunFields` — 한 번 덮어썼다).
 */
import { describe, expect, it } from "vitest";
import type { DeploymentInfo } from "@chaeksas/api-types/c5-deployment-info";
import type { PackageInfo } from "@chaeksas/api-types/c5-package-info";
import type { RunInfo } from "@chaeksas/api-types/c3-run-info";
import { NO_RUNS, SAMPLE, deployedPcs, keyRefsOf, percent, summarize } from "./summary";

const BOT = "finance.invoice";

function run(over: Partial<RunInfo> = {}): RunInfo {
  return {
    schema: 1,
    run_id: `run_2026101${Math.floor(Math.random() * 9)}_090000_abcdef`,
    bpm_process_id: BOT,
    version: "1.0.0",
    status: "success",
    started_at: "2026-10-12T09:00:00+09:00",
    finished_at: "2026-10-12T09:01:00+09:00",
    ...over,
  } as RunInfo;
}

describe("percent", () => {
  it("표본이 없으면 「—」다 (0%로 보이면 「다 실패했다」로 읽힌다)", () => {
    expect(percent(0, 0)).toBeNull();
    expect(percent(3, 0)).toBeNull();
  });

  it("반올림한 백분율", () => {
    expect(percent(1, 3)).toBe("33%");
    expect(percent(2, 3)).toBe("67%");
    expect(percent(20, 20)).toBe("100%");
  });
});

describe("summarize", () => {
  it("(Bot, 버전)으로 묶고 성공·AI·재생을 센다", () => {
    const found = summarize([
      run({ ai_tasks: 2, replayed_tasks: 1 }),
      run({ status: "failed", ai_tasks: 1, replayed_tasks: 1 }),
      run({ version: "2.0.0", ai_tasks: 5 }),
    ]);
    expect([...found.keys()].sort()).toEqual([`${BOT}@1.0.0`, `${BOT}@2.0.0`]);
    const one = found.get(`${BOT}@1.0.0`)!;
    expect([one.sample, one.successes, one.ai_tasks, one.replayed]).toEqual([2, 1, 3, 2]);
    expect(found.get(`${BOT}@2.0.0`)!.sample).toBe(1);
  });

  it("도는 중·기다리는 실행은 표본에 넣지 않는다 (C3 — 요약은 끝날 때 만든다)", () => {
    const found = summarize([run({ status: "running" }), run({ status: "waiting" }), run()]);
    expect(found.get(`${BOT}@1.0.0`)!.sample).toBe(1);
  });

  it("취소도 끝난 실행이라 표본에 들어간다 (성공은 아니다)", () => {
    const one = summarize([run({ status: "cancelled" })]).get(`${BOT}@1.0.0`)!;
    expect([one.sample, one.successes]).toEqual([1, 0]);
  });

  it(`버전마다 최근 ${SAMPLE}회만 센다 (목록은 새것부터 온다)`, () => {
    const many = Array.from({ length: SAMPLE + 5 }, () => run());
    expect(summarize(many).get(`${BOT}@1.0.0`)!.sample).toBe(SAMPLE);
  });

  it("최근 성공 시각은 **처음 만난 성공**이다 (목록이 새것부터 오므로)", () => {
    const one = summarize([
      run({ status: "failed", finished_at: "2026-10-12T11:00:00+09:00" }),
      run({ finished_at: "2026-10-12T10:00:00+09:00" }),
      run({ finished_at: "2026-10-12T09:00:00+09:00" }),
    ]).get(`${BOT}@1.0.0`)!;
    expect(one.last_success).toBe("2026-10-12T10:00:00+09:00");
  });

  it("확인률의 분모는 **그 칸을 보낸 실행**뿐이다 (0으로 세면 조용히 낮아진다)", () => {
    const one = summarize([
      run({ confirmations: 2 }),
      run({ confirmations: 0 }),
      run(), // 옛 Bot UI — 그 칸이 없다
    ]).get(`${BOT}@1.0.0`)!;
    expect([one.sample, one.confirmations, one.confirm_sample]).toEqual([3, 2, 2]);
    expect(percent(one.confirmations, one.confirm_sample)).toBe("100%");
  });

  it("id·버전·상태가 없는 줄은 건너뛴다 (Studio가 보낸 기록에는 Bot이 없다)", () => {
    const found = summarize([
      run({ bpm_process_id: undefined }),
      run({ version: undefined }),
      run({ status: undefined }),
    ]);
    expect(found.size).toBe(0);
  });

  it("세는 쪽은 **제가 세지 않은 칸을 들고 다니지 않는다** (한 번 덮어썼다)", () => {
    const one = summarize([run()]).get(`${BOT}@1.0.0`)!;
    expect(Object.keys(one).sort()).toEqual(Object.keys(NO_RUNS).sort());
    expect(Object.keys(one)).not.toContain("blocked");
    expect(Object.keys(one)).not.toContain("deployments");
  });
});

describe("deployedPcs", () => {
  function deployment(over: Partial<DeploymentInfo> = {}): DeploymentInfo {
    return {
      deployment_id: `dep_${Math.random()}`,
      bpm_process_id: BOT,
      version: "1.0.0",
      target: { type: "bot_ui", id: "bui_1111" },
      ...over,
    } as DeploymentInfo;
  }

  it("같은 PC에 두 번 걸려 있으면 **PC 수보다 건수가 크다**", () => {
    const found = deployedPcs([deployment(), deployment()], BOT, "1.0.0");
    expect(found).toEqual({ pcs: 1, deployments: 2 });
  });

  it("다른 판·다른 Bot·서버 대상은 세지 않는다 (열 이름이 「배포된 Bot UI」다)", () => {
    const found = deployedPcs(
      [
        deployment({ target: { type: "bot_ui", id: "bui_2222" } }),
        deployment({ version: "2.0.0" }),
        deployment({ bpm_process_id: "other" }),
        deployment({ target: { type: "server_runner", id: "*" } }),
      ],
      BOT,
      "1.0.0",
    );
    expect(found).toEqual({ pcs: 1, deployments: 1 });
  });
});

describe("keyRefsOf", () => {
  it("상속 참조와 태스크가 따로 적은 참조를 **함께**, 겹치면 한 번만", () => {
    const info = {
      manifest: {
        requires: {
          service_apps: [
            { app_id: "a", operations: ["x"], key_ref: "ref-a", task_key_refs: ["ref-b", "ref-a"] },
            { app_id: "b", operations: ["y"], key_ref: "ref-c" },
          ],
        },
      },
    } as PackageInfo;
    expect(keyRefsOf(info)).toEqual(["ref-a", "ref-b", "ref-c"]);
  });

  it("매니페스트가 없으면 빈 목록이다 (0이 아니라 없는 것이다)", () => {
    expect(keyRefsOf({} as PackageInfo)).toEqual([]);
  });
});
