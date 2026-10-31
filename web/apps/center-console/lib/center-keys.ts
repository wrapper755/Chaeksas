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

/** 종류 표기 — 「콘솔에서 발급한 연동 키」 표의 「종류」 열. */
export const TYPE_LABEL: Record<string, string> = {
  integration: "연동용",
  relay: "대리 답용",
};

/** 일꾼 폴더 줄의 키 종류 — 일꾼 줄은 일꾼용, 키 줄은 연동용·대리 답용 (ADR-0122·0123). */
const FOLDER_TYPES: Record<string, string[]> = {
  consumer: ["consumer"],
  key: ["integration", "relay"],
};

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
 * 일꾼 폴더의 줄(`kind`·`id`)이 가리키는 키 (CON-07, ADR-0124 §2) — **이름·종류·앞자리 없음**으로 잇는다.
 * 폴더 키는 원문을 몰라 앞자리가 비어 있다. 거둔 확장 줄처럼 키가 없는 줄은 `null`.
 */
export function folderKey<T extends Pick<CenterKeyInfo, "name" | "type" | "prefix" | "state" | "created_at">>(
  item: { kind?: string; id?: string | null },
  keys: T[],
): T | null {
  // `kind`가 없으면 일꾼 줄이다 (C7 `ConsumerFolderItem.kind`의 기본값).
  const types = FOLDER_TYPES[item.kind ?? "consumer"];
  if (!types || !item.id) return null;
  return currentKey(keys.filter((key) => key.name === item.id && types.includes(key.type) && !key.prefix));
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

/**
 * 「콘솔에서 발급한 연동 키」 — 연동용·대리 답용인데 앞자리가 있는 것 (ADR-0123 전에 CON-11이 발급했다).
 * 있을 때만 보인다 — 사라지면 끊을 길이 없다 (ADR-0124 §3).
 */
export function consoleIssuedKeys<T extends Pick<CenterKeyInfo, "type" | "prefix">>(keys: T[]): T[] {
  return keys.filter((key) => Object.hasOwn(TYPE_LABEL, key.type) && Boolean(key.prefix));
}

/** 상태 표기 — `status_map`의 「API 키」 묶음과 같은 글이다. */
export const STATE_LABEL: Record<string, string> = {
  active: "사용 중",
  expired: "만료",
  revoked: "폐기됨",
};
