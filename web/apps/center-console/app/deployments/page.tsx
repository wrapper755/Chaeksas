import Link from "next/link";
import type { Route } from "next";
import { redirect } from "next/navigation";
import { Button, DataTable, EmptyState, ErrorBanner, StatusBadge, type Column } from "@chaeksas/ui";
import type { DeploymentInfo } from "@chaeksas/api-types/c5-deployment-info";
import { CENTER_PUBLIC_URL, CenterError, center, session } from "@/lib/center";
import { Shell } from "@/components/Shell";
import { fullTime } from "@/app/bot-uis/page";
import { RevokeDeployment } from "./tools";

/**
 * CON-15 배포 — 배포를 **만들고 철회하는 한 곳**이다 (ADR-0090). CON-03·CON-12의 배포 줄은
 * 여기로 잇기만 한다 (같은 단추는 한 곳). 봉투는 Center가 서명한다 — 화면은 누가 했는지를 보인다.
 */

/** 배포 하나의 지금 상태 (`status_map` 「배포」). 때는 콘솔 서버의 시각으로 본다. */
function stateOf(row: DeploymentInfo, now: number): string {
  if (row.revoked_at) return "철회됨";
  if (row.expires_at && Date.parse(row.expires_at) <= now) return "만료";
  if (row.not_before && Date.parse(row.not_before) > now) return "예약";
  return "활성";
}

export default async function DeploymentsPage({
  searchParams,
}: {
  searchParams: Promise<{ all?: string; created?: string }>;
}) {
  const found = await session();
  if (!found) redirect("/login");
  const asked = await searchParams;
  const showAll = asked.all === "1";

  let rows: DeploymentInfo[] = [];
  const names = new Map<string, string>();
  let failure: string | null = null;
  try {
    const [deployments, botUis, runners] = await Promise.all([
      center.deployments({ active: showAll ? undefined : true }),
      center.botUis(),
      center.serverRunners(),
    ]);
    rows = deployments;
    for (const one of botUis) names.set(`bot_ui:${one.bot_ui_id}`, one.name);
    for (const one of runners) names.set(`server_runner:${one.server_runner_id}`, one.name);
  } catch (cause) {
    failure = cause instanceof CenterError ? cause.message : "알 수 없는 오류가 생겼습니다";
  }

  const now = Date.now();
  const target = (row: DeploymentInfo): string => {
    const type = String(row.target.type ?? "");
    const id = String(row.target.id ?? "");
    if (type === "server_runner") return id === "*" ? "서버 (전체)" : `서버 ${names.get(`${type}:${id}`) ?? id}`;
    // 아직 등록 기록이 없는 PC는 id 그대로 보인다 — 숨기면 잘못 걸린 배포를 못 찾는다.
    return names.get(`${type}:${id}`) ?? id;
  };

  const columns: Array<Column<DeploymentInfo>> = [
    {
      key: "deployment_id",
      header: "배포 id",
      width: "16ch",
      mono: true,
      cell: (row) => <span id={row.deployment_id}>{row.deployment_id}</span>,
    },
    {
      key: "bot",
      header: "Bot@버전",
      mono: true,
      cell: (row) => `${row.bpm_process_id}@${row.version}`,
    },
    { key: "target", header: "대상", cell: target },
    {
      key: "state",
      header: "상태",
      width: "10ch",
      cell: (row) => <StatusBadge group="배포" label={stateOf(row, now)} />,
    },
    {
      key: "validity",
      header: "유효 기간",
      width: "28ch",
      cell: (row) =>
        `${row.not_before ? fullTime(row.not_before) : "즉시"} ~ ${row.expires_at ? fullTime(row.expires_at) : "무기한"}`,
    },
    {
      key: "limit",
      header: "동시 실행",
      width: "9ch",
      align: "right",
      // 서버 배포에만 있다. 적지 않았으면 「기본」 — 계약의 기본값을 화면에 베끼지 않는다 (CON-12와 같다).
      cell: (row) =>
        String(row.target.type) === "server_runner" ? (row.max_concurrency ?? "기본") : <span className="text-text-muted">—</span>,
    },
    {
      key: "who",
      header: "누가",
      width: "14ch",
      // 사람이 서명하던 때의 배포에는 계정이 없다 (ADR-0090).
      cell: (row) =>
        row.revoked_at ? `철회 ${row.revoked_by ?? "—"}` : (row.deployed_by ?? <span className="text-text-muted">—</span>),
    },
    {
      key: "when",
      header: "배포한 때",
      width: "18ch",
      cell: (row) => fullTime(row.signed_at),
    },
    ...(found.mode === "admin"
      ? [
          {
            key: "actions",
            header: "",
            width: "10ch",
            cell: (row: DeploymentInfo) =>
              row.revoked_at ? null : (
                <RevokeDeployment
                  deploymentId={row.deployment_id}
                  label={`${row.bpm_process_id}@${row.version} → ${target(row)}`}
                />
              ),
          } as Column<DeploymentInfo>,
        ]
      : []),
  ];

  return (
    <Shell mode={found.mode} actor={found.actor} centerUrl={CENTER_PUBLIC_URL} current="/deployments">
      <header className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-h1 font-bold">배포</h1>
          <p className="text-body text-text-secondary">
            {showAll ? `전체 ${rows.length}건` : `살아 있는 배포 ${rows.length}건`} ·{" "}
            <Link className="underline" href={(showAll ? "/deployments" : "/deployments?all=1") as Route}>
              {showAll ? "살아 있는 것만" : "철회된 것도 보기"}
            </Link>
          </p>
        </div>
        {found.mode === "admin" ? (
          <Link href="/deployments/new">
            <Button variant="primary">새 배포...</Button>
          </Link>
        ) : null}
      </header>

      {asked.created ? (
        <p className="mb-3 text-body text-text-secondary">
          배포 {asked.created}건을 만들었습니다. 현장은 다음 하트비트에 받아 설치합니다.
        </p>
      ) : null}

      {failure ? (
        <ErrorBanner message={failure} />
      ) : rows.length === 0 ? (
        <EmptyState
          title="배포가 없습니다."
          hint={found.mode === "admin" ? "승인된 Bot을 「새 배포...」로 배포하세요." : "관리자가 배포하면 여기 보입니다."}
        />
      ) : (
        <DataTable columns={columns} rows={rows} rowKey={(row) => row.deployment_id} caption="배포" />
      )}
    </Shell>
  );
}
