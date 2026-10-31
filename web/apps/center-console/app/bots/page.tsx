import Link from "next/link";
import { redirect } from "next/navigation";
import type { Route } from "next";
import { DataTable, EmptyState, ErrorBanner, StatusBadge, type Column } from "@chaeksas/ui";
import type { BotUiInfo } from "@chaeksas/api-types/c5-bot-ui-info";
import type { DeploymentInfo } from "@chaeksas/api-types/c5-deployment-info";
import { CenterError, center, session } from "@/lib/center";
import { Shell } from "@/components/Shell";
import { PackageActions } from "@/components/PackageActions";
import { ServerRunners } from "@/components/ServerRunners";
import { Schedules } from "@/components/Schedules";
import { STATUS_LABEL, packageHref, time } from "@/app/packages/page";
import { DeleteVersion } from "./tools";
import {
  NO_RUNS,
  SAMPLE,
  SCAN,
  deployedPcs,
  percent,
  placeOf,
  summarize,
  type BotRow,
  type Place,
  type RunFields,
} from "@/lib/summary";

// 세는 일은 `lib/summary.ts`에 있다 (화면을 모르는 자리 — 시험이 그것을 잰다).
export { NO_RUNS, SAMPLE, SCAN, deployedPcs, percent, summarize };
export type { BotRow, RunFields };

/**
 * CON-02 BPM 프로세스 — BPM 프로세스·버전별 준비도.
 *
 * **Center가 집계를 갖고 있지 않다.** 실행 요약(C3 `RunInfo`)·보고된 준비 상태(C4
 * `readiness`)·누락 리소스(C5 `missing_resources`)를 **콘솔에서 묶어** 보인다 — Center에 집계
 * 표를 두면 실행이 올 때마다 낡고, 어느 쪽이 원본인지 흐려진다 (CON-01의 셈 열과 같은 결).
 *
 * **「투입 가능」 같은 판정 열을 두지 않는다** (화면 문서) — 판단은 관리자 몫이고, 화면은 숫자와
 * 경고만 보인다.
 *
 * 셈은 **끝난 실행**만 센다 — 도는 중인 실행의 셈 칸은 `null`이다 (C3: 요약은 받을 때 만든다).
 */


/** 탭 — 실행 위치 (C1 `run_location`). 서버가 먼저다 (서버 우선, ADR-0016). */
const TABS: Array<{ place: Place; label: string }> = [
  { place: "server", label: "서버" },
  { place: "pc", label: "데스크톱" },
];


/**
 * 「확인률」은 C3 요약의 **`confirmations`**(확인만 센 수)로 잰다. 그 칸은 **선택 칸**이라
 * 옛 PC 실행기가 보낸 기록에는 없다 — 그런 실행은 **분모에도 넣지 않는다**(`confirm_sample`).
 * 0으로 세면 「확인이 없었다」와 「세지 않았다」가 같아져 확인률이 조용히 낮아진다.
 */
export const CONFIRM_NOTE =
  "「확인률」은 확인 요청만 셉니다 (결재는 제외) — 그 셈을 보내지 않은 옛 기록은 표본에서 빠집니다.";



/**
 * 비율 막대 — 글자 + 가로 막대 (스타일 가이드 §7: **색만으로 뜻을 전하지 않는다**).
 *
 * 색은 `status_map`이 쓰는 상태 토큰에서 온다 (값을 코드에 적지 않는다).
 */
function Rate({ part, whole, token }: { part: number; whole: number; token: string }) {
  const shown = percent(part, whole);
  if (shown === null) return <span className="text-text-muted">—</span>;
  return (
    <span className="flex items-center gap-2 whitespace-nowrap">
      <span className="tabular-nums">{shown}</span>
      <span
        aria-hidden
        className="h-2 w-16 shrink-0 overflow-hidden"
        style={{ backgroundColor: "var(--color-bg-subtle)", borderRadius: "var(--radius-full)" }}
      >
        <span
          className="block h-full"
          style={{
            width: shown,
            backgroundColor: `var(--status-${token}-solid)`,
            borderRadius: "var(--radius-full)",
          }}
        />
      </span>
    </span>
  );
}





