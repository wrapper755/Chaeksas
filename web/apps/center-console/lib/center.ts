import "server-only";

import { cookies } from "next/headers";
import type { BotUiInfo } from "@chaeksas/api-types/c5-bot-ui-info";
import type { CenterKeyInfo } from "@chaeksas/api-types/c7-center-key-info";
import type { CenterKeyCreated } from "@chaeksas/api-types/c7-center-key-created";
import type { ErrorBody } from "@chaeksas/api-types/c5-error-body";
import { COOKIE_NAME, open, type Session } from "./session";

/**
 * BFF — **브라우저는 Center API를 직접 부르지 않는다** (ADR-0017 §1).
 *
 * 콘솔 서버가 세션 쿠키에서 토큰을 꺼내 들고 부른다. 토큰은 응답에 섞여 나가지 않는다.
 * 타입은 계약 JSON Schema에서 생성한 것만 쓴다 (손으로 쓰지 않는다).
 */

export const CENTER_URL = process.env.CHK_CONSOLE__CENTER_URL ?? "http://localhost:8800";

export class CenterError extends Error {
  constructor(
    readonly status: number,
    readonly body: ErrorBody | null,
    message: string,
  ) {
    super(message);
  }
}

export async function session(): Promise<Session | null> {
  const store = await cookies();
  return open(store.get(COOKIE_NAME)?.value);
}

async function call<T>(path: string, init?: RequestInit & { actor?: string }): Promise<T> {
  const found = await session();
  if (!found) throw new CenterError(401, null, "로그인이 필요합니다");

  const response = await fetch(`${CENTER_URL}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${found.token}`,
      // 행위자 이름은 BFF가 싣는다 (C5 — 본문에서 받지 않는다).
      // **퍼센트 인코딩해서** 넣는다: HTTP 헤더 값은 ASCII라서 한글 이름을 그대로 실으면
      // 요청 자체가 나가지 않는다 (undici가 거부한다).
      "X-CHK-Actor": encodeURIComponent(found.actor),
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
    // 콘솔은 늘 지금 상태를 보여 준다 (「새로 고침」이 그 뜻이다).
    cache: "no-store",
  }).catch(() => {
    // 「무엇이 + 왜 + 무엇을 하면 되는지」 (스타일 가이드 §5).
    throw new CenterError(0, null, `Center에 닿지 못했습니다 (${CENTER_URL}) — 주소와 포트를 확인하세요`);
  });

  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as ErrorBody | null;
    throw new CenterError(response.status, body, body?.message ?? `Center가 ${response.status}를 돌려줬습니다`);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const center = {
  botUis: () => call<BotUiInfo[]>("/api/v1/bot-uis"),
  disableBotUi: (id: string) => call<unknown>(`/api/v1/bot-uis/${id}/disable`, { method: "POST" }),
  enableBotUi: (id: string) => call<unknown>(`/api/v1/bot-uis/${id}/enable`, { method: "POST" }),

  centerKeys: (query: { type?: string; state?: string } = {}) => {
    const search = new URLSearchParams(
      Object.entries(query).filter(([, value]) => Boolean(value)) as [string, string][],
    );
    const suffix = search.size > 0 ? `?${search}` : "";
    return call<CenterKeyInfo[]>(`/api/v1/center-keys${suffix}`);
  },
  createCenterKey: (body: { name: string; type: string; expires_at?: string }) =>
    call<CenterKeyCreated>("/api/v1/center-keys", { method: "POST", body: JSON.stringify(body) }),
  revokeCenterKey: (keyId: string) => call<CenterKeyInfo>(`/api/v1/center-keys/${keyId}`, { method: "DELETE" }),
  unbindCenterKey: (keyId: string) =>
    call<CenterKeyInfo>(`/api/v1/center-keys/${keyId}/unbind`, { method: "POST" }),

  /** 토큰이 쓸 수 있는지 본다 (로그인에서 쓴다). 읽기 경로 하나를 불러 확인한다. */
  check: () => call<CenterKeyInfo[]>("/api/v1/center-keys"),
};
