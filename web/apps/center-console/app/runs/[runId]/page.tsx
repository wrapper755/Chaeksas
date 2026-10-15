import Link from "next/link";
import { redirect } from "next/navigation";
import { DataTable, ErrorBanner, StatusBadge, type Column } from "@chaeksas/ui";
import type { RunEvent } from "@chaeksas/api-types/c3-run-event";
import type { RunInfo } from "@chaeksas/api-types/c3-run-info";
import type { ContributedResource } from "@chaeksas/api-types/c7-contributed-resource";
import type { ServiceAppResource } from "@chaeksas/api-types/c7-service-app-resource";
import { CENTER_URL, CenterError, center, session } from "@/lib/center";
import { FINISHED, type ResumeRow, duration, resumes, waitTotals } from "@/lib/summary";
import { Shell } from "@/components/Shell";
import { LABEL, seconds, time, where } from "../page";

/**
 * CON-01 실행 로그 (상세).
 *
 * **이벤트가 원본이다** — 요약·타임라인·단계 표는 모두 같은 줄에서 만든다. 값은 애초에 오지
 * 않는다 (원칙 6 — 보내는 쪽이 `sanitize()`로 걸렀다).
 *
 * 화면 설계서의 섹션 중 지금 채우는 것은 요약·노드 타임라인·AI 태스크 단계·**UI 태스크**·
 * 사람 개입·로그·원본 이벤트다. 「이어 돈 기록」은 `run_waiting`·`run_resumed`를 쓰는 서버
 * 실행(M7) 몫이다 — **빈 섹션은 「<종류> 이벤트가 없습니다」 한 줄**이다.
 *
 * 「UI 태스크」는 C3 `ui_session` 줄을 읽는다 (확장이 남기고 엔진이 쓴 것, ADR-0041). 「화면」
 * 칸이 **그 앱의 관리 콘솔로 가는 링크**다 — 실행 기록에는 앱이 없고(`page_id`만 있다) C7이
 * 둘을 잇는 칸을 들고 있어, 여기서 리소스 목록 둘을 읽어 맞춘다 (`consoleOf`).
 *
 * **콘솔 주소 그대로 보낸다** — UIA-03으로 바로 보내려면 어느 화면이 「모니터링」인지 알아야
 * 하고, 그것은 **그 확장의 `console.pages`가 아는 것**이다 (ADR-0042). 플랫폼 화면에 확장
 * 이름을 적지 않는다.
 */

/** C3 `ui_session.result` → `status_map`의 「UI 세션」 표기 (그 표에 있는 것만 쓴다). */
const UI_RESULT: Record<string, string> = {
  success: "성공",
  escalated: "전환",
  failed: "실패",
};

/** **못 이은 줄이 있을 때** 가까이 적는 이유 (U3) — 줄은 보이고 링크만 없다. */
const NO_LINK =
  "링크가 없는 화면은 그 화면이 리소스 목록에 없거나(아직 등록되지 않음), 그 확장의 서버 부분이 Center에 등록되지 않았거나, 관리 콘솔 주소가 비어 있는 것입니다.";

/**
 * `page_id` → 그 화면을 가진 앱의 관리 콘솔 주소 (C7, CON-01).
 *
 * **두 걸음이다**: 기여 자원(`ui_page`)의 `extension_id`로 어느 확장인지 알고, 같은
 * `extension_id`를 가진 서비스 앱의 `console_url`을 쓴다. 둘 중 하나가 없으면 **그 화면만**
 * 링크가 없다 (`undefined`).
 */
export function consoleOf(
  pages: ContributedResource[],
  apps: ServiceAppResource[],
): Map<string, string> {
  const urlOf = new Map<string, string>();
  for (const app of apps) {
    if (app.extension_id && app.console_url) urlOf.set(app.extension_id, app.console_url);
  }
  const out = new Map<string, string>();
  for (const page of pages) {
    const url = page.extension_id ? urlOf.get(page.extension_id) : undefined;
    if (url) out.set(page.id, url);
  }
  return out;
}

/** C3 `run_waiting.waiting_for` → 표기 (**열린 문자열**이라 모르는 값은 그대로 보인다). */
const WAITING_FOR: Record<string, string> = {
  approval: "결재",
  message: "메시지",
  timer: "타이머",
};

