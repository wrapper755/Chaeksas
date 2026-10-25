/**
 * CON-11 줄마다의 동작 — **그 줄의 키에** 할 수 있는 것만 낸다 (화면 문서 CON-11 「키 목록」 끝 칸).
 *
 * 화면을 모르는 함수라 vitest가 잰다. 판정은 Center도 한다(폐기된 키는 다시 폐기되지 않는다) —
 * 여기는 「보이지 않을 단추를 보이지 않게」 하는 자리다.
 */
import type { CenterKeyInfo } from "@chaeksas/api-types/c7-center-key-info";

export type KeyAction = "revoke" | "unbind";

export interface KeyActions {
  /** 펼치면 보일 것, 이 차례로. */
  actions: KeyAction[];
  /** `actions`가 비었을 때 「...」를 끄는 까닭 (툴팁). */
  reason: string | null;
}

export function keyActions(row: Pick<CenterKeyInfo, "state" | "bound_to" | "enrollment_id">): KeyActions {
  if (row.state === "revoked") return { actions: [], reason: "폐기된 키입니다." };
  if (row.state !== "active") return { actions: [], reason: "만료된 키입니다. 할 수 있는 일이 없습니다." };
  const actions: KeyAction[] = ["revoke"];
  // 승인이 만든 키에는 「묶음 풀기」가 없다 — 다시 설치한 PC는 새 등록 요청을 승인하면 이어받는다 (ADR-0092).
  if (row.bound_to && !row.enrollment_id) actions.push("unbind");
  return { actions, reason: null };
}
