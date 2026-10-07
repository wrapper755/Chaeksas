import Link from "next/link";
import { redirect } from "next/navigation";
import { Button, DataTable, EmptyState, ErrorBanner, StatusBadge, type Column } from "@chaeksas/ui";
import type { ExtensionResource } from "@chaeksas/api-types/c7-extension-resource";
import type { ServiceAppResource } from "@chaeksas/api-types/c7-service-app-resource";
import type { ToolpackResource } from "@chaeksas/api-types/c7-toolpack-resource";
import type { RuntimeResource } from "@chaeksas/api-types/c7-runtime-resource";
import type { PackageInfo } from "@chaeksas/api-types/c5-package-info";
import { CENTER_URL, CenterError, center, session } from "@/lib/center";
import { Shell } from "@/components/Shell";
import { registerExtension, registerServiceApp } from "@/app/actions";
import { RefreshResources } from "./tools";

/**
 * CON-07 리소스.
 *
 * 고정 탭 넷(확장·서비스 앱·툴팩·런타임). **키는 다루지 않는다** (C7 — 서비스 앱 키는 각
 * 앱의 관리 콘솔에서 발급한다, ADR-0013).
 *
 * 확장이 기여한 자원(「UI 화면」)은 아직 모으지 않는다 — 내장 확장의 정의가 Center에 없어
 * `catalog_url`을 찾을 길이 없다 (C11 manifest에 카탈로그 칸을 더해야 한다). 그래서 그 탭을
 * **끄고 이유를 보인다** (U3 — 없는 것을 빈 탭으로 두지 않는다).
 */

/** C7 상태 → `status_map` 「서비스 앱」 묶음의 표기. 모르는 값은 그대로 (원칙 10). */
const APP_STATUS: Record<string, string> = {
  ok: "정상",
  degraded: "저하",
  unreachable: "응답 없음",
  unknown: "확인 전",
};

const TIER: Record<string, string> = { builtin: "내장", internal: "사내", external: "외부" };

const PROTOCOL: Record<string, string> = { "chk-c11": "C11", "http-adapter": "HTTP 어댑터" };

const PACKAGE_STATUS: Record<string, string> = {
  candidate: "후보",
  approved: "승인됨",
  deprecated: "지원 종료",
  revoked: "철회",
};

const TABS = [
  { key: "extension", label: "확장" },
  { key: "service_app", label: "서비스 앱" },
  { key: "toolpack", label: "툴팩" },
  { key: "runtime", label: "런타임" },
] as const;

