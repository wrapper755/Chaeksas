import { redirect } from "next/navigation";
import { DataTable, EmptyState, ErrorBanner, StatusBadge, type Column } from "@chaeksas/ui";
import type { FallbackSpread, SessionRow } from "@chaeksas/api-types/c9-session-page";
import { APP_URL, load, reason, svc } from "@/lib/page";
import { Shell } from "@/components/Shell";

/**
 * UIA-03 모니터링 — UI 세션(= UI 태스크 한 번) 기록. 출처는 Worker가 보낸 보고 (C8).
 *
 * **보기 전용**이다 — 전환은 현장 Bot UI가 확인으로 처리한다 (프로토타입의 「BPM이 받아감」
 * 단추는 없다). 상세는 `<details>`로 펼친다 (JS 없이 돈다).
 *
 * **업무 값은 없다** — 읽은 값·입력한 글자는 C8 보고에 담기지 않는다 (원칙 6).
 */

const EXTENSION_ID = "ui-automation";
const HERE = "/ext/ui-automation/monitoring";
const LIMIT = 100;

const STATUS_LABEL: Record<string, string> = {
  succeeded: "성공",
  escalated: "전환",
  failed: "실패",
};
const CALLER_LABEL: Record<string, string> = {
  bot_ui: "Bot",
  studio: "Studio",
  worker: "Worker",
  server_runner: "서버 실행기",
};
const MODE_LABEL: Record<string, string> = { autonomous: "자율 수행", deterministic: "결정 수행" };

const ESCALATION_HINT =
  "전환 = 자가 치유가 한도를 넘어 현장 PC(Bot UI)의 확인으로 넘어간 것 (오류가 아닙니다).";
/** C8 보고는 세션이 **끝날 때** 온다 — 그래서 도는 세션은 여기서 알 수 없다. */
const RUNNING_HINT =
  "지금 도는 세션은 여기서 알 수 없습니다 — 보고는 세션이 끝날 때 옵니다 (현장 Bot UI의 BUI-09가 보여 줍니다).";
const NO_SESSIONS = {
  title: "아직 UI 세션 보고가 없습니다.",
  hint: "Bot이 UI 태스크를 돌리거나 BUI-08 「셀렉터 시험」에서 보고를 켜면 쌓입니다.",
};
const NO_FALLBACK = "아직 성공한 실행 기록이 없습니다.";

function Summary({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1 rounded-md border border-border-default bg-bg-surface p-3">
      <span className="text-caption text-text-muted">{label}</span>
      <span className="text-body">{children}</span>
    </div>
  );
}

