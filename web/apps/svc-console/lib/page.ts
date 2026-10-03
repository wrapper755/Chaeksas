import "server-only";

import type { AdminStatus } from "@chaeksas/api-types/c11-admin-status";
import { APP_URL, SvcError, svc, session } from "./svc";
import type { Session } from "./session";

/**
 * 모든 화면이 같은 것을 먼저 한다: 세션 확인 + 위 막대에 쓸 `/admin/v1/status` 읽기.
 *
 * 상태를 못 읽어도 **화면은 그린다** (「응답 없음」으로 보이고 본문에 오류를 적는다) — 앱이
 * 잠깐 멈췄을 때 콘솔까지 하얗게 되면 무엇이 문제인지 알 수 없다.
 */
export interface Loaded {
  session: Session;
  status: AdminStatus | null;
  failure: string | null;
}

export function reason(cause: unknown): string {
  return cause instanceof SvcError ? cause.message : "알 수 없는 오류가 생겼습니다";
}

export async function load(): Promise<Loaded | null> {
  const found = await session();
  if (!found) return null;
  try {
    return { session: found, status: await svc.status(), failure: null };
  } catch (cause) {
    return { session: found, status: null, failure: reason(cause) };
  }
}

export { APP_URL, svc };
