import Link from "next/link";
import { redirect } from "next/navigation";
import { DataTable, EmptyState, ErrorBanner, StatusBadge, type Column } from "@chaeksas/ui";
import type { BotUiInfo } from "@chaeksas/api-types/c5-bot-ui-info";
import type { DeploymentInfo } from "@chaeksas/api-types/c5-deployment-info";
import type { PackageInfo } from "@chaeksas/api-types/c5-package-info";
import type { RunInfo } from "@chaeksas/api-types/c3-run-info";
import { CENTER_URL, CenterError, center, session } from "@/lib/center";
import { Shell } from "@/components/Shell";
import { STATUS_LABEL, packageHref, time } from "@/app/packages/page";
import { DeleteVersion } from "./tools";

/**
 * CON-02 Bot 현황 — Bot(BPM 프로세스)·버전별 준비도.
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

/** 준비도를 재는 표본 (화면 문서 — 「최근 20회 실행 기준」). */
export const SAMPLE = 20;

/**
 * Bot 하나당 훑어보는 실행 수. **버전마다 최근 20회**를 찾으려면 그보다 많이 봐야 한다
 * (한 Bot에 여러 판이 돈다). 그래도 못 채운 버전은 **표본 수가 작게 보인다** — 비어 있는
 * 칸을 「0%」로 그리지 않는 것이 이 화면의 규칙이다.
 */
export const SCAN = 200;

/** 실행 위치 (C1 `run_location`). */
const PLACE: Record<string, string> = { pc: "PC", server: "서버" };

/** 끝난 실행의 상태 (C3) — 표본에 넣는 것들. 도는 중·기다리는 중은 세지 않는다. */
const FINISHED = new Set(["success", "failed", "cancelled"]);

/**
 * **「확인률」 대신 「사람 개입」을 보인다** — C3 요약의 `human_requests`는 결재와 확인을 **한
 * 칸에 합쳐** 센다 (CON-01의 「결재·확인 수」와 같은 값이다). 가르려면 C3에 셈 칸을 더해야
 * 하므로, 화면은 **합을 보이고 그렇게 말한다** (`docs/09-gaps.md` §4-9).
 */
export const HUMAN_NOTE =
  "「사람 개입」은 결재와 확인을 합친 수입니다 — C3 실행 요약이 둘을 한 칸에 세기 때문입니다 (확인만 따로 보려면 그 칸을 갈라야 합니다).";

/** 한 (Bot, 버전)의 집계 한 줄. */
export interface BotRow {
  id: string;
  version: string;
  name: string | null;
  status: string;
  run_location: string | null;
  /** 표본에 들어간 끝난 실행 수 (0이면 재지 않는다). */
  sample: number;
  successes: number;
  ai_tasks: number;
  replayed: number;
  human_requests: number;
  last_success: string | null;
  /** 이 판을 「실행 불가」로 보고한 Bot UI 수 (C4 `readiness.ready === false`). */
  blocked: number;
  /** 그 PC들이 말한 막은 점검 코드 (툴팁). */
  blocked_codes: string[];
  /** 살아 있는 배포 수 (C5). 그룹·전체 배포는 **대상을 풀지 않는다** — 건수로 센다. */
  deployments: number;
  /** 필요한 서비스 앱 키 참조 (C1 `requires.service_apps`). */
  key_refs: string[];
  /** Center에 없는 리소스 (C5 — 배포 때 거부된다). */
  missing: string[];
}

/** 비율 → 「72%」. **표본이 없으면 「—」**다 (0%로 보이면 「다 실패했다」로 읽힌다). */
export function percent(part: number, whole: number): string | null {
  if (whole <= 0) return null;
  return `${Math.round((part / whole) * 100)}%`;
}

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

/** 실행 요약들을 (Bot, 버전)으로 묶어 **최근 20회만** 센다. */
export function summarize(runs: RunInfo[]): Map<string, Omit<BotRow, keyof PackageFields>> {
  const out = new Map<string, Omit<BotRow, keyof PackageFields>>();
  const counted = new Map<string, number>();
  for (const run of runs) {
    const id = run.bpm_process_id;
    const version = run.version;
    if (!id || !version || !run.status || !FINISHED.has(run.status)) continue;
    const key = `${id}@${version}`;
    const seen = counted.get(key) ?? 0;
    if (seen >= SAMPLE) continue; // 목록은 **새것부터** 온다 (C3 — 최근 20회가 앞쪽이다)
    counted.set(key, seen + 1);
    const found =
      out.get(key) ??
      ({
        sample: 0,
        successes: 0,
        ai_tasks: 0,
        replayed: 0,
        human_requests: 0,
        last_success: null,
        blocked: 0,
        blocked_codes: [],
        deployments: 0,
      } as Omit<BotRow, keyof PackageFields>);
    found.sample += 1;
    if (run.status === "success") {
      found.successes += 1;
      // 목록이 새것부터 오므로 **처음 만난 성공**이 최근 성공이다.
      found.last_success = found.last_success ?? run.finished_at ?? run.started_at ?? null;
    }
    found.ai_tasks += run.ai_tasks ?? 0;
    found.replayed += run.replayed_tasks ?? 0;
    found.human_requests += run.human_requests ?? 0;
    out.set(key, found);
  }
  return out;
}

