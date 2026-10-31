import Link from "next/link";
import { redirect } from "next/navigation";
import { DataTable, ErrorBanner, StatusBadge, statusToken, type Column } from "@chaeksas/ui";
import type { RunEvent } from "@chaeksas/api-types/c3-run-event";
import type { RunInfo } from "@chaeksas/api-types/c3-run-info";
import type { ExternalTaskInfo } from "@chaeksas/api-types/c15-external-task-info";
import { CenterError, center, session } from "@/lib/center";
import { FINISHED, TASK_STATE, type ResumeRow, duration, resumes, taskPlace, waitTotals } from "@/lib/summary";
import { type NodeBar, type NodeRow, bars, llmSteps, timeline } from "@/lib/timeline";
import { Shell } from "@/components/Shell";
import { LABEL, seconds, time, where } from "../page";

/**
 * CON-01 로그 (상세).
 *
 * **이벤트가 원본이다** — 요약·타임라인·단계 표는 모두 같은 줄에서 만든다. 값은 애초에 오지
 * 않는다 (원칙 6 — 보내는 쪽이 `sanitize()`로 걸렀다).
 *
 * 화면 설계서의 섹션 중 지금 채우는 것은 요약·노드 타임라인·AI 태스크 단계·
 * 사람 개입·로그·원본 이벤트다. 「이어 돈 기록」은 `run_waiting`·`run_resumed`를 쓰는 서버
 * 실행(M7) 몫이다 — **빈 섹션은 「<종류> 이벤트가 없습니다」 한 줄**이다.
 */

/** C3 `run_waiting.waiting_for` → 표기 (**열린 문자열**이라 모르는 값은 그대로 보인다). */
const WAITING_FOR: Record<string, string> = {
  approval: "결재",
  message: "메시지",
  timer: "타이머",
  delegation: "PC 위임",
  external_task: "외부 작업",
};

/** C3 `run_resumed.reason` → 표기. 없으면 「—」다 (선택 칸이다). */
const RESUME_REASON: Record<string, string> = {
  answer: "답",
  message: "메시지",
  timer: "시각이 됨",
  restart: "실행기 재시작",
  withdraw: "결재 회수",
  delegation: "PC 위임이 끝남",
  external_task: "외부 작업이 끝남",
};

const NODE_STATE: Record<string, string> = {
  started: "실행 중",
  completed: "완료",
  failed: "실패",
  waiting: "기다리는 중",
  replayed: "재생됨",
  skipped: "대기",
};

/** C3 `human_*` 종류 → 표기 (「사람 개입」의 「무엇」). 모르는 종류는 그대로 보인다. */
const HUMAN_KIND: Record<string, string> = {
  human_requested: "요청",
  human_answered: "답",
  human_timeout: "시간 초과",
  human_withdrawn: "회수",
};

/** C3 `human_requested.layer` → 표기. */
const HUMAN_LAYER: Record<string, string> = {
  approval: "결재",
  confirmation: "확인",
};

/**
 * 「노드 타임라인」의 막대 — 노드마다 한 줄 (CON-01).
 *
 * 자리는 `lib/timeline.ts`의 `bars()`가 비율로 주고 색은 `status_map`의 「실행·노드」 색이다.
 * **줄 앞에 노드 id와 상태 글이 있다** — 색만으로 뜻을 전하지 않는다 (스타일 가이드 §7).
 * 기다린 구간은 점선 테두리로 겹친다. 폭이 0인 막대(대기·재생만 찍힌 노드)는 눈금이다.
 */
