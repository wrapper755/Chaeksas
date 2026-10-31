import type { DeploymentInfo } from "@chaeksas/api-types/c5-deployment-info";
import type { JobInfo } from "@chaeksas/api-types/c5-job-info";

/**
 * CON-05 작업 지시의 판단 — 「새 작업」이 어디에 보낼지, 「취소」·「중지」를 보일지.
 *
 * 화면을 모르는 함수만 둔다 (vitest `jobs.test.ts`). 페이지는 `server-only`를 끌고 와 단위
 * 시험에서 부를 수 없다.
 */

/**
 * 그 BPM 프로세스가 서버 실행인가 — **서버 실행기에 배포돼 있으면** 그렇다.
 *
 * 실행 위치는 그림이 하나로 정하므로(C1 `run_location`) 한 BPM 프로세스의 배포가 PC와 서버에
 * 섞이지 않는다. 배포를 읽는 것은 Center가 작업을 받을 때 보는 것과 같은 재료라서다.
 */
export function runsOnServer(deployments: DeploymentInfo[], bot: string): boolean {
  return deployments.some((one) => one.bpm_process_id === bot && one.target.type === "server_runner");
}

/**
 * 서버 BPM 프로세스의 배포된 판들 — **어느 실행기든** 배포돼 있으면 센다.
 *
 * 콘솔은 실행기를 고르지 않는다(`target.id = "*"` — 빈자리가 있는 쪽에 Center가 보낸다, C5
 * `JobTarget`). 그래서 Center도 「어디든 배포돼 있나」를 묻고(`server_versions`) 판이 둘
 * 이상이면 `version_ambiguous`다.
 */
export function serverVersions(deployments: DeploymentInfo[], bot: string): string[] {
  const found = deployments
    .filter((one) => one.bpm_process_id === bot && one.target.type === "server_runner")
    .map((one) => one.version);
  return [...new Set(found)].sort();
}

/**
 * 「동시 실행 상한 <n>」의 <n> — 그 판 배포의 `max_concurrency` (C12 §작업을 나누는 규칙 3).
 *
 * 적지 않은 상한은 **「기본」**이다 (CON-12와 같다 — 계약의 기본값을 화면에 베끼지 않는다).
 * 같은 판의 배포가 실행기마다 다른 상한을 가지면 **모두** 보인다 (하나를 골라 말하면 거짓이다).
 */
export function serverLimit(deployments: DeploymentInfo[], bot: string, version: string): string {
  const limits = deployments
    .filter(
      (one) =>
        one.bpm_process_id === bot && one.target.type === "server_runner" && one.version === version,
    )
    .map((one) => (one.max_concurrency == null ? "기본" : String(one.max_concurrency)));
  const distinct = [...new Set(limits)];
  return distinct.length === 0 ? "기본" : distinct.join(" / ");
}

/**
 * 작업 줄에 붙는 단추 (CON-05 「취소」 표, ADR-0063).
 *
 * - `cancel` — 대기·전달됨·대기열. 「취소」.
 * - `stop` — **도는 서버 실행**(`accepted` + 서버 대상). 「중지...」 → 확인 창.
 * - `pc_running` — 도는 PC 실행. 단추를 **끄고 까닭을 적는다** (Center도 409로 거절한다 —
 *   화면을 만지는 중일 수 있어 현장 사람만 멈춘다, ADR-0014).
 * - `null` — 단추 없음 (끝났거나, 이미 요청했다).
 *
 * 이미 요청한 것(`cancel_requested`)은 다시 보이지 않는다 — 상태 옆 글이 진행을 말한다.
 */
export type CancelControl = "cancel" | "stop" | "pc_running" | null;

const CANCELLABLE = new Set(["pending", "dispatched", "queued"]);

export function cancelControl(job: Pick<JobInfo, "state" | "target" | "cancel_requested">): CancelControl {
  if (job.cancel_requested) return null;
  if (CANCELLABLE.has(job.state)) return "cancel";
  if (job.state === "accepted") return job.target.type === "server_runner" ? "stop" : "pc_running";
  return null;
}

/** 확인 창의 글 (CON-05 — 화면 문서의 문구 그대로). */
export const STOP_CONFIRM = "도는 실행을 멈춥니다. 한 일은 되돌리지 않습니다 — 이미 보낸 메일·웹훅은 그대로입니다.";

/** 도는 PC 실행의 단추를 끈 까닭 (CON-05). */
export const PC_RUNNING_REASON = "실행 중인 PC 프로세스는 현장에서 멈춥니다 (PC 실행기 「중지」)";
