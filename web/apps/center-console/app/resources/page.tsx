import Link from "next/link";
import { redirect } from "next/navigation";
import { DataTable, EmptyState, ErrorBanner, StatusBadge, type Column } from "@chaeksas/ui";
import type { PackageInfo } from "@chaeksas/api-types/c5-package-info";
import type { ContributedResource } from "@chaeksas/api-types/c7-contributed-resource";
import type { ConsumerFolderItem, ConsumerFolderScan } from "@chaeksas/api-types/c7-consumer-folder-scan";
import { CenterError, center, session, type ContributedKind } from "@/lib/center";
import type { FeatureRow } from "@/lib/features";
import { Shell } from "@/components/Shell";
import { loadFeatures } from "./load";
import { RefreshResources } from "./tools";

/**
 * CON-07 리소스 — 「기능」 하나와 확장이 기여한 자원 종류마다 탭 하나.
 *
 * 관리자가 여기서 묻는 것은 하나다: **이 기능을 BPM 프로세스가 지금 쓸 수 있나, 안 되면 무엇을 하나.**
 * 그래서 목록은 「이름 / 쓸 수 있나 / 할 일」 세 칸이고, 그 기능이 안에서 어떻게 도는지(서비스
 * 앱인지 외부 앱인지·무엇을 기여하나·어떤 로컬 런타임을 띄우나)는 보이지 않는다
 * (`docs/06-screens/center-console.md` CON-07). 셈은 `lib/features.ts`가 한다.
 *
 * 기여 자원 탭의 칸은 카탈로그의 **공통 칸**(id·이름·요약·갱신)뿐이다 — `data`는 확장 고유
 * 내용이라 Center도 콘솔도 해석하지 않는다 (C13 §5, ADR-0018).
 *
 * 서비스 앱·외부 앱은 **일꾼**으로 Center에 들어온다 (C15, ADR-0102). 일꾼은 Center 쪽 **일꾼 폴더**의 파일로만
 * 들어오고 외부 확장 정의는 그 일꾼이 올린다 (ADR-0122) — 이 화면에는 등록·승인·해제 단추가 없다. 「기능」 탭
 * 아래의 「일꾼 폴더」가 Center가 뜰 때 들인 결과를 보인다. 주소·키를 넣는 칸은 없다.
 */

/** C7 상태 → `status_map` 「서비스 앱」 묶음의 표기. 모르는 값은 그대로 (원칙 10). */
const APP_STATUS: Record<string, string> = {
  ok: "정상",
  degraded: "저하",
  unreachable: "응답 없음",
  unknown: "확인 전",
};

