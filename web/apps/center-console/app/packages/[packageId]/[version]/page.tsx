import Link from "next/link";
import { redirect } from "next/navigation";
import { DataTable, ErrorBanner, StatusBadge, type Column } from "@chaeksas/ui";
import type { PackageInfo } from "@chaeksas/api-types/c5-package-info";
import type { DependentInfo } from "@chaeksas/api-types/c5-dependent-info";
import type { ProvidedProcess, ProvidedTool } from "@chaeksas/api-types/c1-manifest";
import { CENTER_URL, CenterError, center, session } from "@/lib/center";
import { Shell } from "@/components/Shell";
import { DeletePackage } from "../../tools";
import { KIND_LABEL, STATUS_LABEL, packageHref, time } from "../../page";

/**
 * CON-06 공통 패키지 (상세).
 *
 * 「제공 도구」·「제공 정의」는 **매니페스트의 `provides`**(C1)를 그린다 — Center가 짓지 않는다.
 * `provides`가 아예 없으면 **빈 표로 두지 않고** 「매니페스트에 없습니다」라고 말한다:
 * 「제공하는 것이 없다」와 「적히지 않았다」는 다르다.
 */

/** `relation` → 사람 말 (C5). 모르는 값은 그대로 보인다 (원칙 10). */
const RELATION_LABEL: Record<string, string> = {
  lib: "공유 BPM 프로세스",
  toolpack: "툴팩",
};

const LOCATION_LABEL: Record<string, string> = { pc: "PC", server: "서버" };

/** 「실행 요구」 한 줄 — 비어 있는 칸은 빼고 적는다. */
function requirements(info: PackageInfo): Array<[string, string]> {
  const requires = info.manifest?.requires;
  if (!requires) return [];
  const rows: Array<[string, string]> = [
    ["코어", requires.core ?? ""],
    ["AI 환경", (requires.domains ?? []).join(", ")],
    ["도구", (requires.tools ?? []).join(", ")],
    ["설정", (requires.settings ?? []).join(", ")],
    ["비밀 이름", (requires.secrets ?? []).join(", ")],
    ["서비스 앱", (requires.service_apps ?? []).map((one) => one.app_id).join(", ")],
    ["확장", (requires.extensions ?? []).map((one) => `${one.id} ${one.version}`).join(", ")],
    ["태스크 종류", (requires.task_types ?? []).map((one) => one.id).join(", ")],
    ["공유 BPM 프로세스", (requires.libs ?? []).join(", ")],
    ["툴팩", (requires.toolpacks ?? []).map((one) => `${one.id}@${one.version}`).join(", ")],
    ["런타임", (requires.runtimes ?? []).join(", ")],
    ["OS", (requires.os ?? []).join(", ")],
  ];
  return rows.filter(([, value]) => value !== "");
}

/** 사람 개입을 한 줄로. 아무것도 없으면 「없음」이다. */
function human(found: ProvidedProcess["human"]): string {
  if (!found) return "—";
  const said = [
    found.approval_center ? "Center 결재" : "",
    found.approval_field ? "현장 결재" : "",
    found.confirmation ? "확인" : "",
  ].filter(Boolean);
  return said.length > 0 ? said.join(", ") : "없음";
}

/** 인자 이름만 보인다 — `args`는 JSON Schema다 (값은 없다). */
function argNames(schema: ProvidedTool["args"]): string {
  const found = (schema as { properties?: Record<string, unknown> } | undefined)?.properties;
  return found ? Object.keys(found).join(", ") || "—" : "—";
}

