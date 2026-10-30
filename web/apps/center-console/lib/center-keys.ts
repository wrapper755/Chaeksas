/**
 * CON-11 줄마다의 동작 — **그 줄의 키에** 할 수 있는 것만 낸다 (화면 문서 CON-11 「키 목록」 끝 칸).
 *
 * 화면을 모르는 함수라 vitest가 잰다. 판정은 Center도 한다(폐기되지 않은 키는 409 `not_revoked`) —
 * 여기는 「할 수 없는 일을 보이지 않게」 하는 자리다. 어느 줄이든 할 일이 하나는 있다.
 */
import type { CenterKeyInfo } from "@chaeksas/api-types/c7-center-key-info";

export type KeyAction = "revoke" | "unbind" | "delete";

export interface KeyActions {
  /** 펼치면 보일 것, 이 차례로. */
  actions: KeyAction[];
}

export function keyActions(row: Pick<CenterKeyInfo, "state" | "bound_to" | "enrollment_id">): KeyActions {
  // 폐기된 키는 되살리지 않는다 — 남은 일은 목록에서 지우는 것뿐이다 (ADR-0095: 폐기 → 삭제).
  if (row.state === "revoked") return { actions: ["delete"] };
  // 만료된 키도 지우려면 먼저 폐기한다 — Center가 폐기된 키만 지운다.
  if (row.state !== "active") return { actions: ["revoke"] };
  const actions: KeyAction[] = ["revoke"];
  // 승인이 만든 키에는 「묶음 풀기」가 없다 — 다시 설치한 PC는 새 등록 요청을 승인하면 이어받는다 (ADR-0092).
  if (row.bound_to && !row.enrollment_id) actions.push("unbind");
  return { actions };
}

/** 승인이 만드는 종류 (ADR-0092·0093, 일꾼은 C15) — CON-11 「승인으로 들인 키」 표. */
const ENROLLED_TYPES = new Set(["bot_ui", "studio", "server_runner", "consumer"]);

/**
 * CON-11의 두 표로 가른다 — 「연동 키」(「새 키...」가 만드는 것)와 「승인으로 들인 키」.
 * **종류로 가른다**(자동화로 발급한 PC 실행기용 키도 아래로 간다). 모르는 종류는 위로 — 사라지지 않게.
 */
export function splitKeys<T extends Pick<CenterKeyInfo, "type">>(rows: T[]): { integration: T[]; enrolled: T[] } {
  const integration: T[] = [];
  const enrolled: T[] = [];
  for (const row of rows) (ENROLLED_TYPES.has(row.type) ? enrolled : integration).push(row);
  return { integration, enrolled };
}
