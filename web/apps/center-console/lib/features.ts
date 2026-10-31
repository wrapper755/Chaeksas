/**
 * CON-07 「기능」 — 기능(확장) 하나가 **지금 쓸 수 있나, 안 되면 사람이 할 일이 무엇인가**를 짓는다.
 *
 * 재료는 Center가 이미 주는 넷이다 (C7 리소스 목록, C5 패키지·배포). 계약을 넓히지 않고 콘솔이
 * 맞춘다 — 그래서 화면은 「서비스 앱인가 외부 앱인가」「무엇을 기여하나」를 보이지 않는다.
 *
 * 화면을 모르는 함수라 vitest가 잰다 (`features.test.ts`). 페이지는 `server-only`를 끌고 와서
 * 단위 시험에서 부를 수 없다.
 *
 * 지키는 것:
 * - **PC를 세는 것은 그 기능을 쓰는 BPM 프로세스가 배포된 곳만**이다 — 그 BPM 프로세스를 받지 않은 PC에 없는
 *   것은 할 일이 아니다.
 * - **외부 기능은 PC를 세지 않는다** — 코드가 없어 깔 것이 없다 (C13 E1).
 * - 서버 부분이 없다는 것은 **패키지의 누락 검사**(C7 `missing_resources`)가 말해 준다 — 서비스 앱은
 *   그 토픽을 승인받은 **일꾼이 manifest를 올려야** 생긴다 (C15, ADR-0102). 할 일은 「일꾼을 들이세요」다.
 * - 서버 상태는 **토픽이 말한다** — 그 토픽을 가져가는 일꾼이 있고 마지막으로 가져간 지 오래지 않으면
 *   `ok`다 (C7). Center는 바깥 기능을 읽으러 가지 않는다.
 */
import type { DeploymentInfo } from "@chaeksas/api-types/c5-deployment-info";
import type { PackageInfo } from "@chaeksas/api-types/c5-package-info";
import type { ExtensionResource } from "@chaeksas/api-types/c7-extension-resource";
import type { RuntimeResource } from "@chaeksas/api-types/c7-runtime-resource";
import type { ServiceAppResource } from "@chaeksas/api-types/c7-service-app-resource";

/** `status_map` 「기능」의 표기. */
export type Usable = "쓸 수 있음" | "쓸 수 없음" | "확인 전";

export type TodoKind = "add_consumer" | "server_down" | "missing_on_hosts" | "off_on_hosts" | "wrong_version";

export interface Todo {
  kind: TodoKind;
  text: string;
  /** 누르면 가는 곳. 없으면 글만. */
  href?: string;
}

export interface FeatureRow {
  /** 줄 열쇠이자 상세 주소 조각 — 확장이면 그 id, 확장 없는 서비스 앱이면 `app:<id>`. */
  key: string;
  id: string;
  name: string;
  external: boolean;
  usable: Usable;
  todos: Todo[];
  /** C11 서비스 앱이면 그 앱 (관리 콘솔). */
  serviceAppId: string | null;
  consoleUrl: string | null;
  /** 이 기능의 토픽을 가져가는 일꾼 수 (C7 `consumers`). 서버 부분이 없으면 없다. */
  consumers: number | null;
  /** 일꾼이 마지막으로 가져간 때 (C7 `checked_at` — 들인 일꾼이 없으면 없다). */
  checkedAt: string | null;
  /** 이 기능을 요구하는 BPM 프로세스 (`<id>`) — 해제 확인 창이 쓴다. */
  usedBy: string[];
}

export interface FeatureInput {
  extensions: ExtensionResource[];
  serviceApps: ServiceAppResource[];
  runtimes: RuntimeResource[];
  packages: PackageInfo[];
  deployments: DeploymentInfo[];
}

export const ADD_CONSUMER_HREF = "/resources#consumer-enrollments";

const DOWN = new Set(["unreachable"]);
const UNKNOWN = new Set(["unknown", ""]);

