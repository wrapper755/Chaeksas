import Link from "next/link";
import { redirect } from "next/navigation";
import { DataTable, ErrorBanner, StatusBadge, type Column } from "@chaeksas/ui";
import type { RunEvent } from "@chaeksas/api-types/c3-run-event";
import type { RunInfo } from "@chaeksas/api-types/c3-run-info";
import { CENTER_URL, CenterError, center, session } from "@/lib/center";
import { Shell } from "@/components/Shell";
import { LABEL, seconds, time, where } from "../page";

/**
 * CON-01 실행 로그 (상세).
 *
 * **이벤트가 원본이다** — 요약·타임라인·단계 표는 모두 같은 줄에서 만든다. 값은 애초에 오지
 * 않는다 (원칙 6 — 보내는 쪽이 `sanitize()`로 걸렀다).
 *
 * 화면 설계서의 섹션 중 지금 채우는 것은 요약·노드 타임라인·AI 태스크 단계·사람 개입·로그·
 * 원본 이벤트다. UI 태스크는 M4, 이어 돈 기록은 서버 실행(M7)과 함께 온다 — **빈 섹션은
 * 「<종류> 이벤트가 없습니다」 한 줄**이다.
 */

const NODE_STATE: Record<string, string> = {
  started: "실행 중",
  completed: "완료",
  failed: "실패",
  waiting: "기다리는 중",
  replayed: "재생됨",
  skipped: "대기",
};

interface NodeRow {
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

export function counts(events: RunEvent[]): Record<string, number> {
  const found: Record<string, number> = {};
  for (const event of events) found[event.kind] = (found[event.kind] ?? 0) + 1;
  return found;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-h2 font-semibold">{title}</h2>
      {children}
    </section>
  );
}

function Empty({ kind }: { kind: string }) {
  return <p className="text-body-sm text-text-muted">{kind} 이벤트가 없습니다.</p>;
}