export default async function PackagePage({
  params,
}: {
  params: Promise<{ packageId: string; version: string }>;
}) {
  const found = await session();
  if (!found) redirect("/login");
  const asked = await params;
  const packageId = decodeURIComponent(asked.packageId);
  const version = decodeURIComponent(asked.version);

  let info: PackageInfo | null = null;
  let users: DependentInfo[] = [];
  let failure: string | null = null;
  try {
    info = await center.packageInfo(packageId, version);
    users = await center.dependents(packageId, version);
  } catch (cause) {
    failure = cause instanceof CenterError ? cause.message : "알 수 없는 오류가 생겼습니다";
  }

  const provides = info?.manifest?.provides ?? null;

  const toolColumns: Array<Column<ProvidedTool>> = [
    { key: "name", header: "이름", mono: true },
    { key: "domain", header: "환경", width: "10ch" },
    { key: "description", header: "설명", cell: (row) => row.description ?? "—" },
    { key: "args", header: "인자", cell: (row) => argNames(row.args) },
  ];

  const processColumns: Array<Column<ProvidedProcess>> = [
    { key: "process_id", header: "정의 id", mono: true },
    { key: "name", header: "이름", cell: (row) => row.name ?? "—" },
    { key: "file", header: "파일", mono: true },
    { key: "reads", header: "읽는 변수", cell: (row) => (row.reads ?? []).join(", ") || "—" },
    { key: "writes", header: "쓰는 변수", cell: (row) => (row.writes ?? []).join(", ") || "—" },
    {
      key: "run_location",
      header: "실행 위치",
      width: "9ch",
      cell: (row) => (row.run_location ? LOCATION_LABEL[row.run_location] : "—"),
    },
    { key: "ai_tasks", header: "AI 태스크", width: "10ch", cell: (row) => String(row.ai_tasks ?? 0) },
    { key: "human", header: "결재", cell: (row) => human(row.human) },
    { key: "description", header: "설명", cell: (row) => row.description ?? "—" },
  ];

  const dependentColumns: Array<Column<DependentInfo>> = [
    {
      key: "id",
      header: "id",
      mono: true,
      cell: (row) => (
        <Link className="underline" href={packageHref(row)}>
          {row.id}
        </Link>
      ),
    },
    { key: "version", header: "버전", width: "12ch", mono: true },
    { key: "kind", header: "종류", width: "16ch", cell: (row) => KIND_LABEL[row.kind] ?? row.kind },
    { key: "name", header: "이름", cell: (row) => row.name ?? "—" },
    {
      key: "status",
      header: "상태",
      width: "10ch",
      cell: (row) => <StatusBadge group="패키지" label={STATUS_LABEL[row.status] ?? row.status} />,
    },
    {
      key: "relation",
      header: "관계",
      width: "16ch",
      cell: (row) => RELATION_LABEL[row.relation] ?? row.relation,
    },
    {
      key: "pinned_hash",
      header: "고정 해시",
      mono: true,
      cell: (row) => row.pinned_hash ?? "—",
    },
  ];

  return (
    <Shell mode={found.mode} actor={found.actor} centerUrl={CENTER_URL} current="/packages">
      <header className="mb-4">
        <h1 className="text-h1 font-bold">
          {info?.name ?? packageId} <span className="font-mono text-h2">{version}</span>
        </h1>
        <p className="text-body text-text-secondary">
          <Link className="underline" href="/packages">
            공통 패키지
          </Link>
          로 돌아가기
        </p>
      </header>

      {failure ? <ErrorBanner message={failure} /> : null}

      {info ? (
        <div className="flex flex-col gap-6">
          <section className="flex flex-col gap-2">
            <h2 className="text-h2 font-semibold">요약</h2>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-body sm:grid-cols-4">
              <dt className="text-text-muted">id</dt>
              <dd className="font-mono">{info.id}</dd>
              <dt className="text-text-muted">종류</dt>
              <dd>{KIND_LABEL[info.kind] ?? info.kind}</dd>
              <dt className="text-text-muted">상태</dt>
              <dd>
                <StatusBadge group="패키지" label={STATUS_LABEL[info.status] ?? info.status} />
              </dd>
              <dt className="text-text-muted">내용 해시</dt>
              <dd className="truncate font-mono">{info.content_hash}</dd>
              <dt className="text-text-muted">올린 시각</dt>
              <dd>{time(info.uploaded_at)}</dd>
              <dt className="text-text-muted">올린 이</dt>
              <dd>{info.uploaded_by}</dd>
              <dt className="text-text-muted">승인 서명</dt>
              <dd>{info.signed_by ? `${info.signed_by} · ${time(info.signed_at)}` : "없음"}</dd>
            </dl>
            {info.manifest?.description ? (
              <p className="text-body text-text-secondary">{info.manifest.description}</p>
            ) : null}
            {(info.missing_resources ?? []).length > 0 ? (
              <p className="text-body-sm text-text-muted">
                누락 리소스:{" "}
                {(info.missing_resources ?? [])
                  .map((one) => `${one.type} ${one.id} (${one.reason})`)
                  .join(", ")}
              </p>
            ) : null}
          </section>

          <section className="flex flex-col gap-2">
            <h2 className="text-h2 font-semibold">실행 요구</h2>
            {requirements(info).length === 0 ? (
              <p className="text-body-sm text-text-muted">요구하는 것이 없습니다.</p>
            ) : (
              <dl className="grid grid-cols-[12ch_1fr] gap-x-6 gap-y-1 text-body">
                {requirements(info).map(([label, value]) => (
                  <div key={label} className="contents">
                    <dt className="text-text-muted">{label}</dt>
                    <dd>{value}</dd>
                  </div>
                ))}
              </dl>
            )}
          </section>

          {info.kind === "toolpack" ? (
            <section className="flex flex-col gap-2">
              <h2 className="text-h2 font-semibold">제공 도구</h2>
              {!provides ? (
                <p className="text-body-sm text-text-muted">매니페스트에 `provides`가 없습니다.</p>
              ) : (provides.tools ?? []).length === 0 ? (
                <p className="text-body-sm text-text-muted">제공하는 도구가 없습니다.</p>
              ) : (
                <DataTable
                  columns={toolColumns}
                  rows={provides.tools ?? []}
                  rowKey={(row) => row.name}
                  caption="제공 도구"
                />
              )}
            </section>
          ) : null}

          {info.kind === "process_lib" ? (
            <section className="flex flex-col gap-2">
              <h2 className="text-h2 font-semibold">제공 정의</h2>
              {!provides ? (
                <p className="text-body-sm text-text-muted">매니페스트에 `provides`가 없습니다.</p>
              ) : (provides.processes ?? []).length === 0 ? (
                <p className="text-body-sm text-text-muted">제공하는 정의가 없습니다.</p>
              ) : (
                <DataTable
                  columns={processColumns}
                  rows={provides.processes ?? []}
                  rowKey={(row) => row.process_id}
                  caption="제공 정의"
                />
              )}
            </section>
          ) : null}

          <section className="flex flex-col gap-2">
            <h2 className="text-h2 font-semibold">이 패키지를 쓰는 패키지</h2>
            {users.length === 0 ? (
              <p className="text-body-sm text-text-muted">아직 없습니다.</p>
            ) : (
              <DataTable
                columns={dependentColumns}
                rows={users}
                rowKey={(row) => `${row.id}@${row.version}:${row.relation}`}
                caption="이 패키지를 쓰는 패키지"
              />
            )}
          </section>

          {found.mode === "admin" ? (
            <section className="flex flex-col gap-3">
              <h2 className="text-h2 font-semibold">관리</h2>
              <p className="text-body-sm text-text-muted">
                승인·철회는 콘솔에서 하지 않습니다 — 서명이 필요해서 Admin이 합니다 (CON-00).
              </p>
              <DeletePackage packageId={info.id} version={info.version} />
            </section>
          ) : null}
        </div>
      ) : null}
    </Shell>
  );
}
