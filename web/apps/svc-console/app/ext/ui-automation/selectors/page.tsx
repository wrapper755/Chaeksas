import { redirect } from "next/navigation";
import { DataTable, EmptyState, ErrorBanner, StatusBadge, type Column } from "@chaeksas/ui";
import type { ElementRow, LocatorRow, PageDetail, StrategyStat } from "@chaeksas/api-types/c9-page-detail";
import type { PageBriefRow } from "@chaeksas/api-types/c9-page-listing";
import { APP_URL, load, reason, svc } from "@/lib/page";
import { Shell } from "@/components/Shell";

/**
 * UIA-02 셀렉터 — 화면을 골라 그 화면의 로케이터 전부를 본다 (대체된 것 포함).
 *
 * **보기 전용**이다. 등록·삭제는 Bot UI 「도구」 → 「UI 셀렉터 등록」(BUI-06)의 일이다 (C9).
 * 좁히기·경로 탐색은 **JS 없이** 일반 `<form method="get">`으로 돈다 (CON-05와 같은 결).
 */

const EXTENSION_ID = "ui-automation";
const HERE = "/ext/ui-automation/selectors";

const STATUS_LABEL: Record<string, string> = {
  active: "사용 중",
  unverified: "검증 전",
  deprecated: "대체됨",
};
const PLATFORM_LABEL: Record<string, string> = { web: "웹", desktop: "데스크톱" };

const NO_PAGES = {
  title: "등록된 화면이 없습니다.",
  hint: "Bot UI 「도구」 → 「UI 셀렉터 등록」(BUI-06)으로 등록하세요.",
};
const NO_LOCATORS = {
  title: "이 화면에 등록된 로케이터가 없습니다.",
  hint: "BUI-06에서 요소를 더하세요.",
};

/** 성공률 막대 — 색만으로 뜻을 전하지 않는다 (스타일 가이드 §7): 수를 함께 쓴다. */
function Rate({ rate }: { rate: number | null | undefined }) {
  if (rate === null || rate === undefined) return <span className="text-text-muted">—</span>;
  const percent = Math.round(rate * 1000) / 10;
  return (
    <span className="flex items-center gap-2">
      <span className="h-2 w-16 shrink-0 bg-bg-subtle" aria-hidden>
        <span className="block h-2 bg-primary" style={{ width: `${Math.round(rate * 100)}%` }} />
      </span>
      <span className="text-body-sm">{percent}%</span>
    </span>
  );
}