function Bars({ rows }: { rows: NodeBar[] }) {
  const pct = (value: number) => `${(value * 100).toFixed(2)}%`;
  return (
    <ul className="flex flex-col gap-1" aria-label="노드 타임라인 막대">
      {rows.map((row) => {
        const label = NODE_STATE[row.state] ?? row.state;
        const token = statusToken("실행·노드", label) ?? "neutral";
        return (
          <li key={row.node_id} className="grid grid-cols-[minmax(0,16ch)_10ch_1fr] items-center gap-2 text-body-sm">
            <span className="truncate font-mono" title={row.node_id}>
              {row.node_id}
            </span>
            <span className="text-text-secondary">{label}</span>
            <span
              aria-hidden
              className="relative h-3 overflow-hidden"
              style={{ backgroundColor: "var(--color-bg-subtle)", borderRadius: "var(--radius-full)" }}
            >
              {row.bar ? (
                <span
                  className={`absolute inset-y-0 ${row.bar.width === 0 ? "w-px" : ""}`}
                  style={{
                    left: pct(row.bar.left),
                    ...(row.bar.width === 0 ? {} : { width: pct(row.bar.width) }),
                    backgroundColor: `var(--status-${token}-solid)`,
                    borderRadius: row.bar.width === 0 ? undefined : "var(--radius-full)",
                  }}
                />
              ) : null}
              {row.waits.map((wait, index) => (
                <span
                  key={index}
                  className="absolute inset-y-0 border border-dashed"
                  style={{
                    left: pct(wait.left),
                    width: pct(wait.width),
                    borderColor: "var(--status-waiting-solid)",
                    backgroundColor: "var(--status-waiting-bg)",
                  }}
                />
              ))}
            </span>
          </li>
        );
      })}
    </ul>
  );
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
  const llm = llmSteps(events);
  const seen = counts(events);
  const agent = events.filter((e) => e.kind === "agent");
  const human = events.filter((e) => e.kind.startsWith("human_"));
  const logs = events.filter((e) => e.kind === "log");
  // 「이어 돈 기록」 — `run_waiting`·`run_resumed`를 짝지은다 (**서버 실행만** 남긴다, C3).
  const waits = resumes(events);
  const totals = waitTotals(waits);
  const ended = FINISHED.has(info?.status ?? "");
  // 도는 실행의 끝은 「지금」이다 — 서버 쪽에서 그릴 때의 시각 (화면은 새로 고침으로 다시 그린다).
  const nodeBars = bars(nodes, waits, {
    startedAt: info?.started_at,
    finishedAt: info?.finished_at,
    now: new Date().toISOString(),
  });

  // 「외부 작업」 — 그 실행이 Center에 올린 일감 (C15). **어디서 멈췄는지**(기다림·일꾼이 쥠·다시
  // 나감)는 실행 기록에 없고 Center의 일감에만 있다. 못 읽어도 나머지 상세는 그린다.
  let tasks: ExternalTaskInfo[] = [];
  let tasksFailed = false;
  if (info) {
    try {
      tasks = await center.externalTasks(decodeURIComponent(runId));
    } catch {
      tasksFailed = true;
    }
  }

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
    { key: "kind", header: "무엇", width: "12ch", cell: (row) => HUMAN_KIND[row.kind] ?? row.kind },
    { key: "node_id", header: "노드", mono: true, cell: (row) => row.node_id ?? "—" },
    {
      key: "layer",
      header: "종류",
      width: "10ch",
      // `layer`는 요청 줄에만 있다 (C3) — 답·회수 줄은 「—」다.
      cell: (row) => (row.data?.layer ? (HUMAN_LAYER[String(row.data.layer)] ?? String(row.data.layer)) : "—"),
    },
  ];

  const resumeColumns: Array<Column<ResumeRow>> = [
    {
      key: "waiting_for",
      header: "무엇을",
      width: "10ch",
      cell: (row) => WAITING_FOR[row.waiting_for] ?? row.waiting_for ?? "—",
    },
    { key: "node_id", header: "노드", mono: true, cell: (row) => row.node_id ?? "—" },
    { key: "since", header: "기다리기 시작", width: "14ch", cell: (row) => time(row.since) },
    {
      key: "until",
      header: "기한",
      width: "14ch",
      // 타이머만 기한이 있다 (C3 선택 칸). **지난 기한이 보일 수 있다** — 깨우기는 주기마다
      // 쓸므로 기한은 「그 시각 이후」다 (ADR-0061).
      cell: (row) => time(row.until),
    },
    {
      key: "resumed_at",
      header: "이어 감",
      width: "14ch",
      // **끝난 실행의 짝 없는 줄은 「기다리는 중」이 아니다** — 기다리다 취소되거나 마감으로
      // 닫힌 것이다. 「기다리는 중」이라고 적으면 끝난 실행이 아직 멈춰 있는 것처럼 보인다.
      cell: (row) =>
        row.resumed_at ? time(row.resumed_at) : ended ? "이어 가지 않음" : "기다리는 중",
    },
    {
      key: "seconds",
      header: "기다린 시간",
      width: "14ch",
      align: "right",
      cell: (row) => (row.seconds === null ? "—" : duration(row.seconds)),
    },
    {
      key: "reason",
      header: "깨운 까닭",
      width: "14ch",
      cell: (row) => (row.reason ? (RESUME_REASON[row.reason] ?? row.reason) : "—"),
    },
  ];

  const taskColumns: Array<Column<ExternalTaskInfo>> = [
    { key: "node_id", header: "노드", mono: true, cell: (row) => taskPlace(row) },
    {
      key: "topic",
      header: "토픽",
      mono: true,
      // 일꾼이 없거나 조용한지는 CON-07 「토픽」 표가 말한다.
      cell: (row) => (
        <Link className="underline" href="/resources">
          {row.topic}
        </Link>
      ),
    },
    { key: "operation", header: "작업", mono: true },
    {
      key: "state",
      header: "상태",
      width: "16ch",
      cell: (row) => <StatusBadge group="외부 작업" label={TASK_STATE[row.state] ?? row.state} />,
    },
    { key: "created_at", header: "올린 때", width: "14ch", cell: (row) => time(row.created_at) },
    {
      key: "consumers",
      header: "가져간 일꾼",
      cell: (row) => ((row.consumers ?? []).length > 0 ? (row.consumers ?? []).join(", ") : "—"),
    },
    {
      key: "deliveries",
      header: "건넨 횟수",
      width: "10ch",
      align: "right",
      // 2 이상이면 잠금이 지나 다시 나간 것이다 (C15 — 최소 한 번).
      cell: (row) => String(row.deliveries ?? 0),
    },
    { key: "finished_at", header: "끝난 때", width: "14ch", cell: (row) => time(row.finished_at) },
    {
      key: "error_code",
      header: "오류 코드",
      cell: (row) =>
        row.error_code ? `${row.error_code}${row.outcome_unknown ? " (결과 모름)" : ""}` : "—",
    },
  ];

  const logColumns: Array<Column<RunEvent>> = [
    { key: "ts", header: "시각", width: "14ch", cell: (row) => time(row.ts) },
    { key: "level", header: "수준", width: "8ch", cell: (row) => String(row.data?.level ?? "info") },
    { key: "message", header: "글", cell: (row) => String(row.data?.message ?? "") },
  ];

  return (
    <Shell mode={found.mode} actor={found.actor} current="/runs">
      <header className="mb-4 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-h1 font-bold font-mono">{decodeURIComponent(runId)}</h1>
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
              <dt className="text-text-muted">BPM 프로세스</dt>
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
              {/* `run_finished`가 센 것 — 도는 중에는 「—」다 (목록의 셈 열과 같다, C3). */}
              <dt className="text-text-muted">재생</dt>
              <dd>{info.replayed_tasks ?? "—"}</dd>
              <dt className="text-text-muted">LLM 단계</dt>
              <dd>{llm}</dd>
              <dt className="text-text-muted">결재·확인</dt>
              <dd>{seen.human_requested ?? 0}</dd>
              <dt className="text-text-muted">이벤트</dt>
              <dd>{info.events}</dd>
              {/*
                **PC 위임으로 시작된 실행이면 맡긴 서버 실행이 있다** (C3 `parent_run_id`,
                ADR-0062) — 없는 실행에는 줄도 두지 않는다 (「—」로 두면 모든 실행에 뜻 없는
                칸이 하나 선다). 반대 방향은 그 서버 실행의 작업 요청자다 (C5).
              */}
              {info.parent_run_id ? (
                <>
                  <dt className="text-text-muted">맡긴 서버 실행</dt>
                  <dd>
                    <Link
                      className="underline font-mono"
                      href={`/runs/${encodeURIComponent(info.parent_run_id)}`}
                    >
                      {info.parent_run_id}
                    </Link>
                  </dd>
                </>
              ) : null}
            </dl>
            {info.error_code ? <ErrorBanner message={`오류 코드: ${info.error_code}`} /> : null}
          </Section>

          <Section title="노드 타임라인">
            {nodes.length === 0 ? (
              <Empty kind="노드" />
            ) : (
              <>
                <Bars rows={nodeBars} />
                {waits.length > 0 ? (
                  <p className="text-body-sm text-text-muted">점선은 그 노드가 기다린 구간입니다 (아래 「이어 돈 기록」).</p>
                ) : null}
                <DataTable columns={nodeColumns} rows={nodes} rowKey={(row) => row.node_id} caption="노드" />
              </>
            )}
          </Section>

          {/*
            「이어 돈 기록」 — **기다림이 있을 때만 보인다** (화면 문서). C3가 두 줄을 「서버만
            쓴다」고 두었으니 PC 실행에서는 늘 비는데, 빈 섹션을 늘 그리면 PC 실행 상세마다
            뜻 없는 한 줄이 선다.
          */}
          {waits.length > 0 ? (
            <Section title="이어 돈 기록">
              <p className="text-body-sm text-text-secondary">
                이어 돈 횟수 {totals.resumed}회 · 기다린 시간 합 {duration(totals.seconds)}
              </p>
              <DataTable
                columns={resumeColumns}
                rows={waits}
                rowKey={(row) => String(row.seq)}
                caption="기다림 (서버 실행)"
              />
            </Section>
          ) : null}

          {/*
            「외부 작업」 — **일감이 있을 때만 보인다** (화면 문서). PC·서버·시험 실행이 같은 모양이다
            (셋 다 C15로 부른다). 값은 오지 않는다 (원칙 6).
          */}
          {tasksFailed ? (
            <Section title="외부 작업">
              <p className="text-body-sm text-text-muted">외부 작업을 읽지 못했습니다.</p>
            </Section>
          ) : tasks.length > 0 ? (
            <Section title="외부 작업">
              <DataTable columns={taskColumns} rows={tasks} rowKey={(row) => row.task_id} caption="외부 작업" />
              <p className="text-body-sm text-text-muted">
                바깥 기능은 Center에 일감을 올리고 그 토픽의 일꾼이 가져갑니다. 「기다림」이 오래면 일꾼이
                없거나 조용한 것입니다 — 「리소스」의 「토픽」 표를 보세요. 7일이 지나 지워진 일감은 보이지
                않습니다.
              </p>
            </Section>
          ) : null}

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
