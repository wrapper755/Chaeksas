/** CON-02·CON-12가 세는 일 — **화면을 모르는 자리**다 (`page.tsx`는 이것을 그릴 뿐이다).
 *
 * 여기 있는 것은 전부 **순수 함수**다: 서버 호출(`lib/center.ts`)도, JSX도, `next/*`도 들이지
 * 않는다. 갈라 둔 까닭은 **셈을 시험으로 재려고**다 — 페이지 모듈은 `server-only`를 끌고 와
 * 단위 시험에서 불러올 수 없다 (파이썬 쪽에서 「Qt를 모르는 함수」를 갈라 두는 것과 같은 결).
 *
 * CON-02의 세는 규칙은 C3 요약에서 온다. **끝난 실행만**, **버전마다 최근 20회만**, 확인률은
 * **그 칸을 보낸 실행만** 분모에 넣는다. CON-12 쪽은 C12 보고와 C5 배포를 맞춰 본다.
 */

import type { DeploymentInfo } from "@chaeksas/api-types/c5-deployment-info";
import type { PackageInfo } from "@chaeksas/api-types/c5-package-info";
import type { RunInfo } from "@chaeksas/api-types/c3-run-info";
import type { JobInfo } from "@chaeksas/api-types/c5-job-info";
import type { ServerRunnerInfo } from "@chaeksas/api-types/c12-server-runner-info";

/** 준비도를 재는 표본 (화면 문서 — 「최근 20회 실행 기준」). */
export const SAMPLE = 20;

/**
 * Bot 하나당 훑어보는 실행 수. **버전마다 최근 20회**를 찾으려면 그보다 많이 봐야 한다
 * (한 Bot에 여러 판이 돈다). 그래도 못 채운 버전은 **표본 수가 작게 보인다** — 비어 있는
 * 칸을 「0%」로 그리지 않는 것이 이 화면의 규칙이다.
 */
export const SCAN = 200;
/** 끝난 실행의 상태 (C3) — 표본에 넣는 것들. 도는 중·기다리는 중은 세지 않는다. */
const FINISHED = new Set(["success", "failed", "cancelled"]);
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
  /**
   * 확인 요청 수 (C3 `confirmations`). **그 칸을 보낸 실행만** 센다.
   *
   * 결재와 확인의 **합**(`human_requests`)은 여기서 세지 않는다 — 이 화면의 열이 아니다
   * (CON-01 목록의 「결재·확인」이 그것을 보인다).
   */
  confirmations: number;
  /** `confirmations`를 보낸 끝난 실행 수 — 「확인률」의 분모다 (0이면 재지 않는다). */
  confirm_sample: number;
  last_success: string | null;
  /** 이 판을 「실행 불가」로 보고한 Bot UI 수 (C4 `readiness.ready === false`). */
  blocked: number;
  /** 그 PC들이 말한 막은 점검 코드 (툴팁). */
  blocked_codes: string[];
  /**
   * 이 판이 배포된 **Bot UI(PC) 수** — 살아 있는 PC 배포의 `target.id`를 겹치지 않게 센다.
   *
   * **PC 배포에는 전체(`*`) 대상이 없다** (ADR-0046) — 봉투 하나가 PC 하나를 가리키므로 풀
   * 것이 없고, 이 수는 어림이 아니라 정확하다. 서버 배포(M7)는 PC가 아니라 세지 않는다.
   */
  pcs: number;
  /** 살아 있는 PC 배포 **건수** (툴팁). 같은 PC에 옛 배포가 살아 있으면 `pcs`보다 크다. */
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
 * `summarize`가 채우는 칸 — **실행 요약(C3)에서 오는 것뿐**이다.
 *
 * **세는 쪽은 제가 세지 않은 칸을 들고 다니지 않는다.** 전에는 반환 타입이 「패키지에서 오는
 * 칸만 뺀 나머지」였던 탓에 `summarize`가 `blocked`·`deployments`까지 **0으로 들고** 돌아왔고,
 * 줄을 짓는 자리에서 그것을 **나중에 펼쳐** 실제 값을 덮었다 — 끝난 실행이 있는 판은
 * 「실행 불가」·「배포된 Bot UI」가 늘 0이고 경고 띠도 뜨지 않았다.
 */
export type RunFields = Pick<
  BotRow,
  | "sample"
  | "successes"
  | "ai_tasks"
  | "replayed"
  | "confirmations"
  | "confirm_sample"
  | "last_success"
>;