/** C3 `run_resumed.reason` → 표기. 없으면 「—」다 (선택 칸이다). */
const RESUME_REASON: Record<string, string> = {
  answer: "답",
  message: "메시지",
  timer: "시각이 됨",
  restart: "실행기 재시작",
  withdraw: "결재 회수",
};

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
  // C3 `ui_session` — 확장이 남기고 엔진이 쓴 줄 (ADR-0041). 전환·실패로 끝난 것도 있다.
  const ui = events.filter((e) => e.kind === "ui_session");
  // 「이어 돈 기록」 — `run_waiting`·`run_resumed`를 짝지은다 (**서버 실행만** 남긴다, C3).
  const waits = resumes(events);
  const totals = waitTotals(waits);
  const ended = FINISHED.has(info?.status ?? "");

  // UI 태스크가 없으면 **리소스 목록을 두드리지 않는다.** 읽지 못해도 실행 상세는 그려야 하니
  // (여기서 실패하면 운영자가 볼 것이 아무것도 없다) 못 읽으면 링크만 없다.
  let consoles = new Map<string, string>();
  if (ui.length > 0) {
    try {
      const [pages, apps] = await Promise.all([
        center.contributed("ui_page"),
        center.resources<ServiceAppResource>("service_app"),
      ]);
      consoles = consoleOf(pages.items ?? [], apps.items ?? []);
    } catch {
      consoles = new Map();
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
    { key: "kind", header: "무엇", width: "16ch" },
    { key: "node_id", header: "노드", mono: true, cell: (row) => row.node_id ?? "—" },
    { key: "layer", header: "종류", width: "10ch", cell: (row) => String(row.data?.layer ?? "—") },
  ];

  const uiColumns: Array<Column<RunEvent>> = [
    { key: "node_id", header: "노드", mono: true, cell: (row) => row.node_id ?? "—" },
    {
      key: "page_id",
      header: "화면",
      mono: true,
      // **글자는 늘 보이고 링크만 붙는다** (U3) — 못 이은 까닭은 표 아래 한 줄이다.
      cell: (row) => {
        const pageId = String(row.data?.page_id ?? "");
        const url = consoles.get(pageId);
        if (!pageId) return "—";
        return url ? (
          <a className="underline" href={url} target="_blank" rel="noreferrer noopener">
            {pageId}
          </a>
        ) : (
          pageId
        );
      },
    },
    {
      key: "result",
      header: "결과",
      width: "14ch",
      cell: (row) => (
        <StatusBadge group="UI 세션" label={UI_RESULT[String(row.data?.result ?? "")] ?? "—"} />
      ),
    },
    { key: "steps", header: "스텝 수", width: "10ch", align: "right", cell: (row) => String(row.data?.steps ?? 0) },
    {
      key: "fallback_depth_max",
      header: "폴백 깊이 최대",
      width: "14ch",
      align: "right",
      cell: (row) => String(row.data?.fallback_depth_max ?? 0),
    },
    {
      key: "healed",
      header: "치유",
      width: "8ch",
      cell: (row) => (row.data?.healed ? "예" : "아니오"),
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
              <dt className="text-text-muted">UI 태스크</dt>
              <dd>{ui.length}</dd>
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
              <DataTable columns={nodeColumns} rows={nodes} rowKey={(row) => row.node_id} caption="노드" />
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

          <Section title="AI 태스크 단계">
            {agent.length === 0 ? (
              <Empty kind="AI 태스크" />
            ) : (
              <DataTable columns={agentColumns} rows={agent} rowKey={(row) => String(row.seq)} caption="AI 단계" />
            )}
          </Section>

          <Section title="UI 태스크">
            {ui.length === 0 ? (
              <Empty kind="UI 세션" />
            ) : (
              <>
                <DataTable
                  columns={uiColumns}
                  rows={ui}
                  rowKey={(row) => String(row.seq)}
                  caption="UI 세션 (UI 태스크 한 번)"
                />
                <p className="text-body-sm text-text-muted">
                  「화면」을 누르면 그 화면을 가진 앱의 관리 콘솔이 새 탭에서 열립니다 (UI 세션
                  기록은 그 콘솔의 「모니터링」입니다).
                  {ui.some((row) => !consoles.get(String(row.data?.page_id ?? ""))) ? ` ${NO_LINK}` : ""}
                </p>
              </>
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
