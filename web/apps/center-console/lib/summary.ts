/** CON-02가 세는 일 — **화면을 모르는 자리**다 (`page.tsx`는 이것을 그릴 뿐이다).
 *
 * 여기 있는 것은 전부 **순수 함수**다: 서버 호출(`lib/center.ts`)도, JSX도, `next/*`도 들이지
 * 않는다. 갈라 둔 까닭은 **셈을 시험으로 재려고**다 — 페이지 모듈은 `server-only`를 끌고 와
 * 단위 시험에서 불러올 수 없다 (파이썬 쪽에서 「Qt를 모르는 함수」를 갈라 두는 것과 같은 결).
 *
 * 세는 규칙은 C3 요약에서 온다. **끝난 실행만**, **버전마다 최근 20회만**, 확인률은 **그 칸을
 * 보낸 실행만** 분모에 넣는다.
 */

import type { DeploymentInfo } from "@chaeksas/api-types/c5-deployment-info";
import type { PackageInfo } from "@chaeksas/api-types/c5-package-info";
import type { RunInfo } from "@chaeksas/api-types/c3-run-info";

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