/** 패키지에서 오는 칸들 — `summarize`가 채우지 않는 것. */
type PackageFields = Pick<
  BotRow,
  "id" | "version" | "name" | "status" | "run_location" | "key_refs" | "missing"
>;

/** C1 `requires.service_apps` — 상속 참조와 태스크가 따로 적은 참조를 **함께** 센다. */
export function keyRefsOf(one: PackageInfo): string[] {
  const needs = one.manifest?.requires?.service_apps ?? [];
  const found = needs.flatMap((need) => [need.key_ref, ...(need.task_key_refs ?? [])]);
  return [...new Set(found.filter((ref): ref is string => Boolean(ref)))];
}

export default async function BotsPage() {
  const found = await session();
  if (!found) redirect("/login");

  let rows: BotRow[] = [];
  let failure: string | null = null;
  try {
    // Bot·배포·보고된 준비 상태는 **한 번에** 읽는다 (서로를 기다릴 일이 없다).
    const [packages, botUis, deployments] = await Promise.all([
      center.packages({ kind: "bpm_process" }),
      center.botUis(),
      center.deployments({ active: true }),
    ]);

    // 실행 요약은 **Bot마다** 묻는다 — 한 번에 받아 오면 판이 많은 Bot의 옛 판이 잘린다.
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
          key_refs: keyRefsOf(one),
          // `id`에 판이 붙어 온다 (C5 — `version` 칸이 따로 없다). 사유도 함께 보인다.
          missing: (one.missing_resources ?? []).map((gone) => `${gone.type} ${gone.id} (${gone.reason})`),
          blocked: unusable.length,
          blocked_codes: [
            ...new Set(unusable.flatMap((ready) => ready.blocked ?? [])),
          ],
          deployments: (deployments as DeploymentInfo[]).filter(
            (one_deployment) =>
              one_deployment.bpm_process_id === one.id && one_deployment.version === one.version,
          ).length,
          ...(counts.get(key) ?? {
            sample: 0,
            successes: 0,
            ai_tasks: 0,
            replayed: 0,
            human_requests: 0,
            last_success: null,
          }),
        } as BotRow;
      })
      .sort((a, b) => a.id.localeCompare(b.id) || a.version.localeCompare(b.version));
  } catch (cause) {
    failure = cause instanceof CenterError ? cause.message : "알 수 없는 오류가 생겼습니다";
  }

  const bots = new Set(rows.map((row) => row.id)).size;
  const notReady = rows.filter((row) => row.blocked > 0);
  const incomplete = rows.filter((row) => row.missing.length > 0);

  const columns: Array<Column<BotRow>> = [
    {
      key: "id",
      header: "Bot",
      mono: true,
      cell: (row) => (
        <Link className="underline" href={packageHref(row)}>
          {row.id}
        </Link>
      ),
    },
    { key: "version", header: "버전", width: "12ch", mono: true },
    {
      key: "run_location",
      header: "실행 위치",
      width: "10ch",
      cell: (row) => (row.run_location ? PLACE[row.run_location] ?? row.run_location : "—"),
    },
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
      key: "human_requests",
      header: "사람 개입",
      width: "12ch",
      align: "right",
      cell: (row) =>
        row.sample === 0 ? (
          <span className="text-text-muted">—</span>
        ) : (
          <span className="tabular-nums" title={HUMAN_NOTE}>
            {(row.human_requests / row.sample).toFixed(1)}회
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
      key: "deployments",
      header: "배포",
      width: "9ch",
      align: "right",
      cell: (row) => (row.deployments === 0 ? <span className="text-text-muted">—</span> : `${row.deployments}건`),
    },
    {
      key: "key_refs",
      header: "서비스 앱 키 참조",
      cell: (row) => (row.key_refs.length === 0 ? <span className="text-text-muted">—</span> : row.key_refs.join(", ")),
    },
  ];

  return (
    <Shell mode={found.mode} actor={found.actor} centerUrl={CENTER_URL} current="/bots">
      <header className="mb-4">
        <h1 className="text-h1 font-bold">Bot 현황</h1>
        <p className="text-body text-text-secondary">
          Bot {bots}개, 버전 {rows.length}개 · 준비도는 최근 {SAMPLE}회 실행 기준
        </p>
      </header>

      {failure ? (
        <ErrorBanner message={failure} />
      ) : rows.length === 0 ? (
        <EmptyState
          title="올라온 Bot이 없습니다."
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
            columns={columns}
            rows={rows}
            rowKey={(row) => `${row.id}@${row.version}`}
            caption="Bot·버전별 준비도"
          />
          <p className="text-body-sm text-text-muted">
            {HUMAN_NOTE} 셈은 **끝난 실행**만 셉니다 — 도는 중인 실행은 표본에 들어가지 않습니다.
            Bot마다 최근 {SCAN}건을 훑어 버전별로 {SAMPLE}회까지 셉니다 (그보다 적으면 표본 수가
            작게 보입니다).
          </p>

          {found.mode === "admin" ? (
            <DeleteVersion rows={rows.map((row) => ({ id: row.id, version: row.version }))} />
          ) : (
            <p className="text-body-sm text-text-muted">
              버전을 지우려면 관리자 모드로 켜세요 (위 막대의 「관리자」).
            </p>
          )}
        </div>
      )}
    </Shell>
  );
}
