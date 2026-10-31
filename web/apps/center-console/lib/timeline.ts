/**
 * CON-01 상세 「노드 타임라인」의 셈 — 노드 줄 모으기, 가로 막대 자리, LLM 단계 수.
 *
 * **화면을 모른다** — 막대의 자리는 0~1 비율로만 주고 색은 페이지가 `status_map`에서 고른다
 * (여기서 `@chaeksas/ui`를 들이면 React 구성요소까지 따라와 vitest가 못 부른다).
 */
import type { RunEvent } from "@chaeksas/api-types/c3-run-event";
import type { ResumeRow } from "./summary";

export interface NodeRow {
  node_id: string;
  state: string;
  started_at: string | null;
  ended_at: string | null;
  seconds: number | null;
}

/** 노드마다 **처음 시작**과 **마지막 상태**를 모은다 (반복·재시도는 한 줄로 접는다). */
export function timeline(events: RunEvent[]): NodeRow[] {
  const byNode = new Map<string, NodeRow>();
  for (const event of events) {
    if (event.kind !== "node_state" || !event.node_id) continue;
    const state = String(event.data?.state ?? "");
    const found = byNode.get(event.node_id) ?? {
      node_id: event.node_id,
      state,
      started_at: null,
      ended_at: null,
      seconds: null,
    };
    if (state === "started" && !found.started_at) found.started_at = event.ts;
    if (state !== "started") found.ended_at = event.ts;
    found.state = state;
    byNode.set(event.node_id, found);
  }
  return [...byNode.values()].map((row) => ({
    ...row,
    seconds:
      row.started_at && row.ended_at
        ? (new Date(row.ended_at).getTime() - new Date(row.started_at).getTime()) / 1000
        : null,
  }));
}

/** 막대 한 조각의 자리 — 실행 전체 폭에 대한 비율 (0~1). */
export interface Segment {
  left: number;
  width: number;
}

export interface NodeBar {
  node_id: string;
  state: string;
  /** 시작·끝 시각이 없어 자리를 모르면 `null` — 줄은 보이고 막대만 없다. */
  bar: Segment | null;
  /** 이 노드가 기다린 구간 (점선). 서버 실행만 있다 (C3 `run_waiting`·`run_resumed`). */
  waits: Segment[];
}

const at = (iso: string | null | undefined): number | null => {
  if (!iso) return null;
  const ms = new Date(iso).getTime();
  return Number.isFinite(ms) ? ms : null;
};

/**
 * 노드 줄 → 가로 막대 (CON-01 「노드 타임라인」).
 *
 * 폭 전체는 **실행의 시작~끝**이다 — 시작은 `startedAt`(없으면 가장 이른 줄), 끝은 `finishedAt`
 * (도는 중이면 `now` — 가장 늦은 줄보다 이르면 그 줄). 끝나지 않은 노드는 끝까지 간다.
 * 시작이 없는 노드(대기·재생만 찍힌 것)는 그 시각에 **폭 0** 막대다(페이지가 눈금으로 그린다).
 *
 * 기다림은 `node_id`로 그 노드 줄에 겹친다. 아직 기다리는 중(`resumed_at`이 없음)이면 끝까지 간다.
 */
export function bars(
  rows: NodeRow[],
  waits: ResumeRow[],
  span: { startedAt?: string | null; finishedAt?: string | null; now: string },
): NodeBar[] {
  const times = [
    ...rows.flatMap((row) => [at(row.started_at), at(row.ended_at)]),
    ...waits.flatMap((row) => [at(row.since), at(row.resumed_at)]),
  ].filter((one): one is number => one !== null);
  const start = at(span.startedAt) ?? (times.length > 0 ? Math.min(...times) : null);
  const latest = times.length > 0 ? Math.max(...times) : null;
  const end = at(span.finishedAt) ?? Math.max(at(span.now) ?? 0, latest ?? 0);
  const total = start === null ? 0 : end - start;

  const place = (from: number | null, to: number | null): Segment | null => {
    if (start === null || from === null) return null;
    if (total <= 0) return { left: 0, width: to === null ? 1 : 0 };
    const clamp = (value: number) => Math.min(1, Math.max(0, (value - start) / total));
    const left = clamp(from);
    return { left, width: Math.max(0, clamp(to ?? end) - left) };
  };

  return rows.map((row) => {
    const from = at(row.started_at) ?? at(row.ended_at);
    // 끝난 노드(완료·실패·재생·대기)는 마지막 상태의 시각에서 멈추고, 도는·기다리는 노드는 끝까지.
    const open = row.state === "started" || row.state === "waiting";
    const to = open ? null : (at(row.ended_at) ?? from);
    return {
      node_id: row.node_id,
      state: row.state,
      bar: place(from, to),
      waits: waits
        .filter((wait) => wait.node_id === row.node_id)
        .map((wait) => place(at(wait.since), at(wait.resumed_at)))
        .filter((one): one is Segment => one !== null),
    };
  });
}

/** 모델을 부르는 `agent` 단계 (C3 `action`). `finish`는 재생이면 모델 없이 되밟은 것이다. */
const MODEL_ACTIONS = new Set(["plan", "extract"]);

/**
 * 「LLM 단계」 — **모델을 부른** AI 태스크 단계 수 (CON-01 요약).
 *
 * `plan`·`extract`는 늘 모델이다. `finish`는 자율 수행이면 모델의 마지막 답이고, 재생(그 노드에
 * `node_state: replayed`)이면 명세를 되밟은 것이라 세지 않는다. `tool`은 도구를 부른 것이다.
 */
export function llmSteps(events: RunEvent[]): number {
  const replayed = new Set(
    events
      .filter((e) => e.kind === "node_state" && e.data?.state === "replayed" && e.node_id)
      .map((e) => e.node_id as string),
  );
  return events.filter((e) => {
    if (e.kind !== "agent") return false;
    const action = String(e.data?.action ?? "");
    if (MODEL_ACTIONS.has(action)) return true;
    return action === "finish" && !replayed.has(e.node_id ?? "");
  }).length;
}
