import { redirect } from "next/navigation";
import { DataTable, EmptyState, ErrorBanner, StatusBadge, type Column } from "@chaeksas/ui";
import type { AdminKeyInfo } from "@chaeksas/api-types/c11-admin-key-info";
import { APP_URL, load, reason, svc } from "@/lib/page";
import { Shell } from "@/components/Shell";
import { KeyTools } from "./tools";

/**
 * SVC-02 API 키 — 이 서비스 앱을 부를 때 쓰는 키.
 *
 * **원문은 발급 직후 한 번만** 보인다 (C11). 목록에는 앞자리 16자만 있다. Center는 이 키를
 * 모른다 (ADR-0013 — 앱이 자기 키를 발급한다).
 */

const STATE_LABEL: Record<string, string> = { active: "사용 중", expired: "만료", revoked: "폐기됨" };
const MODE_LABEL: Record<string, string> = { autonomous: "자율", deterministic: "결정" };

function day(value: string | null | undefined): string {
  if (!value) return "—";
  const at = new Date(value);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}`;
}

export default async function KeysPage() {
  const found = await load();
  if (!found) redirect("/login");
  const { status, session } = found;

  let rows: AdminKeyInfo[] = [];
  let failure: string | null = found.failure;
  try {
    rows = await svc.keys();
  } catch (cause) {
    failure = reason(cause);
  }

  const columns: Array<Column<AdminKeyInfo>> = [
    { key: "name", header: "이름", mono: true },
    {
      key: "allowed_operations",
      header: "허용 작업",
      cell: (row) =>
        (row.allowed_operations ?? []).includes("*") ? "모든 작업" : (row.allowed_operations ?? []).join(", "),
    },
    {
      key: "allowed_modes",
      header: "허용 모드",
      width: "14ch",
      cell: (row) => (row.allowed_modes ?? []).map((mode) => MODE_LABEL[mode] ?? mode).join(" · ") || "—",
    },
    {
      key: "extra_scopes",
      header: "추가 권한",
      width: "16ch",
      cell: (row) => (row.extra_scopes ?? []).join(", ") || "—",
    },
    { key: "prefix", header: "앞자리", width: "20ch", mono: true, cell: (row) => `${row.prefix}…` },
    { key: "created_at", header: "만든 날", width: "13ch", cell: (row) => day(row.created_at) },
    { key: "expires_at", header: "만료", width: "13ch", cell: (row) => day(row.expires_at) },
    { key: "last_used_at", header: "마지막 사용", width: "13ch", cell: (row) => day(row.last_used_at) },
    {
      key: "state",
      header: "상태",
      width: "11ch",
      cell: (row) => <StatusBadge group="API 키" label={STATE_LABEL[row.state] ?? row.state} />,
    },
  ];

  return (
    <Shell status={status} actor={session.actor} appUrl={APP_URL} current="/keys">
      <header className="mb-4">
        <h1 className="text-h1 font-bold">API 키</h1>
        <p className="text-body text-text-secondary">
          BPM 프로세스가 이 앱을 부를 때 쓰는 키입니다. 이름을 BPM 프로세스의 <strong>키 참조 이름</strong>과
          맞추세요 (예: <span className="font-mono">finance-invoice</span>) — BPM 파일에는 키 값을 넣지 않습니다.
        </p>
      </header>

      {failure ? <ErrorBanner message={failure} /> : null}
      <div className="flex flex-col gap-4">
        <KeyTools rows={rows} operations={(status?.operations ?? []).map((row) => row.name)} appId={status?.app_id} />
        {rows.length === 0 && !failure ? (
          <EmptyState title="발급한 키가 없습니다." hint="「새 키...」로 첫 키를 만드세요." />
        ) : rows.length > 0 ? (
          <DataTable columns={columns} rows={rows} rowKey={(row) => row.name} caption="서비스 앱 API 키 목록" />
        ) : null}
      </div>
    </Shell>
  );
}
