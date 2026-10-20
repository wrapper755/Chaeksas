import Link from "next/link";
import { redirect } from "next/navigation";
import { Button, DataTable, EmptyState, ErrorBanner, StatusBadge, type Column } from "@chaeksas/ui";
import type { VirtualWorkerInfo } from "@chaeksas/api-types/c5-virtual-worker-info";
import { CENTER_URL, CenterError, center, session } from "@/lib/center";
import { Shell } from "@/components/Shell";
import { createVirtualWorker } from "@/app/actions";

/**
 * CON-13 가상 직원 (목록).
 *
 * 사람이 아닌 업무 주체 — 접수 Bot과 감독자를 묶는다 (C5 §가상 직원, ADR-0085). 일괄·자식은
 * 상세에서 보인다 — **Center가 읽을 때 이어 붙인 것**이고 콘솔이 세지 않는다.
 */

/** C5 상태 → `status_map` 「가상 직원」 묶음의 표기. 모르는 값은 그대로 보인다 (원칙 10). */
export const STATE_LABEL: Record<string, string> = {
  active: "사용 중",
  stopped: "멈춤",
};

const INPUT = "h-9 border border-border-strong bg-bg-surface px-2 text-body";

export default async function VirtualWorkersPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const found = await session();
  if (!found) redirect("/login");
  const asked = await searchParams;

  let rows: VirtualWorkerInfo[] = [];
  let failure: string | null = null;
  try {
    rows = await center.virtualWorkers();
  } catch (cause) {
    failure = cause instanceof CenterError ? cause.message : "알 수 없는 오류가 생겼습니다";
  }

  const columns: Array<Column<VirtualWorkerInfo>> = [
    {
      key: "name",
      header: "이름",
      cell: (row) => (
        <Link className="underline" href={`/virtual-workers/${encodeURIComponent(row.id)}`}>
          {row.name}
        </Link>
      ),
    },
    { key: "id", header: "id", width: "20ch", mono: true },
    { key: "intake", header: "접수 Bot", mono: true },
    { key: "supervisors", header: "감독자", cell: (row) => (row.supervisors ?? []).join(", ") || "—" },
    {
      key: "state",
      header: "상태",
      width: "10ch",
      cell: (row) => <StatusBadge group="가상 직원" label={STATE_LABEL[row.state ?? ""] ?? row.state ?? "—"} />,
    },
  ];

  return (
    <Shell mode={found.mode} actor={found.actor} centerUrl={CENTER_URL} current="/virtual-workers">
      <header className="mb-4">
        <h1 className="text-h1 font-bold">가상 직원</h1>
        <p className="text-body text-text-secondary">
          접수 Bot과 감독자를 묶은 업무 주체입니다. 일괄은 접수 Bot 실행 한 번입니다.
        </p>
      </header>

      {asked.error ? <ErrorBanner message={asked.error} /> : null}
      {failure ? (
        <ErrorBanner message={failure} />
      ) : rows.length === 0 ? (
        <EmptyState title="등록한 가상 직원이 없습니다." />
      ) : (
        <DataTable columns={columns} rows={rows} rowKey={(row) => row.id} caption="가상 직원 목록" />
      )}

      {found.mode === "admin" ? (
        <section className="mt-6 flex max-w-xl flex-col gap-3">
          <h2 className="text-h2 font-bold">새 가상 직원</h2>
          {/* 일반 폼 + 서버 액션 — JS 없이도 된다. 거부되면 사유가 위에 보인다 (B16 포함). */}
          <form action={createVirtualWorker} className="flex flex-col gap-3">
            <label className="flex flex-col gap-1 text-body-sm">
              <span className="text-text-muted">id *</span>
              <input name="id" required pattern="[a-z0-9][a-z0-9._\-]{0,63}" className={INPUT} />
            </label>
            <label className="flex flex-col gap-1 text-body-sm">
              <span className="text-text-muted">이름 *</span>
              <input name="name" required className={INPUT} />
            </label>
            <label className="flex flex-col gap-1 text-body-sm">
              <span className="text-text-muted">감독자 (쉼표로 나눔)</span>
              <input name="supervisors" className={INPUT} />
            </label>
            <label className="flex flex-col gap-1 text-body-sm">
              <span className="text-text-muted">접수 Bot (패키지 id) *</span>
              <input name="intake" required className={INPUT} />
            </label>
            <p className="text-caption text-text-muted">
              접수 Bot에 결재 없는 일괄 기동이 있으면 등록되지 않습니다.
            </p>
            <div>
              <Button type="submit" variant="primary">
                등록
              </Button>
            </div>
          </form>
        </section>
      ) : null}
    </Shell>
  );
}
