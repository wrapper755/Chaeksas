import Link from "next/link";
import { redirect } from "next/navigation";
import { Button, DataTable, EmptyState, ErrorBanner, StatusBadge, type Column } from "@chaeksas/ui";
import type { BotUiInfo } from "@chaeksas/api-types/c5-bot-ui-info";
import { CENTER_URL, CenterError, center, session } from "@/lib/center";
import { Shell } from "@/components/Shell";

/**
 * CON-03 Bot UI 현황 (목록).
 *
 * 값은 **Bot UI가 하트비트로 보고한 그대로**다 (C4·C5 `BotUiInfo`). Center가 더하는 것은
 * 온라인 판정과 키 정보뿐이다. 상세(대기열·배포·확장·최근 배치 결정)는 이름을 누르면 열린다.
 */

export function time(value: string | null | undefined): string {
  if (!value) return "—";
  const at = new Date(value);
  const today = new Date().toDateString() === at.toDateString();
  const pad = (n: number) => String(n).padStart(2, "0");
  const clock = `${pad(at.getHours())}:${pad(at.getMinutes())}`;
  return today ? clock : `${pad(at.getMonth() + 1)}-${pad(at.getDate())} ${clock}`;
}

/**
 * **연도까지** 적는 시각 — 배포 유효 기간처럼 「언제까지냐」가 요점인 자리에 쓴다.
 * 짧은 `time()`은 `2027-01-01`을 「01-01」로 보여서, 내일인지 내년인지 알 수 없다.
 */
export function fullTime(value: string | null | undefined): string {
  if (!value) return "—";
  const at = new Date(value);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())} ${pad(at.getHours())}:${pad(at.getMinutes())}`;
}

export function running(row: BotUiInfo): string {
  if (!row.current_run) return "없음";
  return `${row.current_run.bpm_process_id}@${row.current_run.node_id ?? row.current_run.state}`;
}

/** 브라우저·데스크톱 백엔드 (C4 `runtimes`). 등록할 때만 오므로 없을 수 있다. */
export function runtimeLabel(row: BotUiInfo): string {
  const found = row.runtimes;
  if (!found) return "보고 없음";
  const parts = [...(found.browsers ?? []), found.desktop_backend].filter(Boolean);
  return parts.length > 0 ? parts.join(" · ") : "보고 없음";
}

/** C4의 열린 문자열 상태 → `status_map`에 있는 표기 (스타일 가이드 §2-2). */
export function statusLabel(status: string): string {
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

export function workerLabel(state: string): string {
  const table: Record<string, string> = {
    running: "실행 중",
    off: "꺼 둠",
    restarting: "다시 띄우는 중",
    stopped: "멈춤",
  };
  return table[state] ?? state;
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
    {
      key: "name",
      header: "Bot UI 이름",
      cell: (row) => (
        <Link className="underline" href={`/bot-uis/${encodeURIComponent(row.bot_ui_id)}`}>
          {row.name}
        </Link>
      ),
    },
    {
      key: "status",
      header: "상태",
      width: "14ch",
      cell: (row) =>
        row.disabled ? (
          <StatusBadge group="Bot UI" label="비활성" />
        ) : row.status ? (
          <StatusBadge group="Bot" label={statusLabel(row.status)} />
        ) : (
          "—"
        ),
    },
    { key: "os", header: "OS", width: "20ch" },
    { key: "versions", header: "버전", width: "10ch", mono: true, cell: (row) => row.versions.bot_ui },
    { key: "last_seen_at", header: "마지막 하트비트", width: "16ch", cell: (row) => time(row.last_seen_at) },
    { key: "current_run", header: "실행 중", cell: running },
    {
      key: "queue",
      header: "대기열",
      width: "9ch",
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
    { key: "runtimes", header: "런타임", width: "22ch", cell: runtimeLabel },
    {
      key: "key",
      header: "Center API 키",
      width: "26ch",
      mono: true,
      cell: (row) =>
        row.key
          ? `${row.key.prefix}… ${row.key.expires_at ? `(${fullTime(row.key.expires_at)}까지)` : "(무기한)"}`
          : "—",
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
        <DataTable columns={columns} rows={rows} rowKey={(row) => row.bot_ui_id} caption="Bot UI 목록" />
      )}
    </Shell>
  );
}
