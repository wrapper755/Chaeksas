import { redirect } from "next/navigation";
import { DataTable, ErrorBanner, StatusBadge, type Column } from "@chaeksas/ui";
import type { AccountInfo } from "@chaeksas/api-types/c5-account-info";
import { CENTER_PUBLIC_URL, CenterError, center, session } from "@/lib/center";
import { Shell } from "@/components/Shell";
import { fullTime } from "@/app/bot-uis/page";
import { AccountMenu, NewAccount } from "./tools";

/**
 * CON-14 관리자 계정 (ADR-0090). **관리자에게만** 보인다. 계정은 지우지 않고 멈춘다 — 기록의
 * 「누가」가 가리킬 곳이 남아야 한다. 마지막 관리자를 멈추거나 내리려 하면 Center가 막는다.
 */
const ROLE_LABEL: Record<string, string> = { admin: "관리자", viewer: "보기 전용" };
const PERMISSION_LABEL: Record<string, string> = { design: "설계" };

export default async function AccountsPage() {
  const found = await session();
  if (!found) redirect("/login");
  if (found.mode !== "admin") redirect("/bot-uis");

  let rows: AccountInfo[] = [];
  let failure: string | null = null;
  try {
    rows = await center.accounts();
  } catch (cause) {
    failure = cause instanceof CenterError ? cause.message : "알 수 없는 오류가 생겼습니다";
  }

  const columns: Array<Column<AccountInfo>> = [
    { key: "username", header: "아이디", mono: true },
    { key: "role", header: "역할", width: "12ch", cell: (row) => ROLE_LABEL[row.role] ?? row.role },
    {
      key: "permissions",
      header: "권한",
      width: "10ch",
      // 관리자는 모든 권한을 가진다 (C5). 보기 전용은 켜 둔 것만.
      cell: (row) =>
        row.role === "admin"
          ? "전부"
          : (row.permissions ?? []).map((one) => PERMISSION_LABEL[one] ?? one).join(", ") || "—",
    },
    {
      key: "studio_logins",
      header: "Studio 로그인",
      width: "22ch",
      cell: (row) => {
        const logins = row.studio_logins ?? [];
        if (logins.length === 0) return "—";
        // 누르면 펼친다 — JS 없이 (`<details>`).
        return (
          <details>
            <summary className="cursor-pointer">{logins.length}곳</summary>
            <ul className="mt-1 flex flex-col gap-1 text-body-sm">
              {logins.map((one) => (
                <li key={one.key_id}>
                  {one.machine_name} · 로그인 {fullTime(one.created_at)} · 마지막 사용{" "}
                  {one.last_used_at ? fullTime(one.last_used_at) : "—"} · {fullTime(one.expires_at)}까지
                </li>
              ))}
            </ul>
          </details>
        );
      },
    },
    {
      key: "state",
      header: "상태",
      width: "10ch",
      cell: (row) => <StatusBadge group="관리자 계정" label={row.state === "disabled" ? "멈춤" : "사용 중"} />,
    },
    {
      key: "last_login_at",
      header: "마지막 로그인",
      width: "20ch",
      cell: (row) => (row.last_login_at ? fullTime(row.last_login_at) : "—"),
    },
    { key: "created", header: "만든 이", width: "16ch", cell: (row) => `${row.created_by} · ${fullTime(row.created_at)}` },
    {
      key: "actions",
      header: "",
      width: "18ch",
      cell: (row) => (
        <AccountMenu
          username={row.username}
          role={row.role}
          disabled={row.state === "disabled"}
          self={row.username === found.actor}
          permissions={row.permissions ?? []}
          studioLogins={(row.studio_logins ?? []).map((one) => ({ key_id: one.key_id, machine_name: one.machine_name }))}
        />
      ),
    },
  ];

  return (
    <Shell mode={found.mode} actor={found.actor} centerUrl={CENTER_PUBLIC_URL} current="/accounts">
      <header className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-h1 font-bold">관리자 계정</h1>
          <p className="text-body text-text-secondary">계정 {rows.length}개</p>
        </div>
        <NewAccount />
      </header>
      {failure ? (
        <ErrorBanner message={failure} />
      ) : (
        <DataTable columns={columns} rows={rows} rowKey={(row) => row.username} caption="관리자 계정" />
      )}
    </Shell>
  );
}
