import Link from "next/link";
import type { Route } from "next";
import { redirect } from "next/navigation";
import { DataTable, EmptyState, ErrorBanner, type Column } from "@chaeksas/ui";
import { CenterError, center, session } from "@/lib/center";
import { Shell } from "@/components/Shell";
import { fullTime } from "@/app/bot-uis/page";
import { APP_KINDS, APP_LABEL, buildAppLog, type AppKind, type AppLogRow } from "@/lib/app-logs";

/**
 * CON-16 앱 로그 — 앱(Studio·Bot·서버 실행기)이 Center와 주고받은 이력 (ADR-0121).
 *
 * **새로 쌓는 것은 없다** — 등록 요청(C5)·키(C7)·배치 결정(C4·C12)을 읽어 `buildAppLog`가 합친다.
 * 하트비트가 끊긴 때는 Center가 남기지 않아 여기 없다 (지금 상태는 CON-03이 말한다).
 */

const LIMITS = [50, 100, 200, 500];
const DEFAULT_LIMIT = 100;

export default async function AppLogsPage({
  searchParams,
}: {
  searchParams: Promise<{ app?: string; limit?: string }>;
}) {
  const found = await session();
  if (!found) redirect("/login");
  const query = await searchParams;
  const app = (APP_KINDS as string[]).includes(query.app ?? "") ? (query.app as AppKind) : null;
  const limit = LIMITS.includes(Number(query.limit)) ? Number(query.limit) : DEFAULT_LIMIT;

  let rows: AppLogRow[] = [];
  let failure: string | null = null;
  try {
    const [enrollments, keys, bots, runners] = await Promise.all([
      center.enrollmentHistory(),
      center.centerKeys(),
      center.botUis(),
      center.serverRunners(),
    ]);
    rows = buildAppLog({
      enrollments,
      keys,
      hosts: [
        ...bots.map((one) => ({ kind: "bot_ui" as const, name: one.name, results: one.deployment_results ?? [] })),
        ...runners.map((one) => ({
          kind: "server_runner" as const,
          name: one.name,
          results: one.deployment_results ?? [],
        })),
      ],
    });
  } catch (cause) {
    failure = cause instanceof CenterError ? cause.message : "알 수 없는 오류가 생겼습니다";
  }
  const shown = (app ? rows.filter((row) => row.kind === app) : rows).slice(0, limit);

  const columns: Array<Column<AppLogRow>> = [
    { key: "at", header: "시각", width: "18ch", cell: (row) => fullTime(row.at) },
    { key: "kind", header: "앱", width: "12ch", cell: (row) => APP_LABEL[row.kind] },
    { key: "name", header: "이름" },
    { key: "what", header: "일", width: "12ch" },
    { key: "detail", header: "자세히", cell: (row) => row.detail || "—" },
    { key: "who", header: "누가", width: "14ch" },
  ];

  const tabs: Array<{ key: AppKind | null; label: string }> = [
    { key: null, label: "전체" },
    ...APP_KINDS.map((one) => ({ key: one, label: APP_LABEL[one] })),
  ];
  const href = (key: AppKind | null) =>
    `/app-logs?${new URLSearchParams({ ...(key ? { app: key } : {}), limit: String(limit) })}` as Route;

  return (
    <Shell mode={found.mode} actor={found.actor} current="/app-logs">
      <header className="mb-4">
        <h1 className="text-h1 font-bold">앱 로그</h1>
      </header>

      <nav className="mb-4 flex flex-wrap items-center gap-2" aria-label="앱 종류">
        {tabs.map((one) => (
          <Link
            key={one.label}
            href={href(one.key)}
            aria-current={app === one.key ? "page" : undefined}
            className={
              app === one.key
                ? "rounded-md border border-transparent bg-primary-subtle px-3 py-1 text-body font-semibold text-primary"
                : "rounded-md border border-border-default bg-bg-surface px-3 py-1 text-body text-text-secondary hover:bg-bg-subtle"
            }
          >
            {one.label}
          </Link>
        ))}
        <form className="ml-auto flex items-center gap-2 text-body-sm" action="/app-logs">
          {app ? <input type="hidden" name="app" value={app} /> : null}
          <label className="flex items-center gap-2">
            최근 n건
            <select
              name="limit"
              defaultValue={String(limit)}
              className="h-9 rounded-md border border-border-strong bg-bg-surface px-2 text-body"
            >
              {LIMITS.map((one) => (
                <option key={one} value={one}>
                  {one}건
                </option>
              ))}
            </select>
          </label>
          <button
            type="submit"
            className="h-9 rounded-md border border-border-strong bg-bg-surface px-3 text-body hover:bg-bg-subtle"
          >
            좁히기
          </button>
        </form>
      </nav>

      {failure ? (
        <ErrorBanner message={failure} />
      ) : shown.length === 0 ? (
        <EmptyState title="아직 이력이 없습니다." hint="앱이 등록을 요청하거나 키·배포를 받으면 여기 쌓입니다." />
      ) : (
        <DataTable columns={columns} rows={shown} rowKey={(row) => `${row.at}-${row.kind}-${row.name}-${row.what}-${row.detail}`} caption="앱 로그" />
      )}
      <p className="mt-2 text-caption text-text-muted">
        등록 요청·API 키·설치(배치 결정)를 모은 것입니다. 하트비트가 끊긴 때는 남지 않습니다 — 지금 상태는 「운영 현황 › 앱」에서 봅니다.
      </p>
    </Shell>
  );
}
