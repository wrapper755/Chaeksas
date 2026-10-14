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
import type { JobInfo } from "@chaeksas/api-types/c5-job-info";
import type { ServerRunnerInfo } from "@chaeksas/api-types/c12-server-runner-info";
import {
  NO_RUNS,
  SAMPLE,
  botLimitRows,
  deployedPcs,
  elapsed,
  keyRefsOf,
  percent,
  queueReason,
  runnerStatus,
  serverDeployments,
  summarize,
} from "./summary";

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

// ───────────────────────────── CON-12 서버 실행 ─────────────────────────────

/** 재는 것 넷: **무엇이 이기는가**(상태), **줄의 출처**, **지어내지 않는 숫자**, **대기 이유**. */

const RUNNER = "srv_1a2b3c4d";

function runner(over: Partial<ServerRunnerInfo> = {}): ServerRunnerInfo {
  return {
    server_runner_id: RUNNER,
    name: "서버-1",
    os: "Ubuntu 24.04",
    status: "running",
    online: true,
    paused: false,
    capacity: { max: 3, running: 1 },
    running: [],
    waiting: [],
    queued: 0,
    readiness: [],
    extensions: [],
    deployment_results: [],
    ...over,
  } as ServerRunnerInfo;
}

function serverDeployment(over: Partial<DeploymentInfo> = {}): DeploymentInfo {
  return {
    deployment_id: "dep_1",
    bpm_process_id: BOT,
    version: "1.0.0",
    content_hash: "sha256:x",
    signed_at: "2026-10-01T09:00:00+09:00",
    signed_by: "admin-1",
    target: { type: "server_runner", id: RUNNER },
    ...over,
  } as DeploymentInfo;
}

function queuedJob(over: Partial<JobInfo> = {}): JobInfo {
  return {
    job_id: "job_1a2b3c4d",
    bpm_process_id: BOT,
    version: "1.0.0",
    state: "pending",
    inputs: {},
    requested_at: "2026-10-12T09:00:00+09:00",
    requested_by: "운영자",
    target: { type: "server_runner" },
    ...over,
  } as JobInfo;
}

describe("runnerStatus", () => {
  it("오프라인이 보고된 상태를 **이긴다** (보고는 지난 이야기다)", () => {
    expect(runnerStatus(runner({ online: false, status: "running" }))).toBe("오프라인");
  });

  it("「일시 중지」는 Center의 뜻이라 실행기가 아직 「running」이라고 해도 이긴다", () => {
    // 거꾸로 두면 막 멈춘 실행기가 한 주기 동안 「동작」으로 보인다.
    expect(runnerStatus(runner({ paused: true, status: "running" }))).toBe("일시 중지");
  });

  it("아는 값은 표기로, 모르는 값은 그대로 (열린 문자열이다)", () => {
    expect(runnerStatus(runner({ status: "draining" }))).toBe("정리 중");
    expect(runnerStatus(runner({ status: "error" }))).toBe("오류");
    expect(runnerStatus(runner({ status: "wedged" }))).toBe("wedged");
  });
});

describe("serverDeployments", () => {
  it("id를 주지 않으면 **서버 배포 전부**다 (대기열은 어느 실행기에도 묶이지 않았다)", () => {
    // PC 봉투가 섞이면 같은 Bot의 PC 상한을 서버 대기열의 「Bot별 상한 n」으로 보인다.
    const found = serverDeployments([
      serverDeployment(),
      serverDeployment({ deployment_id: "dep_other", target: { type: "server_runner", id: "srv_99999999" } }),
      serverDeployment({ deployment_id: "dep_pc", max_concurrency: 1, target: { type: "bot_ui", id: "bui_1" } }),
    ]).map((one) => one.deployment_id);
    expect(found).toEqual(["dep_1", "dep_other"]);
  });

  it("이 실행기 것과 전체(`*`) 것을 함께, PC 배포는 빼고", () => {
    const found = serverDeployments(
      [
        serverDeployment(),
        serverDeployment({ deployment_id: "dep_any", target: { type: "server_runner", id: "*" } }),
        serverDeployment({ deployment_id: "dep_other", target: { type: "server_runner", id: "srv_99999999" } }),
        serverDeployment({ deployment_id: "dep_pc", target: { type: "bot_ui", id: RUNNER } }),
      ],
      RUNNER,
    ).map((one) => one.deployment_id);
    expect(found).toEqual(["dep_1", "dep_any"]);
  });
});

