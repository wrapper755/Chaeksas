import Link from "next/link";
import type { Route } from "next";
import { redirect } from "next/navigation";
import { DataTable, EmptyState, ErrorBanner, StatusBadge, type Column } from "@chaeksas/ui";
import type { PackageInfo } from "@chaeksas/api-types/c5-package-info";
import { CENTER_URL, CenterError, center, session } from "@/lib/center";
import { Shell } from "@/components/Shell";

/**
 * CON-06 공통 패키지 (목록).
 *
 * **Bot이 아닌 패키지만** 둔다 — `bpm_process`는 Bot이라 CON-02의 몫이다. 종류 두 가지를
 * 한 목록에 섞는 것은 「Bot 아닌 것」이 운영자에게 한 덩이로 보이기 때문이다 (C5 `kind`).
 */

/** 이 화면이 다루는 종류 (C1 `kind`). 순서가 목록의 묶음 순서다. */
export const COMMON_KINDS = ["process_lib", "toolpack"] as const;

export const KIND_LABEL: Record<string, string> = {
  process_lib: "공유 BPM 프로세스",
  toolpack: "툴팩",
  bpm_process: "Bot",
};

/** C5 상태 → `status_map`의 「패키지」 표기. 모르는 값은 **그대로 보인다** (원칙 10). */
export const STATUS_LABEL: Record<string, string> = {
  candidate: "후보",
  approved: "승인됨",
  deprecated: "지원 종료",
  revoked: "철회",
};

/** 연도까지 적는다 — 「01-01」로는 내일인지 내년인지 모른다 (CON-03과 같은 규칙). */
export function time(value: string | null | undefined): string {
  if (!value) return "—";
  const at = new Date(value);
  return Number.isNaN(at.getTime()) ? value : at.toLocaleString("ko-KR");
}

/** 타입 라우트는 질의·경로가 붙은 주소를 리터럴로 요구한다 — 한 자리에서 만든다. */
export function packageHref(row: { id: string; version: string }): Route {
  return `/packages/${encodeURIComponent(row.id)}/${encodeURIComponent(row.version)}` as Route;
}

export default async function PackagesPage() {
  const found = await session();
  if (!found) redirect("/login");

  let rows: PackageInfo[] = [];
  let failure: string | null = null;
  try {
    // 종류별로 따로 묻지 않고 한 번 읽어 **콘솔에서 가른다** — 목록 하나에 둘을 함께 보인다.
    const all = await center.packages();
    const order = new Map<string, number>(COMMON_KINDS.map((kind, at) => [kind, at]));
    rows = all
      .filter((one) => order.has(one.kind))
      .sort(
        (a, b) =>
          (order.get(a.kind) ?? 0) - (order.get(b.kind) ?? 0) ||
          a.id.localeCompare(b.id) ||
          a.version.localeCompare(b.version),
      );
  } catch (cause) {
    failure = cause instanceof CenterError ? cause.message : "알 수 없는 오류가 생겼습니다";
  }

  const columns: Array<Column<PackageInfo>> = [
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
    {
      key: "kind",
      header: "종류",
      width: "16ch",
      cell: (row) => KIND_LABEL[row.kind] ?? row.kind,
    },
    { key: "name", header: "이름", cell: (row) => row.name ?? "—" },
    {
      key: "status",
      header: "상태",
      width: "10ch",
      cell: (row) => <StatusBadge group="패키지" label={STATUS_LABEL[row.status] ?? row.status} />,
    },
    { key: "uploaded_at", header: "올린 시각", width: "18ch", cell: (row) => time(row.uploaded_at) },
    { key: "uploaded_by", header: "올린 이", width: "14ch" },
  ];

  return (
    <Shell mode={found.mode} actor={found.actor} centerUrl={CENTER_URL} current="/packages">
      <header className="mb-4">
        <h1 className="text-h1 font-bold">공통 패키지</h1>
        <p className="text-body text-text-secondary">
          Bot이 아닌 패키지 — 여러 Bot이 가져다 쓰는 공유 BPM 프로세스와 툴팩입니다.
        </p>
      </header>

      {failure ? (
        <ErrorBanner message={failure} />
      ) : rows.length === 0 ? (
        <EmptyState title="올라온 공통 패키지가 없습니다." hint="Studio의 「공유 BPM 프로세스로 내보내기...」로 만든 패키지나 툴팩을 올리세요." />
      ) : (
        <DataTable
          columns={columns}
          rows={rows}
          rowKey={(row) => `${row.id}@${row.version}`}
          caption="공통 패키지 목록"
        />
      )}
    </Shell>
  );
}