/** 「폴백 깊이 분포」 — 깊이마다 막대 하나. 수를 함께 쓴다 (색만으로 전하지 않는다). */
function Fallback({ spread }: { spread: FallbackSpread }) {
  const entries = Object.entries(spread.depths ?? {}).sort((a, b) => Number(a[0]) - Number(b[0]));
  const most = Math.max(...entries.map(([, n]) => n), 1);
  const counted = spread.counted ?? 0;
  if (entries.length === 0) return <p className="text-body">{NO_FALLBACK}</p>;
  return (
    <>
      <ul className="flex flex-col gap-2">
        {entries.map(([depth, n]) => (
          <li key={depth} className="flex items-center gap-3 text-body-sm">
            <span className="w-28 shrink-0">
              {depth === "0" ? "1순위 (깊이 0)" : `깊이 ${depth}`}
            </span>
            <span className="h-3 w-64 shrink-0 bg-bg-subtle" aria-hidden>
              <span className="block h-3 bg-primary" style={{ width: `${(n / most) * 100}%` }} />
            </span>
            <span>{n}건</span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-body-sm text-text-secondary">
        1순위 로케이터로 바로 성공한 비율{" "}
        {counted > 0 ? `${Math.round(((spread.first_hit ?? 0) / counted) * 1000) / 10}%` : "—"} (성공한 요소{" "}
        {counted}건)
      </p>
    </>
  );
}

export default async function UiAutomationMonitoringPage() {
  const found = await load();
  if (!found) redirect("/login");
  const { status, failure, session } = found;

  const mine = status?.extension?.id === EXTENSION_ID;
  let rows: SessionRow[] = [];
  let counts: Record<string, number> = {};
  let spread: FallbackSpread = {};
  let trouble: string | null = null;
  if (mine) {
    try {
      const page = await svc.uiAutomationSessions(LIMIT);
      rows = page.rows ?? [];
      counts = (page.counts ?? {}) as Record<string, number>;
      spread = page.fallback ?? {};
    } catch (cause) {
      trouble = reason(cause);
    }
  }

  const columns: Array<Column<SessionRow>> = [
    {
      key: "status",
      header: "상태",
      width: "9ch",
      cell: (row) => {
        const value = String(row.report?.status ?? "");
        const test = row.report?.origin === "test";
        return <StatusBadge group="UI 세션" label={test ? "시험" : (STATUS_LABEL[value] ?? value ?? "—")} />;
      },
    },
    { key: "page_id", header: "화면", mono: true, cell: (row) => String(row.report?.page_id ?? "—") },
    {
      key: "business_key",
      header: "실행 id",
      mono: true,
      cell: (row) => String(row.report?.business_key ?? "—"),
    },
    { key: "bpm_process_id", header: "Bot", cell: (row) => row.bpm_process_id ?? "—" },
    { key: "host", header: "Bot UI", cell: (row) => row.host ?? "—" },
    {
      key: "caller",
      header: "요청 쪽",
      width: "11ch",
      cell: (row) => CALLER_LABEL[row.caller ?? ""] ?? row.caller ?? "—",
    },
    {
      key: "mode",
      header: "수행 모드",
      width: "12ch",
      cell: (row) => MODE_LABEL[row.mode ?? ""] ?? row.mode ?? "—",
    },
    {
      key: "steps",
      header: "진행",
      width: "9ch",
      cell: (row) => `${row.report?.steps_completed ?? 0}/${row.report?.steps_total ?? 0}`,
    },
    {
      key: "healed",
      header: "치유",
      width: "8ch",
      align: "right",
      cell: (row) => String((row.report?.healed as unknown[] | undefined)?.length ?? 0),
    },
    { key: "at", header: "받은 시각", width: "22ch", cell: (row) => row.at ?? "—" },
    {
      key: "error",
      header: "오류",
      cell: (row) => {
        const error = row.report?.error as { code?: string; message?: string } | undefined;
        return error?.code ? `${error.code}: ${error.message ?? ""}` : "—";
      },
    },
  ];

  return (
    <Shell status={status} actor={session.actor} appUrl={APP_URL} current={HERE}>
      <h1 className="mb-4 text-h1 font-bold">모니터링</h1>
      {failure ? <ErrorBanner message={failure} /> : null}
      {!mine ? (
        <ErrorBanner
          message={`이 화면은 UI 자동화 앱의 것입니다 — 접속한 앱은 ${status?.app_id ?? "알 수 없음"}입니다.`}
        />
      ) : null}
      {trouble ? <ErrorBanner message={trouble} /> : null}

      {mine && !trouble ? (
        <div className="flex flex-col gap-6">
          <section>
            <h2 className="mb-2 text-h3 font-semibold">요약</h2>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
              <Summary label="전체">{counts.total ?? 0}건</Summary>
              <Summary label="성공">{counts.succeeded ?? 0}건</Summary>
              <Summary label="전환">{counts.escalated ?? 0}건</Summary>
              <Summary label="실패">{counts.failed ?? 0}건</Summary>
              <Summary label="자가 치유">{counts.healed ?? 0}건</Summary>
              <Summary label="시험">{counts.test ?? 0}건</Summary>
            </div>
            <p className="mt-2 text-body-sm text-text-secondary">{ESCALATION_HINT}</p>
            <p className="text-body-sm text-text-secondary">{RUNNING_HINT}</p>
          </section>

          <section>
            <h2 className="mb-2 text-h3 font-semibold">폴백 깊이 분포</h2>
            <Fallback spread={spread} />
          </section>

          <section>
            <h2 className="mb-2 text-h3 font-semibold">UI 세션 이력</h2>
            <DataTable
              columns={columns}
              rows={rows}
              rowKey={(row, index) => `${row.report?.business_key ?? index}`}
              density="compact"
              empty={NO_SESSIONS}
              caption={`최근 ${LIMIT}건까지 (시험 보고 포함)`}
            />
          </section>

          {rows.length > 0 ? (
            <section>
              <h2 className="mb-2 text-h3 font-semibold">상세</h2>
              <ul className="flex flex-col gap-2">
                {rows.map((row, index) => {
                  const report = row.report ?? {};
                  const healed = (report.healed ?? []) as Array<Record<string, unknown>>;
                  const escalation = report.escalation as Record<string, unknown> | undefined;
                  return (
                    <li key={`${report.business_key ?? index}`} className="border border-border-default p-3">
                      <details>
                        <summary className="cursor-pointer text-body">
                          <span className="font-mono">{String(report.business_key ?? "—")}</span> ·{" "}
                          {String(report.page_id ?? "—")} ·{" "}
                          {STATUS_LABEL[String(report.status ?? "")] ?? String(report.status ?? "—")}
                        </summary>
                        <div className="mt-2 flex flex-col gap-3">
                          {escalation ? (
                            <ErrorBanner
                              message={`전환됨 — ${String(escalation.semantic_key ?? "")}: ${String(escalation.reason ?? "")} (시도 ${String(escalation.attempts ?? "—")})`}
                            />
                          ) : null}
                          {healed.length > 0 ? (
                            <div>
                              <h3 className="text-body font-semibold">자가 치유 내역</h3>
                              <ul className="mt-1 flex flex-col gap-1 text-body-sm">
                                {healed.map((one, at) => {
                                  const locator = (one.locator ?? {}) as Record<string, unknown>;
                                  return (
                                    <li key={at}>
                                      <span className="font-mono">{String(one.semantic_key ?? "")}</span> →{" "}
                                      <span className="font-mono">
                                        {String(locator.type ?? "")}|{String(locator.value ?? "")}
                                      </span>
                                      {one.reasoning ? ` — ${String(one.reasoning)}` : ""}
                                    </li>
                                  );
                                })}
                              </ul>
                            </div>
                          ) : null}
                          <details>
                            <summary className="cursor-pointer text-body-sm text-text-secondary">
                              감사 로그 (보고 원문)
                            </summary>
                            <pre className="mt-1 overflow-x-auto bg-bg-subtle p-2 text-caption">
                              {JSON.stringify(report, null, 2)}
                            </pre>
                          </details>
                        </div>
                      </details>
                    </li>
                  );
                })}
              </ul>
            </section>
          ) : (
            <EmptyState {...NO_SESSIONS} />
          )}
        </div>
      ) : null}
    </Shell>
  );
}
