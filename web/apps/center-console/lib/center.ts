import "server-only";

import { cookies } from "next/headers";
import type { BotUiInfo } from "@chaeksas/api-types/c5-bot-ui-info";
import type { DeploymentInfo } from "@chaeksas/api-types/c5-deployment-info";
import type { ApprovalInfo } from "@chaeksas/api-types/c6-approval-info";
import type { ServerRunnerInfo } from "@chaeksas/api-types/c12-server-runner-info";
import type { ServiceAppResource } from "@chaeksas/api-types/c7-service-app-resource";
import type { ExtensionResource } from "@chaeksas/api-types/c7-extension-resource";
import type { ContributedResource } from "@chaeksas/api-types/c7-contributed-resource";

/**
 * 기여 자원 **종류** 한 줄 (CON-07 탭). Center가 계약 모델 없이 짓는 모양이라 여기 적는다 —
 * C7은 자원 자체(`ContributedResource`)만 정하고, 「어떤 탭이 있나」는 화면의 일이다.
 */
export interface ContributedKind {
  resource_type: string;
  label: string;
  count: number;
  extensions: string[];
  errors: string[];
}
import type { JobInfo } from "@chaeksas/api-types/c5-job-info";
import type { VirtualWorkerInfo } from "@chaeksas/api-types/c5-virtual-worker-info";
import type { VirtualWorkerRequest } from "@chaeksas/api-types/c5-virtual-worker-request";
import type { JobCreateRequest } from "@chaeksas/api-types/c5-job-create-request";
import type { PackageInfo } from "@chaeksas/api-types/c5-package-info";
import type { DependentInfo } from "@chaeksas/api-types/c5-dependent-info";
import type { CenterKeyInfo } from "@chaeksas/api-types/c7-center-key-info";
import type { EnrollmentInfo } from "@chaeksas/api-types/c5-enrollment-info";
import type { EnrollmentDecision } from "@chaeksas/api-types/c5-enrollment-decision";
import type { ConsumerInfo } from "@chaeksas/api-types/c15-consumer-info";
import type { TopicStatus } from "@chaeksas/api-types/c15-topic-status";
import type { ExternalTaskInfo } from "@chaeksas/api-types/c15-external-task-info";
import type { ScheduleInfo } from "@chaeksas/api-types/c5-schedule-info";
import type { CenterKeyCreated } from "@chaeksas/api-types/c7-center-key-created";
import type { ErrorBody } from "@chaeksas/api-types/c5-error-body";
import type { RunListing } from "@chaeksas/api-types/c3-run-listing";
import type { RunInfo } from "@chaeksas/api-types/c3-run-info";
import type { RunEventsResponse } from "@chaeksas/api-types/c3-run-events-response";
import type { AccountInfo } from "@chaeksas/api-types/c5-account-info";
import type { DeploymentRequest } from "@chaeksas/api-types/c5-deployment-request";
import type { SessionInfo } from "@chaeksas/api-types/c5-session-info";
import { COOKIE_NAME, open, type Session } from "./session";

/**
 * BFF — **브라우저는 Center API를 직접 부르지 않는다** (ADR-0017 §1).
 *
 * 콘솔 서버가 세션 쿠키에서 토큰을 꺼내 들고 부른다. 토큰은 응답에 섞여 나가지 않는다.
 * 타입은 계약 JSON Schema에서 생성한 것만 쓴다 (손으로 쓰지 않는다).
 */

export const CENTER_URL = process.env.CHK_CONSOLE__CENTER_URL ?? "http://localhost:8800";

/** 위 막대에 보일 주소 — 사람이 PC 실행기·Studio에 적는 바깥 주소다. 콘솔이 부르는 주소는 컨테이너 이름일 수 있다. */
export const CENTER_PUBLIC_URL = process.env.CHK_CONSOLE__CENTER_PUBLIC_URL || CENTER_URL;

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

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const found = await session();
  if (!found) throw new CenterError(401, null, "로그인이 필요합니다");
  return send<T>(path, init, found.token);
}

/**
 * Center 한 번. 행위자는 **세션이 정한다** (ADR-0090) — Center가 세션 토큰에서 계정 아이디를
 * 읽으므로 `X-CHK-Actor`를 싣지 않는다.
 */
