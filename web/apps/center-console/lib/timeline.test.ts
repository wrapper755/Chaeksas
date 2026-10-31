/** CON-01 「노드 타임라인」·「LLM 단계」의 셈 (`lib/timeline.ts`) — 막대 자리를 **숫자로** 본다. */
import { describe, expect, it } from "vitest";
import type { RunEvent } from "@chaeksas/api-types/c3-run-event";
import { resumes } from "./summary";
import { bars, llmSteps, timeline } from "./timeline";

let seq = 0;
const ev = (kind: string, ts: string, node_id: string | null, data: Record<string, unknown> = {}): RunEvent =>
  ({ schema: 1, run_id: "run_20261031_000000_abcdef", seq: ++seq, ts, kind, node_id, data }) as RunEvent;
/** 비율은 부동소수라 소수 여섯째 자리에서 맞춘다. */
const near = <T,>(value: T): T =>
  JSON.parse(JSON.stringify(value), (_k, v) => (typeof v === "number" ? Math.round(v * 1e6) / 1e6 : v));
const t = (s: number) => new Date(Date.UTC(2026, 9, 31, 0, 0, s)).toISOString();

describe("bars", () => {
  it("실행 시작~끝을 폭 전체로 두고 노드 자리를 비율로 준다", () => {
    const events = [
      ev("node_state", t(0), "a", { state: "started" }),
      ev("node_state", t(10), "a", { state: "completed" }),
      ev("node_state", t(10), "b", { state: "started" }),
      ev("node_state", t(100), "b", { state: "completed" }),
    ];
    const out = bars(timeline(events), [], { startedAt: t(0), finishedAt: t(100), now: t(500) });
    expect(near(out[0]?.bar)).toEqual({ left: 0, width: 0.1 });
    expect(near(out[1]?.bar)).toEqual({ left: 0.1, width: 0.9 });
  });

  it("기다린 구간은 그 노드 줄에 겹치고, 아직 기다리면 끝까지 간다", () => {
    const events = [
      ev("node_state", t(0), "ask", { state: "started" }),
      ev("run_waiting", t(20), "ask", { waiting_for: "approval" }),
      ev("run_resumed", t(60), "ask", { after_s: 40, reason: "answer" }),
      ev("node_state", t(80), "ask", { state: "completed" }),
      ev("node_state", t(80), "wait", { state: "started" }),
      ev("run_waiting", t(90), "wait", { waiting_for: "timer" }),
    ];
    const out = bars(timeline(events), resumes(events), { startedAt: t(0), finishedAt: null, now: t(100) });
    expect(near(out[0]?.waits)).toEqual([{ left: 0.2, width: 0.4 }]);
    // 도는 실행 — 끝은 `now`, 기다리는 노드·기다림은 끝까지.
    expect(near(out[1]?.bar)).toEqual({ left: 0.8, width: 0.2 });
    expect(near(out[1]?.waits)).toEqual([{ left: 0.9, width: 0.1 }]);
  });

  it("시작이 없는 노드는 그 시각에 폭 0이고, 시각이 하나도 없으면 막대가 없다", () => {
    const rows = timeline([ev("node_state", t(50), "skip", { state: "skipped" })]);
    expect(bars(rows, [], { startedAt: t(0), finishedAt: t(100), now: t(100) })[0]?.bar).toEqual({
      left: 0.5,
      width: 0,
    });
    const blank = [{ node_id: "x", state: "", started_at: null, ended_at: null, seconds: null }];
    expect(bars(blank, [], { now: t(0) })[0]?.bar).toBeNull();
  });

  it("폭이 0인 실행에서도 나누지 않는다", () => {
    const rows = timeline([
      ev("node_state", t(5), "a", { state: "started" }),
      ev("node_state", t(5), "a", { state: "completed" }),
    ]);
    expect(bars(rows, [], { startedAt: t(5), finishedAt: t(5), now: t(5) })[0]?.bar).toEqual({ left: 0, width: 0 });
  });
});

describe("llmSteps", () => {
  it("plan·extract와 재생이 아닌 finish만 센다", () => {
    const events = [
      ev("agent", t(1), "auto", { step: 1, action: "plan" }),
      ev("agent", t(2), "auto", { step: 2, action: "tool", tool: "pdf" }),
      ev("agent", t(3), "auto", { step: 3, action: "finish" }),
      ev("agent", t(4), "rep", { step: 1, action: "tool", tool: "pdf" }),
      ev("agent", t(5), "rep", { step: 2, action: "finish" }),
      ev("agent", t(6), "rep", { step: 3, action: "extract" }),
      ev("node_state", t(7), "rep", { state: "replayed" }),
    ];
    expect(llmSteps(events)).toBe(3);
  });
});
