import Link from "next/link";
import { redirect } from "next/navigation";
import { Button, DataTable, ErrorBanner, StatusBadge, type Column } from "@chaeksas/ui";
import type { ExtensionResource } from "@chaeksas/api-types/c7-extension-resource";
import { CENTER_URL, CenterError, center, session } from "@/lib/center";
import { Shell } from "@/components/Shell";
import { revokeExtension } from "@/app/actions";
import { appStatus } from "../../page";

/**
 * CON-07 「확장」 상세 — 외부 확장의 정의·허용 호스트·이 확장을 쓰는 Bot.
 *
 * **정의가 Center에 있는 것은 외부 확장뿐이다** (내장·사내는 설치 파일에 든다). 그래서
 * 이 화면은 외부 확장만 다룬다.
 *
 * 「해제」도 **봉투가 필요하다** (`extension_revoke`) — 토큰만으로는 거둘 수 없다 (C2).
 */

const TIER: Record<string, string> = { builtin: "내장", internal: "사내", external: "외부" };

interface AdapterOperation {
  name?: unknown;
  modes?: unknown;
  idempotent?: unknown;
  description?: unknown;
}

/** 어댑터 선언에서 사람이 볼 것만 꺼낸다 — Center는 뜻을 해석하지 않는다 (C13 §4). */
function adapterOf(definition: ExtensionResource["definition"]): {
  hosts: string[];
  privateNetwork: boolean;
  operations: AdapterOperation[];
} {
  const service = (definition as { service?: { adapter?: Record<string, unknown> } } | null)?.service;
  const adapter = service?.adapter;
  if (!adapter) return { hosts: [], privateNetwork: false, operations: [] };
  return {
    hosts: Array.isArray(adapter.allowed_hosts) ? (adapter.allowed_hosts as string[]) : [],
    privateNetwork: adapter.allow_private_network === true,
    operations: Array.isArray(adapter.operations) ? (adapter.operations as AdapterOperation[]) : [],
  };
}

