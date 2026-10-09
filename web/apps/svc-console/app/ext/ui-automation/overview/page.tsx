import { redirect } from "next/navigation";
import { DataTable, ErrorBanner, StatusBadge, type Column } from "@chaeksas/ui";
import type { DeployCheck } from "@chaeksas/api-types/c9-console-overview";
import { APP_URL, load, reason, svc } from "@/lib/page";
import { Shell } from "@/components/Shell";

/**
 * UIA-01 개요 — UI 자동화 앱 고유 화면 (C13 `console.pages`, ADR-0042).
 *
 * **이 앱만의 화면이다.** 콘솔 한 벌이 모든 서비스 앱을 그리지만, 탐색 줄은 접속한 앱의
 * `extension.id`로 고르므로 이 경로는 UI 자동화 앱에 붙었을 때만 메뉴에 보인다. 주소로 바로
 * 들어온 경우를 위해 **어느 앱인지 한 번 더 본다**.
 *
 * 읽는 길은 앱 고유 관리 경로(`GET /admin/v1/overview`, C9 §관리 콘솔이 읽는 길)이고
 * **관리자 토큰으로만** 열린다 — 브라우저는 토큰을 모른다 (BFF가 부른다, ADR-0017).
 */

const EXTENSION_ID = "ui-automation";

/** 「배포 전 확인」 배지 — `status_map`의 「사전 점검」 표기만 쓴다 (스타일 가이드). */
const CHECK_LABEL: Record<string, string> = { ok: "정상", warn: "경고" };

const PROMOTION_HINT = "검증 전 로케이터는 연속 3회 정상 동작하면 자동으로 사용 중으로 올라갑니다.";
/** C8 보고는 세션이 **끝날 때** 온다 — 그래서 앱은 도는 세션을 모른다 (현장의 BUI-09가 안다). */
const RUNNING_HINT = "지금 도는 세션은 여기서 알 수 없습니다 — 보고는 세션이 끝날 때 옵니다 (현장 Bot UI의 BUI-09가 보여 줍니다).";
const LLM_HINT = "주소와 키는 보이지 않습니다 (C11). 계획과 치유가 같은 모델을 씁니다.";

function Summary({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1 rounded-md border border-border-default bg-bg-surface p-3">
      <span className="text-caption text-text-muted">{label}</span>
      <span className="text-body">{children}</span>
    </div>
  );
}

export default async function UiAutomationOverviewPage() {
  const found = await load();
  if (!found) redirect("/login");
  const { status, failure, session } = found;

  const mine = status?.extension?.id === EXTENSION_ID;
  let overview = null;
  let trouble: string | null = null;
  if (mine) {
    try {
      overview = await svc.uiAutomationOverview();
    } catch (cause) {
      trouble = reason(cause);
    }
  }

  const checks: Array<Column<DeployCheck>> = [
    { key: "label", header: "확인", width: "20ch" },
    {
      key: "level",
      header: "상태",
      width: "10ch",
      cell: (row) => <StatusBadge group="사전 점검" label={CHECK_LABEL[row.level ?? "ok"] ?? "정상"} />,
    },
    { key: "detail", header: "내용", cell: (row) => row.detail ?? "—" },
  ];

  const counts = overview?.counts;
  const sessions = overview?.sessions;
  const llm = overview?.llm;

  return (
    <Shell status={status} actor={session.actor} appUrl={APP_URL} current="/ext/ui-automation/overview">
      <h1 className="mb-4 text-h1 font-bold">개요</h1>
      {failure ? <ErrorBanner message={failure} /> : null}
      {!mine ? (
        <ErrorBanner
          message={`이 화면은 UI 자동화 앱의 것입니다 — 접속한 앱은 ${status?.app_id ?? "알 수 없음"}입니다.`}
        />
      ) : null}
      {trouble ? <ErrorBanner message={trouble} /> : null}

      {overview ? (
        <div className="flex flex-col gap-6">
          <section>
            <h2 className="mb-2 text-h3 font-semibold">관리 중인 셀렉터</h2>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
              <Summary label="화면">{counts?.pages ?? 0}개</Summary>
              <Summary label="요소">{counts?.elements ?? 0}개</Summary>
              <Summary label="로케이터 전체">{counts?.locators ?? 0}개</Summary>
              <Summary label="검증 전">{counts?.unverified ?? 0}개</Summary>
              <Summary label="대체됨">{counts?.deprecated ?? 0}개</Summary>
            </div>
            <p className="mt-2 text-body-sm text-text-secondary">{PROMOTION_HINT}</p>
          </section>

          <section>
            <h2 className="mb-2 text-h3 font-semibold">LLM</h2>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <Summary label="연결">
                <StatusBadge group="서비스 앱" label={llm?.configured ? "정상" : "확인 전"} />
              </Summary>
              <Summary label="모델">
                <span className="font-mono text-body-sm break-all">{llm?.model || "설정되지 않음"}</span>
              </Summary>
              <Summary label="마지막 호출">{llm?.last_status ?? "unknown"}</Summary>
              <Summary label="치유 최대 횟수">{llm?.max_healing_attempts ?? 3}회</Summary>
            </div>
            <p className="mt-2 text-body-sm text-text-secondary">{LLM_HINT}</p>
          </section>

          <section>
            <h2 className="mb-2 text-h3 font-semibold">최근 UI 세션</h2>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
              <Summary label="오늘">{sessions?.today ?? 0}건</Summary>
              <Summary label="전체 (보고받은 것)">{sessions?.total ?? 0}건</Summary>
              <Summary label="사람에게 전환">{sessions?.escalated ?? 0}건</Summary>
              <Summary label="실패">{sessions?.failed ?? 0}건</Summary>
              <Summary label="자가 치유">{sessions?.healed ?? 0}건</Summary>
            </div>
            <p className="mt-2 text-body-sm text-text-secondary">
              {RUNNING_HINT} 셀렉터 시험(BUI-08) 보고 {sessions?.test ?? 0}건은 위 수에 들어가지 않습니다.
            </p>
          </section>

          <section>
            <h2 className="mb-2 text-h3 font-semibold">배포 전 확인</h2>
            <DataTable
              columns={checks}
              rows={overview.checks ?? []}
              rowKey={(row) => row.id}
              caption="이 앱이 스스로 볼 수 있는 것"
            />
            <p className="mt-2 text-body-sm text-text-secondary">
              경고가 있어도 앱은 돕니다 — 무엇이 안 되는지 알려 주는 줄입니다.
            </p>
          </section>

          <p className="text-caption text-text-muted">
            레지스트리 판 {overview.revision ?? 1} · 읽은 시각 {overview.generated_at ?? "—"}
          </p>
        </div>
      ) : null}
    </Shell>
  );
}
