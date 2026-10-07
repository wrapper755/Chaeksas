import "server-only";

import { cookies } from "next/headers";
import type { BotUiInfo } from "@chaeksas/api-types/c5-bot-ui-info";
import type { DeploymentInfo } from "@chaeksas/api-types/c5-deployment-info";
import type { ApprovalInfo } from "@chaeksas/api-types/c6-approval-info";
import type { ServiceAppResource } from "@chaeksas/api-types/c7-service-app-resource";
import type { JobInfo } from "@chaeksas/api-types/c5-job-info";
import type { JobCreateRequest } from "@chaeksas/api-types/c5-job-create-request";
import type { PackageInfo } from "@chaeksas/api-types/c5-package-info";
import type { CenterKeyInfo } from "@chaeksas/api-types/c7-center-key-info";
import type { CenterKeyCreated } from "@chaeksas/api-types/c7-center-key-created";
import type { ErrorBody } from "@chaeksas/api-types/c5-error-body";
import type { RunListing } from "@chaeksas/api-types/c3-run-listing";
import type { RunInfo } from "@chaeksas/api-types/c3-run-info";
import type { RunEventsResponse } from "@chaeksas/api-types/c3-run-events-response";
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

  /** 패키지 목록 (C5). `missing_resources`는 Center가 **읽을 때** 세어 준다 (C7). */
  packages: () => call<PackageInfo[]>("/api/v1/packages"),

  /** 리소스 목록 (C7·CON-07). `{items, fetched_at}` 그대로 돌려준다. */
  resources: <T>(type?: string) =>
    call<{ items: T[]; fetched_at: string }>(`/api/v1/resources${type ? `?type=${type}` : ""}`),
  serviceApp: (appId: string) =>
    call<ServiceAppResource>(`/api/v1/resources/service-apps/${encodeURIComponent(appId)}`),
  registerServiceApp: (baseUrl: string) =>
    call<ServiceAppResource>("/api/v1/resources/service-apps", {
      method: "POST",
      body: JSON.stringify({ base_url: baseUrl }),
    }),
  setServiceAppUrl: (appId: string, baseUrl: string) =>
    call<ServiceAppResource>(`/api/v1/resources/service-apps/${encodeURIComponent(appId)}`, {
      method: "PUT",
      body: JSON.stringify({ base_url: baseUrl }),
    }),
  unregisterServiceApp: (appId: string) =>
    call<void>(`/api/v1/resources/service-apps/${encodeURIComponent(appId)}`, { method: "DELETE" }),
  refreshResources: () =>
    call<unknown>("/api/v1/resources/refresh", { method: "POST", body: JSON.stringify({}) }),

  /** 결재함 (C6·CON-04). */
  approvals: (query: { state?: string; bpm_process_id?: string; host?: string } = {}) => {
    const search = new URLSearchParams(
      Object.entries(query).filter(([, value]) => Boolean(value)) as [string, string][],
    );
    const suffix = search.size > 0 ? `?${search}` : "";
    return call<ApprovalInfo[]>(`/api/v1/approvals${suffix}`);
  },
  approval: (requestId: string) =>
    call<ApprovalInfo>(`/api/v1/approvals/${encodeURIComponent(requestId)}`),
  /** 답하기. 행위자는 BFF가 `X-CHK-Actor`로 싣는다 (C6) — 본문에 없다. */
  answerApproval: (requestId: string, answer: Record<string, unknown>, actor: string) =>
    call<ApprovalInfo>(`/api/v1/approvals/${encodeURIComponent(requestId)}/answer`, {
      method: "POST",
      body: JSON.stringify({ answer }),
      headers: { "X-CHK-Actor": encodeURIComponent(actor) },
    }),
  withdrawApproval: (requestId: string) =>
    call<ApprovalInfo>(`/api/v1/approvals/${encodeURIComponent(requestId)}`, { method: "DELETE" }),

  /** 배포 목록 (C5). `botUi`를 주면 그 PC에 걸린 것만 — `*` 배포도 함께 온다. */
  deployments: (query: { botUi?: string; active?: boolean } = {}) => {
    const search = new URLSearchParams();
    if (query.botUi) search.set("bot_ui", query.botUi);
    if (query.active !== undefined) search.set("active", String(query.active));
    const suffix = search.size > 0 ? `?${search}` : "";
    return call<DeploymentInfo[]>(`/api/v1/deployments${suffix}`);
  },

  /** 작업 지시 (C5·CON-05). `state`는 쉼표로 여럿. */
  jobs: (query: { state?: string; target_id?: string; limit?: number } = {}) => {
    const search = new URLSearchParams(
      Object.entries(query)
        .filter(([, value]) => value !== undefined && value !== "")
        .map(([key, value]) => [key, String(value)]),
    );
    const suffix = search.size > 0 ? `?${search}` : "";
    return call<JobInfo[]>(`/api/v1/jobs${suffix}`);
  },
  job: (jobId: string) => call<JobInfo>(`/api/v1/jobs/${encodeURIComponent(jobId)}`),
  /** 만들기. 요청자는 BFF가 `X-CHK-Actor`로 싣는다 (C5 — 본문에 없다). */
  createJob: (body: JobCreateRequest) =>
    call<JobInfo>("/api/v1/jobs", { method: "POST", body: JSON.stringify(body) }),
  /** 취소. 200이면 끝, 202면 `cancel_requested` — 현장의 다음 하트비트를 기다린다 (C5). */
  cancelJob: (jobId: string) =>
    call<JobInfo>(`/api/v1/jobs/${encodeURIComponent(jobId)}`, { method: "DELETE" }),
  /** 패키지 정보 — 매니페스트의 `inputs`로 「새 작업」의 입력 칸을 그린다 (C1). */
  packageInfo: (packageId: string, version: string) =>
    call<PackageInfo>(
      `/api/v1/packages/${encodeURIComponent(packageId)}/${encodeURIComponent(version)}/info`,
    ),

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

  runs: (query: { status?: string; bpm_process_id?: string; limit?: number } = {}) => {
    const search = new URLSearchParams(
      Object.entries(query)
        .filter(([, value]) => value !== undefined && value !== "")
        .map(([key, value]) => [key, String(value)]),
    );
    const suffix = search.size > 0 ? `?${search}` : "";
    return call<RunListing>(`/api/v1/runs${suffix}`);
  },
  run: (runId: string) => call<RunInfo>(`/api/v1/runs/${encodeURIComponent(runId)}`),
  runEvents: (runId: string) =>
    call<RunEventsResponse>(`/api/v1/runs/${encodeURIComponent(runId)}/events`),

  /** 토큰이 쓸 수 있는지 본다 (로그인에서 쓴다). 읽기 경로 하나를 불러 확인한다. */
  check: () => call<CenterKeyInfo[]>("/api/v1/center-keys"),
};