export function time(value: string | null | undefined): string {
  if (!value) return "—";
  const at = new Date(value);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(at.getMonth() + 1)}-${pad(at.getDate())} ${pad(at.getHours())}:${pad(at.getMinutes())}`;
}

export function appStatus(value: string): string {
  return APP_STATUS[value] ?? value;
}

export default async function ResourcesPage({
  searchParams,
}: {
  searchParams: Promise<{
    tab?: string;
    error?: string;
    registered?: string;
    extension?: string;
    revoked?: string;
  }>;
}) {
  const found = await session();
  if (!found) redirect("/login");
  const asked = await searchParams;
  const tab = TABS.some((one) => one.key === asked.tab) ? asked.tab! : "extension";

  let items: unknown[] = [];
  let fetchedAt = "";
  let packages: PackageInfo[] = [];
  let failure: string | null = null;
  try {
    const got = await center.resources<unknown>(tab);
    items = got.items;
    fetchedAt = got.fetched_at;
    // 경고 띠는 **패키지가 요구하는데 없는 것**에서 온다 (C7 누락 검사).
    packages = await center.packages();
  } catch (cause) {
    failure = cause instanceof CenterError ? cause.message : "알 수 없는 오류가 생겼습니다";
  }

  const shortfall = packages
    .flatMap((one) =>
      (one.missing_resources ?? []).map((miss) => `${one.id}@${one.version}: ${miss.type} ${miss.id} (${miss.reason})`),
    )
    .slice(0, 8);

  return (
    <Shell mode={found.mode} actor={found.actor} centerUrl={CENTER_URL} current="/resources">
      <header className="mb-4 flex items-end justify-between gap-4">
        <div>
          <h1 className="text-h1 font-bold">리소스</h1>
          <p className="text-body text-text-secondary">
            Bot이 실행에 필요로 하는 바깥 자원입니다. 키는 각 서비스 앱의 관리 콘솔에서 다룹니다.
            {fetchedAt ? ` · 확인 ${time(fetchedAt)}` : ""}
          </p>
        </div>
        {found.mode === "admin" ? <RefreshResources /> : null}
      </header>

      <nav className="mb-4 flex flex-wrap gap-2" aria-label="리소스 종류">
        {TABS.map((one) => (
          <Link
            key={one.key}
            href={`/resources?tab=${one.key}`}
            aria-current={tab === one.key ? "page" : undefined}
            className={
              tab === one.key
                ? "border border-border-strong bg-bg-subtle px-3 py-1 text-body"
                : "border border-border-default px-3 py-1 text-body text-text-secondary"
            }
          >
            {one.label}
          </Link>
        ))}
        {/* 아직 없는 탭은 **끄고 이유를 보인다** (U3). */}
        <span
          className="cursor-not-allowed border border-border-default px-3 py-1 text-body text-text-muted"
          title="내장 확장의 카탈로그 주소를 Center가 아직 알 수 없습니다 (C11 manifest에 칸을 더해야 합니다)"
        >
          UI 화면 (M5에서 만듭니다)
        </span>
      </nav>

      {failure ? <ErrorBanner message={failure} /> : null}
      {asked.error ? <ErrorBanner message={asked.error} /> : null}
      {asked.registered ? (
        <p className="mb-4 text-body text-status-completed-fg">서비스 앱을 등록했습니다.</p>
      ) : null}
      {asked.extension ? (
        <p className="mb-4 text-body text-status-completed-fg">확장을 등록했습니다.</p>
      ) : null}
      {shortfall.length > 0 ? (
        <div className="mb-4">
          <ErrorBanner message={`Bot이 요구하지만 없는 리소스: ${shortfall.join(" · ")}`} />
        </div>
      ) : null}

      {asked.revoked ? (
        <p className="mb-4 text-body text-status-completed-fg">확장 등록을 해제했습니다.</p>
      ) : null}

      {tab === "extension" ? (
        <Extensions items={items as ExtensionResource[]} admin={found.mode === "admin"} />
      ) : null}
      {tab === "service_app" ? (
        <ServiceApps items={items as ServiceAppResource[]} admin={found.mode === "admin"} />
      ) : null}
      {tab === "toolpack" ? <Toolpacks items={items as ToolpackResource[]} /> : null}
      {tab === "runtime" ? <Runtimes items={items as RuntimeResource[]} /> : null}
    </Shell>
  );
}

function Extensions({ items, admin }: { items: ExtensionResource[]; admin: boolean }) {
  const columns: Array<Column<ExtensionResource>> = [
    {
      key: "name",
      header: "이름",
      cell: (row) =>
        // 외부 확장만 상세가 있다 — 정의·봉투가 Center에 있는 것이 그것뿐이다.
        row.tier === "external" ? (
          <Link className="underline" href={`/resources/extensions/${encodeURIComponent(row.id)}`}>
            {row.name ?? row.id}
          </Link>
        ) : (
          (row.name ?? "—")
        ),
    },
    { key: "id", header: "id", mono: true },
    { key: "tier", header: "등급", width: "10ch", cell: (row) => TIER[row.tier] ?? row.tier },
    { key: "version", header: "버전", width: "12ch", mono: true },
    {
      key: "protocol",
      header: "연결 방식",
      width: "14ch",
      cell: (row) => (row.protocol ? (PROTOCOL[row.protocol] ?? row.protocol) : "없음"),
    },
    {
      key: "installed_on",
      header: "설치된 Bot UI",
      width: "14ch",
      align: "right",
      cell: (row) => `${row.installed_on?.hosts ?? 0}대`,
    },
    {
      key: "service_app_id",
      header: "서버 부분",
      // HTTP 어댑터 확장도 **서버 부분이 있다** (바깥 앱) — C11 서비스 앱이 아닐 뿐이다.
      // 「없음」이라고 적으면 키를 어디로 보내는지 모르는 것처럼 읽힌다.
      cell: (row) =>
        row.service_app_id ? (
          <Link className="underline" href={`/resources/service-apps/${encodeURIComponent(row.service_app_id)}`}>
            {row.service_app_id}
          </Link>
        ) : row.protocol === "http-adapter" ? (
          "외부 앱 (어댑터)"
        ) : (
          "없음 (클라이언트 기여만)"
        ),
    },
    {
      key: "status",
      header: "상태",
      width: "12ch",
      cell: (row) =>
        row.status === "n/a" ? "—" : <StatusBadge group="서비스 앱" label={appStatus(row.status ?? "")} />,
    },
  ];
  return (
    <div className="flex flex-col gap-6">
      {items.length === 0 ? (
        <EmptyState
          title="설치·등록된 확장이 없습니다."
          hint="내장 확장은 Bot UI가 보고하면 나타납니다. 외부 확장은 아래에서 등록하세요."
        />
      ) : (
        <DataTable columns={columns} rows={items} rowKey={(row) => row.id} caption="확장" />
      )}

      {admin ? (
        <section className="flex flex-col gap-2">
          <h2 className="text-h2 font-semibold">확장 추가 (외부)</h2>
          <p className="text-body-sm text-text-muted">
            정의 파일과 <strong>Admin 서명 봉투</strong>를 함께 올리세요 — 서명 없이는 등록되지
            않습니다. 봉투는 관리자 PC에서 <code>chk-admin sign-extension &lt;정의 파일&gt;</code>로
            만듭니다. 내장·사내 확장은 설치 파일에 든 것만 쓰므로 여기서 등록할 수 없습니다.
          </p>
          <form action={registerExtension} className="flex max-w-2xl flex-col gap-2">
            <label className="flex flex-col gap-1 text-body-sm">
              <span className="text-text-muted">확장 정의 파일 (extension.json) *</span>
              <input type="file" name="definition" accept=".json,application/json" required className="text-body" />
            </label>
            <label className="flex flex-col gap-1 text-body-sm">
              <span className="text-text-muted">서명 봉투 파일 *</span>
              <input type="file" name="envelope" accept=".json,application/json" required className="text-body" />
            </label>
            <div>
              <Button type="submit" variant="primary">
                등록
              </Button>
            </div>
          </form>
        </section>
      ) : null}
    </div>
  );
}

function ServiceApps({ items, admin }: { items: ServiceAppResource[]; admin: boolean }) {
  const columns: Array<Column<ServiceAppResource>> = [
    {
      key: "name",
      header: "앱 이름",
      cell: (row) => (
        <Link className="underline" href={`/resources/service-apps/${encodeURIComponent(row.app_id)}`}>
          {row.name ?? row.app_id}
        </Link>
      ),
    },
    { key: "app_id", header: "id", mono: true },
    {
      key: "category",
      header: "구분",
      width: "10ch",
      cell: (row) => (row.category === "system" ? "시스템" : row.category === "business" ? "업무" : "—"),
    },
    { key: "version", header: "버전", width: "10ch", mono: true, cell: (row) => row.version ?? "—" },
    {
      key: "status",
      header: "상태",
      cell: (row) => (
        <span className="inline-flex items-center gap-2">
          <StatusBadge group="서비스 앱" label={appStatus(row.status ?? "unknown")} />
          <span className="text-caption text-text-muted">{time(row.checked_at)}</span>
        </span>
      ),
    },
    { key: "base_url", header: "API 주소", mono: true, cell: (row) => row.base_url ?? "—" },
    {
      key: "operations",
      header: "작업",
      width: "8ch",
      align: "right",
      cell: (row) => `${row.operations?.length ?? 0}개`,
    },
  ];

  return (
    <div className="flex flex-col gap-6">
      {items.length === 0 ? (
        <EmptyState
          title="등록된 서비스 앱이 없습니다."
          hint={admin ? "아래 「서비스 앱 추가」에 API 주소를 넣으세요." : undefined}
        />
      ) : (
        <DataTable columns={columns} rows={items} rowKey={(row) => row.app_id} caption="서비스 앱" />
      )}

      {admin ? (
        <section className="flex flex-col gap-2">
          <h2 className="text-h2 font-semibold">서비스 앱 추가</h2>
          <p className="text-body-sm text-text-muted">
            주소만 넣으세요 — Center가 <code>/manifest</code>를 읽어 앱 이름과 작업을 가져옵니다.
            읽지 못하면 등록하지 않습니다.
          </p>
          <form action={registerServiceApp} className="flex max-w-xl flex-wrap items-end gap-2">
            <label className="flex flex-1 flex-col gap-1 text-body-sm">
              <span className="text-text-muted">API 주소 *</span>
              <input
                type="url"
                name="base_url"
                required
                placeholder="http://svc-uia:8810"
                className="h-9 border border-border-strong bg-bg-surface px-2 text-body"
              />
            </label>
            <Button type="submit" variant="primary">
              등록
            </Button>
          </form>
        </section>
      ) : null}
    </div>
  );
}

function Toolpacks({ items }: { items: ToolpackResource[] }) {
  const columns: Array<Column<ToolpackResource>> = [
    { key: "id", header: "id", mono: true },
    { key: "version", header: "버전", width: "12ch", mono: true },
    {
      key: "status",
      header: "상태",
      width: "12ch",
      cell: (row) => <StatusBadge group="패키지" label={PACKAGE_STATUS[row.status] ?? row.status} />,
    },
    {
      key: "tools",
      header: "도구",
      cell: (row) =>
        (row.tools ?? []).length > 0
          ? (row.tools ?? []).map((one) => String((one as { name?: unknown }).name ?? "")).join(", ")
          : "—",
    },
  ];
  if (items.length === 0) {
    return (
      <EmptyState
        title="올라온 툴팩이 없습니다."
        hint="툴팩은 따로 등록하지 않습니다 — 패키지로 올리면 여기에 나타납니다."
      />
    );
  }
  return (
    <DataTable columns={columns} rows={items} rowKey={(row) => `${row.id}@${row.version}`} caption="툴팩" />
  );
}

function Runtimes({ items }: { items: RuntimeResource[] }) {
  const columns: Array<Column<RuntimeResource>> = [
    {
      key: "host",
      header: "실행하는 곳",
      cell: (row) =>
        row.host.type === "bot_ui" ? (
          <Link className="underline" href={`/bot-uis/${encodeURIComponent(row.host.id)}`}>
            {row.host.name ?? row.host.id}
          </Link>
        ) : (
          (row.host.name ?? row.host.id)
        ),
    },
    {
      key: "type",
      header: "종류",
      width: "12ch",
      cell: (row) => (row.host.type === "bot_ui" ? "Bot UI" : "서버 실행기"),
    },
    { key: "os", header: "OS", width: "20ch", cell: (row) => row.os ?? "—" },
    {
      key: "core",
      header: "core",
      width: "10ch",
      mono: true,
      cell: (row) => row.versions?.core ?? "—",
    },
    {
      key: "worker",
      header: "Worker",
      width: "10ch",
      mono: true,
      cell: (row) => row.versions?.worker ?? "—",
    },
    { key: "browsers", header: "브라우저", cell: (row) => (row.browsers ?? []).join(", ") || "—" },
    {
      key: "desktop_backend",
      header: "데스크톱",
      width: "12ch",
      cell: (row) => row.desktop_backend ?? "—",
    },
    {
      key: "extensions",
      header: "확장",
      cell: (row) =>
        (row.extensions ?? [])
          .map((one) => String((one as { id?: unknown }).id ?? ""))
          .filter(Boolean)
          .join(", ") || "—",
    },
  ];
  if (items.length === 0) {
    return (
      <EmptyState
        title="보고된 런타임이 없습니다."
        hint="Bot UI가 등록·하트비트로 보고하면 여기에 나타납니다."
      />
    );
  }
  return <DataTable columns={columns} rows={items} rowKey={(row) => row.host.id} caption="런타임" />;
}