export default async function ExtensionPage({
  params,
  searchParams,
}: {
  params: Promise<{ extensionId: string }>;
  searchParams: Promise<{ error?: string }>;
}) {
  const found = await session();
  if (!found) redirect("/login");
  const { extensionId } = await params;
  const asked = await searchParams;
  const wanted = decodeURIComponent(extensionId);

  let info: ExtensionResource | null = null;
  let failure: string | null = null;
  try {
    info = await center.extension(wanted);
  } catch (cause) {
    failure = cause instanceof CenterError ? cause.message : "알 수 없는 오류가 생겼습니다";
  }

  const adapter = adapterOf(info?.definition ?? null);
  const usedBy = (info as { used_by?: unknown } | null)?.used_by;
  const users = Array.isArray(usedBy) ? (usedBy as string[]) : [];

  const columns: Array<Column<AdapterOperation>> = [
    { key: "name", header: "작업", mono: true, cell: (row) => String(row.name ?? "—") },
    { key: "description", header: "설명", cell: (row) => String(row.description ?? "—") },
    {
      key: "modes",
      header: "수행 모드",
      cell: (row) =>
        Array.isArray(row.modes)
          ? (row.modes as string[])
              .map((one) => (one === "deterministic" ? "결정 수행" : one === "autonomous" ? "자율 수행" : one))
              .join(", ")
          : "—",
    },
    {
      key: "idempotent",
      header: "멱등",
      width: "8ch",
      // 멱등이 아니면 결과를 모르는 실패를 **다시 부르지 않는다** (C13 §4-1).
      cell: (row) => (row.idempotent === true ? "예" : "아니오"),
    },
  ];

  return (
    <Shell mode={found.mode} actor={found.actor} centerUrl={CENTER_URL} current="/resources">
      <header className="mb-4">
        <h1 className="text-h1 font-bold">{info?.name ?? wanted}</h1>
        <p className="text-body text-text-secondary">
          <Link className="underline" href="/resources?tab=extension">
            리소스 — 확장
          </Link>
          으로 돌아가기
        </p>
      </header>

      {failure ? <ErrorBanner message={failure} /> : null}
      {asked.error ? <ErrorBanner message={asked.error} /> : null}

      {info ? (
        <div className="flex flex-col gap-6">
          <section className="flex flex-col gap-2">
            <h2 className="text-h2 font-semibold">요약</h2>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-body sm:grid-cols-4">
              <dt className="text-text-muted">id</dt>
              <dd className="font-mono">{info.id}</dd>
              <dt className="text-text-muted">버전</dt>
              <dd className="font-mono">{info.version}</dd>
              <dt className="text-text-muted">등급</dt>
              <dd>{TIER[info.tier] ?? info.tier}</dd>
              <dt className="text-text-muted">만든 곳</dt>
              <dd>{info.publisher ?? "—"}</dd>
              <dt className="text-text-muted">연결 방식</dt>
              <dd>{info.protocol === "http-adapter" ? "HTTP 어댑터" : (info.protocol ?? "없음")}</dd>
              <dt className="text-text-muted">서버 부분</dt>
              <dd>
                {info.service_app_id ? (
                  <Link
                    className="underline"
                    href={`/resources/service-apps/${encodeURIComponent(info.service_app_id)}`}
                  >
                    {info.service_app_id}
                  </Link>
                ) : (
                  "없음"
                )}
              </dd>
              <dt className="text-text-muted">상태</dt>
              <dd>
                {info.status === "n/a" ? "—" : <StatusBadge group="서비스 앱" label={appStatus(info.status ?? "")} />}
              </dd>
              <dt className="text-text-muted">설치된 Bot UI</dt>
              <dd>{info.installed_on?.hosts ?? 0}대</dd>
              <dt className="text-text-muted">정의 해시</dt>
              <dd className="font-mono text-body-sm">{info.definition_hash ?? "—"}</dd>
            </dl>
          </section>

          {info.protocol === "http-adapter" ? (
            <section className="flex flex-col gap-2">
              <h2 className="text-h2 font-semibold">어댑터</h2>
              <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-body">
                <dt className="text-text-muted">허용 호스트</dt>
                <dd className="font-mono">{adapter.hosts.join(", ") || "(없음)"}</dd>
                <dt className="text-text-muted">사설망 허용</dt>
                <dd>{adapter.privateNetwork ? "예" : "아니오"}</dd>
              </dl>
              {adapter.operations.length > 0 ? (
                <DataTable
                  columns={columns}
                  rows={adapter.operations}
                  rowKey={(row, index) => String(row.name ?? index)}
                  caption="어댑터 작업"
                />
              ) : null}
            </section>
          ) : null}

          <section className="flex flex-col gap-2">
            <h2 className="text-h2 font-semibold">이 확장을 쓰는 Bot</h2>
            {users.length === 0 ? (
              <p className="text-body-sm text-text-muted">아직 없습니다.</p>
            ) : (
              <ul className="list-disc pl-5 text-body">
                {users.map((one) => (
                  <li key={one} className="font-mono">
                    {one}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="flex flex-col gap-2">
            <h2 className="text-h2 font-semibold">정의</h2>
            <details>
              <summary className="cursor-pointer text-body-sm text-text-muted">
                정의 전체 — 펼쳐 보기 (실행하는 쪽이 이것을 받아 봉투로 다시 검증합니다)
              </summary>
              <pre className="mt-2 overflow-auto bg-bg-surface p-3 text-body-sm">
                {JSON.stringify(info.definition, null, 2)}
              </pre>
            </details>
          </section>

          {found.mode === "admin" ? (
            <section className="flex flex-col gap-2">
              <h2 className="text-h2 font-semibold">관리</h2>
              <p className="text-body-sm text-text-muted">
                해제하려면 <strong>해제 봉투</strong>가 필요합니다 —{" "}
                <code>chk-admin revoke-extension {info.id} {info.version}</code>으로 만듭니다.
                {users.length > 0
                  ? ` 해제하면 이 정의를 쓰는 Bot ${users.length}개가 실행 불가가 됩니다.`
                  : ""}{" "}
                되살릴 수 없습니다.
              </p>
              <form action={revokeExtension} className="flex max-w-xl flex-wrap items-end gap-2">
                <input type="hidden" name="extension_id" value={info.id} />
                <label className="flex flex-1 flex-col gap-1 text-body-sm">
                  <span className="text-text-muted">해제 봉투 파일 *</span>
                  <input
                    type="file"
                    name="envelope"
                    accept=".json,application/json"
                    required
                    className="text-body"
                  />
                </label>
                <Button type="submit" variant="danger">
                  등록 해제
                </Button>
              </form>
            </section>
          ) : null}
        </div>
      ) : null}
    </Shell>
  );
}