/** 표본이 없는 판 — **0%가 아니라 「—」**로 그려진다 (`percent`가 `null`을 준다). */
export const NO_RUNS: RunFields = {
  sample: 0,
  successes: 0,
  ai_tasks: 0,
  replayed: 0,
  confirmations: 0,
  confirm_sample: 0,
  last_success: null,
};
/** 실행 요약들을 (Bot, 버전)으로 묶어 **최근 20회만** 센다. */
export function summarize(runs: RunInfo[]): Map<string, RunFields> {
  const out = new Map<string, RunFields>();
  const counted = new Map<string, number>();
  for (const run of runs) {
    const id = run.bpm_process_id;
    const version = run.version;
    if (!id || !version || !run.status || !FINISHED.has(run.status)) continue;
    const key = `${id}@${version}`;
    const seen = counted.get(key) ?? 0;
    if (seen >= SAMPLE) continue; // 목록은 **새것부터** 온다 (C3 — 최근 20회가 앞쪽이다)
    counted.set(key, seen + 1);
    const found = out.get(key) ?? { ...NO_RUNS };
    found.sample += 1;
    if (run.status === "success") {
      found.successes += 1;
      // 목록이 새것부터 오므로 **처음 만난 성공**이 최근 성공이다.
      found.last_success = found.last_success ?? run.finished_at ?? run.started_at ?? null;
    }
    found.ai_tasks += run.ai_tasks ?? 0;
    found.replayed += run.replayed_tasks ?? 0;
    // **보낸 실행만** 센다 — 안 보낸 실행을 0으로 넣으면 확인률이 조용히 낮아진다 (C3).
    if (run.confirmations !== null && run.confirmations !== undefined) {
      found.confirmations += run.confirmations;
      found.confirm_sample += 1;
    }
    out.set(key, found);
  }
  return out;
}
/**
 * 「배포된 Bot UI」 — 그 판이 **살아 있는 PC 배포로 걸린 PC 수**와 그 건수 (C5).
 *
 * **PC 배포는 대상이 `bot_ui_id` 하나씩이다** (ADR-0046) — 그래서 `target.id`를 겹치지 않게
 * 세면 끝이고, Center가 대상을 풀어 줄 필요가 없다. 겹침을 지우는 까닭은 같은 판을 같은 PC에
 * 두 번 배포할 수 있어서다(옛 배포가 살아 있는 채) — 그때 **건수는 PC 수보다 크다**.
 *
 * `target.type`이 `bot_ui`인 것만 센다 — 열의 이름이 「배포된 **Bot UI**」다 (서버 배포는 M7).
 *
 * **등록된 Bot UI와 맞춰 보지 않는다.** 세는 것은 「배포가 가리키는 PC」이고, 가리킨 PC가 아직
 * 등록하지 않았으면 그것은 **보여야 하는 어긋남**이다 (잘못 서명한 배포가 0대로 숨으면
 * 아무도 못 찾는다). 어느 PC가 정말 있는지는 CON-03이 말한다.
 */
export function deployedPcs(
  all: DeploymentInfo[],
  bot: string,
  version: string,
): { pcs: number; deployments: number } {
  const mine = all.filter(
    (one) =>
      one.target.type === "bot_ui" && one.bpm_process_id === bot && one.version === version,
  );
  return { pcs: new Set(mine.map((one) => String(one.target.id))).size, deployments: mine.length };
}
/** C1 `requires.service_apps` — 상속 참조와 태스크가 따로 적은 참조를 **함께** 센다. */
export function keyRefsOf(one: PackageInfo): string[] {
  const needs = one.manifest?.requires?.service_apps ?? [];
  const found = needs.flatMap((need) => [need.key_ref, ...(need.task_key_refs ?? [])]);
  return [...new Set(found.filter((ref): ref is string => Boolean(ref)))];
}

// ───────────────────────────── CON-12 서버 실행 ─────────────────────────────

/**
 * 서버 실행기 상태 → `status_map` 「서버 실행기」의 표기 (C12 `status`는 열린 문자열이다).
 *
 * **오프라인이 먼저고, 그다음이 「일시 중지」다.** 오프라인이면 실행기가 보고한 `status`는
 * 지난 이야기라 「동작」으로 보이면 거짓이 되고, `paused`는 **Center의 뜻**이라 실행기가
 * 다음 하트비트로 알기 전에도 참이다 (거꾸로 두면 막 멈춘 실행기가 한 주기 동안 「동작」이다).
 */
export function runnerStatus(row: ServerRunnerInfo): string {
  if (!row.online) return "오프라인";
  if (row.paused) return "일시 중지";
  const table: Record<string, string> = {
    running: "동작",
    paused: "일시 중지",
    draining: "정리 중",
    error: "오류",
    offline: "오프라인",
  };
  return table[row.status] ?? row.status;
}

