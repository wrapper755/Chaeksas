import { redirect } from "next/navigation";
import { Button, DataTable, EmptyState, ErrorBanner, StatusBadge, type Column } from "@chaeksas/ui";
import type { CenterKeyInfo } from "@chaeksas/api-types/c7-center-key-info";
import { CENTER_URL, CenterError, center, session } from "@/lib/center";
import { Shell } from "@/components/Shell";
import { KeyTools } from "./tools";

/**
 * CON-11 Center API 키.
 *
 * **원문은 발급 직후 한 번만** 보인다 (C7). 목록에는 앞자리 16자만 있다. 서비스 앱 키는 여기서
 * 다루지 않는다 — 각 서비스 앱 관리 콘솔이다.
 */

const TYPE_LABEL: Record<string, string> = {
  bot_ui: "Bot UI용",
  studio: "Studio용",
  server_runner: "서버 실행기용",
  integration: "연동용",
};

const STATE_LABEL: Record<string, string> = {
  active: "사용 중",
  expired: "만료",
  revoked: "폐기됨",
};

function day(value: string | null | undefined): string {
  if (!value) return "—";
  const at = new Date(value);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}`;
}

export default async function CenterKeysPage() {
  const found = await session();
  if (!found) redirect("/login");

  let rows: CenterKeyInfo[] = [];
  let failure: string | null = null;
  try {
    rows = await center.centerKeys();
  } catch (cause) {
    failure = cause instanceof CenterError ? cause.message : "알 수 없는 오류가 생겼습니다";
  }

  const columns: Array<Column<CenterKeyInfo>> = [
    { key: "name", header: "이름" },
    { key: "type", header: "종류", width: "16ch", cell: (row) => TYPE_LABEL[row.type] ?? row.type },
    {
      key: "bound_to",
      header: "연결된 대상",
      cell: (row) => (row.bound_to ? `${row.bound_to.name} (${day(row.bound_to.first_seen)})` : "등록 전"),
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

  return (
    <Shell mode={found.mode} actor={found.actor} centerUrl={CENTER_URL} current="/center-keys">
      <header className="mb-4 flex items-end justify-between gap-4">
        <div>
          <h1 className="text-h1 font-bold">Center API 키</h1>
          <p className="text-body text-text-secondary">
            Bot UI·Studio·서버 실행기·외부 시스템이 Center에 접속할 때 쓰는 키입니다. 서비스 앱 키는 각 앱의
            관리 콘솔에서 발급합니다.
          </p>
        </div>
      </header>

      {failure ? (
        <ErrorBanner message={failure} />
      ) : (
        <div className="flex flex-col gap-4">
          {found.mode === "admin" ? <KeyTools rows={rows} /> : null}
          {rows.length === 0 ? (
            <EmptyState
              title="발급한 키가 없습니다."
              hint="「새 키...」로 Bot UI용 키부터 만드세요."
              action={found.mode === "admin" ? undefined : <Button variant="secondary" disabled
                disabledReason="관리자 토큰으로 들어와야 발급할 수 있습니다.">새 키...</Button>}
            />
          ) : (
            <DataTable columns={columns} rows={rows} rowKey={(row) => row.key_id} caption="Center API 키 목록" />
          )}
        </div>
      )}
    </Shell>
  );
}
