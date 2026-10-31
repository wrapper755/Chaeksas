import Link from "next/link";
import { redirect } from "next/navigation";
import { Button, DataTable, EmptyState, ErrorBanner, StatusBadge, type Column } from "@chaeksas/ui";
import type { CenterKeyInfo } from "@chaeksas/api-types/c7-center-key-info";
import { CenterError, center, session } from "@/lib/center";
import { Shell } from "@/components/Shell";
import { KeyMenu, KeyTools } from "./tools";
import { STATE_LABEL, TYPE_LABEL, keyFilter, splitKeys } from "@/lib/center-keys";

/**
 * CON-11 API 키.
 *
 * **원문은 발급 직후 한 번만** 보인다 (C7). 목록에는 앞자리 16자만 있다. 일꾼(서비스 앱·어댑터
 * 일꾼, C15)은 여기서 다루지 않는다 — 일꾼은 Center 일꾼 폴더의 파일로 들어온다 (ADR-0122, CON-07 「일꾼 폴더」).
 */

/** 필터로 좁혔는데 빈 표 — 「아직 없다」와 가른다(그 안내는 좁히지 않았을 때만 맞다). */
const NO_MATCH = "조건에 맞는 키가 없습니다.";

function day(value: string | null | undefined): string {
  if (!value) return "—";
  const at = new Date(value);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}`;
}

export default async function CenterKeysPage({
  searchParams,
}: {
  searchParams: Promise<{ type?: string; state?: string }>;
}) {
  const found = await session();
  if (!found) redirect("/login");
  // 필터 「종류」·「상태」 (CON-11 「키 목록」) — 다른 목록처럼 GET 폼이고 Center가 거른다.
  const filter = keyFilter(await searchParams);
  const filtered = Boolean(filter.type || filter.state);

  let rows: CenterKeyInfo[] = [];
  let failure: string | null = null;
  try {
    // 「승인 대기」는 여기 없다 — PC 실행기·Studio는 「데스크톱 앱」, 서버 실행기는 「BPM 프로세스」 서버 탭 (CON-11).
    rows = await center.centerKeys(filter);
  } catch (cause) {
    failure = cause instanceof CenterError ? cause.message : "알 수 없는 오류가 생겼습니다";
  }

  const columns: Array<Column<CenterKeyInfo>> = [
    { key: "name", header: "이름" },
    { key: "type", header: "종류", width: "16ch", cell: (row) => TYPE_LABEL[row.type] ?? row.type },
    {
      key: "bound_to",
      header: "연결된 대상",
      cell: (row) => {
        const target = row.bound_to ? `${row.bound_to.name} (${day(row.bound_to.first_seen)})` : "등록 전";
        // 등록 승인이 만든 키 (C7 `enrollment_id`, ADR-0092) — 사람이 건넨 키가 아니다.
        return row.enrollment_id ? `${target} · 승인으로 발급` : target;
      },
    },
    { key: "prefix", header: "앞자리", width: "20ch", mono: true, cell: (row) => `${row.prefix}…` },
    { key: "created_at", header: "만든 날", width: "13ch", cell: (row) => day(row.created_at) },
    { key: "expires_at", header: "만료", width: "13ch", cell: (row) => day(row.expires_at) },
    { key: "last_used_at", header: "마지막 사용", width: "13ch", cell: (row) => day(row.last_used_at) },
    {
      key: "state",
      header: "상태",
      width: "12ch",
      cell: (row) => <StatusBadge group="API 키" label={STATE_LABEL[row.state] ?? row.state} />,
    },
  ];
  // 폐기·묶음 풀기는 **줄마다** 건다 — 표 위 단추로는 어느 키인지 화면이 말하지 못한다 (CON-11 끝 칸).
  if (found.mode === "admin") {
    columns.push({ key: "actions", header: "", width: "8ch", cell: (row) => <KeyMenu row={row} /> });
  }

  const { integration, enrolled } = splitKeys(rows);

  return (
    <Shell mode={found.mode} actor={found.actor} current="/center-keys">
      <header className="mb-4 flex flex-wrap items-end justify-between gap-4">
        <h1 className="text-h1 font-bold">API 키</h1>
      </header>

      <form className="filter-card flex flex-wrap items-end gap-3" method="get">
        <label className="flex flex-col gap-1 text-body-sm">
          종류
          <select
            name="type"
            defaultValue={filter.type ?? ""}
            className="h-9 rounded-md border border-border-strong bg-bg-surface px-2 text-body"
          >
            <option value="">(전체)</option>
            {Object.entries(TYPE_LABEL).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-body-sm">
          상태
          <select
            name="state"
            defaultValue={filter.state ?? ""}
            className="h-9 rounded-md border border-border-strong bg-bg-surface px-2 text-body"
          >
            <option value="">(전체)</option>
            {Object.entries(STATE_LABEL).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <Link href="/center-keys" className="ml-auto inline-flex h-9 items-center rounded-md px-3 text-body text-text-secondary hover:bg-bg-subtle">
          초기화
        </Link>
        <Button type="submit" variant="secondary">
          좁히기
        </Button>
      </form>

      {failure ? (
        <ErrorBanner message={failure} />
      ) : (
        <div className="flex flex-col gap-8">
          {/* 표가 둘이다 — 「새 키...」가 만드는 것과 등록 승인이 만드는 것 (CON-11, ADR-0092·0093). */}
          <section className="flex flex-col gap-3">
            <div className="flex items-end justify-between gap-4">
              <h2 className="text-h2 font-semibold">연동 키</h2>
              {found.mode === "admin" ? (
                <KeyTools />
              ) : (
                <Button variant="secondary" disabled disabledReason="관리자 계정으로 들어와야 발급할 수 있습니다.">
                  새 키...
                </Button>
              )}
            </div>
            {integration.length === 0 && filtered ? (
              <EmptyState title={NO_MATCH} />
            ) : integration.length === 0 ? (
              <EmptyState
                title="발급한 연동 키가 없습니다."
                hint="외부 시스템이 작업을 만들거나 결재에 대신 답하게 하려면 「새 키...」로 만드세요."
              />
            ) : (
              <DataTable columns={columns} rows={integration} rowKey={(row) => row.key_id} caption="연동 키 목록" />
            )}
          </section>

          <section className="flex flex-col gap-3">
            <h2 className="text-h2 font-semibold">승인으로 들인 키</h2>
            {enrolled.length === 0 && filtered ? (
              <EmptyState title={NO_MATCH} />
            ) : enrolled.length === 0 ? (
              <EmptyState
                title="승인으로 들인 키가 없습니다."
                hint="PC 실행기·Studio·서버 실행기에 Center 주소를 넣으면 등록 요청이 옵니다 — PC 실행기·Studio는 「데스크톱 앱」, 서버 실행기는 「BPM 프로세스」의 「서버」 탭에서 승인합니다."
              />
            ) : (
              <DataTable
                columns={columns}
                rows={enrolled}
                rowKey={(row) => row.key_id}
                caption="승인으로 들인 키 목록"
              />
            )}
          </section>
        </div>
      )}
    </Shell>
  );
}