export default async function RunPage({ params }: { params: Promise<{ runId: string }> }) {
  const found = await session();
  if (!found) redirect("/login");
  const { runId } = await params;

  let info: RunInfo | null = null;
  let events: RunEvent[] = [];
  let failure: string | null = null;
  try {
    info = await center.run(decodeURIComponent(runId));
    events = (await center.runEvents(decodeURIComponent(runId))).events ?? [];
  } catch (cause) {
    failure = cause instanceof CenterError ? cause.message : "알 수 없는 오류가 생겼습니다";
  }

  const nodes = timeline(events);
  const seen = counts(events);
  const agent = events.filter((e) => e.kind === "agent");
  const human = events.filter((e) => e.kind.startsWith("human_"));
  const logs = events.filter((e) => e.kind === "log");

  const nodeColumns: Array<Column<NodeRow>> = [
    { key: "node_id", header: "노드", mono: true },
    {
      key: "state",
      header: "상태",
      width: "12ch",
      cell: (row) => <StatusBadge group="실행·노드" label={NODE_STATE[row.state] ?? row.state} />,
    },
    { key: "started_at", header: "시작", width: "14ch", cell: (row) => time(row.started_at) },
    { key: "ended_at", header: "끝", width: "14ch", cell: (row) => time(row.ended_at) },
    { key: "seconds", header: "소요", width: "10ch", align: "right", cell: (row) => seconds(row.seconds) },
  ];

  const agentColumns: Array<Column<RunEvent>> = [
    { key: "seq", header: "순번", width: "8ch", align: "right" },
    { key: "ts", header: "시각", width: "14ch", cell: (row) => time(row.ts) },
    { key: "node_id", header: "노드", mono: true, cell: (row) => row.node_id ?? "—" },
    { key: "action", header: "단계", width: "10ch", cell: (row) => String(row.data?.action ?? "—") },
    { key: "tool", header: "도구", cell: (row) => String(row.data?.tool ?? "—") },
  ];

  const humanColumns: Array<Column<RunEvent>> = [
    { key: "seq", header: "순번", width: "8ch", align: "right" },
    { key: "ts", header: "시각", width: "14ch", cell: (row) => time(row.ts) },
    { key: "kind", header: "무엇", width: "16ch" },
    { key: "node_id", header: "노드", mono: true, cell: (row) => row.node_id ?? "—" },
    { key: "layer", header: "종류", width: "10ch", cell: (row) => String(row.data?.layer ?? "—") },
  ];

  const logColumns: Array<Column<RunEvent>> = [
    { key: "ts", header: "시각", width: "14ch", cell: (row) => time(row.ts) },
    { key: "level", header: "수준", width: "8ch", cell: (row) => String(row.data?.level ?? "info") },
    { key: "message", header: "글", cell: (row) => String(row.data?.message ?? "") },
  ];

  return (
    <Shell mode={found.mode} actor={found.actor} centerUrl={CENTER_URL} current="/runs">
      <header className="mb-4 flex items-end justify-between gap-4">
        <div>
          <h1 className="text-h1 font-bold font-mono">{decodeURIComponent(runId)}</h1>
          <p className="text-body text-text-secondary">
            <Link className="underline" href="/runs">
              실행 로그
            </Link>
            로 돌아가기
          </p>
        </div>
      </header>

      {failure ? <ErrorBanner message={failure} /> : null}

      {info ? (
        <div className="flex flex-col gap-6">
          <Section title="요약">
            <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-body sm:grid-cols-4">
              <dt className="text-text-muted">상태</dt>
              <dd>
                <StatusBadge group="실행·노드" label={LABEL[info.status ?? ""] ?? info.status ?? "—"} />
              </dd>
              <dt className="text-text-muted">Bot</dt>
              <dd>
                {info.bpm_process_id ?? "—"}
                {info.version ? ` @${info.version}` : ""}
              </dd>
              <dt className="text-text-muted">실행 위치</dt>
              <dd>{where(info.run_location)}</dd>
              <dt className="text-text-muted">수행 모드</dt>
              <dd>{info.mode === "deterministic" ? "결정 수행" : info.mode === "autonomous" ? "자율 수행" : "—"}</dd>
              <dt className="text-text-muted">시작 · 끝</dt>
              <dd>
                {time(info.started_at)} · {time(info.finished_at)}
              </dd>
              <dt className="text-text-muted">소요</dt>
              <dd>{seconds(info.duration_s)}</dd>
              <dt className="text-text-muted">AI 태스크 단계</dt>
              <dd>{seen.agent ?? 0}</dd>
              <dt className="text-text-muted">이벤트</dt>
              <dd>{info.events}</dd>
            </dl>
            {info.error_code ? <ErrorBanner message={`오류 코드: ${info.error_code}`} /> : null}
          </Section>

          <Section title="노드 타임라인">
            {nodes.length === 0 ? (
              <Empty kind="노드" />
            ) : (
              <DataTable columns={nodeColumns} rows={nodes} rowKey={(row) => row.node_id} caption="노드" />
            )}
          </Section>

          <Section title="AI 태스크 단계">
            {agent.length === 0 ? (
              <Empty kind="AI 태스크" />
            ) : (
              <DataTable columns={agentColumns} rows={agent} rowKey={(row) => String(row.seq)} caption="AI 단계" />
            )}
          </Section>

          <Section title="사람 개입">
            {human.length === 0 ? (
              <Empty kind="결재·확인" />
            ) : (
              <DataTable columns={humanColumns} rows={human} rowKey={(row) => String(row.seq)} caption="사람 개입" />
            )}
          </Section>

          <Section title="로그">
            {logs.length === 0 ? (
              <Empty kind="로그" />
            ) : (
              <DataTable columns={logColumns} rows={logs} rowKey={(row) => String(row.seq)} caption="로그" />
            )}
          </Section>

          <Section title="원본 이벤트">
            <details>
              <summary className="cursor-pointer text-body-sm text-text-muted">{events.length}줄</summary>
              <pre className="overflow-auto bg-bg-surface p-3 text-body-sm">
                {events.map((event) => JSON.stringify(event)).join("\n")}
              </pre>
            </details>
          </Section>
        </div>
      ) : null}
    </Shell>
  );
}
