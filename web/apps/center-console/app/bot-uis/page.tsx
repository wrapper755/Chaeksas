import Link from "next/link";
import type { Route } from "next";
import { redirect } from "next/navigation";
import { Button, DataTable, EmptyState, ErrorBanner, StatusBadge, type Column } from "@chaeksas/ui";
import type { BotUiInfo } from "@chaeksas/api-types/c5-bot-ui-info";
import type { CenterKeyInfo } from "@chaeksas/api-types/c7-center-key-info";
import { STATE_LABEL } from "@/lib/center-keys";
import { CENTER_PUBLIC_URL, CenterError, center, session } from "@/lib/center";
import { CenterAddress } from "@/components/CenterAddress";
import { Shell } from "@/components/Shell";
import { Enrollments } from "@/components/Enrollments";
import { lastReportNote } from "@/lib/labels";
import type { EnrollmentInfo } from "@chaeksas/api-types/c5-enrollment-info";

/**
 * CON-03 앱 — 탭 「Studio」/「Bot」(PC 실행기, ADR-0121). 탭마다 표 하나와 그 위의 「승인 대기」가 있다.
 *
 * PC 실행기 값은 **PC 실행기가 하트비트로 보고한 그대로**다 (C4·C5 `BotUiInfo`). Center가 더하는 것은
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
    error: "오류",
  };
  return table[status] ?? status;
}


/** 탭 — 이 차례이고 기본은 Studio다 (CON-03). */
type AppTab = "studio" | "bot";
const TABS: Array<{ tab: AppTab; label: string }> = [
  { tab: "studio", label: "Studio" },
  { tab: "bot", label: "Bot" },
];

