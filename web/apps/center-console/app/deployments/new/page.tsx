import Link from "next/link";
import { redirect } from "next/navigation";
import { Button, ErrorBanner } from "@chaeksas/ui";
import type { BotUiInfo } from "@chaeksas/api-types/c5-bot-ui-info";
import type { PackageInfo } from "@chaeksas/api-types/c5-package-info";
import type { ServerRunnerInfo } from "@chaeksas/api-types/c12-server-runner-info";
import { CenterError, center, session } from "@/lib/center";
import { Shell } from "@/components/Shell";
import { createDeployment } from "@/app/actions";

/**
 * CON-15 「새 배포」 — **두 걸음이고 JS 없이 돈다** (CON-05 「새 작업」과 같은 결).
 *
 * 1. 「BPM 프로세스@버전」을 고른다 (GET — 주소에 남는다). **승인된 판만** 고를 거리다.
 * 2. 그 판의 실행 위치로 대상 칸이 갈린다: PC면 PC 실행기를 **여럿** 고르고(PC마다 배포 하나 —
 *    PC 배포에 전체 대상은 없다, ADR-0046), 서버면 「전체」나 실행기 하나와 동시 실행 상한이다.
 *
 * 봉투는 Center가 지어 서명한다 (ADR-0090). 받아들이는 규칙(대상·리소스 누락 등)은 Center가 보고
 * 거부하면 그 사유를 이 화면에 보인다.
 */
const FIELD = "h-9 border border-border-strong bg-bg-surface px-2 text-body";

export default async function NewDeploymentPage({
  searchParams,
}: {
  searchParams: Promise<{ bot?: string; error?: string }>;
}) {
  const found = await session();
  if (!found) redirect("/login");
  if (found.mode !== "admin") redirect("/deployments");
  const asked = await searchParams;
  const bot = asked.bot ?? "";

  let approved: PackageInfo[] = [];
  let botUis: BotUiInfo[] = [];
  let runners: ServerRunnerInfo[] = [];
  let failure: string | null = asked.error ?? null;
  try {
    [approved, botUis, runners] = await Promise.all([
      center.packages({ kind: "bpm_process" }).then((all) => all.filter((one) => one.status === "approved")),
      center.botUis(),
      center.serverRunners(),
    ]);
  } catch (cause) {
    failure = cause instanceof CenterError ? cause.message : "알 수 없는 오류가 생겼습니다";
  }
  approved.sort((a, b) => a.id.localeCompare(b.id) || a.version.localeCompare(b.version));
  const picked = approved.find((one) => `${one.id}@${one.version}` === bot);
  const server = picked?.run_location === "server";
  // 비활성 PC에는 배포를 보내지 않는다 (C4 `disabled`) — 고를 거리에서 뺀다.
  const pcs = botUis.filter((one) => !one.disabled).sort((a, b) => a.name.localeCompare(b.name));

  return (
    <Shell mode={found.mode} actor={found.actor} current="/deployments">
      <header className="mb-4">
        <h1 className="text-h1 font-bold">새 배포</h1>
        <p className="text-body text-text-secondary">
          <Link className="underline" href="/deployments">
            배포
          </Link>
          로 돌아가기
        </p>
      </header>

      {failure ? <ErrorBanner message={failure} /> : null}

      <form className="mb-6 flex flex-wrap items-end gap-3" method="get">
        <label className="flex flex-col gap-1 text-body-sm">
          <span className="text-text-muted">BPM 프로세스@버전 (승인된 것)</span>
          <select name="bot" defaultValue={bot} className={FIELD}>
            <option value="">(고르세요)</option>
            {approved.map((one) => (
              <option key={`${one.id}@${one.version}`} value={`${one.id}@${one.version}`}>
                {one.id}@{one.version}
                {one.name ? ` — ${one.name}` : ""}
              </option>
            ))}
          </select>
        </label>
        <Button type="submit" variant="secondary">
          고르기
        </Button>
      </form>

      {approved.length === 0 && !failure ? (
        <p className="text-body text-text-secondary">
          승인된 BPM 프로세스가 없습니다. 「BPM 프로세스 현황」에서 먼저 승인하세요.
        </p>
      ) : null}

      {picked ? (
        <form action={createDeployment} className="flex max-w-2xl flex-col gap-4">
          <input type="hidden" name="bot" value={bot} />
          <input type="hidden" name="place" value={server ? "server" : "pc"} />

          {server ? (
            <fieldset className="flex flex-col gap-3 border border-border-default p-3">
              <legend className="px-1 text-body font-medium">대상 — 서버 실행기</legend>
              <label className="flex flex-col gap-1 text-body-sm">
                <span className="text-text-muted">실행기</span>
                <select name="runner" defaultValue="" className={FIELD}>
                  <option value="">전체</option>
                  {runners.map((one) => (
                    <option key={one.server_runner_id} value={one.server_runner_id}>
                      {one.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-body-sm">
                <span className="text-text-muted" title="이 BPM 프로세스가 서버에서 한꺼번에 도는 수. 비우면 기본입니다.">
                  동시 실행 상한 (비우면 기본)
                </span>
                <input type="number" name="max_concurrency" min={1} className={FIELD} />
              </label>
            </fieldset>
          ) : (
            <fieldset className="flex flex-col gap-2 border border-border-default p-3">
              <legend className="px-1 text-body font-medium">대상 — PC 실행기 (여럿 고를 수 있습니다)</legend>
              {pcs.length === 0 ? (
                <p className="text-body-sm text-text-muted">
                  등록된 PC 실행기가 없습니다. PC에서 PC 실행기를 한 번 연결해야 배포할 수 있습니다.
                </p>
              ) : (
                pcs.map((one) => (
                  <label key={one.bot_ui_id} className="flex items-center gap-2 text-body">
                    <input type="checkbox" name="bot_ui" value={one.bot_ui_id} />
                    {one.name}
                    <span className="text-text-muted">{one.online ? "● 온라인" : "○ 오프라인"}</span>
                  </label>
                ))
              )}
            </fieldset>
          )}

          <div className="flex flex-wrap gap-3">
            <label className="flex flex-col gap-1 text-body-sm">
              <span className="text-text-muted">시작 (비우면 즉시)</span>
              <input type="datetime-local" name="not_before" className={FIELD} />
            </label>
            <label className="flex flex-col gap-1 text-body-sm">
              <span className="text-text-muted">끝 (비우면 무기한)</span>
              <input type="datetime-local" name="expires_at" className={FIELD} />
            </label>
          </div>
          <div>
            <Button type="submit" variant="primary">
              배포
            </Button>
          </div>
        </form>
      ) : null}
    </Shell>
  );
}
