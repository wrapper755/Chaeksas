import type { EnrollmentInfo } from "@chaeksas/api-types/c5-enrollment-info";
import type { CenterKeyInfo } from "@chaeksas/api-types/c7-center-key-info";
import type { DeploymentResult } from "@chaeksas/api-types/c5-bot-ui-info";

/**
 * CON-16 앱 로그 — Center가 이미 들고 있는 것(등록 요청·키·배치 결정)을 **읽어 합친다** (ADR-0121).
 *
 * 새로 쌓지 않는다 — 집계를 따로 두면 낡는다(CON-02의 셈과 같은 결). 화면을 모르는 함수라
 * vitest가 잰다 (`app-logs.test.ts`).
 */

/** 앱 종류 — 등록 요청·키의 `type` 값. 일꾼(`consumer`)은 앱이 아니라 넣지 않는다. */
export type AppKind = "studio" | "bot_ui" | "server_runner";
export const APP_KINDS: AppKind[] = ["studio", "bot_ui", "server_runner"];
export const APP_LABEL: Record<AppKind, string> = { studio: "Studio", bot_ui: "Bot", server_runner: "서버 실행기" };

/** 들이기 비밀로 받는 자리에서 승인된 요청의 「누가」 (ADR-0117 — Center `JOIN_TOKEN_ACTOR`). */
const JOIN_TOKEN_ACTOR = "join_token";

/** 배치 결정 사유 코드 → 글 (C2 위반 코드). 모르는 값은 **그대로 보인다** (원칙 10). */
export const DEPLOYMENT_REASON: Record<string, string> = {
  bad_signature: "서명이 맞지 않음",
  unknown_key: "모르는 서명 키",
  revoked_key: "서명 키 철회됨",
  wrong_kind: "봉투 종류가 다름",
  expired: "유효 기간 지남",
  not_yet: "아직 시작 전",
  wrong_target: "다른 대상용",
  hash_mismatch: "패키지 내용이 다름",
  unsigned_package: "승인 서명 없음",
  unsupported_alg: "모르는 서명 방식",
  float_in_payload: "봉투에 소수가 들어 있음",
};

export interface AppLogRow {
  at: string;
  kind: AppKind;
  name: string;
  what: string;
  detail: string;
  who: string;
}

/** 배치 결정을 올린 앱 하나 — Bot(C4)·서버 실행기(C12)가 같은 모양이다. */
export interface ReportingHost {
  kind: AppKind;
  name: string;
  results: DeploymentResult[];
}

function isApp(type: string): type is AppKind {
  return (APP_KINDS as string[]).includes(type);
}

export function buildAppLog(input: {
  enrollments: EnrollmentInfo[];
  keys: CenterKeyInfo[];
  hosts: ReportingHost[];
}): AppLogRow[] {
  const rows: AppLogRow[] = [];
  for (const one of input.enrollments) {
    if (!isApp(one.type)) continue;
    const base = { kind: one.type, name: one.name };
    rows.push({
      ...base,
      at: one.requested_at,
      what: "등록 요청",
      // 결정 없이 닫힌 요청은 **닫힌 때를 모른다** — 기한이 지났거나 같은 기계가 다시 요청해 닫혔다.
      // 기한(`expires_at`)을 시각으로 쓰면 미래 시각에 「만료」가 찍힌다. 그래서 요청 줄에 붙인다.
      detail: `요청 코드 ${one.code}${one.remote_addr ? ` · ${one.remote_addr}` : ""}${
        !one.decided_at && one.state === "expired" ? " · 결정 없이 닫힘" : ""
      }`,
      who: "—",
    });
    if (one.decided_at && (one.state === "approved" || one.state === "expired")) {
      const auto = one.decided_by === JOIN_TOKEN_ACTOR;
      rows.push({
        ...base,
        at: one.decided_at,
        what: auto ? "자동 승인" : "승인",
        detail: auto ? "들이기 비밀" : "",
        who: auto ? "—" : (one.decided_by ?? "—"),
      });
    } else if (one.decided_at && one.state === "rejected") {
      rows.push({ ...base, at: one.decided_at, what: "거절", detail: one.reason ?? "", who: one.decided_by ?? "—" });
    }
  }
  for (const key of input.keys) {
    if (!isApp(key.type)) continue;
    const base = { kind: key.type, name: key.name, who: "—" };
    rows.push({ ...base, at: key.created_at, what: "키 발급", detail: `${key.prefix}…` });
    if (key.revoked_at) rows.push({ ...base, at: key.revoked_at, what: "키 폐기", detail: `${key.prefix}…` });
  }
  for (const host of input.hosts) {
    for (const result of host.results) {
      const reason = result.reason ? ` — ${DEPLOYMENT_REASON[result.reason] ?? result.reason}` : "";
      rows.push({
        kind: host.kind,
        name: host.name,
        at: result.at,
        what: result.result === "applied" ? "설치 적용" : result.result === "rejected" ? "설치 거부" : `설치 ${result.result}`,
        detail: `${result.bpm_process_id}@${result.version}${reason}`,
        who: "—",
      });
    }
  }
  // 새 것이 위다. 시각이 같으면 넣은 차례(요청 → 결정 → 키)를 거꾸로 — 위에서 아래로 읽으면 일이 거슬러 간다.
  return rows
    .map((row, index) => ({ row, index }))
    .sort((a, b) => (a.row.at === b.row.at ? b.index - a.index : a.row.at < b.row.at ? 1 : -1))
    .map(({ row }) => row);
}
