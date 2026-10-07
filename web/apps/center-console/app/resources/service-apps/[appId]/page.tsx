import Link from "next/link";
import { redirect } from "next/navigation";
import { Button, DataTable, ErrorBanner, StatusBadge, type Column } from "@chaeksas/ui";
import type { Operation, ServiceAppResource } from "@chaeksas/api-types/c7-service-app-resource";
import { CENTER_URL, CenterError, center, session } from "@/lib/center";
import { Shell } from "@/components/Shell";
import { setServiceAppUrl } from "@/app/actions";
import { UnregisterServiceApp } from "../../tools";
import { appStatus, time } from "../../page";

/**
 * CON-07 「서비스 앱」 상세 — 작업 목록과 이 앱을 쓰는 Bot.
 *
 * **키는 여기서 다루지 않는다** (ADR-0013) — 발급은 그 앱의 관리 콘솔(SVC-02)이다.
 * 「관리 콘솔 열기」만 건다.
 */

const MODE: Record<string, string> = { deterministic: "결정 수행", autonomous: "자율 수행" };

/** 입력·출력 필드 이름 — JSON Schema의 `properties` 열쇠만 보인다 (값은 없다). */
function fields(schema: unknown): string {
  if (!schema || typeof schema !== "object") return "—";
  const found = (schema as { properties?: Record<string, unknown> }).properties;
  return found ? Object.keys(found).join(", ") || "—" : "—";
}

export default async function ServiceAppPage({
  params,
  searchParams,
}: {
  params: Promise<{ appId: string }>;
  searchParams: Promise<{ error?: string; moved?: string }>;
}) {
  const found = await session();
  if (!found) redirect("/login");
  const { appId } = await params;
  const asked = await searchParams;
  const wanted = decodeURIComponent(appId);

  let info: ServiceAppResource | null = null;
  let failure: string | null = null;
  try {
    info = await center.serviceApp(wanted);
  } catch (cause) {
    failure = cause instanceof CenterError ? cause.message : "알 수 없는 오류가 생겼습니다";
  }

  const columns: Array<Column<Operation>> = [
    { key: "name", header: "작업", mono: true },
    { key: "description", header: "설명", cell: (row) => row.description ?? "—" },
    { key: "input", header: "입력", cell: (row) => fields(row.input_schema) },
    { key: "output", header: "출력", cell: (row) => fields(row.output_schema) },
    {
      key: "modes",
      header: "수행 모드",
      cell: (row) => (row.modes ?? []).map((one) => MODE[one] ?? one).join(", ") || "—",
    },
    {
      key: "fallback",
      header: "폴백",
      width: "12ch",
      cell: (row) => (row.fallback && row.fallback !== "none" ? row.fallback : "없음"),
    },
    {
      key: "server_ok",
      header: "서버 실행",
      width: "10ch",
      cell: (row) => (row.server_ok === false ? "안 됨" : "됨"),
    },
  ];

  return (
    <Shell mode={found.mode} actor={found.actor} centerUrl={CENTER_URL} current="/resources">
      <header className="mb-4">
        <h1 className="text-h1 font-bold">{info?.name ?? wanted}</h1>
        <p className="text-body text-text-secondary">
          <Link className="underline" href="/resources?tab=service_app">
            리소스 — 서비스 앱
          </Link>
          으로 돌아가기
        </p>
      </header>

      {failure ? <ErrorBanner message={failure} /> : null}
      {asked.error ? <ErrorBanner message={asked.error} /> : null}
      {asked.moved ? <p className="mb-4 text-body text-status-completed-fg">주소를 바꿨습니다.</p> : null}

      {info ? (
        <div className="flex flex-col gap-6">
          <section className="flex flex-col gap-2">
            <h2 className="text-h2 font-semibold">요약</h2>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-body sm:grid-cols-4">
              <dt className="text-text-muted">id</dt>
              <dd className="font-mono">{info.app_id}</dd>
              <dt className="text-text-muted">상태</dt>
              <dd>
                <StatusBadge group="서비스 앱" label={appStatus(info.status ?? "unknown")} />
              </dd>
              <dt className="text-text-muted">버전</dt>
              <dd>{info.version ?? "—"}</dd>
              <dt className="text-text-muted">구분</dt>
              <dd>
                {info.category === "system" ? "시스템" : info.category === "business" ? "업무" : "—"}
              </dd>
              <dt className="text-text-muted">API 주소</dt>
              <dd className="font-mono">{info.base_url ?? "—"}</dd>
              <dt className="text-text-muted">어느 확장의 서버 부분</dt>
              <dd>{info.extension_id ?? "없음"}</dd>
              <dt className="text-text-muted">마지막 확인</dt>
              <dd>{time(info.checked_at)}</dd>
              <dt className="text-text-muted">manifest 읽은 때</dt>
              <dd>{time(info.manifest_at)}</dd>
            </dl>
            {(info.status_reasons ?? []).length > 0 ? (
              <p className="text-body-sm text-text-muted">사유: {(info.status_reasons ?? []).join(", ")}</p>
            ) : null}
            {info.console_url ? (
              <p className="text-body-sm">
                <a
                  className="underline"
                  href={info.console_url}
                  target="_blank"
                  rel="noreferrer noopener"
                >
                  관리 콘솔 열기
                </a>
                <span className="text-text-muted"> — 키 발급은 거기서 합니다 (Center는 키를 갖지 않습니다)</span>
              </p>
            ) : null}
          </section>

          <section className="flex flex-col gap-2">
            <h2 className="text-h2 font-semibold">작업</h2>
            {(info.operations ?? []).length === 0 ? (
              <p className="text-body-sm text-text-muted">manifest에 작업이 없습니다.</p>
            ) : (
              <DataTable
                columns={columns}
                rows={info.operations ?? []}
                rowKey={(row) => row.name}
                caption="작업"
              />
            )}
          </section>

          <section className="flex flex-col gap-2">
            <h2 className="text-h2 font-semibold">이 앱을 쓰는 Bot</h2>
            {(info.used_by ?? []).length === 0 ? (
              <p className="text-body-sm text-text-muted">아직 없습니다.</p>
            ) : (
              <ul className="list-disc pl-5 text-body">
                {(info.used_by ?? []).map((one) => (
                  <li key={one} className="font-mono">
                    {one}
                  </li>
                ))}
              </ul>
            )}
          </section>

          {found.mode === "admin" ? (
            <section className="flex flex-col gap-3">
              <h2 className="text-h2 font-semibold">관리</h2>
              <p className="text-body-sm text-text-muted">
                주소는 여기서만 바꿉니다 — 클라이언트는 이 주소만 씁니다 (C7).
              </p>
              <form action={setServiceAppUrl} className="flex max-w-xl flex-wrap items-end gap-2">
                <input type="hidden" name="app_id" value={info.app_id} />
                <label className="flex flex-1 flex-col gap-1 text-body-sm">
                  <span className="text-text-muted">API 주소 *</span>
                  <input
                    type="url"
                    name="base_url"
                    required
                    defaultValue={info.base_url ?? ""}
                    className="h-9 border border-border-strong bg-bg-surface px-2 text-body"
                  />
                </label>
                <Button type="submit" variant="primary">
                  주소 바꾸기
                </Button>
              </form>
              <UnregisterServiceApp appId={info.app_id} />
            </section>
          ) : null}
        </div>
      ) : null}
    </Shell>
  );
}