export default async function BotsPage({ searchParams }: { searchParams: Promise<{ tab?: string }> }) {
  const found = await session();
  if (!found) redirect("/login");
  const place: Place = (await searchParams).tab === "pc" ? "pc" : "server";

  let rows: BotRow[] = [];
  let pcs: BotUiInfo[] = [];
  let failure: string | null = null;
  try {
    // BPM 프로세스·배포·보고된 준비 상태는 **한 번에** 읽는다 (서로를 기다릴 일이 없다).
    const [packages, botUis, deployments] = await Promise.all([
      center.packages({ kind: "bpm_process" }),
      center.botUis(),
      center.deployments({ active: true }),
    ]);
    pcs = botUis as BotUiInfo[];

    // 실행 요약은 **BPM 프로세스마다** 묻는다 — 한 번에 받아 오면 판이 많은 BPM 프로세스의 옛 판이 잘린다.
    const ids = [...new Set(packages.map((one) => one.id))];
    const sampled = await Promise.all(
      ids.map(async (id) => summarize((await center.runs({ bpm_process_id: id, limit: SCAN })).runs ?? [])),
    );
    const counts = new Map(sampled.flatMap((one) => [...one.entries()]));

    rows = packages
      .map((one) => {
        const key = `${one.id}@${one.version}`;
        const reported = (botUis as BotUiInfo[]).flatMap((pc) =>
          (pc.readiness ?? []).filter(
            (ready) => ready.bpm_process_id === one.id && ready.version === one.version,
          ),
        );
        const unusable = reported.filter((ready) => ready.ready === false);
        return {
          id: one.id,
          version: one.version,
          name: one.name ?? null,
          status: one.status,
          run_location: one.run_location ?? null,
          // `id`에 판이 붙어 온다 (C5 — `version` 칸이 따로 없다). 사유도 함께 보인다.
          missing: (one.missing_resources ?? []).map((gone) => `${gone.type} ${gone.id} (${gone.reason})`),
          blocked: unusable.length,
          blocked_codes: [
            ...new Set(unusable.flatMap((ready) => ready.blocked ?? [])),
          ],
          ...deployedPcs(deployments as DeploymentInfo[], one.id, one.version),
          // **실행 요약은 제 칸만 덮는다** (`RunFields`) — 위에서 센 「실행 불가」·「배포된
          // PC 실행기」가 살아 있어야 한다.
          ...(counts.get(key) ?? NO_RUNS),
        } as BotRow;
      })
      .sort((a, b) => a.id.localeCompare(b.id) || a.version.localeCompare(b.version));
  } catch (cause) {
    failure = cause instanceof CenterError ? cause.message : "알 수 없는 오류가 생겼습니다";
  }

  const counts = { server: 0, pc: 0 };
  for (const row of rows) counts[placeOf(row.run_location)] += 1;
  // 탭은 **실행 위치로** 가른다 — 그래서 표에 「실행 위치」 열이 없다 (CON-02).
  rows = rows.filter((row) => placeOf(row.run_location) === place);
  const notReady = rows.filter((row) => row.blocked > 0);
  const incomplete = rows.filter((row) => row.missing.length > 0);

  const columns: Array<Column<BotRow>> = [
    {
      key: "id",
      header: "프로세스",
      mono: true,
      cell: (row) => (
        <Link className="underline" href={packageHref(row)}>
          {row.id}
        </Link>
      ),
    },
    { key: "version", header: "버전", width: "12ch", mono: true },
    {
      key: "status",
      header: "상태",
      width: "10ch",
      cell: (row) => <StatusBadge group="패키지" label={STATUS_LABEL[row.status] ?? row.status} />,
    },
    {
      key: "blocked",
      header: "실행 불가",
      width: "10ch",
      align: "right",
      cell: (row) =>
        row.blocked === 0 ? (
          <span className="text-text-muted">—</span>
        ) : (
          <span title={row.blocked_codes.join(", ") || undefined}>{row.blocked}대</span>
        ),
    },
    {
      key: "missing",
      header: "경고",
      width: "12ch",
      cell: (row) =>
        row.missing.length === 0 ? (
          <span className="text-text-muted">—</span>
        ) : (
          <span title={row.missing.join(", ")}>리소스 {row.missing.length}개 없음</span>
        ),
    },
    {
      key: "successes",
      header: "성공률",
      width: "14ch",
      cell: (row) => <Rate part={row.successes} whole={row.sample} token="done" />,
    },
    {
      key: "replayed",
      header: "재생률",
      width: "14ch",
      cell: (row) => <Rate part={row.replayed} whole={row.ai_tasks} token="replayed" />,
    },
    {
      key: "confirmations",
      header: "확인률",
      width: "12ch",
      align: "right",
      // **분모는 그 칸을 보낸 실행 수**다 — 0이면 「—」다 (0.0회로 보이면 「확인이 없었다」로 읽힌다).
      cell: (row) =>
        row.confirm_sample === 0 ? (
          <span className="text-text-muted" title={CONFIRM_NOTE}>
            —
          </span>
        ) : (
          <span className="tabular-nums" title={CONFIRM_NOTE}>
            {(row.confirmations / row.confirm_sample).toFixed(1)}회
          </span>
        ),
    },
    {
      key: "sample",
      header: "표본 수",
      width: "9ch",
      align: "right",
      cell: (row) => (row.sample === 0 ? <span className="text-text-muted">—</span> : `${row.sample}회`),
    },
    { key: "last_success", header: "최근 성공", width: "18ch", cell: (row) => time(row.last_success) },
    {
      key: "pcs",
      header: "배포된 Bot",
      width: "14ch",
      align: "right",
      // **건수가 아니라 PC 수**다 (ADR-0046). 건수는 툴팁에 — 같은 PC에 옛 배포가 살아 있으면
      // 둘이 다르고, 그때 「왜 수가 적나」의 답이 그 자리에 있어야 한다.
      cell: (row) =>
        row.pcs === 0 ? (
          <span className="text-text-muted">—</span>
        ) : (
          <span className="tabular-nums" title={`살아 있는 배포 ${row.deployments}건`}>
            {row.pcs}대
          </span>
        ),
    },
    // 승인은 **이 줄에서** 한다 (ADR-0090 — Center가 서명한다). 배포는 「배포」 화면 한 곳이다.
    ...(found.mode === "admin"
      ? [
          {
            key: "actions",
            header: "승인",
            cell: (row: BotRow) => <PackageActions packageId={row.id} version={row.version} status={row.status} />,
          } as Column<BotRow>,
        ]
      : []),
  ];

  // 「배포된 PC 실행기」는 PC BPM 프로세스의 것이다 — 서버 BPM 프로세스는 PC에 배포하지 않는다.
  const shown = place === "pc" ? columns : columns.filter((column) => column.key !== "pcs");

  return (
    <Shell mode={found.mode} actor={found.actor} current="/bots">
      <header className="mb-4">
        <h1 className="text-h1 font-bold">프로세스</h1>
      </header>

      <nav className="mb-4 flex flex-wrap gap-2" aria-label="실행 위치">
        {TABS.map((one) => (
          <Link
            key={one.place}
            href={`/bots?tab=${one.place}` as Route}
            aria-current={place === one.place ? "page" : undefined}
            className={
              place === one.place
                ? "rounded-md border border-transparent bg-primary-subtle px-3 py-1 text-body font-semibold text-primary"
                : "rounded-md border border-border-default bg-bg-surface px-3 py-1 text-body text-text-secondary hover:bg-bg-subtle"
            }
          >
            {one.label} ({counts[one.place]})
          </Link>
        ))}
      </nav>

      {failure ? (
        <ErrorBanner message={failure} />
      ) : rows.length === 0 ? (
        <EmptyState
          title={place === "server" ? "올라온 서버 프로세스가 없습니다." : "올라온 PC 프로세스가 없습니다."}
          hint="Studio에서 「Center로 올리기」로 올리세요."
        />
      ) : (
        <div className="flex flex-col gap-3">
          {notReady.length > 0 ? (
            <ErrorBanner
              message={`사전 점검에 실행 불가 항목이 있는 버전: ${notReady
                .map((row) => `${row.id}@${row.version} (${row.blocked}대)`)
                .join(", ")}`}
            />
          ) : null}
          {incomplete.length > 0 ? (
            <ErrorBanner
              message={`필요한 리소스가 Center에 없는 버전 (배포 시 거부됨): ${incomplete
                .map((row) => `${row.id}@${row.version}`)
                .join(", ")}`}
            />
          ) : null}

          <DataTable
            columns={shown}
            rows={rows}
            rowKey={(row) => `${row.id}@${row.version}`}
            caption="프로세스·버전별 준비도"
          />
          <p className="text-body-sm text-text-muted">
            {CONFIRM_NOTE} 셈은 끝난 실행만 셉니다 — 도는 중인 실행은 표본에 들어가지 않습니다.
            프로세스마다 최근 {SCAN}건을 훑어 버전별로 {SAMPLE}회까지 셉니다 (그보다 적으면 표본 수가
            작게 보입니다).
          </p>

          {found.mode === "admin" ? (
            <DeleteVersion rows={rows.map((row) => ({ id: row.id, version: row.version }))} />
          ) : (
            <p className="text-body-sm text-text-muted">
              승인·삭제는 관리자 계정으로 합니다.
            </p>
          )}
        </div>
      )}

      {/* 서버 BPM 프로세스가 도는 곳 — 서버 실행기 목록·승인 대기·대기열 (옛 CON-12 목록). */}
      {place === "server" ? (
        <div className="mt-8">
          <ServerRunners admin={found.mode === "admin"} />
        </div>
      ) : null}

      {/* [S] 「일정」 — 타이머로 시작하는 그 탭의 배포 (C5 §일정). 없으면 영역이 없다. */}
      {failure ? null : <Schedules place={place} botUis={pcs} />}
    </Shell>
  );
}
