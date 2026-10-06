import Link from "next/link";
import { redirect } from "next/navigation";
import { Button, DataTable, EmptyState, ErrorBanner, StatusBadge, type Column } from "@chaeksas/ui";
import type { ApprovalInfo } from "@chaeksas/api-types/c6-approval-info";
import type { BotUiInfo } from "@chaeksas/api-types/c5-bot-ui-info";
import { CENTER_URL, CenterError, center, session } from "@/lib/center";
import { Shell } from "@/components/Shell";

/**
 * CON-04 결재함 (목록).
 *
 * **값은 목록에 보이지 않는다** — 검토 자료는 상세에서 접힌 채로만 보인다 (U10). 목록에는
 * 「변수 키」만 둔다. 필터는 주소(URL)에 남겨 새로 고쳐도 그대로다.
 */

/** C6 상태 → `status_map` 「결재」 묶음의 표기. 모르는 값은 그대로 보인다 (원칙 10). */
export const STATE_LABEL: Record<string, string> = {
  open: "대기",
  answered: "답함",
  expired: "시간 초과",
  withdrawn: "회수됨",
};

/** 회수 사유 → 글 (C6). */
export const WITHDRAW_LABEL: Record<string, string> = {
  answered_in_field: "현장에서 먼저 답함",
  run_ended: "실행이 끝남",
  admin_withdraw: "관리자 회수",
  host_lost: "Bot UI 기록 유실",
};

export function time(value: string | null | undefined): string {
  if (!value) return "—";
  const at = new Date(value);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(at.getMonth() + 1)}-${pad(at.getDate())} ${pad(at.getHours())}:${pad(at.getMinutes())}`;
}

/** 실행하는 곳 — Bot UI 이름, 서버면 「서버」 (CON-04). */
export function where(row: ApprovalInfo): string {
  if (row.host.type === "server_runner") return "서버";
  return row.host.name ?? row.host.id;
}

const STATES = [
  { value: "", label: "(전체)" },
  { value: "open", label: "대기" },
  { value: "answered", label: "답함" },
  { value: "expired", label: "시간 초과" },
  { value: "withdrawn", label: "회수됨" },
];

export default async function ApprovalsPage({
  searchParams,
}: {
  searchParams: Promise<{ state?: string; host?: string }>;
}) {
  const found = await session();
  if (!found) redirect("/login");
  const asked = await searchParams;
  const state = asked.state ?? "";
  const host = asked.host ?? "";

  let rows: ApprovalInfo[] = [];
  let hosts: BotUiInfo[] = [];
  let failure: string | null = null;
  try {
    rows = await center.approvals({ state: state || undefined, host: host || undefined });
    hosts = await center.botUis();
  } catch (cause) {
    failure = cause instanceof CenterError ? cause.message : "알 수 없는 오류가 생겼습니다";
  }

  const columns: Array<Column<ApprovalInfo>> = [
    {
      key: "state",
      header: "상태",
      width: "12ch",
      cell: (row) => <StatusBadge group="결재" label={STATE_LABEL[row.state] ?? row.state} />,
    },
    {
      key: "title",
      header: "제목",
      cell: (row) => (
        <Link className="underline" href={`/approvals/${encodeURIComponent(row.request_id)}`}>
          {row.title ?? "결재 요청"}
        </Link>
      ),
    },
    { key: "request_id", header: "요청 id", width: "28ch", mono: true },
    { key: "host", header: "실행하는 곳", width: "16ch", cell: where },
    {
      key: "bpm_process_id",
      header: "Bot",
      cell: (row) => `${row.bpm_process_id}@${row.version}`,
    },
    {
      // **키만** 보인다 (U10) — 값은 상세에서 접힌 채로만.
      key: "keys",
      header: "변수 키",
      cell: (row) => Object.keys(row.review ?? {}).join(", ") || "—",
    },
    { key: "created_at", header: "요청 시각", width: "14ch", cell: (row) => time(row.created_at) },
    { key: "expires_at", header: "시한", width: "14ch", cell: (row) => time(row.expires_at) },
    { key: "answered_by", header: "답한 사람", width: "14ch", cell: (row) => row.answered_by ?? "—" },
    {
      key: "delivered",
      header: "전달됨",
      width: "10ch",
      cell: (row) => (row.delivered ? "받아 감" : "—"),
    },
  ];

  return (
    <Shell mode={found.mode} actor={found.actor} centerUrl={CENTER_URL} current="/approvals">
      <header className="mb-4">
        <h1 className="text-h1 font-bold">결재함</h1>
        <p className="text-body text-text-secondary">
          실행하는 쪽이 올린 결재입니다. 답하면 다음 하트비트에 받아 갑니다.
        </p>
      </header>

      {/* 필터는 JS 없이도 돈다 — GET 폼이 주소에 남긴다. */}
      <form className="mb-4 flex flex-wrap items-end gap-3" method="get">
        <label className="flex flex-col gap-1 text-body-sm">
          <span className="text-text-muted">상태</span>
          <select
            name="state"
            defaultValue={state}
            className="h-9 border border-border-strong bg-bg-surface px-2 text-body"
          >
            {STATES.map((one) => (
              <option key={one.value} value={one.value}>
                {one.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-body-sm">
          <span className="text-text-muted">실행하는 곳</span>
          <select
            name="host"
            defaultValue={host}
            className="h-9 border border-border-strong bg-bg-surface px-2 text-body"
          >
            <option value="">(전체)</option>
            {hosts.map((one) => (
              <option key={one.bot_ui_id} value={one.bot_ui_id}>
                {one.name}
              </option>
            ))}
          </select>
        </label>
        <Button type="submit" variant="secondary">
          보기
        </Button>
      </form>

      {failure ? (
        <ErrorBanner message={failure} />
      ) : rows.length === 0 ? (
        <EmptyState
          title={
            state || host
              ? "해당하는 결재 요청이 없습니다."
              : "기다리는 결재가 없습니다."
          }
          hint={state || host ? "필터를 「(전체)」로 바꿔 보세요." : undefined}
        />
      ) : (
        <DataTable
          columns={columns}
          rows={rows}
          rowKey={(row) => row.request_id}
          caption="결재 목록"
        />
      )}
    </Shell>
  );
}