/** 「전략별 성공·실패」 — 간단한 막대 둘. 내용이 있을 때만 보인다 (화면 설계서). */
function Strategies({ rows }: { rows: StrategyStat[] }) {
  const most = Math.max(...rows.map((one) => (one.success ?? 0) + (one.fail ?? 0)), 1);
  return (
    <ul className="flex flex-col gap-2">
      {rows.map((one) => {
        const success = one.success ?? 0;
        const fail = one.fail ?? 0;
        return (
          <li key={one.type} className="flex items-center gap-3 text-body-sm">
            <span className="w-24 shrink-0 font-mono">{one.type}</span>
            <span className="flex h-3 w-64 shrink-0 bg-bg-subtle" aria-hidden>
              <span className="block h-3 bg-primary" style={{ width: `${(success / most) * 100}%` }} />
              <span className="block h-3 bg-danger" style={{ width: `${(fail / most) * 100}%` }} />
            </span>
            <span>
              성공 {success} · 실패 {fail}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

export default async function UiAutomationSelectorsPage({
  searchParams,
}: {
  searchParams: Promise<{ page?: string; status?: string; key?: string; q?: string; start?: string; goal?: string }>;
}) {
  const found = await load();
  if (!found) redirect("/login");
  const { status, failure, session } = found;
  const query = await searchParams;

  const mine = status?.extension?.id === EXTENSION_ID;
  let pages: PageBriefRow[] = [];
  let detail: PageDetail | null = null;
  let path: { found: boolean; path: string[] } | null = null;
  let trouble: string | null = null;

  if (mine) {
    try {
      pages = (await svc.uiAutomationPages()).pages ?? [];
      // 고르지 않았으면 첫 화면을 보여 준다 — 빈 화면보다 낫다.
      const chosen = query.page || pages[0]?.page_id;
      if (chosen) detail = await svc.uiAutomationPage(chosen);
      if (query.start && query.goal) {
        const result = await svc.uiAutomationPath(query.start, query.goal);
        path = { found: result.found ?? false, path: result.path ?? [] };
      }
    } catch (cause) {
      trouble = reason(cause);
    }
  }

  const all = detail?.locators ?? [];
  const narrowed = all.filter(
    (one) =>
      (!query.status || one.status === query.status) &&
      (!query.key || one.semantic_key.includes(query.key)) &&
      (!query.q || one.value.includes(query.q) || (one.name ?? "").includes(query.q)),
  );
  const narrowing = Boolean(query.status || query.key || query.q);

  const columns: Array<Column<LocatorRow>> = [
    { key: "semantic_key", header: "시맨틱 키", mono: true, width: "22ch" },
    { key: "rank", header: "순위", width: "7ch", align: "right", cell: (row) => String(row.rank) },
    { key: "type", header: "전략", width: "12ch", mono: true },
    { key: "value", header: "셀렉터", mono: true, cell: (row) => row.value },
    { key: "name", header: "접근성 이름", width: "16ch", cell: (row) => row.name ?? "—" },
    {
      key: "status",
      header: "상태",
      width: "11ch",
      cell: (row) => (
        <StatusBadge group="로케이터" label={STATUS_LABEL[row.status ?? ""] ?? row.status ?? "—"} />
      ),
    },
    { key: "success", header: "성공", width: "8ch", align: "right", cell: (row) => String(row.success ?? 0) },
    { key: "fail", header: "실패", width: "8ch", align: "right", cell: (row) => String(row.fail ?? 0) },
    { key: "success_rate", header: "성공률", width: "16ch", cell: (row) => <Rate rate={row.success_rate} /> },
    { key: "streak", header: "연속 성공", width: "11ch", align: "right", cell: (row) => String(row.streak ?? 0) },
    {
      key: "healed",
      header: "자가 치유",
      width: "14ch",
      cell: (row) =>
        row.healed ? (
          <span title={(row.supersedes ?? []).join(", ") || undefined}>
            치유가 더함{(row.supersedes ?? []).length > 0 ? ` (대체 ${row.supersedes!.length})` : ""}
          </span>
        ) : (
          "—"
        ),
    },
  ];

  const elements: Array<Column<ElementRow>> = [
    { key: "semantic_key", header: "시맨틱 키", mono: true, width: "22ch" },
    { key: "role", header: "역할", width: "12ch", cell: (row) => row.role ?? "—" },
    { key: "description", header: "설명", cell: (row) => row.description ?? row.name ?? "—" },
    { key: "concepts", header: "업무 개념", cell: (row) => (row.concepts ?? []).join(", ") || "—" },
    { key: "depends_on", header: "선행 입력", cell: (row) => (row.depends_on ?? []).join(", ") || "—" },
    { key: "navigates_to", header: "이동하는 화면", cell: (row) => row.navigates_to ?? "—" },
    { key: "actions", header: "가능한 동작", cell: (row) => (row.actions ?? []).join(", ") || "—" },
  ];

  const superseded = all.filter((one) => (one.supersedes ?? []).length > 0);

  return (
    <Shell status={status} actor={session.actor} appUrl={APP_URL} current={HERE}>
      <h1 className="mb-4 text-h1 font-bold">셀렉터</h1>
      {failure ? <ErrorBanner message={failure} /> : null}
      {!mine ? (
        <ErrorBanner
          message={`이 화면은 UI 자동화 앱의 것입니다 — 접속한 앱은 ${status?.app_id ?? "알 수 없음"}입니다.`}
        />
      ) : null}
      {trouble ? <ErrorBanner message={trouble} /> : null}

      {mine && pages.length === 0 && !trouble ? <EmptyState {...NO_PAGES} /> : null}

      {detail ? (
        <div className="flex flex-col gap-6">
          <form className="flex flex-wrap items-end gap-3" method="get">
            <label className="flex flex-col gap-1 text-body-sm">
              화면
              <select
                name="page"
                defaultValue={detail.page_id}
                className="h-9 border border-border-default bg-bg-surface px-2"
              >
                {pages.map((one) => (
                  <option key={one.page_id} value={one.page_id}>
                    {one.page_id}
                    {one.name ? ` — ${one.name}` : ""}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-body-sm">
              상태
              <select
                name="status"
                defaultValue={query.status ?? ""}
                className="h-9 border border-border-default bg-bg-surface px-2"
              >
                <option value="">전체</option>
                {Object.entries(STATUS_LABEL).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-body-sm">
              시맨틱 키
              <input
                name="key"
                defaultValue={query.key ?? ""}
                className="h-9 border border-border-default bg-bg-surface px-2"
              />
            </label>
            <label className="flex flex-col gap-1 text-body-sm">
              셀렉터 검색
              <input
                name="q"
                defaultValue={query.q ?? ""}
                className="h-9 border border-border-default bg-bg-surface px-2"
              />
            </label>
            <button type="submit" className="h-9 border border-border-default px-3 text-body-sm">
              적용
            </button>
          </form>

          <p className="text-body-sm text-text-secondary">
            {detail.page_id}
            {detail.name ? ` — ${detail.name}` : ""} · {PLATFORM_LABEL[detail.platform ?? ""] ?? detail.platform ?? "—"} · 판{" "}
            {detail.revision} · 마지막 등록 {detail.updated_at ?? "—"}
            {detail.url_pattern ? ` · 주소 ${detail.url_pattern}` : ""}
            {detail.app ? ` · 앱 ${detail.app}` : ""}
          </p>

          {(detail.warnings ?? []).length > 0 ? (
            <ErrorBanner
              message={`최근 실패율이 높은 사용 중 로케이터 ${detail.warnings!.length}개 — 화면이 바뀌었을 수 있습니다: ${detail.warnings!.join(" / ")}`}
            />
          ) : null}

          <section>
            {narrowing ? (
              <p className="mb-2 text-body-sm text-text-secondary">
                전체 {all.length}건 중 <strong>{narrowed.length}건</strong> — 좁히기가 켜져 있습니다.
              </p>
            ) : null}
            <DataTable
              columns={columns}
              rows={narrowed}
              rowKey={(row, index) => `${row.semantic_key}:${row.type}:${row.value}:${index}`}
              density="compact"
              empty={narrowing ? { title: "좁히기에 맞는 로케이터가 없습니다." } : NO_LOCATORS}
              caption="로케이터와 성적 (대체된 것 포함)"
            />
          </section>

          {superseded.length > 0 ? (
            <details>
              <summary className="cursor-pointer text-h3 font-semibold">대체 관계 {superseded.length}건</summary>
              <ul className="mt-2 flex flex-col gap-1 text-body-sm">
                {superseded.map((one) => (
                  <li key={`${one.semantic_key}:${one.value}`}>
                    <span className="font-mono">{one.semantic_key}</span>: 치유가 더한{" "}
                    <span className="font-mono">
                      {one.type}|{one.value}
                    </span>
                    이(가){" "}
                    <span className="font-mono">{(one.supersedes ?? []).join(", ")}</span>을(를) 밀어냈습니다.
                  </li>
                ))}
              </ul>
            </details>
          ) : null}

          {(detail.strategies ?? []).length > 0 ? (
            <section>
              <h2 className="mb-2 text-h3 font-semibold">전략별 성공·실패</h2>
              <Strategies rows={detail.strategies!} />
            </section>
          ) : null}

          {(detail.elements ?? []).length > 0 ? (
            <details>
              <summary className="cursor-pointer text-h3 font-semibold">선행 조건·화면 이동</summary>
              <div className="mt-2">
                <DataTable
                  columns={elements}
                  rows={detail.elements!}
                  rowKey={(row) => row.semantic_key}
                  density="compact"
                  caption="요소가 아는 것 (설계할 때 쓴다)"
                />
              </div>
            </details>
          ) : null}

          <section>
            <h2 className="mb-2 text-h3 font-semibold">화면 간 경로 탐색</h2>
            <form className="flex flex-wrap items-end gap-3" method="get">
              <input type="hidden" name="page" value={detail.page_id} />
              <label className="flex flex-col gap-1 text-body-sm">
                출발
                <select
                  name="start"
                  defaultValue={query.start ?? detail.page_id}
                  className="h-9 border border-border-default bg-bg-surface px-2"
                >
                  {pages.map((one) => (
                    <option key={one.page_id} value={one.page_id}>
                      {one.page_id}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-body-sm">
                도착
                <select
                  name="goal"
                  defaultValue={query.goal ?? ""}
                  className="h-9 border border-border-default bg-bg-surface px-2"
                >
                  <option value="">고르세요</option>
                  {pages.map((one) => (
                    <option key={one.page_id} value={one.page_id}>
                      {one.page_id}
                    </option>
                  ))}
                </select>
              </label>
              <button type="submit" className="h-9 border border-border-default px-3 text-body-sm">
                찾기
              </button>
            </form>
            {path ? (
              <p className="mt-2 text-body">
                {path.found ? (
                  <span className="font-mono">{path.path.join(" → ")}</span>
                ) : (
                  "두 화면을 잇는 경로가 없습니다 — 등록의 화면 이동을 확인하세요."
                )}
              </p>
            ) : null}
          </section>
        </div>
      ) : null}
    </Shell>
  );
}