/**
 * **서버 배포**만 (C5). `runnerId`를 주면 그 실행기 것과 전체(`"*"`) 것으로 좁힌다.
 *
 * **`"*"`는 서버 실행기만 쓴다** (ADR-0046) — PC 배포에는 전체 대상이 없다. Center의
 * `GET /deployments?bot_ui=`는 PC 대상만 풀어 주므로(그쪽은 `"*"`가 없다) 서버 쪽은
 * **활성 배포를 한 번 읽어 여기서** 좁힌다 (CON-06이 패키지 종류를 콘솔에서 가리는 것과 같은 결).
 *
 * **종류를 먼저 거르는 것이 요점이다** — 같은 Bot이 PC와 서버에 함께 배포돼 있으면 PC 봉투의
 * 상한을 서버 대기열의 「Bot별 상한 n」으로 보일 수 있다. 대기열은 아직 어느 실행기에도 묶이지
 * 않아(C12) `runnerId` 없이 부른다.
 */
export function serverDeployments(all: DeploymentInfo[], runnerId?: string): DeploymentInfo[] {
  return all.filter(
    (one) =>
      one.target.type === "server_runner" &&
      (runnerId === undefined || one.target.id === runnerId || one.target.id === "*"),
  );
}

/** 지금 그 Bot을 돌리고 있는 실행 수 (C12 `running[]` — **기다리는 실행은 세지 않는다**). */
export function runningOfBot(row: ServerRunnerInfo, bot: string): number {
  return (row.running ?? []).filter((one) => one.bpm_process_id === bot).length;
}

/**
 * 그 Bot의 **동시 실행 상한** — 배포 봉투에 적힌 값이다 (C12 §Center가 작업을 나누는 규칙 3).
 *
 * **적혀 있지 않으면 `null`이다.** 기본값(계약의 `DEFAULT_PER_BOT_CONCURRENCY`)을 여기 베껴
 * 적지 않는다 — 계약 쪽 숫자가 바뀌면 화면만 조용히 거짓말을 한다. 화면은 「기본」이라고 적고
 * 숫자를 지어내지 않는다.
 */
export function perBotLimit(deployments: DeploymentInfo[], bot: string): number | null {
  const found = deployments.find((one) => one.bpm_process_id === bot);
  return found?.max_concurrency ?? null;
}

/**
 * **확장이 없어서** 막힌 점검 코드 (`core.preflight`의 이름 그대로).
 *
 * 이름으로 어림하지 않고 **적어 둔다** — 「extension이 들어간 코드」로 걸렀더니
 * `task_types_unsupported`·`missing_agent_environment`가 빠져 화면이 「확장 없음」 대신
 * 「사전 점검 실행 불가」라고 했다 (운영자가 확장을 깔러 가는 대신 로그를 뒤진다).
 * 코드가 늘면 여기 더한다 — `extension_turned_off`는 **이 묶음이 아니다**(켜면 된다).
 */
const EXTENSION_MISSING_CODES = new Set([
  "task_types_unsupported",
  "extensions_unusable",
  "missing_agent_environment",
]);

/** 준비 상태의 알맹이 — C4·C12의 `Readiness`가 **같은 모양**이라 둘 다 들어온다. */
interface ReadinessLike {
  ready?: boolean;
  missing_key_refs?: string[];
  blocked?: string[];
}

/**
 * 보고된 준비 상태 → `status_map` 「Bot 준비」의 표기와 툴팁 거리 (C4·C12 `Readiness`).
 *
 * 보고가 없으면 **`null`**이다 (「확인 전」이라고 단정하지 않는다 — 모르는 것을 안다고 하지
 * 않는다). 가르는 순서는 BUI-04와 **같고**, **「꺼 뒀다」와 「없다」는 다른 점검이다**
 * ([ADR-0043](../../../../docs/decisions/0043-turned-off-extensions.md)) — 뭉치면 켜면 될 일에
 * 「판을 올리세요」라고 한다. CON-03과 CON-12가 **이 함수 하나**를 쓴다 (베끼면 갈라진다).
 */
export function readinessLabel(
  found: ReadinessLike | undefined,
): { label: string; detail: string[] } | null {
  if (!found) return null;
  if (found.ready) return { label: "준비됨", detail: [] };
  const missing = found.missing_key_refs ?? [];
  if (missing.length > 0) return { label: "서비스 앱 키 없음", detail: missing };
  const blocked = found.blocked ?? [];
  if (blocked.includes("extension_turned_off")) return { label: "확장 꺼짐", detail: blocked };
  if (blocked.some((code) => EXTENSION_MISSING_CODES.has(code)))
    return { label: "확장 없음", detail: blocked };
  return { label: "사전 점검 실행 불가", detail: blocked };
}

