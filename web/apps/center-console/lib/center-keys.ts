/**
 * 키 줄마다의 동작 — **그 줄의 키에** 할 수 있는 것만 낸다 (화면 문서 CON-11 「키 동작」 — 동작은 그 키가 가리키는 화면에 있다, ADR-0124).
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

/**
 * 키 여럿에서 **그 대상의 지금 키** 하나를 고른다 — 사용 중인 것, 없으면 가장 최근에 만든 것.
 * 폴더 파일이 바뀔 때마다 옛 키가 폐기된 채 남아 같은 이름이 여럿이다 (ADR-0123).
 */
export function currentKey<T extends Pick<CenterKeyInfo, "state" | "created_at">>(rows: T[]): T | null {
  const active = rows.find((row) => row.state === "active");
  if (active) return active;
  return rows.reduce<T | null>((best, row) => (!best || row.created_at > best.created_at ? row : best), null);
}

/**
 * Bot·서버 실행기가 보고에 싣는 키 앞자리로 그 키를 찾는다 (CON-03·CON-12 상세의 「API 키」).
 * 묶인 대상의 id는 기계 id라 화면의 id와 다르다 — 앞자리(16자)로 잇는다.
 */
export function keyByPrefix<T extends Pick<CenterKeyInfo, "type" | "prefix" | "state" | "created_at">>(
  keys: T[],
  type: string,
  prefix: string | null | undefined,
): T | null {
  if (!prefix) return null;
  return currentKey(keys.filter((key) => key.type === type && key.prefix === prefix));
}

/** 상태 표기 — `status_map`의 「API 키」 묶음과 같은 글이다. */
export const STATE_LABEL: Record<string, string> = {
  active: "사용 중",
  expired: "만료",
  revoked: "폐기됨",
};