export function time(value: string | null | undefined): string {
  if (!value) return "—";
  const at = new Date(value);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(at.getMonth() + 1)}-${pad(at.getDate())} ${pad(at.getHours())}:${pad(at.getMinutes())}`;
}

export function appStatus(value: string): string {
  return APP_STATUS[value] ?? value;
}

export function featureHref(row: FeatureRow): string {
  return `/resources/features/${encodeURIComponent(row.key)}`;
}

export default async function ResourcesPage({
  searchParams,
}: {
  searchParams: Promise<{
    tab?: string;
    error?: string;
  }>;
}) {
  const found = await session();
  if (!found) redirect("/login");
  const asked = await searchParams;
  let rows: FeatureRow[] = [];
  let items: ContributedResource[] = [];
  let fetchedAt = "";
  let packages: PackageInfo[] = [];
  let kinds: ContributedKind[] = [];
  let failure: string | null = null;
  let folder: ConsumerFolderScan | null = null;
  // 어떤 기여 탭이 있는지는 **Center가 안다** (확장이 기여한 종류). 탭 이름을 화면이 짓지 않는다.
  try {
    kinds = (await center.contributedKinds()).items;
  } catch {
    kinds = []; // 종류를 못 읽어도 「기능」은 보여야 한다
  }
  const contributedTab = kinds.find((one) => one.resource_type === asked.tab);

  try {
    if (contributedTab) {
      const got = await center.contributed(contributedTab.resource_type);
      items = got.items;
      fetchedAt = got.fetched_at;
      packages = await center.packages();
    } else {
      const got = await loadFeatures();
      rows = got.rows;
      fetchedAt = got.fetchedAt;
      packages = got.input.packages;
    }
  } catch (cause) {
    failure = cause instanceof CenterError ? cause.message : "알 수 없는 오류가 생겼습니다";
  }
  // 일꾼 폴더는 따로 잡는다 — 못 읽으면 칸이 없을 뿐이다 (ADR-0122).
  try {
    if (!contributedTab) folder = await center.consumerFolder();
  } catch {
    folder = null;
  }

  const shortfall = packages
    .flatMap((one) =>
      (one.missing_resources ?? []).map((miss) => `${one.id}@${one.version}: ${miss.type} ${miss.id} (${miss.reason})`),
    )
    .slice(0, 8);

  const tabClass = (on: boolean) =>
    on
      ? "rounded-md border border-transparent bg-primary-subtle px-3 py-1 text-body font-semibold text-primary"
      : "rounded-md border border-border-default bg-bg-surface px-3 py-1 text-body text-text-secondary hover:bg-bg-subtle";

  return (
    <Shell mode={found.mode} actor={found.actor} current="/resources">
      <header className="mb-4 flex flex-wrap items-end justify-between gap-4">
        <h1 className="text-h1 font-bold">리소스</h1>
        <div className="flex items-center gap-3">
          {fetchedAt ? <span className="text-body-sm text-text-muted">확인 {time(fetchedAt)}</span> : null}
          {found.mode === "admin" ? <RefreshResources /> : null}
        </div>
      </header>

      <nav className="mb-4 flex flex-wrap gap-2" aria-label="리소스 종류">
        <Link href="/resources" aria-current={!contributedTab ? "page" : undefined} className={tabClass(!contributedTab)}>
          기능
        </Link>
        {/* 확장이 기여한 자원 종류마다 탭 하나 (C7) — 플랫폼은 그 뜻을 모른다. */}
        {kinds.map((one) => (
          <Link
            key={one.resource_type}
            href={`/resources?tab=${encodeURIComponent(one.resource_type)}`}
            aria-current={contributedTab?.resource_type === one.resource_type ? "page" : undefined}
            className={tabClass(contributedTab?.resource_type === one.resource_type)}
          >
            {one.label} ({one.count})
          </Link>
        ))}
      </nav>

      {shortfall.length > 0 ? (
        <div className="mb-4">
          <ErrorBanner message={`프로세스가 요구하지만 쓸 수 없는 기능: ${shortfall.join(" · ")}`} />
        </div>
      ) : null}
      {failure ? <ErrorBanner message={failure} /> : null}
      {asked.error ? <ErrorBanner message={asked.error} /> : null}

      {contributedTab ? (
        <Contributed kind={contributedTab} items={items} />
      ) : (
        <>
          <Features rows={rows} />
          {folder?.configured ? <ConsumerFolder scan={folder} /> : null}
        </>
      )}
    </Shell>
  );
}

function Features({ rows }: { rows: FeatureRow[] }) {
  const columns: Array<Column<FeatureRow>> = [
    {
      key: "name",
      header: "이름",
      cell: (row) => (
        <Link className="underline" href={featureHref(row) as never}>
          {row.name}
        </Link>
      ),
    },
    {
      key: "usable",
      header: "쓸 수 있나",
      width: "14ch",
      cell: (row) => <StatusBadge group="기능" label={row.usable} />,
    },
    {
      key: "todos",
      header: "할 일",
      cell: (row) =>
        row.todos.length === 0 ? (
          ""
        ) : (
          <span className="flex flex-col gap-1">
            {row.todos.map((todo) =>
              todo.href ? (
                <Link key={todo.kind} className="underline" href={todo.href as never}>
                  {todo.text}
                </Link>
              ) : (
                <span key={todo.kind}>{todo.text}</span>
              ),
            )}
          </span>
        ),
    },
  ];
  return (
    <div className="flex flex-col gap-6">
      {rows.length === 0 ? (
        <EmptyState
          title="쓸 수 있는 기능이 없습니다."
          hint="일꾼 폴더에 일꾼 파일을 두고 Center를 다시 띄운 뒤 그 일꾼을 띄우면 여기에 보입니다."
        />
      ) : (
        <DataTable columns={columns} rows={rows} rowKey={(row) => row.key} caption="기능" />
      )}

    </div>
  );
}

const FOLDER_OUTCOME: Record<string, string> = {
  registered: "들임",
  unchanged: "그대로",
  refused: "거절",
  revoked: "해제함",
};

function folderTarget(row: ConsumerFolderItem): string {
  if (!row.id) return "—";
  if (row.kind === "consumer") return `일꾼 ${row.id}`;
  if (row.kind === "key") return `키 ${row.id}`;
  return `${row.id}@${row.version ?? "?"}`;
}

/**
 * 「일꾼 폴더」 (ADR-0122·0123) — Center가 **뜰 때** 일꾼 파일·키 파일을 들인 결과와, 맡은 일꾼이 없어 거둔 확장. 고치는
 * 단추는 없다 — 파일을 바꾸거나 빼고 Center를 다시 띄우는 것이 고치는 길이다.
 */
function ConsumerFolder({ scan }: { scan: ConsumerFolderScan }) {
  const items = scan.items ?? [];
  const columns: Array<Column<ConsumerFolderItem>> = [
    { key: "file", header: "파일", mono: true, cell: (row) => row.file ?? "—" },
    { key: "target", header: "대상", mono: true, cell: folderTarget },
    { key: "outcome", header: "결과", width: "10ch", cell: (row) => FOLDER_OUTCOME[row.outcome] ?? row.outcome },
    { key: "message", header: "사유", cell: (row) => row.message ?? "" },
  ];
  return (
    <section
      id="consumer-folder"
      className="mt-6 flex flex-col gap-2 rounded-lg border border-border-default bg-bg-surface p-5 shadow-sm"
    >
      <h2 className="text-h2 font-semibold">일꾼 폴더</h2>
      <p className="text-body-sm text-text-muted">
        Center가 뜰 때 <span className="font-mono">{scan.dir}</span>을 읽었습니다 ({time(scan.scanned_at)})
      </p>
      {scan.problem ? (
        <ErrorBanner message={scan.problem} />
      ) : items.length === 0 ? (
        <p className="text-body text-text-muted">폴더에 일꾼 파일(*.consumer.json)·키 파일(*.key.json)이 없습니다.</p>
      ) : (
        <DataTable
          columns={columns}
          rows={items}
          rowKey={(row) => `${row.kind}:${row.file ?? ""}:${row.id ?? ""}:${row.version ?? ""}`}
          caption="일꾼 폴더"
        />
      )}
    </section>
  );
}

/**
 * 확장이 기여한 자원 하나의 종류 (CON-07 탭).
 *
 * **공통 칸만 그린다** — `data`는 확장 고유 내용이라 콘솔이 해석하지 않는다 (C13 §5). 자원의
 * 자세한 모습은 그 확장의 관리 콘솔에서 본다.
 */
function Contributed({ kind, items }: { kind: ContributedKind; items: ContributedResource[] }) {
  const columns: Array<Column<ContributedResource>> = [
    { key: "id", header: "자원 id", mono: true },
    { key: "name", header: "이름", cell: (row) => row.name ?? "—" },
    { key: "summary", header: "요약", cell: (row) => row.summary ?? "—" },
    { key: "extension_id", header: "기여한 확장", width: "18ch", cell: (row) => row.extension_id ?? "—" },
    { key: "updated_at", header: "마지막 갱신", width: "16ch", cell: (row) => time(row.updated_at) },
    {
      key: "used_by",
      header: "쓰는 프로세스",
      cell: (row) => ((row.used_by ?? []).length > 0 ? (row.used_by ?? []).join(", ") : "—"),
    },
  ];

  return (
    <div className="flex flex-col gap-4">
      {/* 읽기 실패를 **조용히 빈 목록으로 보이지 않는다** — 「없다」와 「못 읽었다」는 다르다. */}
      {kind.errors.length > 0 ? (
        <ErrorBanner
          message={`카탈로그를 읽지 못했습니다 — 아래는 마지막으로 읽은 것입니다: ${kind.errors.join(" · ")}`}
        />
      ) : null}
      {items.length === 0 ? (
        <EmptyState
          title={`${kind.label}이 아직 없습니다.`}
          hint={
            kind.extensions.length > 0
              ? `${kind.extensions.join(", ")}이 올린 것이 없습니다.`
              : undefined
          }
        />
      ) : (
        <DataTable
          columns={columns}
          rows={items}
          rowKey={(row) => `${row.resource_type}:${row.id}`}
          caption={kind.label}
        />
      )}
    </div>
  );
}
