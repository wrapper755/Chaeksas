import Link from "next/link";
import type { Route } from "next";
import { redirect } from "next/navigation";
import { DataTable, EmptyState, ErrorBanner, StatusBadge, cn, type Column } from "@chaeksas/ui";
import type { CompanyInfo } from "@chaeksas/api-types/c16-company-info";
import type { DepartmentInfo } from "@chaeksas/api-types/c16-department-info";
import type { StaffInfo } from "@chaeksas/api-types/c16-staff-info";
import { CenterError, center, session } from "@/lib/center";
import { Shell } from "@/components/Shell";
import { fullTime } from "@/app/bot-uis/page";
import { LABEL as RUN_LABEL, time } from "@/app/runs/page";
import { packageHref } from "@/app/packages/page";
import {
  KIND_LABEL,
  nodeParam,
  orgStateLabel,
  orgTree,
  parseNode,
  removeBlocked,
  triggersLabel,
  type OrgKind,
} from "@/lib/organization";
import { NewOrgItem, OrgItemTools, type OrgItem } from "./tools";

/**
 * CON-13 조직 (C16, ADR-0125·ADR-0127) — 왼쪽 나무(회사 > 부서 > 직원) + 오른쪽 고른 자리의 상세.
 *
 * 고르기는 **링크**(`?node=<종류>:<id>`)라 JS 없이 돈다. 회사가 정해진 계정에게는 **Center가** 제 회사
 * 것만 준다 — 화면이 거르지 않는다. 그 자리 업무·최근 실행은 하나 읽기가 준다(셈은 Center가 읽을 때 한다).
 * 업무 자리는 Studio가 올릴 때 고르므로 여기서 업무를 옮기는 손잡이는 없다 (ADR-0127).
 */

type Detail = CompanyInfo | DepartmentInfo | StaffInfo;
type Work = NonNullable<Detail["work"]>[number];
type Recent = NonNullable<Detail["recent_runs"]>[number];

function href(kind: OrgKind, id: string): Route {
  return `/organization?node=${encodeURIComponent(nodeParam(kind, id))}` as Route;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-h2 font-semibold">{title}</h2>
      {children}
    </section>
  );
}

/** 나무 한 줄 — 「멈춤」이면 흐리게. 고른 줄은 진하게. */
function TreeLine({
  kind,
  item,
  selected,
  depth,
}: {
  kind: OrgKind;
  item: { id: string; name: string; state?: string | null };
  selected: boolean;
  depth: number;
}) {
  const stopped = item.state === "stopped";
  return (
    <li>
      <Link
        href={href(kind, item.id)}
        aria-current={selected ? "page" : undefined}
        className={cn(
          "flex items-center gap-2 py-1 pr-2 text-body hover:bg-bg-subtle",
          selected && "bg-bg-subtle font-semibold",
          stopped && "text-text-muted",
        )}
        style={{ paddingLeft: `calc(var(--space-3) * ${depth + 1})` }}
      >
        <span className="truncate">{item.name}</span>
        {stopped ? <span className="text-body-sm">(멈춤)</span> : null}
      </Link>
    </li>
  );
}

