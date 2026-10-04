import Link from "next/link";
import { redirect } from "next/navigation";
import { Button, DataTable, ErrorBanner, StatusBadge, type Column } from "@chaeksas/ui";
import type { RunInfo } from "@chaeksas/api-types/c3-run-info";
import { CENTER_URL, CenterError, center, session } from "@/lib/center";
import { Shell } from "@/components/Shell";

/**
 * CON-01 실행 로그 (목록).
 *
 * 값은 **실행하는 쪽이 보낸 이벤트에서** 나온다 (C3). Center가 받을 때 요약을 만들어 두므로
 * 목록을 그릴 때 줄을 다시 읽지 않는다.
 *
 * 좁히기는 상태·Bot 둘뿐이다 — 실행 위치·Bot UI로 좁히는 것은 그 값이 쌓이는 M5(배포)와 함께
 * 붙인다. **없는 것을 있는 척하지 않는다** (U3).
 */

/** C3 `status` → 화면 표기. `status_map`의 「실행·노드」 묶음에 있는 말만 쓴다. */
export const LABEL: Record<string, string> = {
  running: "실행 중",
  waiting: "기다리는 중",
  success: "완료",
  failed: "실패",
  cancelled: "취소됨",
};

const CHOICES = ["", "running", "waiting", "success", "failed", "cancelled"];

export function time(value: string | null | undefined): string {
  if (!value) return "—";
  const at = new Date(value);
  if (Number.isNaN(at.getTime())) return value;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(at.getMonth() + 1)}-${pad(at.getDate())} ${pad(at.getHours())}:${pad(at.getMinutes())}`;
}

export function seconds(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${Math.round(value * 10) / 10}초`;
}

export function where(value: string | null | undefined): string {
  return value === "pc" ? "PC" : value === "server" ? "서버" : "—";
}

export default async function RunsPage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string; bpm_process_id?: string }>;
}) {
  const found = await session();
  if (!found) redirect("/login");
  const query = await searchParams;

  let rows: RunInfo[] = [];
  let total = 0;
  let failure: string | null = null;
  try {
    const listing = await center.runs({
      status: query.status,
      bpm_process_id: query.bpm_process_id,
    });
    rows = listing.runs ?? [];
    total = listing.total ?? rows.length;
  } catch (cause) {
    failure = cause instanceof CenterError ? cause.message : "알 수 없는 오류가 생겼습니다";
  }

  const columns: Array<Column<RunInfo>> = [
    {
      key: "status",
      header: "상태",
      width: "12ch",
      // 색만으로 뜻을 전하지 않는다 — 글자를 함께 쓴다 (스타일 가이드 §7).
      cell: (row) => <StatusBadge group="실행·노드" label={LABEL[row.status ?? ""] ?? row.status ?? "—"} />,
    },
    {
      key: "run_id",
      header: "실행 id",
      mono: true,
      cell: (row) => (
        <Link className="underline" href={`/runs/${encodeURIComponent(row.run_id)}`}>
          {row.run_id}
        </Link>
      ),
    },
    { key: "bpm_process_id", header: "Bot", cell: (row) => row.bpm_process_id ?? "—" },
    { key: "version", header: "버전", width: "10ch", cell: (row) => row.version ?? "—" },
    { key: "run_location", header: "실행 위치", width: "10ch", cell: (row) => where(row.run_location) },
    { key: "source", header: "시작 방식", width: "10ch", cell: (row) => row.source ?? "—" },
    { key: "started_at", header: "시작", width: "14ch", cell: (row) => time(row.started_at) },
    { key: "finished_at", header: "끝", width: "14ch", cell: (row) => time(row.finished_at) },
    {
      key: "duration_s",
      header: "소요",
      width: "10ch",
      align: "right",
      cell: (row) => seconds(row.duration_s),
    },
    { key: "error_code", header: "오류 코드", cell: (row) => row.error_code ?? "—" },
  ];

  return (
    <Shell mode={found.mode} actor={found.actor} centerUrl={CENTER_URL} current="/runs">
      <header className="mb-4">
        <h1 className="text-h1 font-bold">실행 로그</h1>
        <p className="text-body text-text-secondary">
          실행하는 쪽이 보낸 기록입니다. Center가 꺼져 있던 동안의 기록은 다시 닿을 때 올라옵니다.
        </p>
      </header>

      <form className="mb-4 flex flex-wrap items-end gap-3" method="get">
        <label className="flex flex-col gap-1 text-body-sm">
          상태
          <select
            name="status"
            defaultValue={query.status ?? ""}
            className="h-9 border border-border-default bg-bg-surface px-2"
          >
            {CHOICES.map((one) => (
              <option key={one || "all"} value={one}>
                {one ? LABEL[one] : "(전체)"}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-body-sm">
          Bot
          <input
            name="bpm_process_id"
            defaultValue={query.bpm_process_id ?? ""}
            placeholder="(전체)"
            className="h-9 border border-border-default bg-bg-surface px-2"
          />
        </label>
        <Button type="submit" variant="secondary">
          좁히기
        </Button>
      </form>

      {failure ? (
        <ErrorBanner message={failure} />
      ) : (
        <div className="flex flex-col gap-2">
          <DataTable
            columns={columns}
            rows={rows}
            rowKey={(row) => row.run_id}
            caption="실행 목록"
            empty={{
              title: "조건에 맞는 실행이 없습니다.",
              hint: "Studio 시험 실행이나 Bot UI가 보낸 기록이 여기 쌓입니다.",
            }}
          />
          {rows.length > 0 ? <p className="text-body-sm text-text-muted">{total}건</p> : null}
        </div>
      )}
    </Shell>
  );
}
