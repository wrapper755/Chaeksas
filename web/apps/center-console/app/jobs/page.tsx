import Link from "next/link";
import { redirect } from "next/navigation";
import { Button, DataTable, EmptyState, ErrorBanner, StatusBadge, type Column } from "@chaeksas/ui";
import type { JobInfo } from "@chaeksas/api-types/c5-job-info";
import type { BotUiInfo } from "@chaeksas/api-types/c5-bot-ui-info";
import { CENTER_URL, CenterError, center, session } from "@/lib/center";
import { Shell } from "@/components/Shell";
import { CancelJob } from "./cancel";
import {
  CANCELLABLE,
  STATES,
  STATE_LABEL,
  botLabel,
  delegatedFrom,
  location,
  reason,
  stateNote,
  targetName,
  time,
} from "./labels";

/**
 * CON-05 작업 지시 (목록).
 *
 * **입력 값은 목록에 보이지 않는다** — 「입력 키」만 둔다 (U10). 값은 상세에서 접힌 채로만.
 * 필터는 주소(URL)에 남겨 새로 고쳐도 그대로다 (JS 없이 GET 폼).
 */

const LIMIT_DEFAULT = 100;
const LIMIT_MIN = 10;
const LIMIT_MAX = 1000;

function clampLimit(raw: string | undefined): number {
  const value = Number(raw ?? LIMIT_DEFAULT);
  if (!Number.isFinite(value)) return LIMIT_DEFAULT;
  return Math.min(LIMIT_MAX, Math.max(LIMIT_MIN, Math.trunc(value)));
}