describe("botLimitRows", () => {
  it("줄은 **배포**가 정한다 — 준비 상태를 아직 안 올린 Bot도 보인다", () => {
    // 거꾸로 `readiness`로 줄을 지으면 「배포는 했는데 왜 안 도나」가 화면에서 사라진다.
    const rows = botLimitRows(runner(), [serverDeployment()]);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ bot: BOT, version: "1.0.0", running: 0, readiness: null });
  });

  it("상한이 적혀 있지 않으면 **`null`**이다 (기본값을 베껴 적지 않는다)", () => {
    expect(botLimitRows(runner(), [serverDeployment()])[0]?.limit).toBeNull();
    expect(botLimitRows(runner(), [serverDeployment({ max_concurrency: 2 })])[0]?.limit).toBe(2);
  });

  it("지금 실행 수는 `running[]`에서 세고 **기다리는 실행은 세지 않는다**", () => {
    const found = runner({
      running: [
        { run_id: "run_a", bpm_process_id: BOT, version: "1.0.0", started_at: "2026-10-12T09:00:00+09:00" },
        { run_id: "run_b", bpm_process_id: BOT, version: "1.0.0", started_at: "2026-10-12T09:00:00+09:00" },
        { run_id: "run_c", bpm_process_id: "other", version: "1.0.0", started_at: "2026-10-12T09:00:00+09:00" },
      ],
      waiting: [
        {
          run_id: "run_d",
          bpm_process_id: BOT,
          version: "1.0.0",
          waiting_for: "approval",
          request_id: "apr_1",
          since: "2026-10-12T09:00:00+09:00",
        },
      ],
    } as Partial<ServerRunnerInfo>);
    expect(botLimitRows(found, [serverDeployment()])[0]?.running).toBe(2);
  });

  it("같은 Bot의 판이 둘 살아 있으면 **줄도 둘**이다", () => {
    const rows = botLimitRows(runner(), [
      serverDeployment({ version: "2.0.0" }),
      serverDeployment(),
    ]);
    expect(rows.map((one) => one.version)).toEqual(["1.0.0", "2.0.0"]);
  });

  it("준비는 「꺼 뒀다」와 「없다」를 가른다 (ADR-0043)", () => {
    const ready = (over: Record<string, unknown>) =>
      botLimitRows(
        runner({
          readiness: [{ bpm_process_id: BOT, version: "1.0.0", ready: false, ...over }],
        } as Partial<ServerRunnerInfo>),
        [serverDeployment()],
      )[0]?.readiness?.label;
    expect(ready({ missing_key_refs: ["crm-key"] })).toBe("서비스 앱 키 없음");
    expect(ready({ blocked: ["extension_turned_off"] })).toBe("확장 꺼짐");
    expect(ready({ blocked: ["task_types_unsupported"] })).toBe("확장 없음");
    expect(ready({ blocked: ["something_else"] })).toBe("사전 점검 실행 불가");
  });
});

describe("queueReason", () => {
  it("Center가 적는 사유는 `per_bot_limit` 하나 — n은 **배포 봉투**에서 온다", () => {
    const job = queuedJob({ state_reason: "per_bot_limit" });
    expect(queueReason(job, [runner()], [serverDeployment({ max_concurrency: 2 })])).toBe("Bot별 상한 2");
    // 적혀 있지 않으면 **숫자를 지어내지 않는다**.
    expect(queueReason(job, [runner()], [serverDeployment()])).toBe("Bot별 상한");
  });

  it("사유 없이 남은 것은 「전체 상한」, 다 멈춰 있으면 「일시 중지」", () => {
    expect(queueReason(queuedJob(), [runner()], [])).toBe("전체 상한");
    expect(queueReason(queuedJob(), [runner({ paused: true })], [])).toBe("일시 중지");
    // 하나라도 받을 수 있으면 멈춘 까닭이 아니다.
    expect(queueReason(queuedJob(), [runner({ paused: true }), runner()], [])).toBe("전체 상한");
    // 실행기가 아예 없을 때도 「전체 상한」이다 — 없다는 말은 빈 상태가 한다.
    expect(queueReason(queuedJob(), [], [])).toBe("전체 상한");
  });
});

describe("elapsed", () => {
  const now = new Date("2026-10-12T12:00:00+09:00").getTime();
  const ago = (ms: number) => new Date(now - ms).toISOString();

  it("초·분·시간·일로 끊어 적는다", () => {
    expect(elapsed(ago(5_000), now)).toBe("5초");
    expect(elapsed(ago(3 * 60_000), now)).toBe("3분");
    expect(elapsed(ago(130 * 60_000), now)).toBe("2시간 10분");
    expect(elapsed(ago(27 * 3_600_000), now)).toBe("1일 3시간");
  });

  it("앞으로의 시각은 **0초로 깎는다** (시계가 어긋나도 「-3분」을 보이지 않는다)", () => {
    expect(elapsed(new Date(now + 60_000).toISOString(), now)).toBe("0초");
  });

  it("없는 값·읽을 수 없는 값은 「—」다", () => {
    expect(elapsed(null, now)).toBe("—");
    expect(elapsed("어제", now)).toBe("—");
  });
});
