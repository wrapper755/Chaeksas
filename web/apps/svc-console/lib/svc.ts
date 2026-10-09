import "server-only";

import { cookies } from "next/headers";
import type { AdminStatus } from "@chaeksas/api-types/c11-admin-status";
import type { AdminKeyCreated } from "@chaeksas/api-types/c11-admin-key-created";
import type { AdminKeyInfo } from "@chaeksas/api-types/c11-admin-key-info";
import type { UsagePage } from "@chaeksas/api-types/c11-usage-page";
import type { ConsoleOverview } from "@chaeksas/api-types/c9-console-overview";
import type { PageListing } from "@chaeksas/api-types/c9-page-listing";
import type { PageDetail } from "@chaeksas/api-types/c9-page-detail";
import type { PathResult } from "@chaeksas/api-types/c9-path-result";
import type { SessionPage } from "@chaeksas/api-types/c9-session-page";
import type { ErrorBody } from "@chaeksas/api-types/c5-error-body";
import { COOKIE_NAME, open, type Session } from "./session";

/**
 * BFF — **브라우저는 서비스 앱의 관리 API를 직접 부르지 않는다** (ADR-0017 §1).
 *
 * 콘솔 한 벌이 모든 서비스 앱의 콘솔을 그린다. 어느 앱을 보는지는 **설정**(`CHK_SVC_CONSOLE__APP_URL`)으로
 * 정하고, 앱 이름·버전·고유 메뉴는 `/admin/v1/status`의 `app_id`에서 온다 (화면 설계서 SVC-00).
 * 타입은 계약 JSON Schema에서 생성한 것만 쓴다 (손으로 쓰지 않는다).
 */

export const APP_URL = process.env.CHK_SVC_CONSOLE__APP_URL ?? "http://localhost:8000";

export class SvcError extends Error {
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

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const found = await session();
  if (!found) throw new SvcError(401, null, "로그인이 필요합니다");

  const response = await fetch(`${APP_URL}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${found.token}`,
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
    // 콘솔은 늘 지금 상태를 보여 준다 (「새로 고침」이 그 뜻이다).
    cache: "no-store",
  }).catch(() => {
    // 「무엇이 + 왜 + 무엇을 하면 되는지」 (스타일 가이드 §5).
    throw new SvcError(0, null, `서비스 앱에 닿지 못했습니다 (${APP_URL}) — 주소와 포트를 확인하세요`);
  });

  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as ErrorBody | null;
    if (response.status === 503 && body?.code === "admin_disabled") {
      throw new SvcError(503, body, "이 앱은 관리 API가 꺼져 있습니다 — 앱 설정에 관리자 토큰을 넣으세요");
    }
    throw new SvcError(response.status, body, body?.message ?? `서비스 앱이 ${response.status}를 돌려줬습니다`);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export interface KeyCreateInput {
  name: string;
  allowed_operations: string[];
  allowed_modes: string[];
  extra_scopes: string[];
  expires_at?: string;
  note?: string;
}

export const svc = {
  status: () => call<AdminStatus>("/admin/v1/status"),
  keys: () => call<AdminKeyInfo[]>("/admin/v1/keys"),
  createKey: (body: KeyCreateInput) =>
    call<AdminKeyCreated>("/admin/v1/keys", { method: "POST", body: JSON.stringify(body) }),
  // 이름에 한글·공백이 올 수 있다 — 경로에 넣기 전에 인코딩한다.
  revokeKey: (name: string) => call<AdminKeyInfo>(`/admin/v1/keys/${encodeURIComponent(name)}`, { method: "DELETE" }),
  usage: (limit = 100) => call<UsagePage>(`/admin/v1/usage?limit=${limit}`),
  // 앱 고유 관리 경로 (확장이 기여한 화면이 읽는다 — C9 §관리 콘솔이 읽는 길).
  // 모든 앱에 있는 길이 아니다: 그 확장의 화면에서만 부른다 (`console.pages`, ADR-0042).
  uiAutomationOverview: () => call<ConsoleOverview>("/admin/v1/overview"),
  uiAutomationPages: () => call<PageListing>("/admin/v1/pages"),
  // 화면 id에 점·하이픈이 오고(C9) 경로에 들어가므로 인코딩한다.
  uiAutomationPage: (pageId: string) => call<PageDetail>(`/admin/v1/pages/${encodeURIComponent(pageId)}`),
  uiAutomationPath: (start: string, goal: string) =>
    call<PathResult>(`/admin/v1/path?start=${encodeURIComponent(start)}&goal=${encodeURIComponent(goal)}`),
  uiAutomationSessions: (limit = 100) => call<SessionPage>(`/admin/v1/sessions?limit=${limit}`),
};