export default async function OrganizationPage({ searchParams }: { searchParams: Promise<{ node?: string }> }) {
  const found = await session();
  if (!found) redirect("/login");
  const query = await searchParams;
  const manage = found.mode === "admin";
  // 회사 만들기·멈추기·이름 바꾸기는 **Center 관리자만** (C16).
  const centerAdmin = manage && !found.company;

  let companies: CompanyInfo[] = [];
  let departments: DepartmentInfo[] = [];
  let staff: StaffInfo[] = [];
  let failure: string | null = null;
  try {
    [companies, departments, staff] = await Promise.all([
      center.companies(),
      center.departments(),
      center.staffList(),
    ]);
  } catch (cause) {
    failure = cause instanceof CenterError ? cause.message : "알 수 없는 오류가 생겼습니다";
  }
  const tree = orgTree(companies, departments, staff);

  const wanted = parseNode(query.node) ?? (tree[0] ? { kind: "company" as const, id: tree[0].company.id } : null);
  let detail: Detail | null = null;
  let detailFailure: string | null = null;
  if (wanted && !failure) {
    try {
      detail = await center.orgItem<Detail>(wanted.kind, wanted.id);
    } catch (cause) {
      detailFailure =
        cause instanceof CenterError && cause.status === 404
          ? `그 ${KIND_LABEL[wanted.kind]}이 없습니다: ${wanted.id}`
          : cause instanceof CenterError
            ? cause.message
            : "알 수 없는 오류가 생겼습니다";
    }
  }
  const selectedKey = wanted ? nodeParam(wanted.kind, wanted.id) : "";
  const isSelected = (kind: OrgKind, id: string) => selectedKey === nodeParam(kind, id);

  const companyOf = !detail ? "" : wanted?.kind === "company" ? detail.id : (detail as DepartmentInfo | StaffInfo).company;
  const companyDepartments = departments
    .filter((one) => one.company === companyOf)
    .map((one) => ({ id: one.id, name: one.name }));
  const companyName = (id: string) => companies.find((one) => one.id === id)?.name ?? id;
  const departmentName = (id: string | null | undefined) =>
    id ? (departments.find((one) => one.id === id)?.name ?? id) : null;

  const workColumns: Array<Column<Work>> = [
    {
      key: "bpm_process_id",
      header: "프로세스",
      cell: (row) => {
        const version = row.versions?.[0];
        return version ? (
          <Link className="underline" href={packageHref({ id: row.bpm_process_id, version })}>
            {row.bpm_process_id}
          </Link>
        ) : (
          row.bpm_process_id
        );
      },
    },
    {
      key: "versions",
      header: "판",
      width: "16ch",
      cell: (row) => (row.versions && row.versions.length > 0 ? row.versions.join(", ") : "배포 없음"),
    },
    { key: "triggers", header: "시작 방법", cell: (row) => triggersLabel(row.triggers) },
  ];
  const runColumns: Array<Column<Recent>> = [
    {
      key: "run_id",
      header: "실행",
      mono: true,
      cell: (row) => (
        <Link className="underline" href={`/runs/${encodeURIComponent(row.run_id)}` as Route}>
          {row.run_id}
        </Link>
      ),
    },
    { key: "bpm_process_id", header: "프로세스", cell: (row) => row.bpm_process_id ?? "—" },
    {
      key: "status",
      header: "상태",
      width: "12ch",
      cell: (row) => <StatusBadge group="실행·노드" label={RUN_LABEL[row.status ?? ""] ?? row.status ?? "—"} />,
    },
    { key: "started_at", header: "시작", width: "12ch", cell: (row) => time(row.started_at) },
    { key: "requested_by", header: "시작한 것", cell: (row) => row.requested_by ?? "—" },
  ];

  let item: OrgItem | null = null;
  if (detail && wanted) {
    item = {
      kind: wanted.kind,
      id: detail.id,
      name: detail.name,
      state: detail.state ?? "active",
      company: companyOf,
      department: wanted.kind === "staff" ? (detail as StaffInfo).department : null,
    };
  }

  return (
    <Shell mode={found.mode} actor={found.actor} current="/organization">
      <header className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-h1 font-bold">조직</h1>
      </header>
      {failure ? (
        <ErrorBanner message={failure} />
      ) : (
        <div className="flex flex-col gap-6 md:flex-row md:items-start">
          {/* [T] 나무 */}
          <nav aria-label="조직 나무" className="flex w-full shrink-0 flex-col gap-2 md:w-64">
            {centerAdmin ? (
              <div key={`new-company-${selectedKey}`}>
                <NewOrgItem kind="company" />
              </div>
            ) : null}
            {tree.length === 0 ? (
              <EmptyState title="회사가 없습니다." />
            ) : (
              <ul className="flex flex-col border border-border-default bg-bg-surface py-1">
                {tree.map((one) => (
                  <li key={one.company.id}>
                    <ul>
                      <TreeLine kind="company" item={one.company} selected={isSelected("company", one.company.id)} depth={0} />
                      {one.departments.map((group) => (
                        <li key={group.department.id}>
                          <ul>
                            <TreeLine
                              kind="department"
                              item={group.department}
                              selected={isSelected("department", group.department.id)}
                              depth={1}
                            />
                            {group.staff.map((person) => (
                              <TreeLine
                                key={person.id}
                                kind="staff"
                                item={person}
                                selected={isSelected("staff", person.id)}
                                depth={2}
                              />
                            ))}
                          </ul>
                        </li>
                      ))}
                      {one.staff.map((person) => (
                        <TreeLine
                          key={person.id}
                          kind="staff"
                          item={person}
                          selected={isSelected("staff", person.id)}
                          depth={1}
                        />
                      ))}
                    </ul>
                  </li>
                ))}
              </ul>
            )}
          </nav>

          <div className="flex min-w-0 flex-1 flex-col gap-6">
            {detailFailure ? <ErrorBanner message={detailFailure} /> : null}
            {detail && item && wanted ? (
              <>
                {/* [H] 요약과 관리 동작 */}
                <section
                  key={selectedKey}
                  className="flex flex-wrap items-start justify-between gap-3 border border-border-default bg-bg-surface p-4"
                >
                  <div className="flex flex-col gap-1">
                    <span className="text-body-sm text-text-muted">{KIND_LABEL[wanted.kind]}</span>
                    <h2 className="flex items-center gap-2 text-h2 font-semibold">
                      {detail.name}
                      <StatusBadge group="조직" label={orgStateLabel(detail.state)} />
                    </h2>
                    <span className="text-body-sm text-text-muted">
                      <span className="font-mono">{detail.id}</span>
                      {wanted.kind !== "company" ? ` · ${companyName(companyOf)}` : ""}
                      {wanted.kind === "staff" ? ` · ${departmentName(item.department) ?? "부서 없음"}` : ""}
                      {` · 만든 날 ${fullTime(detail.created_at)}`}
                    </span>
                  </div>
                  {manage ? (
                    <div className="flex flex-wrap items-center gap-2">
                      {wanted.kind === "company" ? <NewOrgItem kind="department" company={companyOf} /> : null}
                      {wanted.kind !== "staff" ? (
                        <NewOrgItem
                          kind="staff"
                          company={companyOf}
                          departments={companyDepartments}
                          department={wanted.kind === "department" ? detail.id : null}
                        />
                      ) : null}
                      <OrgItemTools
                        item={item}
                        departments={companyDepartments}
                        canRename={wanted.kind !== "company" || centerAdmin}
                        canStop={wanted.kind !== "company" || centerAdmin}
                        removeBlocked={removeBlocked({
                          staff: "staff" in detail && typeof detail.staff === "number" ? detail.staff : 0,
                          work: detail.work,
                          recent_runs: detail.recent_runs,
                        })}
                      />
                    </div>
                  ) : null}
                </section>

                {/* [W] 그 자리의 업무 */}
                <Section title="이 자리의 업무">
                  {(detail.work ?? []).length === 0 ? (
                    <EmptyState
                      title="이 자리에 놓인 업무가 없습니다."
                      hint="업무 자리는 Studio가 올릴 때 고릅니다."
                    />
                  ) : (
                    <DataTable
                      columns={workColumns}
                      rows={detail.work ?? []}
                      rowKey={(row) => row.bpm_process_id}
                      caption="이 자리의 업무"
                    />
                  )}
                </Section>

                {/* [R] 최근 실행 */}
                <Section title="최근 실행">
                  {(detail.recent_runs ?? []).length === 0 ? (
                    <EmptyState title="이 자리 업무의 실행이 없습니다." />
                  ) : (
                    <DataTable
                      columns={runColumns}
                      rows={detail.recent_runs ?? []}
                      rowKey={(row) => row.run_id}
                      caption="최근 실행"
                    />
                  )}
                </Section>
              </>
            ) : null}
          </div>
        </div>
      )}
    </Shell>
  );
}
