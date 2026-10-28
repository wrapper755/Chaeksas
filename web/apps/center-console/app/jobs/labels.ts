import type { JobInfo } from "@chaeksas/api-types/c5-job-info";
import type { BotUiInfo } from "@chaeksas/api-types/c5-bot-ui-info";

/**
 * CON-05 작업 지시의 표기 — 목록과 상세가 같이 쓴다.
 *
 * 상태 글은 `status_map` 「작업」 묶음의 것만 쓴다 (스타일 가이드). 모르는 값은 그대로 보인다.
 */

/** C5 작업 상태 → 화면 표기. */
export const STATE_LABEL: Record<string, string> = {
  pending: "대기",
  dispatched: "전달됨",
  queued: "대기열",
  accepted: "수락",
  rejected: "거절",
  expired: "만료",
  cancelled: "취소됨",
};

/** 필터에 보일 순서 (CON-05). */
export const STATES = Object.keys(STATE_LABEL);

/** 거절·대기 사유 → 글 (C5 `state_reason`). */
export const REASON_LABEL: Record<string, string> = {
  queue_full: "대기열 가득",
  no_deployment: "배포 없음",
  not_ready: "준비 안 됨",
  bot_ui_shutdown: "Bot UI 종료",
  bot_ui_lost: "Bot UI 기록 유실",
  server_location: "서버 실행 Bot",
  cancelled_on_pc: "현장에서 취소",
  global_limit: "서버 실행기 빈자리 없음",
  per_bot_limit: "Bot별 동시 실행 상한",
  paused: "일시 중지",
};

/** 취소할 수 있는 상태 (C5 「취소」 표 — 그 밖은 409). */
export const CANCELLABLE = new Set(["pending", "dispatched", "queued"]);

/** PC 위임의 요청자 예약값 (C5 `server_bot:<run_id>`). */
const SERVER_BOT = "server_bot:";

export function time(value: string | null | undefined): string {
  if (!value) return "—";
  const at = new Date(value);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(at.getMonth() + 1)}-${pad(at.getDate())} ${pad(at.getHours())}:${pad(at.getMinutes())}`;
}

/** 실행 위치 — PC / 서버 (C5 `target.type`). */
export function location(job: JobInfo): string {
  return job.target.type === "server_runner" ? "서버" : "PC";
}

/** 대상 — Bot UI 이름, 서버면 「서버」. 이름은 바뀌므로 읽을 때 찾는다. */
export function targetName(job: JobInfo, botUis: BotUiInfo[]): string {
  if (job.target.type === "server_runner") return "서버";
  const id = job.target.id ?? "";
  return botUis.find((one) => one.bot_ui_id === id)?.name ?? id;
}

/** `이름@버전`, 버전을 비웠으면 「(배포된 버전)」 (CON-05). */
export function botLabel(job: JobInfo): string {
  return `${job.bpm_process_id}@${job.version ?? "(배포된 버전)"}`;
}

/** PC 위임이면 그 서버 실행의 id, 아니면 `null`. */
export function delegatedFrom(job: JobInfo): string | null {
  return job.requested_by.startsWith(SERVER_BOT) ? job.requested_by.slice(SERVER_BOT.length) : null;
}

/**
 * 상태 옆에 붙는 한 줄 — 취소의 진행, 대기열 순번 (CON-05).
 *
 * - 취소를 요청했는데 아직 상태가 그대로면 「취소 요청함 — 다음 하트비트에 반영」.
 * - 그사이 시작됐으면 작업은 「수락」 그대로이고 「취소 못 함 — 이미 시작됨」.
 * - 대기열이면 「Bot UI 대기열 N번째 — 실행 중 <Bot>」 (Bot UI가 보고한 지금 실행).
 */
export function stateNote(job: JobInfo, botUis: BotUiInfo[]): string | null {
  if (job.cancel_result === "refused_already_started") return "취소 못 함 — 이미 시작됨";
  if (job.cancel_requested && job.state !== "cancelled") return "취소 요청함 — 다음 하트비트에 반영";
  if (job.state === "queued" && job.queue_position) {
    const host = botUis.find((one) => one.bot_ui_id === job.target.id);
    const running = host?.current_run?.bpm_process_id;
    return `Bot UI 대기열 ${job.queue_position}번째${running ? ` — 실행 중 ${running}` : ""}`;
  }
  return null;
}

export function reason(job: JobInfo): string {
  if (!job.state_reason) return "—";
  return REASON_LABEL[job.state_reason] ?? job.state_reason;
}
