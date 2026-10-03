import { redirect } from "next/navigation";
import { DataTable, EmptyState, ErrorBanner, StatusBadge, type Column } from "@chaeksas/ui";
import type { UsageRecord } from "@chaeksas/api-types/c11-usage-page";
import { APP_URL, load, reason, svc } from "@/lib/page";
import { Shell } from "@/components/Shell";

/**
 * SVC-03 사용 기록.
 *
 * **업무 값이 없다** (계약 원칙 6 — 키·작업·결과·소요만). 그래서 이 표에 「입력」 열이 없다.
 * 좁히기와 「키별 합계」는 다음에 붙인다.
 */

const MODE_LABEL: Record<string, string> = { autonomous: "자율", deterministic: "결정" };

/** HTTP 상태 → status_map 「작업」 표기. 403은 「거절」이다 (키 권한에 막힌 것). */
function outcome(status: number): string {
  if (status < 300) return "수락";
  if (status === 403) return "거절";
  return "실패";
}

function moment(value: string): string {
  const at = new Date(value);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())} ${pad(at.getHours())}:${pad(at.getMinutes())}:${pad(at.getSeconds())}`;
}

export default async function UsagePage() {
  const found = await load();
  if (!found) redirect("/login");
  const { status, session } = found;

  let rows: UsageRecord[] = [];
  let total = 0;
  let failure: string | null = found.failure;
  try {
    const page = await svc.usage();
    rows = page.items ?? [];
    total = page.total ?? rows.length;
  } catch (cause) {
    failure = reason(cause);
  }

  const columns: Array<Column<UsageRecord>> = [
    { key: "at", header: "시각", width: "20ch", cell: (row) => moment(row.at) },
    { key: "key_name", header: "키 이름", width: "20ch", mono: true },
    { key: "operation", header: "작업", width: "14ch", mono: true },
    { key: "mode", header: "수행 모드", width: "10ch", cell: (row) => MODE_LABEL[row.mode] ?? row.mode },
    {
      key: "status",
      header: "결과",
      width: "10ch",
      cell: (row) => <StatusBadge group="작업" label={outcome(row.status)} />,
    },
    { key: "duration_ms", header: "소요", width: "10ch", cell: (row) => `${row.duration_ms} ms` },
    { key: "run_id", header: "실행 id", width: "22ch", mono: true, cell: (row) => row.run_id ?? "—" },
    {
      key: "usage",
      header: "LLM",
      cell: (row) =>
        row.usage ? `${row.usage.model} (${row.usage.input_tokens ?? 0}/${row.usage.output_tokens ?? 0})` : "—",
    },
  ];

  return (
    <Shell status={status} actor={session.actor} appUrl={APP_URL} current="/usage">
      <header className="mb-4">
        <h1 className="text-h1 font-bold">사용 기록</h1>
        <p className="text-body text-text-secondary">
          누가·어떤 작업을·어떤 모드로 불렀는지입니다. <strong>업무 값은 기록하지 않습니다.</strong>
          {rows.length > 0 ? ` 최근 ${rows.length}건 (전체 ${total}건).` : null}
        </p>
      </header>

      {failure ? <ErrorBanner message={failure} /> : null}
      {rows.length === 0 && !failure ? (
        <EmptyState title="호출 기록이 없습니다." hint="키를 발급하고 BPM 프로세스에서 이 앱을 부르면 쌓입니다." />
      ) : rows.length > 0 ? (
        <DataTable columns={columns} rows={rows} rowKey={(row, index) => `${row.at}-${index}`} caption="사용 기록" />
      ) : null}
    </Shell>
  );
}