export default async function BotUisPage({ searchParams }: { searchParams: Promise<{ tab?: string }> }) {
  const found = await session();
  if (!found) redirect("/login");
  const tab: AppTab = (await searchParams).tab === "bot" ? "bot" : "studio";

  let rows: BotUiInfo[] = [];
  let enrollments: EnrollmentInfo[] = [];
  let studios: CenterKeyInfo[] = [];
  let studioEnrollments: EnrollmentInfo[] = [];
  let failure: string | null = null;
  try {
    rows = await center.botUis();
    // 「승인 대기」 — 등록 요청이 있을 때만 목록 위에 보인다 (C4 §등록 요청과 승인, ADR-0092).
    enrollments = await center.enrollments("bot_ui");
    // Studio는 하트비트가 없다 — **승인 하나가 키 하나**라 Studio용 키 목록이 곧 Studio 목록이다 (ADR-0093).
    studios = await center.centerKeys({ type: "studio" });
    studioEnrollments = await center.enrollments("studio");
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
      header: "Bot 이름",
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
          <StatusBadge group="PC 실행기" label="비활성" />
        ) : row.status ? (
          <StatusBadge group="BPM 프로세스" label={statusLabel(row.status)} />
        ) : (
          "—"
        ),
    },
    { key: "os", header: "OS", width: "20ch" },
    { key: "versions", header: "버전", width: "10ch", mono: true, cell: (row) => row.versions.bot_ui },
    { key: "last_seen_at", header: "마지막 하트비트", width: "16ch", cell: (row) => time(row.last_seen_at) },
    // 오프라인이면 실행·대기열이 지금 값이 아니다 — 언제 기준인지 칸에 붙인다 (CON-03, U8).
    { key: "current_run", header: "실행 중", cell: (row) => <AsOf row={row}>{running(row)}</AsOf> },
    {
      key: "queue",
      header: "대기열",
      width: "16ch",
      align: "right",
      cell: (row) => <AsOf row={row}>{`${row.queue?.items?.length ?? 0}건`}</AsOf>,
    },
    { key: "runtimes", header: "런타임", width: "22ch", cell: runtimeLabel },
    {
      key: "key",
      header: "API 키",
      width: "26ch",
      mono: true,
      cell: (row) =>
        row.key
          ? `${row.key.prefix}… ${row.key.expires_at ? `(${fullTime(row.key.expires_at)}까지)` : "(무기한)"}`
          : "—",
    },
  ];

  const online = rows.filter((row) => row.online).length;

  const studioColumns: Array<Column<CenterKeyInfo>> = [
    { key: "name", header: "이름" },
    { key: "pc", header: "PC", cell: (row) => row.bound_to?.machine_name ?? "—" },
    { key: "created_at", header: "승인한 날", width: "18ch", cell: (row) => fullTime(row.created_at) },
    // 하트비트가 없어 「온라인」 대신 마지막으로 Center를 부른 때다.
    { key: "last_used_at", header: "마지막 사용", width: "16ch", cell: (row) => time(row.last_used_at) },
    { key: "expires_at", header: "키 만료", width: "18ch", cell: (row) => fullTime(row.expires_at) },
    {
      key: "state",
      header: "상태",
      width: "12ch",
      cell: (row) => <StatusBadge group="API 키" label={STATE_LABEL[row.state] ?? row.state} />,
    },
  ];

  return (
    <Shell mode={found.mode} actor={found.actor} current="/bot-uis">
      <header className="mb-4 flex flex-wrap items-end justify-between gap-4">
        <h1 className="text-h1 font-bold">앱</h1>
        <CenterAddress url={CENTER_PUBLIC_URL} who={tab === "bot" ? "Bot" : "Studio"} />
      </header>

      <nav className="mb-4 flex flex-wrap gap-2" aria-label="앱 종류">
        {TABS.map((one) => (
          <Link
            key={one.tab}
            href={`/bot-uis?tab=${one.tab}` as Route}
            aria-current={tab === one.tab ? "page" : undefined}
            className={
              tab === one.tab
                ? "rounded-md border border-transparent bg-primary-subtle px-3 py-1 text-body font-semibold text-primary"
                : "rounded-md border border-border-default bg-bg-surface px-3 py-1 text-body text-text-secondary hover:bg-bg-subtle"
            }
          >
            {one.label} ({one.tab === "bot" ? rows.length : studios.length})
          </Link>
        ))}
      </nav>

      {failure ? (
        <ErrorBanner message={failure} action={<Button variant="secondary">다시 시도</Button>} />
      ) : tab === "bot" ? (
          <section className="flex flex-col gap-3">
            <h2 className="text-h2 font-semibold">
              Bot{rows.length > 0 ? ` · ${online}/${rows.length} 온라인` : ""}
            </h2>
            <Enrollments rows={enrollments} where="현장 화면" canDecide={found.mode === "admin"} />
            {rows.length === 0 ? (
              <EmptyState
                title="등록된 Bot이 없습니다."
                hint="현장 PC의 PC 실행기 설정에 Center 주소를 넣으면 등록 요청을 보냅니다. 현장 화면의 요청 코드와 같은 줄을 위의 「승인 대기」에서 승인하세요."
              />
            ) : (
              <DataTable columns={columns} rows={rows} rowKey={(row) => row.bot_ui_id} caption="Bot 목록" />
            )}
          </section>
      ) : (
          <section className="flex flex-col gap-3">
            <Enrollments
              rows={studioEnrollments}
              where="Studio 설정 창"
              canDecide={found.mode === "admin"}
              nameHelp="이 이름이 Studio에서 올린 것의 「누가」로 남습니다 (예: 김OO 설계 PC)."
            />
            {studios.length === 0 ? (
              <EmptyState
                title="승인된 Studio가 없습니다."
                hint="Studio 설정 창에 Center 주소를 넣으면 등록 요청이 옵니다."
              />
            ) : (
              <DataTable columns={studioColumns} rows={studios} rowKey={(row) => row.key_id} caption="Studio 목록" />
            )}
            <p className="text-caption text-text-muted">
              폐기·삭제는 「API 키」의 「승인으로 들인 키」에서 합니다.
            </p>
          </section>
      )}
    </Shell>
  );
}

/** 칸 값과, 오프라인이면 그 아래 「마지막 보고 <시각> 기준」 (`lastReportNote`). */
function AsOf({ row, children }: { row: BotUiInfo; children: React.ReactNode }) {
  const note = lastReportNote(row.online, row.last_seen_at, time);
  if (!note) return <>{children}</>;
  return (
    <span className="flex flex-col">
      <span>{children}</span>
      <span className="text-caption text-text-muted">{note}</span>
    </span>
  );
}