/**
 * 그 배포가 이 실행기에서 **돌 준비가 됐는가** — 실행기가 보고한 `readiness`에서 찾는다 (C12).
 *
 * 판은 `version`까지 맞춰 본다 — 다른 판의 보고를 끌어다 쓰면 막 올린 판이 「준비됨」이 된다.
 */
export function runnerReadiness(
  row: ServerRunnerInfo,
  bot: string,
  version: string,
): { label: string; detail: string[] } | null {
  return readinessLabel(
    (row.readiness ?? []).find((one) => one.bpm_process_id === bot && one.version === version),
  );
}

/** CON-12 상세 「Bot별 상한」 한 줄. */
export interface BotLimitRow {
  bot: string;
  version: string;
  /** 배포 봉투에 적힌 상한. **없으면 `null`** — 화면이 「기본」이라고 적는다. */
  limit: number | null;
  running: number;
  readiness: { label: string; detail: string[] } | null;
}

/**
 * 「Bot별 상한」 — **배포가 줄을 정하고**, 실행 수와 준비는 실행기 보고에서 온다.
 *
 * 줄의 출처가 배포인 까닭: 배포됐는데 실행기가 아직 준비 상태를 올리지 않은 Bot이 **보여야
 * 한다** (「배포는 했는데 왜 안 도나」가 이 화면에서 풀려야 한다 — CON-03과 같은 결). 거꾸로
 * `readiness`로 줄을 지으면 그 Bot이 아예 사라진다.
 *
 * 철회된 배포는 부르는 쪽이 `active`로 걸러 온다. 같은 Bot의 판이 둘 이상 살아 있으면 **줄도
 * 둘**이다 (실행기는 판마다 따로 준비 상태를 올린다).
 */
export function botLimitRows(
  row: ServerRunnerInfo,
  deployments: DeploymentInfo[],
): BotLimitRow[] {
  const seen = new Set<string>();
  const out: BotLimitRow[] = [];
  for (const one of deployments) {
    const key = `${one.bpm_process_id}@${one.version}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({
      bot: one.bpm_process_id,
      version: one.version,
      limit: one.max_concurrency ?? null,
      running: runningOfBot(row, one.bpm_process_id),
      readiness: runnerReadiness(row, one.bpm_process_id, one.version),
    });
  }
  return out.sort((a, b) => a.bot.localeCompare(b.bot) || a.version.localeCompare(b.version));
}

/**
 * 「대기 이유」 (CON-12 목록의 대기열 표) — C12 §Center가 작업을 나누는 규칙 3.
 *
 * Center가 사유를 **적는 것은 `per_bot_limit` 하나**다. 사유 없이 남은 작업은 아직 보지도
 * 않은 것이라 「전체 상한」이고, 실행기가 **모두 멈춰 있으면** 빈자리가 0인 까닭이 상한이
 * 아니라 사람이 멈춘 것이므로 그렇게 말한다 (`free_slots`가 `paused`면 0을 준다).
 *
 * 등록된 실행기가 없을 때도 「전체 상한」이다 — 빈자리가 없는 것은 맞고, 실행기가 없다는 말은
 * 바로 위 빈 상태가 한다 (없는 표기를 지어내지 않는다).
 */
export function queueReason(
  job: JobInfo,
  runners: ServerRunnerInfo[],
  deployments: DeploymentInfo[],
): string {
  if (job.state_reason === "per_bot_limit") {
    const limit = perBotLimit(deployments, job.bpm_process_id);
    return limit === null ? "Bot별 상한" : `Bot별 상한 ${limit}`;
  }
  if (job.state_reason) return job.state_reason;
  if (runners.length > 0 && runners.every((one) => one.paused)) return "일시 중지";
  return "전체 상한";
}

/**
 * 「경과」·「기다린 시간」 — 지금과의 차 (CON-12 상세).
 *
 * `now`를 **받는다** — `Date.now()`를 들이면 이 셈을 시험으로 잴 수 없다. 앞으로의 시각(시계
 * 어긋남)은 **0초로 깎는다**(음수를 「-3분」으로 보이면 사람이 버그를 쫓는다).
 */
export function elapsed(since: string | null | undefined, now: number): string {
  if (!since) return "—";
  const at = new Date(since).getTime();
  if (Number.isNaN(at)) return "—";
  const seconds = Math.max(0, Math.floor((now - at) / 1000));
  if (seconds < 60) return `${seconds}초`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}분`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}시간 ${minutes % 60}분`;
  return `${Math.floor(hours / 24)}일 ${hours % 24}시간`;
}
