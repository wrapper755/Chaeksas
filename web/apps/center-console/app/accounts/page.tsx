import { redirect } from "next/navigation";
import { DataTable, ErrorBanner, StatusBadge, type Column } from "@chaeksas/ui";
import type { AccountInfo } from "@chaeksas/api-types/c5-account-info";
import { CenterError, center, session } from "@/lib/center";
import { Shell } from "@/components/Shell";
import { fullTime } from "@/app/bot-uis/page";
import { AccountMenu, NewAccount } from "./tools";

/**
 * CON-14 관리자 계정 (ADR-0090). **관리자에게만** 보인다. 계정은 지우지 않고 멈춘다 — 기록의
 * 「누가」가 가리킬 곳이 남아야 한다. 마지막 관리자를 멈추거나 내리려 하면 Center가 막는다.
 */
const ROLE_LABEL: Record<string, string> = { admin: "관리자", viewer: "보기 전용" };

export default async function AccountsPage() {
  const found = await session();
  if (!found) redirect("/login");
  if (found.mode !== "admin") redirect("/bots");

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
        />
      ),
    },
  ];

  return (
    <Shell mode={found.mode} actor={found.actor} current="/accounts">
      <header className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-h1 font-bold">관리자 계정</h1>
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
