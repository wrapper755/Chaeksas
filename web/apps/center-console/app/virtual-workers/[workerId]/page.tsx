import Link from "next/link";
import { redirect } from "next/navigation";
import { DataTable, EmptyState, ErrorBanner, StatusBadge, type Column } from "@chaeksas/ui";
import type { VirtualWorkerBatch, VirtualWorkerInfo } from "@chaeksas/api-types/c5-virtual-worker-info";
import { CenterError, center, session } from "@/lib/center";
import { Shell } from "@/components/Shell";
import { LABEL as RUN_LABEL } from "../../runs/page";
import { fullTime } from "../../bot-uis/page";
import { STATE_LABEL } from "../page";
import { WorkerTools } from "./tools";

/**
 * CON-13 가상 직원 (상세) — 요약과 **최근 일괄**.
 *
 * 일괄 = 접수 Bot 실행 한 번, 기동한 건 = `parent_run_id`가 그 실행인 것 (C5 §가상 직원).
 * **Center가 읽을 때 센 것을 그대로 보인다** — 콘솔이 다시 세지 않는다.
 *
 * **감독자와 결재 담당자는 다른 칸이다** — 담당자는 그림이 정한다(C14 `assignees`, ADR-0080).
 */

/** 「3 — 완료 2 · 실패 1」 — 상태별 수는 `status_map` 「실행·노드」의 표기로. */
export function children(batch: VirtualWorkerBatch): string {
  const parts = Object.entries(batch.children_by_status ?? {}).map(
    ([status, count]) => `${RUN_LABEL[status] ?? status} ${count}`,
  );
  return parts.length > 0 ? `${batch.children} — ${parts.join(" · ")}` : String(batch.children ?? 0);
}

export default async function VirtualWorkerPage({ params }: { params: Promise<{ workerId: string }> }) {
  const found = await session();
  if (!found) redirect("/login");
  const { workerId } = await params;

  let info: VirtualWorkerInfo | null = null;
  let failure: string | null = null;
  try {
    info = await center.virtualWorker(decodeURIComponent(workerId));
  } catch (cause) {
    failure = cause instanceof CenterError ? cause.message : "알 수 없는 오류가 생겼습니다";
  }

  const columns: Array<Column<VirtualWorkerBatch>> = [
    {
      key: "run_id",
      header: "일괄",
      mono: true,
      cell: (row) => (
        <Link className="underline" href={`/runs/${encodeURIComponent(row.run_id)}`}>
          {row.run_id}
        </Link>
      ),
    },
    {
      key: "status",
      header: "상태",
      width: "12ch",
      cell: (row) => <StatusBadge group="실행·노드" label={RUN_LABEL[row.status ?? ""] ?? row.status ?? "—"} />,
    },
    { key: "started_at", header: "시작", width: "18ch", cell: (row) => fullTime(row.started_at) },
    { key: "children", header: "기동한 건", cell: children },
    {
      key: "open_approvals",
      header: "결재",
      width: "10ch",
      cell: (row) => {
        const first = (row.open_approvals ?? [])[0];
        return first ? (
          <Link className="underline" href={`/approvals/${encodeURIComponent(first)}`}>
            <StatusBadge group="결재" label="대기" />
          </Link>
        ) : (
          "—"
        );
      },
    },
  ];

  return (
    <Shell mode={found.mode} actor={found.actor} current="/virtual-workers">
      <p className="mb-2 text-body-sm">
        <Link className="underline" href="/virtual-workers">
          가상 직원
        </Link>
      </p>
      {failure || !info ? (
        <ErrorBanner message={failure ?? "가상 직원을 읽지 못했습니다"} />
      ) : (
        <>
          <header className="mb-4">
            <h1 className="text-h1 font-bold">{info.name}</h1>
          </header>
          <dl className="mb-6 grid grid-cols-2 gap-x-6 gap-y-1 text-body sm:grid-cols-4">
            <dt className="text-text-muted">id</dt>
            <dd className="font-mono">{info.id}</dd>
            <dt className="text-text-muted">접수 Bot</dt>
            <dd className="font-mono">{info.intake}</dd>
            <dt className="text-text-muted">감독자</dt>
            <dd>{(info.supervisors ?? []).join(", ") || "—"}</dd>
            <dt className="text-text-muted">상태</dt>
            <dd>
              <StatusBadge group="가상 직원" label={STATE_LABEL[info.state ?? ""] ?? info.state ?? "—"} />
            </dd>
            <dt className="text-text-muted">만든 날</dt>
            <dd>{fullTime(info.created_at)}</dd>
            <dt className="text-text-muted">바꾼 날</dt>
            <dd>{fullTime(info.updated_at)}</dd>
          </dl>

          <h2 className="mb-2 text-h2 font-bold">최근 일괄</h2>
          {(info.batches ?? []).length === 0 ? (
            <EmptyState title="아직 일괄이 없습니다. 접수 Bot이 실행되면 여기 보입니다." />
          ) : (
            <DataTable columns={columns} rows={info.batches ?? []} rowKey={(row) => row.run_id} caption="최근 일괄" />
          )}

          {found.mode === "admin" ? <WorkerTools id={info.id} state={info.state ?? "active"} /> : null}
        </>
      )}
    </Shell>
  );
}
