import { redirect } from "next/navigation";
import { DataTable, EmptyState, ErrorBanner, StatusBadge, type Column } from "@chaeksas/ui";
import type { OperationStatus } from "@chaeksas/api-types/c11-admin-status";
import type { Dependency } from "@chaeksas/api-types/c11-admin-status";
import { APP_URL, load } from "@/lib/page";
import { Shell } from "@/components/Shell";

/**
 * SVC-01 상태 — 요약·작업·의존·Center 등록.
 *
 * 수는 앱 안의 사용 기록에서 센다 (업무 값은 세지 않는다). 아무것도 손보지 않는 **보기 전용** 화면이다.
 */

const CATEGORY_LABEL: Record<string, string> = { business: "업무", system: "시스템" };
const MODE_LABEL: Record<string, string> = { autonomous: "자율 수행", deterministic: "결정 수행" };
const FALLBACK_LABEL: Record<string, string> = {
  none: "없음 (바로 실패)",
  retry: "다시 시도",
  manual: "사람에게 확인",
};
const DEPENDENCY_LABEL: Record<string, string> = {
  ok: "정상",
  degraded: "저하",
  unreachable: "응답 없음",
  unknown: "확인 전",
};

/** 「3시간 12분」처럼. 초까지 보일 만큼 짧으면 초로 보인다. */
function uptime(seconds: number): string {
  if (seconds < 60) return `${seconds}초`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}분`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}시간 ${minutes % 60}분`;
  return `${Math.floor(hours / 24)}일 ${hours % 24}시간`;
}

function Summary({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1 rounded-md border border-border-default bg-bg-surface p-3">
      <span className="text-caption text-text-muted">{label}</span>
      <span className="text-body">{children}</span>
    </div>
  );
}

export default async function StatusPage() {
  const found = await load();
  if (!found) redirect("/login");
  const { status, failure, session } = found;

  const operations: Array<Column<OperationStatus>> = [
    { key: "name", header: "작업", width: "16ch", mono: true },
    { key: "description", header: "설명", cell: (row) => row.description ?? "—" },
    {
      key: "modes",
      header: "지원 모드",
      width: "22ch",
      cell: (row) => (row.modes ?? []).map((mode) => MODE_LABEL[mode] ?? mode).join(" · "),
    },
    {
      key: "fallback",
      header: "결정 수행 폴백",
      width: "18ch",
      cell: (row) => FALLBACK_LABEL[row.fallback ?? "none"] ?? row.fallback ?? "—",
    },
    { key: "calls_24h", header: "24시간 호출", width: "13ch", cell: (row) => String(row.calls_24h ?? 0) },
    {
      key: "error_rate",
      header: "오류율",
      width: "10ch",
      cell: (row) => `${Math.round((row.error_rate ?? 0) * 1000) / 10}%`,
    },
  ];

  const dependencies: Array<Column<Dependency>> = [
    { key: "name", header: "이름", width: "24ch" },
    {
      key: "status",
      header: "상태",
      width: "14ch",
      cell: (row) => <StatusBadge group="서비스 앱" label={DEPENDENCY_LABEL[row.status] ?? "확인 전"} />,
    },
    { key: "detail", header: "설명", cell: (row) => row.detail ?? "—" },
  ];

  return (
    <Shell status={status} actor={session.actor} appUrl={APP_URL} current="/status">
      <h1 className="mb-4 text-h1 font-bold">상태</h1>
      {failure ? <ErrorBanner message={failure} /> : null}
      {status ? (
        <div className="flex flex-col gap-6">
          <section className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            <Summary label="앱 id">
              <span className="font-mono">{status.app_id}</span>
            </Summary>
            <Summary label="구분">{CATEGORY_LABEL[status.category] ?? status.category}</Summary>
            <Summary label="버전">{status.version}</Summary>
            <Summary label="가동 시간">{uptime(status.uptime_s ?? 0)}</Summary>
            <Summary label="API 주소">
              <span className="font-mono text-body-sm break-all">{APP_URL}</span>
            </Summary>
          </section>

          <section>
            <h2 className="mb-2 text-h3 font-semibold">작업</h2>
            {(status.operations ?? []).length === 0 ? (
              <EmptyState title="선언된 작업이 없습니다." hint="앱의 매니페스트(C11) `operations`를 확인하세요." />
            ) : (
              <DataTable
                columns={operations}
                rows={status.operations ?? []}
                rowKey={(row) => row.name}
                caption="작업과 최근 24시간 통계"
              />
            )}
          </section>

          <section>
            <h2 className="mb-2 text-h3 font-semibold">의존</h2>
            {(status.dependencies ?? []).length === 0 ? (
              <EmptyState
                title="바깥 의존이 없습니다."
                hint="DB·LLM 게이트웨이를 쓰는 앱은 여기에 상태가 보입니다."
              />
            ) : (
              <DataTable
                columns={dependencies}
                rows={status.dependencies ?? []}
                rowKey={(row) => row.name}
                caption="바깥 의존 상태"
              />
            )}
          </section>

          <section>
            <h2 className="mb-2 text-h3 font-semibold">Center 등록</h2>
            <p className="text-body">
              {status.center?.registered
                ? `Center 리소스 목록에 올라가 있습니다 (${status.center.base_url ?? "주소 미정"}).`
                : "아직 Center에 보고하지 않았습니다 — Center 콘솔의 리소스 목록에 보이지 않습니다."}
            </p>
            <p className="text-body-sm text-text-secondary">
              마지막 보고: {status.center?.last_reported_at ?? "—"}
            </p>
          </section>
        </div>
      ) : null}
    </Shell>
  );
}
