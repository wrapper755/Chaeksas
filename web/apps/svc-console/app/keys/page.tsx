import { redirect } from "next/navigation";
import { DataTable, EmptyState, ErrorBanner, StatusBadge, type Column } from "@chaeksas/ui";
import type { AdminKeyInfo } from "@chaeksas/api-types/c11-admin-key-info";
import { APP_URL, load, reason, svc } from "@/lib/page";
import { Shell } from "@/components/Shell";
import { KeyTools } from "./tools";

/**
 * SVC-02 API 키 — 이 서비스 앱을 부를 때 쓰는 키. **무엇이 있나 보고 비상 폐기하는 자리**다.
 *
 * 키는 Center가 배포와 함께 짓고 이 앱에는 해시만 온다 (ADR-0094, C11 §Center가 발급하는 키) —
 * 그래서 「새 키」가 없다. 「발급」 열이 누구를 위해 지은 키인지 말하고, **배포에 묶이지 않은 키**는
 * 맨 위 띠로 드러난다 (Center가 뚫렸을 때 보이는 자리다, ADR-0092 「보안 대가」).
 */

/** 「발급」 열 — C11 `issued_by`·`issued_for`. */
function issuedLine(row: AdminKeyInfo): string {
  if (row.issued_by !== "center") return "관리자";
  const made = row.issued_for;
  if (!made) return "Center";
  if (made.kind === "studio") return `Center — Studio ${made.center_key?.name ?? ""} (개발)`.trim();
  const target = made.target?.name ?? made.target?.id ?? "";
  if (made.kind === "utility") return `Center — ${target} (셀렉터 등록)`;
  return `Center — ${made.bpm_process_id ?? "?"} → ${target}`;
}

/** 배포·Studio·셀렉터 등록 어디에도 묶이지 않은 키 — 사람이 보고 판단할 것이다. */
function unbound(row: AdminKeyInfo): boolean {
  if (row.state !== "active") return false;
  if (row.issued_by !== "center") return true;
  const made = row.issued_for;
  if (!made) return true;
  if (made.kind === "deployment") return !made.deployment_id;
  return made.kind !== "studio" && made.kind !== "utility";
}

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

  const loose = rows.filter(unbound);
  const centerOff = (status?.dependencies ?? []).every((one) => one.name !== "center");

  const columns: Array<Column<AdminKeyInfo>> = [
    { key: "name", header: "이름", mono: true },
    { key: "issued_for", header: "발급", cell: (row) => issuedLine(row) },
    {
      key: "deployment",
      header: "배포",
      width: "14ch",
      mono: true,
      cell: (row) => row.issued_for?.deployment_id ?? "—",
    },
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
          BPM 프로세스가 이 앱을 부를 때 쓰는 키입니다. <strong>Center가 배포와 함께 짓고</strong> 이 앱에는
          해시만 옵니다 — 여기서 발급하지 않습니다. 키가 샜을 때 비상 폐기만 합니다.
        </p>
        {centerOff ? (
          <p className="mt-2 text-body-sm text-text-muted">
            이 앱은 Center 발급을 받지 않습니다 — 키는 관리 API로만 생깁니다 (CHK_SVC_&lt;APP&gt;__CENTER__URL).
          </p>
        ) : null}
      </header>

      {failure ? <ErrorBanner message={failure} /> : null}
      {loose.length > 0 ? (
        <ErrorBanner
          message={`배포 없이 생긴 키 ${loose.length}개: ${loose.map((row) => row.name).join(", ")} — 누가 왜 만들었는지 확인하세요. 모르면 폐기하세요.`}
        />
      ) : null}
      <div className="flex flex-col gap-4">
        <KeyTools rows={rows} />
        {rows.length === 0 && !failure ? (
          <EmptyState title="키가 없습니다." hint="이 앱을 쓰는 Bot을 Center에서 배포하면 Center가 키를 짓습니다." />
        ) : rows.length > 0 ? (
          <DataTable columns={columns} rows={rows} rowKey={(row) => row.name} caption="서비스 앱 API 키 목록" />
        ) : null}
      </div>
    </Shell>
  );
}