function shortTime(value: string | null | undefined): string {
  if (!value) return "";
  const at = new Date(value);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(at.getMonth() + 1)}-${pad(at.getDate())} ${pad(at.getHours())}:${pad(at.getMinutes())}`;
}

/** 이 기능을 요구하는 BPM 프로세스 패키지 — 확장 id 또는 그 서버(서비스 앱) id로. */
function botsUsing(packages: PackageInfo[], extensionId: string | null, appId: string | null): PackageInfo[] {
  return packages.filter((one) => {
    if (one.kind && one.kind !== "bpm_process") return false;
    const requires = one.manifest?.requires;
    if (!requires) return false;
    const byExtension = extensionId !== null && (requires.extensions ?? []).some((need) => need.id === extensionId);
    const byApp = appId !== null && (requires.service_apps ?? []).some((need) => need.app_id === appId);
    return byExtension || byApp;
  });
}

/** 그 BPM 프로세스들이 **지금 배포된** 곳 — `(종류, id)`. 철회된 배포는 세지 않는다. */
function deployedHosts(deployments: DeploymentInfo[], bots: PackageInfo[]): Array<{ type: string; id: string }> {
  const wanted = new Set(bots.map((one) => one.id));
  const seen = new Map<string, { type: string; id: string }>();
  for (const one of deployments) {
    if (one.revoked_at || !wanted.has(one.bpm_process_id)) continue;
    const type = String(one.target.type ?? "");
    const id = String(one.target.id ?? "");
    if (!type || !id || id === "*") continue; // 서버 전체 대상은 아래에서 서버 실행기 모두로 본다
    seen.set(`${type}:${id}`, { type, id });
  }
  return [...seen.values()];
}

function hostTodos(row: ExtensionResource, input: FeatureInput, bots: PackageInfo[]): Todo[] {
  const hosts = deployedHosts(input.deployments, bots);
  const wildcard = input.deployments.some(
    (one) => !one.revoked_at && bots.some((bot) => bot.id === one.bpm_process_id) && one.target.id === "*",
  );
  const runtimes = new Map(input.runtimes.map((one) => [`${one.host.type}:${one.host.id}`, one]));
  if (wildcard) {
    for (const one of input.runtimes) {
      if (one.host.type === "server_runner") hosts.push({ type: "server_runner", id: one.host.id });
    }
  }
  let missing = 0;
  let off = 0;
  let wrong = 0;
  const counted = new Set<string>();
  for (const host of hosts) {
    const key = `${host.type}:${host.id}`;
    if (counted.has(key)) continue;
    counted.add(key);
    const runtime = runtimes.get(key);
    const state = (runtime?.extensions ?? []).find((one) => (one as { id?: unknown }).id === row.id) as
      | { enabled?: boolean; off?: boolean }
      | undefined;
    if (!state) missing += 1;
    else if (state.off) off += 1;
    else if (state.enabled === false) wrong += 1;
  }
  const out: Todo[] = [];
  const where = (n: number) => `${n}대`;
  if (missing > 0) out.push({ kind: "missing_on_hosts", text: `PC ${where(missing)}에 없음`, href: "/bot-uis?tab=bot" });
  if (off > 0) out.push({ kind: "off_on_hosts", text: `PC ${where(off)}에서 꺼짐`, href: "/bot-uis?tab=bot" });
  if (wrong > 0) out.push({ kind: "wrong_version", text: `PC ${where(wrong)}가 맞지 않는 판`, href: "/bot-uis?tab=bot" });
  return out;
}

function serverTodos(status: string, checkedAt: string | null | undefined): Todo[] {
  if (DOWN.has(status)) {
    const at = shortTime(checkedAt);
    return [{ kind: "server_down", text: `일꾼이 가져가지 않습니다${at ? ` (마지막 ${at})` : ""}` }];
  }
  return [];
}

function verdict(todos: Todo[], status: string, hasServer: boolean): Usable {
  if (todos.length > 0) return "쓸 수 없음";
  if (hasServer && UNKNOWN.has(status)) return "확인 전";
  return "쓸 수 있음";
}

/** 누락 검사가 「없다」고 한 서비스 앱 id들 (C7 `missing_resources`) — 그 토픽을 맡은 일꾼이 manifest를 올리지 않았다. */
function missingApps(packages: PackageInfo[]): Set<string> {
  const out = new Set<string>();
  for (const one of packages) {
    for (const miss of one.missing_resources ?? []) {
      if (miss.type === "service_app") out.add(String(miss.id));
    }
  }
  return out;
}

/** 그 토픽을 가져가는 일꾼 수 (C7 `ServiceAppResource.consumers`). */
function consumersOf(app: ServiceAppResource): number {
  const raw = (app as { consumers?: unknown }).consumers;
  return typeof raw === "number" ? raw : 0;
}

const RANK: Record<Usable, number> = { "쓸 수 없음": 0, "확인 전": 1, "쓸 수 있음": 2 };

/** CON-07 「기능」 목록 — **쓸 수 없는 것이 맨 위**다. */
export function featureRows(input: FeatureInput): FeatureRow[] {
  const apps = new Map(input.serviceApps.map((one) => [one.app_id, one]));
  const appOfExtension = new Map(
    input.serviceApps.filter((one) => one.extension_id).map((one) => [String(one.extension_id), one]),
  );
  const missing = missingApps(input.packages);
  const rows: FeatureRow[] = [];
  const claimedApps = new Set<string>();

  for (const ext of input.extensions) {
    const app = (ext.service_app_id ? apps.get(ext.service_app_id) : undefined) ?? appOfExtension.get(ext.id) ?? null;
    if (app) claimedApps.add(app.app_id);
    const external = ext.tier === "external";
    const status = String(ext.status ?? "");
    const hasServer = status !== "n/a";
    const bots = botsUsing(input.packages, ext.id, app?.app_id ?? null);
    const todos: Todo[] = [];
    // 서버 부분이 없다 — 누락 검사가 **확장 id와 같은 서비스 앱**을 찾지 못했다 (내장 확장은 대개 같다).
    if (!app && !external && missing.has(ext.id)) {
      todos.push({ kind: "add_consumer", text: "일꾼을 들이세요", href: ADD_CONSUMER_HREF });
    }
    todos.push(...serverTodos(status, ext.checked_at));
    if (!external) todos.push(...hostTodos(ext, input, bots));
    rows.push({
      key: ext.id,
      id: ext.id,
      name: ext.name ?? ext.id,
      external,
      usable: verdict(todos, status, hasServer || todos.some((one) => one.kind === "add_consumer")),
      todos,
      serviceAppId: app?.app_id ?? null,
      consoleUrl: app?.console_url ?? null,
      consumers: app ? consumersOf(app) : null,
      checkedAt: ext.checked_at ?? null,
      usedBy: bots.map((one) => one.id),
    });
  }

  // 확장에 속하지 않은 서비스 앱 — 사람에게는 둘 다 「BPM 프로세스가 부르는 기능」이라 같은 표에 둔다.
  for (const app of input.serviceApps) {
    if (claimedApps.has(app.app_id)) continue;
    const status = String(app.status ?? "");
    const todos = serverTodos(status, app.checked_at);
    rows.push({
      key: `app:${app.app_id}`,
      id: app.app_id,
      name: app.name ?? app.app_id,
      external: false,
      usable: verdict(todos, status, true),
      todos,
      serviceAppId: app.app_id,
      consoleUrl: app.console_url ?? null,
      consumers: consumersOf(app),
      checkedAt: app.checked_at ?? null,
      usedBy: botsUsing(input.packages, null, app.app_id).map((one) => one.id),
    });
  }

  // 누락 검사가 말하는데 아무 줄에도 없는 서비스 앱 — 그 토픽을 맡은 일꾼이 아직 들어오지 않았다.
  for (const id of missing) {
    if (rows.some((one) => one.id === id || one.serviceAppId === id)) continue;
    rows.push({
      key: `app:${id}`,
      id,
      name: id,
      external: false,
      usable: "쓸 수 없음",
      todos: [{ kind: "add_consumer", text: "일꾼을 들이세요", href: ADD_CONSUMER_HREF }],
      serviceAppId: null,
      consoleUrl: null,
      consumers: 0,
      checkedAt: null,
      usedBy: botsUsing(input.packages, null, id).map((one) => one.id),
    });
  }

  return rows.sort((a, b) => RANK[a.usable] - RANK[b.usable] || a.name.localeCompare(b.name, "ko"));
}
