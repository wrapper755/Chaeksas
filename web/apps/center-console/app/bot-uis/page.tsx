import { Button, DataTable, EmptyState, ErrorBanner, StatusBadge, type Column } from "@chaeksas/ui";
import type { BotUiInfo } from "@chaeksas/api-types/c5-bot-ui-info";
import { CENTER_URL, CenterError, center, session } from "@/lib/center";
import { Shell } from "@/components/Shell";
import { BotUiActions } from "./actions-ui";
import { redirect } from "next/navigation";

/**
 * CON-03 Bot UI 현황.
 *
 * 값은 **Bot UI가 하트비트로 보고한 그대로**다 (C4·C5 `BotUiInfo`). 오프라인이면 실행·대기열이
 * 지금 상태가 아니므로 「마지막 보고 … 기준」을 붙인다 (U8).
 */

function time(value: string | null | undefined): string {
  if (!value) return "—";
  const at = new Date(value);
  const today = new Date().toDateString() === at.toDateString();
  const pad = (n: number) => String(n).padStart(2, "0");
  const clock = `${pad(at.getHours())}:${pad(at.getMinutes())}`;
  return today ? clock : `${pad(at.getMonth() + 1)}-${pad(at.getDate())} ${clock}`;
}

function running(row: BotUiInfo): string {
  if (!row.current_run) return "없음";
  return `${row.current_run.bpm_process_id}@${row.current_run.node_id ?? row.current_run.state}`;
}

export default async function BotUisPage() {
  const found = await session();
  if (!found) redirect("/login");

  let rows: BotUiInfo[] = [];
  let failure: string | null = null;
  try {
    rows = await center.botUis();
  } catch (cause) {
    failure = cause instanceof CenterError ? cause.message : "알 수 없는 오류가 생겼습니다";
  }

  const columns: Array<Column<BotUiInfo>> = [
    {
      key: "online",
      header: "온라인",
      width: "12ch",
      // 색만으로 뜻을 전하지 않는다 — 글자를 함께 쓴다 (스타일 가이드 §7).
      cell: (row) => <StatusBadge group="온라인" label={row.online ? "온라인" : "오프라인"} />,
    },
    { key: "name", header: "Bot UI 이름" },
    {
      key: "status",
      header: "상태",
      width: "14ch",
      cell: (row) => (row.status ? <StatusBadge group="Bot" label={statusLabel(row.status)} /> : "—"),
    },
    { key: "os", header: "OS", width: "20ch" },
    {
      key: "versions",
      header: "버전",
      width: "12ch",
      mono: true,
      cell: (row) => row.versions.bot_ui,
    },
    { key: "last_seen_at", header: "마지막 하트비트", width: "16ch", cell: (row) => time(row.last_seen_at) },
    { key: "current_run", header: "실행 중", cell: running },
    {
      key: "queue",
      header: "대기열",
      width: "10ch",
      align: "right",
      cell: (row) => `${row.queue?.items?.length ?? 0}건`,
    },
    {
      key: "worker",
      header: "Worker 프로세스",
      width: "18ch",
      cell: (row) =>
        row.worker ? <StatusBadge group="Worker 프로세스" label={workerLabel(row.worker.state)} /> : "—",
    },
    {
      key: "key",
      header: "Center API 키",
      width: "22ch",
      mono: true,
      cell: (row) => (row.key ? `${row.key.prefix}…` : "—"),
    },
  ];

  const online = rows.filter((row) => row.online).length;

  return (
    <Shell mode={found.mode} actor={found.actor} centerUrl={CENTER_URL} current="/bot-uis">
      <header className="mb-4 flex items-end justify-between gap-4">
        <div>
          <h1 className="text-h1 font-bold">Bot UI 현황</h1>
          <p className="text-body text-text-secondary">
            {rows.length > 0 ? `${online}/${rows.length} 온라인` : "PC마다 하나인 Bot UI의 상태입니다."}
          </p>
        </div>
      </header>

      {failure ? (
        <ErrorBanner message={failure} action={<Button variant="secondary">다시 시도</Button>} />
      ) : rows.length === 0 ? (
        <EmptyState
          title="등록된 Bot UI가 없습니다."
          hint="「Center API 키」에서 Bot UI용 키를 발급해 현장 PC의 Bot UI 설정에 넣으면 여기에 나타납니다."
        />
      ) : (
        <div className="flex flex-col gap-6">
          <DataTable columns={columns} rows={rows} rowKey={(row) => row.bot_ui_id} caption="Bot UI 목록" />
          {rows.map((row) => (
            <section key={row.bot_ui_id} className="flex flex-col gap-2">
              <h2 className="text-h2 font-semibold">{row.name}</h2>
              {!row.online && row.last_seen_at ? (
                <p className="text-body-sm text-text-muted">
                  오프라인입니다 — 아래는 마지막 보고 {time(row.last_seen_at)} 기준입니다.
                </p>
              ) : null}
              <dl className="grid gap-x-6 gap-y-1 text-body-sm md:grid-cols-2">
                <div className="flex gap-2">
                  <dt className="text-text-muted">대기열</dt>
                  <dd>{row.queue?.items?.length ?? 0}건 (최대 {row.queue?.max ?? "—"})</dd>
                </div>
                <div className="flex gap-2">
                  <dt className="text-text-muted">확장</dt>
                  <dd>
                    {row.extensions && row.extensions.length > 0
                      ? row.extensions.map((e) => `${e.id}@${e.version}`).join(", ")
                      : "보고 없음"}
                  </dd>
                </div>
              </dl>
              {found.mode === "admin" ? <BotUiActions botUiId={row.bot_ui_id} disabled={row.disabled ?? false} /> : null}
            </section>
          ))}
        </div>
      )}
    </Shell>
  );
}

/** C4의 열린 문자열 상태 → `status_map`에 있는 표기 (스타일 가이드 §2-2). */
function statusLabel(status: string): string {
  const table: Record<string, string> = {
    idle: "대기",
    running: "실행 중",
    waiting_approval: "결재 대기",
    waiting_confirmation: "확인 대기",
    selector_registration: "실행 중",
    error: "오류",
  };
  return table[status] ?? status;
}

function workerLabel(state: string): string {
  const table: Record<string, string> = {
    running: "실행 중",
    off: "꺼 둠",
    restarting: "다시 띄우는 중",
    stopped: "멈춤",
  };
  return table[state] ?? state;
}