async function send<T>(path: string, init: RequestInit | undefined, token: string | null): Promise<T> {
  const response = await fetch(`${CENTER_URL}${path}`, {
    ...init,
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
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

/** 로그인 (C5 `POST /auth/login`). 세션 토큰은 이 응답에만 실린다 — 받은 쪽이 쿠키에 담는다. */
export function signIn(username: string, password: string): Promise<SessionInfo> {
  return send<SessionInfo>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  }, null);
}

/** 로그아웃 — Center의 세션을 지운다. 닿지 못해도 쿠키는 부르는 쪽이 지운다. */
export function signOut(token: string): Promise<void> {
  return send<void>("/api/v1/auth/logout", { method: "POST" }, token);
}

const pkg = (packageId: string, version: string) =>
  `/api/v1/packages/${encodeURIComponent(packageId)}/${encodeURIComponent(version)}`;

export const center = {
  botUis: () => call<BotUiInfo[]>("/api/v1/bot-uis"),
  disableBotUi: (id: string) => call<unknown>(`/api/v1/bot-uis/${id}/disable`, { method: "POST" }),
  enableBotUi: (id: string) => call<unknown>(`/api/v1/bot-uis/${id}/enable`, { method: "POST" }),

  /**
   * 서버 실행기 목록 (C12·CON-12). **목록 하나가 상세의 재료까지 들고 온다** — 실행 중·기다리는
   * 실행·준비 상태·확장·최근 배치 결정이 모두 한 줄에 있어 상세가 따로 부를 길이 없다.
   *
   * `queued`는 **Center가 센 것**이다 (실행기가 보내는 값이 아니다 — 대기열은 Center가 가진다).
   */
  serverRunners: () => call<ServerRunnerInfo[]>("/api/v1/server-runners"),
  /** 일시 중지·다시 시작 (C12). 다음 하트비트 응답의 `paused`로 전달된다. */
  pauseRunner: (runnerId: string) =>
    call<unknown>(`/api/v1/server-runners/${encodeURIComponent(runnerId)}/pause`, { method: "POST" }),
  resumeRunner: (runnerId: string) =>
    call<unknown>(`/api/v1/server-runners/${encodeURIComponent(runnerId)}/resume`, { method: "POST" }),
  /** 재시작 (C12, ADR-0117). 다음 하트비트 응답의 `restart`로 전달된다. */
  restartRunner: (runnerId: string) =>
    call<unknown>(`/api/v1/server-runners/${encodeURIComponent(runnerId)}/restart`, { method: "POST" }),
  /** 유실 처리 (C12). **오프라인인 실행기만** — 온라인이면 409 `runner_online`이다. */
  markRunnerLost: (runnerId: string) =>
    call<unknown>(`/api/v1/server-runners/${encodeURIComponent(runnerId)}/mark-lost`, {
      method: "POST",
    }),

  /** 패키지 목록 (C5). `missing_resources`는 Center가 **읽을 때** 세어 준다 (C7). */
  packages: (query: { kind?: string } = {}) =>
    call<PackageInfo[]>(`/api/v1/packages${query.kind ? `?kind=${encodeURIComponent(query.kind)}` : ""}`),

  /** 이 패키지를 쓰는 패키지 (C5·CON-06). Center가 **읽을 때** 센다. */
  dependents: (packageId: string, version: string) =>
    call<DependentInfo[]>(
      `/api/v1/packages/${encodeURIComponent(packageId)}/${encodeURIComponent(version)}/dependents`,
    ),
  /** 삭제 (C5). 배포나 다른 패키지가 참조하면 409 `in_use`다 — 아무것도 지워지지 않는다. */
  deletePackage: (packageId: string, version: string) =>
    call<void>(
      `/api/v1/packages/${encodeURIComponent(packageId)}/${encodeURIComponent(version)}`,
      { method: "DELETE" },
    ),

  /** 리소스 목록 (C7·CON-07). `{items, fetched_at}` 그대로 돌려준다. */
  resources: <T>(type?: string) =>
    call<{ items: T[]; fetched_at: string }>(`/api/v1/resources${type ? `?type=${type}` : ""}`),
  /** 기여 자원 **종류** 목록 (CON-07 탭 하나씩). 읽기 실패도 함께 온다. */
  contributedKinds: () =>
    call<{ items: ContributedKind[]; fetched_at: string }>("/api/v1/resources/contributed-kinds"),
  /** 그 종류의 기여 자원들. `data`는 확장 고유 내용이라 **해석하지 않는다** (C13 §5). */
  contributed: (resourceType: string) =>
    call<{ items: ContributedResource[]; fetched_at: string }>(
      `/api/v1/resources?type=contributed&resource_type=${encodeURIComponent(resourceType)}`,
    ),

  extension: (extensionId: string) =>
    call<ExtensionResource>(`/api/v1/resources/extensions/${encodeURIComponent(extensionId)}`),
  /** 외부 확장 등록 — 정의만 보낸다. 검사를 지나면 **Center가 서명한다** (C13 E6, ADR-0090). */
  registerExtension: (definition: unknown) =>
    call<ExtensionResource>("/api/v1/resources/extensions", {
      method: "POST",
      body: JSON.stringify({ definition }),
    }),
  /** 등록 해제 — 그 판을 쓰는 BPM 프로세스는 실행 불가가 된다. **되살릴 수 없다.** */
  revokeExtension: (extensionId: string, version: string) =>
    call<ExtensionResource>("/api/v1/resources/extensions", {
      method: "DELETE",
      body: JSON.stringify({ id: extensionId, version }),
    }),

  serviceApp: (appId: string) =>
    call<ServiceAppResource>(`/api/v1/resources/service-apps/${encodeURIComponent(appId)}`),
  /** 들인 일꾼 (C15, CON-07 「일꾼」). */
  consumers: () => call<ConsumerInfo[]>("/api/v1/consumers"),
  /** 토픽마다 일꾼 수·마지막으로 가져간 때·기다리는 일감 (C15, CON-07 「토픽」). */
  externalTopics: () => call<TopicStatus[]>("/api/v1/external-topics"),
  /** 그 실행이 올린 일감 (C15, CON-01 「외부 작업」) — 값 없이 자리·상태·일꾼만. */
  externalTasks: (runId: string) =>
    call<ExternalTaskInfo[]>(`/api/v1/external-tasks?run_id=${encodeURIComponent(runId)}`),
  /** 타이머 시작의 일정 (C5 §일정, CON-02 「일정」). */
  schedules: () => call<ScheduleInfo[]>("/api/v1/schedules"),

  /** 결재함 (C6·CON-04). */
  /** 결재함 (C6). `assignee`는 그 이름이 담당자에 있는 것만 (ADR-0080) — 콘솔은 거르기만 한다. */
  approvals: (query: { state?: string; bpm_process_id?: string; host?: string; assignee?: string } = {}) => {
    const search = new URLSearchParams(
      Object.entries(query).filter(([, value]) => Boolean(value)) as [string, string][],
    );
    const suffix = search.size > 0 ? `?${search}` : "";
    return call<ApprovalInfo[]>(`/api/v1/approvals${suffix}`);
  },
  approval: (requestId: string) =>
    call<ApprovalInfo>(`/api/v1/approvals/${encodeURIComponent(requestId)}`),
  /** 답하기. 답한 사람은 **로그인한 계정**이다 (ADR-0090) — 본문에 없다. */
  answerApproval: (requestId: string, answer: Record<string, unknown>) =>
    call<ApprovalInfo>(`/api/v1/approvals/${encodeURIComponent(requestId)}/answer`, {
      method: "POST",
      body: JSON.stringify({ answer }),
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
  /** 배포 (C5). Center가 봉투를 지어 서명한다 — 배포 id·해시도 Center가 채운다 (ADR-0090). */
  createDeployment: (body: DeploymentRequest) =>
    call<DeploymentInfo>("/api/v1/deployments", { method: "POST", body: JSON.stringify(body) }),
  /** 배포 철회. **되살릴 수 없다.** */
  revokeDeployment: (deploymentId: string) =>
    call<DeploymentInfo>("/api/v1/deployments", {
      method: "DELETE",
      body: JSON.stringify({ deployment_id: deploymentId }),
    }),

  /** 승인 (C5 `PUT …/signature`). 본문 없음 — Center가 서명한다. */
  approvePackage: (packageId: string, version: string) =>
    call<unknown>(`${pkg(packageId, version)}/signature`, { method: "PUT" }),
  /** 승인 철회. 그 패키지의 배포가 모두 무효가 된다. **되살릴 수 없다.** */
  revokePackage: (packageId: string, version: string) =>
    call<unknown>(`${pkg(packageId, version)}/revoke`, { method: "POST", body: JSON.stringify({}) }),
  /** 지원 종료 — 새 배포만 막는다. 되돌리는 길은 승인이다 (C5). */
  deprecatePackage: (packageId: string, version: string) =>
    call<PackageInfo>(`${pkg(packageId, version)}/status`, {
      method: "PUT",
      body: JSON.stringify({ status: "deprecated" }),
    }),

  /** 관리자 계정 (C5 §관리자 계정·CON-14). 관리자만. */
  accounts: () => call<AccountInfo[]>("/api/v1/accounts"),
  createAccount: (body: { username: string; password: string; role: string }) =>
    call<AccountInfo>("/api/v1/accounts", { method: "POST", body: JSON.stringify(body) }),
  updateAccount: (username: string, body: { role?: string; disabled?: boolean; password?: string }) =>
    call<AccountInfo>(`/api/v1/accounts/${encodeURIComponent(username)}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  /** 자기 비밀번호 — 지금 비밀번호가 맞아야 한다. 바꾸면 그 계정의 세션이 모두 끝난다. */
  changePassword: (current: string, next: string) =>
    call<AccountInfo>("/api/v1/auth/password", {
      method: "PUT",
      body: JSON.stringify({ current_password: current, new_password: next }),
    }),

  /**
   * 작업 지시 (C5·CON-05). `state`는 쉼표로 여럿.
   *
   * `target_type`은 CON-12의 「대기열」이 쓴다 — 서버 대기열은 **아직 어느 실행기에도 묶이지
   * 않아**(C12) `target_id`로는 좁힐 수 없고, 종류로 걸러야 PC 작업이 섞이지 않는다.
   */
  jobs: (
    query: { state?: string; target_type?: string; target_id?: string; limit?: number } = {},
  ) => {
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

  /** 가상 직원 (C5 §가상 직원·CON-13). 일괄·자식은 **Center가 읽을 때** 이어 붙인다 — 콘솔이 세지 않는다. */
  virtualWorkers: () => call<VirtualWorkerInfo[]>("/api/v1/virtual-workers"),
  virtualWorker: (id: string) => call<VirtualWorkerInfo>(`/api/v1/virtual-workers/${encodeURIComponent(id)}`),
  createVirtualWorker: (body: VirtualWorkerRequest) =>
    call<VirtualWorkerInfo>("/api/v1/virtual-workers", { method: "POST", body: JSON.stringify(body) }),
  updateVirtualWorker: (id: string, body: VirtualWorkerRequest) =>
    call<VirtualWorkerInfo>(`/api/v1/virtual-workers/${encodeURIComponent(id)}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteVirtualWorker: (id: string) =>
    call<unknown>(`/api/v1/virtual-workers/${encodeURIComponent(id)}`, { method: "DELETE" }),
  unbindCenterKey: (keyId: string) =>
    call<CenterKeyInfo>(`/api/v1/center-keys/${keyId}/unbind`, { method: "POST" }),
  /** 삭제 (C7 `purge`, ADR-0095) — **폐기된 키만**. 아니면 409 `not_revoked`. */
  purgeCenterKey: (keyId: string) => call<void>(`/api/v1/center-keys/${keyId}/purge`, { method: "POST" }),

  /**
   * 등록 요청 (C5 §등록 승인, ADR-0092) — CON-03·CON-12 「승인 대기」·CON-07 「일꾼 승인 대기」. 기본은 대기 중인 것만.
   * 사람은 키를 보지 않는다 — 승인 응답에도 원문이 없다.
   */
  enrollments: (type: "bot_ui" | "server_runner" | "studio" | "consumer") =>
    call<EnrollmentInfo[]>(`/api/v1/enrollments?type=${type}`),
  /** 모든 상태의 등록 요청 — CON-16 「앱 로그」가 이력으로 읽는다 (C5 `state`는 쉼표로 여럿). */
  enrollmentHistory: () =>
    call<EnrollmentInfo[]>("/api/v1/enrollments?state=pending,approved,rejected,expired"),
  /** `topics`는 일꾼(`type: consumer`)만 — 요청한 토픽 안에서 줄인다. 비우면 요청한 것 그대로 (C5). */
  approveEnrollment: (id: string, name?: string, topics?: string[]) =>
    call<EnrollmentDecision>(`/api/v1/enrollments/${encodeURIComponent(id)}/approve`, {
      method: "POST",
      body: JSON.stringify({ ...(name ? { name } : {}), ...(topics && topics.length > 0 ? { topics } : {}) }),
    }),
  rejectEnrollment: (id: string, reason?: string) =>
    call<EnrollmentInfo>(`/api/v1/enrollments/${encodeURIComponent(id)}/reject`, {
      method: "POST",
      body: JSON.stringify(reason ? { reason } : {}),
    }),

  runs: (
    query: {
      status?: string;
      bpm_process_id?: string;
      run_location?: string;
      /** 어느 PC가 보낸 기록인가 (C3 — Center가 보낸 키로 푼다). */
      bot_ui_id?: string;
      limit?: number;
    } = {},
  ) => {
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
};