export default async function JobsPage({
  searchParams,
}: {
  searchParams: Promise<{ state?: string | string[]; bot_ui?: string; limit?: string }>;
}) {
  const found = await session();
  if (!found) redirect("/login");
  const asked = await searchParams;
  // 상태는 여러 개 (체크 칸) — 하나면 글자, 여럿이면 배열로 온다.
  const states = ([] as string[]).concat(asked.state ?? []).filter((one) => STATES.includes(one));
  const botUi = asked.bot_ui ?? "";
  const limit = clampLimit(asked.limit);
  const admin = found.mode === "admin";

  let rows: JobInfo[] = [];
  let botUis: BotUiInfo[] = [];
  let failure: string | null = null;
  try {
    rows = await center.jobs({
      state: states.length > 0 ? states.join(",") : undefined,
      target_id: botUi || undefined,
      limit,
    });
    botUis = await center.botUis();
  } catch (cause) {
    failure = cause instanceof CenterError ? cause.message : "알 수 없는 오류가 생겼습니다";
  }

  const columns: Array<Column<JobInfo>> = [
    {
      key: "state",
      header: "상태",
      width: "16ch",
      cell: (row) => {
        const note = stateNote(row, botUis);
        return (
          <div className="flex flex-col gap-1">
            <StatusBadge group="작업" label={STATE_LABEL[row.state] ?? row.state} />
            {note ? <span className="text-body-sm text-text-muted">{note}</span> : null}
          </div>
        );
      },
    },
    {
      key: "job_id",
      header: "작업 id",
      width: "14ch",
      mono: true,
      cell: (row) => (
        <Link className="underline" href={`/jobs/${encodeURIComponent(row.job_id)}`}>
          {row.job_id}
        </Link>
      ),
    },
    { key: "location", header: "실행 위치", width: "8ch", cell: location },
    { key: "target", header: "Bot UI", width: "14ch", cell: (row) => targetName(row, botUis) },
    { key: "bot", header: "Bot", cell: botLabel },
    {
      // **키만** 보인다 (U10) — 값은 상세에서 접힌 채로만.
      key: "inputs",
      header: "입력 키",
      cell: (row) => Object.keys(row.inputs ?? {}).join(", ") || "—",
    },
    {
      key: "requested_by",
      header: "요청자",
      cell: (row) => {
        const from = delegatedFrom(row);
        return from ? (
          <Link className="underline" href={`/runs/${encodeURIComponent(from)}`}>
            서버 Bot ({from})
          </Link>
        ) : (
          row.requested_by
        );
      },
    },
    { key: "requested_at", header: "요청 시각", width: "12ch", cell: (row) => time(row.requested_at) },
    { key: "expires_at", header: "만료", width: "12ch", cell: (row) => time(row.expires_at) },
    {
      key: "run_id",
      header: "실행 id",
      mono: true,
      cell: (row) =>
        row.run_id ? (
          <Link className="underline" href={`/runs/${encodeURIComponent(row.run_id)}`}>
            {row.run_id}
          </Link>
        ) : (
          "—"
        ),
    },
    // 실행의 성패는 작업 상태가 아니다 — C3 `run_finished`가 정한다 (C5).
    { key: "run_status", header: "실행 상태", width: "10ch", cell: (row) => row.run_status ?? "—" },
    { key: "state_reason", header: "사유", width: "14ch", cell: reason },
    { key: "note", header: "메모", cell: (row) => row.note ?? "—" },
  ];
  if (admin) {
    columns.push({
      key: "cancel",
      header: "",
      width: "8ch",
      cell: (row) =>
        CANCELLABLE.has(row.state) && !row.cancel_requested ? <CancelJob jobId={row.job_id} /> : null,
    });
  }

  const filtered = states.length > 0 || Boolean(botUi);

  return (
    <Shell mode={found.mode} actor={found.actor} centerUrl={CENTER_URL} current="/jobs">
      <header className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-h1 font-bold">작업 지시</h1>
          <p className="text-body text-text-secondary">
            배포된 Bot을 언제 돌릴지 정합니다. Bot UI가 다음 하트비트에 받아 갑니다.
          </p>
        </div>
        {admin ? (
          <Link
            href="/jobs/new"
            className="inline-flex h-9 items-center border border-transparent bg-primary px-4 text-body font-medium text-primary-fg hover:bg-primary-hover"
          >
            새 작업...
          </Link>
        ) : null}
      </header>

      <form className="mb-4 flex flex-wrap items-end gap-4" method="get">
        <fieldset className="flex flex-col gap-1 text-body-sm">
          <legend className="text-text-muted">상태</legend>
          <div className="flex flex-wrap gap-3">
            {STATES.map((one) => (
              <label key={one} className="flex items-center gap-1">
                <input type="checkbox" name="state" value={one} defaultChecked={states.includes(one)} />
                {STATE_LABEL[one]}
              </label>
            ))}
          </div>
        </fieldset>
        <label className="flex flex-col gap-1 text-body-sm">
          <span className="text-text-muted">Bot UI</span>
          <select
            name="bot_ui"
            defaultValue={botUi}
            className="h-9 border border-border-strong bg-bg-surface px-2 text-body"
          >
            <option value="">(전체)</option>
            {botUis.map((one) => (
              <option key={one.bot_ui_id} value={one.bot_ui_id}>
                {one.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-body-sm">
          <span className="text-text-muted">최대</span>
          <input
            type="number"
            name="limit"
            min={LIMIT_MIN}
            max={LIMIT_MAX}
            defaultValue={limit}
            className="h-9 w-24 border border-border-strong bg-bg-surface px-2 text-body"
          />
        </label>
        <Button type="submit" variant="secondary">
          보기
        </Button>
      </form>

      {failure ? (
        <ErrorBanner message={failure} />
      ) : rows.length === 0 ? (
        <EmptyState
          title={filtered ? "해당하는 작업 지시가 없습니다." : "작업 지시가 없습니다. 「새 작업...」으로 만드세요."}
          hint={filtered ? "필터를 비워 보세요." : undefined}
        />
      ) : (
        <DataTable columns={columns} rows={rows} rowKey={(row) => row.job_id} caption="작업 지시 목록" />
      )}
    </Shell>
  );
}
