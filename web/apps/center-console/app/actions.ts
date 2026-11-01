"use server";

import type { Route } from "next";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { center, CenterError, session, signIn, signOut } from "@/lib/center";
import { fromCaller } from "@/lib/inputs";
import { COOKIE_NAME, seal } from "@/lib/session";

/**
 * 쓰기 동작 — 모두 **콘솔 서버에서** 돈다 (Server Action). 브라우저는 토큰을 모른다.
 *
 * 승인·배포·외부 확장 등록도 여기서 한다 — 봉투는 **Center가 서버의 키로 서명한다** (ADR-0090).
 * 「누가」는 로그인한 계정이고 Center가 세션에서 읽는다.
 */

export interface ActionResult {
  error?: string;
}

function message(cause: unknown): string {
  return cause instanceof CenterError ? cause.message : "알 수 없는 오류가 생겼습니다";
}

export async function login(_previous: ActionResult, form: FormData): Promise<ActionResult> {
  const username = String(form.get("username") ?? "").trim();
  const password = String(form.get("password") ?? "");
  if (!username || !password) return { error: "아이디와 비밀번호를 넣으세요." };

  let made;
  try {
    made = await signIn(username, password);
  } catch (cause) {
    return { error: message(cause) };
  }
  (await cookies()).set(
    COOKIE_NAME,
    seal({
      // 회사 관리자도 **제 회사 안에서는** 관리자다 — 무엇을 다룰 수 있는지는 Center가 회사로 가른다 (C16).
      mode: made.role === "admin" || made.role === "company_admin" ? "admin" : "read",
      token: made.token,
      actor: made.username,
      company: made.company ?? null,
    }),
    {
      httpOnly: true,
      sameSite: "lax",
      secure: process.env.NODE_ENV === "production",
      path: "/",
      // Center 세션과 **같이 끝난다** — 끝난 세션을 들고 있으면 화면마다 「로그인이 끝났습니다」가 뜬다.
      expires: new Date(made.expires_at),
    },
  );
  // 첫 화면 — 메뉴 맨 위 「운영 현황 › 프로세스」 (ADR-0121).
  redirect("/bots");
}

export async function logout(): Promise<void> {
  const found = await session();
  if (found) await signOut(found.token).catch(() => undefined); // 닿지 못해도 쿠키는 지운다
  (await cookies()).delete(COOKIE_NAME);
  redirect("/login");
}

export async function setBotUiDisabled(botUiId: string, disabled: boolean): Promise<ActionResult> {
  try {
    await (disabled ? center.disableBotUi(botUiId) : center.enableBotUi(botUiId));
  } catch (cause) {
    return { error: message(cause) };
  }
  // 목록과 상세가 **둘 다** 이 값을 보인다 — `layout`이라야 아래 경로까지 함께 새로 그린다.
  revalidatePath("/bot-uis", "layout");
  return {};
}

/**
 * 서버 실행기 일시 중지·다시 시작 (CON-12, C12).
 *
 * 멈춰도 **도는 실행은 끝까지 간다** — 막는 것은 새 작업뿐이다. 그래서 「일시 중지」에만 확인
 * 창이 붙고 「다시 시작」은 바로 된다 (U9 — 되돌릴 수 있고 해가 없는 쪽은 묻지 않는다).
 */
export async function setRunnerPaused(runnerId: string, paused: boolean): Promise<ActionResult> {
  try {
    await (paused ? center.pauseRunner(runnerId) : center.resumeRunner(runnerId));
  } catch (cause) {
    return { error: message(cause) };
  }
  revalidatePath("/server-runners", "layout");
  revalidatePath("/bots");
  return {};
}

/**
 * 서버 실행기 재시작 (CON-02 「서버」 탭, C12, ADR-0117).
 *
 * 실행기는 새 작업을 받지 않고 도는 실행이 끝나면 **스스로 끝난다** — 다시 띄우는 것은 compose다.
 */
export async function restartRunner(runnerId: string): Promise<ActionResult> {
  try {
    await center.restartRunner(runnerId);
  } catch (cause) {
    return { error: message(cause) };
  }
  revalidatePath("/server-runners", "layout");
  revalidatePath("/bots");
  return {};
}

/**
 * 유실 처리 (CON-12, C12 `mark-lost`) — **되돌릴 수 없다.**
 *
 * 그 실행기의 실행을 `failed`(`runner_lost`)로 닫고 결재를 회수한다 (C6 `host_lost`).
 * **온라인인 실행기는 Center가 409 `runner_online`으로 막는다** — 화면도 단추를 끄지만,
 * 그사이 돌아온 실행기를 닫지 않는 것은 Center가 지킨다 (판정이 두 곳에 있으면 갈라진다).
 */
export async function markRunnerLost(runnerId: string): Promise<ActionResult> {
  try {
    await center.markRunnerLost(runnerId);
  } catch (cause) {
    return { error: message(cause) };
  }
  // 결재함도 바뀐다 — 회수된 결재가 그 화면에 남아 보이면 안 된다 (C6 `host_lost`).
  revalidatePath("/server-runners", "layout");
  revalidatePath("/bots");
  revalidatePath("/approvals", "layout");
  revalidatePath("/runs", "layout");
  return {};
}

/**
 * 결재 답하기 (CON-04). **일반 `<form>`이 부른다** — JS 없이도 답할 수 있다.
 *
 * 폼 칸의 타입은 **Center에 저장된 것**을 다시 읽어 맞춘다 (브라우저가 보낸 글자를 믿고
 * 타입을 정하지 않는다). 틀린 답은 Center가 칸마다 돌려주고, 그 자리로 되돌아가 보인다.
 */
export async function answerApproval(form: FormData): Promise<void> {
  const requestId = String(form.get("request_id") ?? "");
  // 타입 라우트는 질의 문자열이 붙은 주소를 리터럴로 요구한다 — 한 자리에서 만든다.
  const back = (query: string): Route =>
    `/approvals/${encodeURIComponent(requestId)}?${query}` as Route;

  let answer: Record<string, unknown>;
  try {
    const found = await center.approval(requestId);
    answer = readAnswer(found.form?.fields ?? [], form);
  } catch (cause) {
    redirect(back(`error=${encodeURIComponent(message(cause))}`));
  }

  try {
    await center.answerApproval(requestId, answer);
  } catch (cause) {
    // 칸마다 오류를 그 자리에 보이려고 칸 이름을 함께 넘긴다 (C6 `detail.fields`).
    const fields =
      cause instanceof CenterError && Array.isArray(cause.body?.detail?.fields)
        ? (cause.body.detail.fields as string[]).join(",")
        : "";
    redirect(
      back(`error=${encodeURIComponent(message(cause))}&fields=${encodeURIComponent(fields)}`),
    );
  }
  revalidatePath("/approvals", "layout");
  redirect(back("answered=1"));
}

/** FormData를 폼 칸의 **타입대로** 읽는다. 폼이 없으면 「승인 / 반려」다 (C6). */
function readAnswer(
  fields: Array<{ key: string; type: string }>,
  form: FormData,
): Record<string, unknown> {
  if (fields.length === 0) {
    const decision = String(form.get("decision") ?? "");
    const comment = String(form.get("comment") ?? "").trim();
    return comment ? { decision, comment } : { decision };
  }
  const out: Record<string, unknown> = {};
  for (const field of fields) {
    const raw = form.get(field.key);
    if (field.type === "bool") {
      // 체크 안 한 칸은 **`false`**다 (빠진 것이 아니다 — 필수 칸이 통과해야 한다).
      out[field.key] = raw === "on" || raw === "true";
      continue;
    }
    const text = String(raw ?? "").trim();
    if (text === "") continue; // 비운 칸은 보내지 않는다 — 필수면 Center가 잡는다
    out[field.key] = field.type === "number" ? Number(text) : text;
  }
  return out;
}

export async function withdrawApproval(requestId: string): Promise<ActionResult> {
  try {
    await center.withdrawApproval(requestId);
  } catch (cause) {
    return { error: message(cause) };
  }
  revalidatePath("/approvals", "layout");
  return {};
}

/**
 * 작업 지시 만들기 (CON-05 「새 작업」). **일반 `<form>`이 부른다** — JS 없이도 만든다.
 *
 * 입력 칸의 타입은 **Center에 올라간 매니페스트**(C1 `inputs`)를 다시 읽어 맞춘다 (브라우저가
 * 보낸 글자로 타입을 정하지 않는다). 매니페스트에 없는 입력은 「이름 = 값」 줄로 받는다.
 */
export async function createJob(form: FormData): Promise<void> {
  const bot = String(form.get("bot") ?? "");
  const botUi = String(form.get("bot_ui") ?? "");
  const version = String(form.get("version") ?? "");
  // 서버 BPM 프로세스는 실행기를 고르지 않는다 — Center가 빈자리로 보낸다 (C5 `JobTarget`).
  const server = form.get("place") === "server";
  const picked = `bot=${encodeURIComponent(bot)}&bot_ui=${encodeURIComponent(botUi)}&version=${encodeURIComponent(version)}`;
  const back = (query: string): Route => `/jobs/new?${picked}&${query}` as Route;

  let inputs: Record<string, unknown>;
  try {
    // 입력 칸은 **그 대상에 배포된 버전**의 매니페스트로 그렸다 (`version`을 비워 보내도).
    const shown = String(form.get("inputs_from") ?? "") || version;
    const declared = shown ? fromCaller((await center.packageInfo(bot, shown)).manifest?.inputs ?? []) : [];
    inputs = readInputs(declared, form);
  } catch (cause) {
    redirect(back(`error=${encodeURIComponent(message(cause))}`));
  }

  const expires = String(form.get("expires_at") ?? "").trim();
  const note = String(form.get("note") ?? "").trim();
  let made: string;
  try {
    const job = await center.createJob({
      bpm_process_id: bot,
      target: server ? { type: "server_runner", id: "*" } : { type: "bot_ui", id: botUi },
      inputs,
      // 비우면 그 대상에 배포된 버전으로 Center가 채운다 (C5).
      version: version || null,
      // `datetime-local`은 시간대가 없다 — 콘솔 서버의 시간대로 읽어 ISO로 보낸다.
      expires_at: expires ? new Date(expires).toISOString() : null,
      note: note || null,
    });
    made = job.job_id;
  } catch (cause) {
    redirect(back(`error=${encodeURIComponent(message(cause))}`));
  }
  revalidatePath("/jobs", "layout");
  // 서버 작업은 CON-12의 「대기열」에도 보인다.
  if (server) revalidatePath("/server-runners", "layout");
  redirect(`/jobs/${encodeURIComponent(made)}?created=1` as Route);
}

/** 입력을 매니페스트의 **타입대로** 읽는다. 「그 밖의 입력」은 `이름 = 값` 줄 (글자 그대로). */
function readInputs(
  declared: Array<{ name: string; type: string }>,
  form: FormData,
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const one of declared) {
    const raw = form.get(`input:${one.name}`);
    if (one.type === "bool") {
      if (raw === "true" || raw === "false") out[one.name] = raw === "true";
      continue; // 「(주지 않음)」 — 빠진 것이다. 필수면 실행하는 쪽이 막는다
    }
    const text = String(raw ?? "").trim();
    if (text === "") continue;
    if (one.type === "int" || one.type === "number") {
      const value = Number(text);
      if (Number.isNaN(value)) throw new CenterError(422, null, `입력 ${one.name}은 수여야 합니다`);
      out[one.name] = value;
    } else if (one.type === "list" || one.type === "dict") {
      try {
        out[one.name] = JSON.parse(text);
      } catch {
        throw new CenterError(422, null, `입력 ${one.name}은 JSON이어야 합니다 (${one.type})`);
      }
    } else {
      out[one.name] = text;
    }
  }
  for (const line of String(form.get("extra") ?? "").split("\n")) {
    const at = line.indexOf("=");
    if (at <= 0) continue;
    const name = line.slice(0, at).trim();
    if (name && !(name in out)) out[name] = line.slice(at + 1).trim();
  }
  return out;
}

/** 작업 취소 (CON-05). 202면 **아직 끝나지 않았다** — 화면이 「취소 요청함」으로 보인다. */
export async function cancelJob(jobId: string): Promise<ActionResult> {
  try {
    await center.cancelJob(jobId);
  } catch (cause) {
    return { error: message(cause) };
  }
  revalidatePath("/jobs", "layout");
  // 서버 작업은 CON-12의 「대기열」에도 같은 줄로 보인다 — 한쪽만 새로 그리면 취소한 작업이
  // 다른 화면에 남는다.
  revalidatePath("/server-runners", "layout");
  revalidatePath("/bots");
  return {};
}

/**
 * 패키지 삭제 (CON-06 「삭제...」). **되돌릴 수 없다** — 확인 창을 거쳐서만 온다.
 *
 * 409 `in_use`면 **아무것도 지워지지 않았다** — 막은 배포·패키지를 그대로 보여 준다 (C5).
 * 성공하면 그 상세 주소가 404가 되므로 목록으로 돌아간다.
 */
export async function deletePackage(packageId: string, version: string): Promise<ActionResult> {
  try {
    await center.deletePackage(packageId, version);
  } catch (cause) {
    if (cause instanceof CenterError && cause.status === 409) {
      const detail = cause.body?.detail ?? {};
      const said = [
        ...(Array.isArray(detail.deployments) ? (detail.deployments as string[]) : []),
        ...(Array.isArray(detail.dependents) ? (detail.dependents as string[]) : []),
      ].join(", ");
      return { error: said ? `${cause.message} — ${said}` : cause.message };
    }
    return { error: message(cause) };
  }
  revalidatePath("/packages", "layout");
  // CON-02도 같은 패키지 표를 읽는다 (BPM 프로세스·버전별 준비도) — 지운 줄이 그대로 남으면 안 된다.
  revalidatePath("/bots", "layout");
  return {};
}

/** 키 동작은 그 키가 가리키는 화면에 있다 (ADR-0124) — 그 화면들을 다시 그린다. */
function revalidateKeys() {
  revalidatePath("/bot-uis", "layout");
  revalidatePath("/server-runners", "layout");
  revalidatePath("/resources");
}

export async function revokeCenterKey(keyId: string): Promise<ActionResult> {
  try {
    await center.revokeCenterKey(keyId);
  } catch (cause) {
    return { error: message(cause) };
  }
  revalidateKeys();
  return {};
}

/**
 * 등록 요청 승인·거절 (CON-03·CON-12 「승인 대기」, C5 §등록 승인). 키는 Center가 만들어
 * 요청의 공개키로 봉해 둔다 — 여기서도 원문은 지나가지 않는다.
 */
export async function decideEnrollment(
  enrollmentId: string,
  decision: "approve" | "reject",
  text: string,
  company?: string,
): Promise<ActionResult> {
  try {
    if (decision === "approve") await center.approveEnrollment(enrollmentId, text.trim() || undefined, company);
    else await center.rejectEnrollment(enrollmentId, text.trim() || undefined);
  } catch (cause) {
    return { error: message(cause) };
  }
  revalidatePath("/bot-uis", "layout");
  revalidatePath("/resources", "layout");
  revalidatePath("/server-runners", "layout");
  revalidatePath("/bots");
  return {};
}

/** 키 「삭제...」 — 폐기된 키의 행을 지운다 (C7 `purge`, ADR-0095). */
export async function deleteCenterKey(keyId: string): Promise<ActionResult> {
  try {
    await center.purgeCenterKey(keyId);
  } catch (cause) {
    return { error: message(cause) };
  }
  revalidateKeys();
  return {};
}

export async function unbindCenterKey(keyId: string): Promise<ActionResult> {
  try {
    await center.unbindCenterKey(keyId);
  } catch (cause) {
    return { error: message(cause) };
  }
  revalidateKeys();
  return {};
}

// ─────────────────── 승인·배포 (ADR-0090 — Center가 서명한다) ───────────────────

/** 패키지 상태를 바꾸면 그것을 읽는 화면 셋을 함께 새로 그린다 (CON-02·CON-06·배포). */
function packagesChanged(): void {
  revalidatePath("/bots", "layout");
  revalidatePath("/packages", "layout");
  revalidatePath("/deployments", "layout");
}

/** 승인 (CON-02·CON-06). 지원 종료된 것을 다시 승인하면 새 배포가 다시 열린다 (C5). */
export async function approvePackage(packageId: string, version: string): Promise<ActionResult> {
  try {
    await center.approvePackage(packageId, version);
  } catch (cause) {
    return { error: message(cause) };
  }
  packagesChanged();
  return {};
}

/** 승인 철회 — 그 판의 배포가 **모두** 무효가 된다. 되살릴 수 없다. */
export async function revokePackage(packageId: string, version: string): Promise<ActionResult> {
  try {
    await center.revokePackage(packageId, version);
  } catch (cause) {
    return { error: message(cause) };
  }
  packagesChanged();
  return {};
}

/** 지원 종료 — 새 배포만 막는다. 이미 배포된 것은 그대로 돈다. */
export async function deprecatePackage(packageId: string, version: string): Promise<ActionResult> {
  try {
    await center.deprecatePackage(packageId, version);
  } catch (cause) {
    return { error: message(cause) };
  }
  packagesChanged();
  return {};
}

/**
 * 새 배포 (CON-15). **일반 `<form>`이 부른다.** PC는 여럿을 고를 수 있고 **PC마다 배포 하나**다
 * (ADR-0046 — PC 배포에 전체 대상은 없다). 하나라도 거부되면 그 까닭을 보이고, 이미 된 것은
 * 목록에 남는다.
 */
export async function createDeployment(form: FormData): Promise<void> {
  const bot = String(form.get("bot") ?? "");
  const [botId = "", version = ""] = bot.split("@");
  const place = String(form.get("place") ?? "pc");
  const back = (query: string): Route => `/deployments/new?${query}` as Route;
  const keep = `bot=${encodeURIComponent(bot)}`;
  const fail = (said: string): never => redirect(back(`${keep}&error=${encodeURIComponent(said)}`));

  const when = (name: string): string | undefined => {
    const raw = String(form.get(name) ?? "").trim();
    // `datetime-local`은 지역 시각이라 그대로 두면 Center가 시간대를 모른다 — 서버의 시각으로 읽는다.
    return raw ? new Date(raw).toISOString() : undefined;
  };
  const common = {
    bpm_process_id: botId,
    version,
    not_before: when("not_before"),
    expires_at: when("expires_at"),
  };

  if (!botId || !version) fail("배포할 프로세스와 버전을 고르세요.");
  let targets: Array<{ type: string; id: string }>;
  let limit: number | undefined;
  if (place === "server") {
    const runner = String(form.get("runner") ?? "").trim();
    targets = [{ type: "server_runner", id: runner || "*" }];
    const raw = String(form.get("max_concurrency") ?? "").trim();
    limit = raw ? Number(raw) : undefined;
    if (limit !== undefined && !(Number.isInteger(limit) && limit >= 1)) fail("동시 실행 상한은 1 이상의 정수입니다.");
  } else {
    targets = form.getAll("bot_ui").map((one) => ({ type: "bot_ui", id: String(one) })).filter((one) => one.id);
    if (targets.length === 0) fail("배포할 Bot을 하나 이상 고르세요.");
  }

  const done: string[] = [];
  for (const target of targets) {
    try {
      const made = await center.createDeployment({ ...common, target, max_concurrency: limit });
      done.push(made.deployment_id);
    } catch (cause) {
      const said = done.length > 0 ? `${message(cause)} (먼저 만든 배포 ${done.length}건은 남았습니다)` : message(cause);
      revalidatePath("/deployments", "layout");
      fail(said);
    }
  }
  revalidatePath("/deployments", "layout");
  revalidatePath("/bots", "layout");
  redirect(`/deployments?created=${done.length}` as Route);
}

/** 배포 철회 — 확인 창을 거쳐서만 온다. **되살릴 수 없다.** */
export async function revokeDeployment(deploymentId: string): Promise<ActionResult> {
  try {
    await center.revokeDeployment(deploymentId);
  } catch (cause) {
    return { error: message(cause) };
  }
  revalidatePath("/deployments", "layout");
  revalidatePath("/bots", "layout");
  return {};
}

// ─────────────────── 관리자 계정 (CON-14) ───────────────────

export async function createAccount(_previous: ActionResult, form: FormData): Promise<ActionResult> {
  try {
    await center.createAccount({
      username: String(form.get("username") ?? "").trim(),
      password: String(form.get("password") ?? ""),
      role: String(form.get("role") ?? "admin"),
      // 회사 관리자는 회사가 꼭 있고 Center 관리자는 없다 — 맞는지는 Center가 본다 (C16).
      company: String(form.get("company") ?? "") || null,
    });
  } catch (cause) {
    return { error: message(cause) };
  }
  revalidatePath("/accounts");
  return {};
}

/** 역할 바꾸기·멈추기·다시 쓰기·비밀번호 새로 정하기 — 한 길이다 (C5 `PUT /accounts/{id}`). */
export async function updateAccount(
  username: string,
  change: { role?: string; disabled?: boolean; password?: string },
): Promise<ActionResult> {
  try {
    await center.updateAccount(username, change);
  } catch (cause) {
    return { error: message(cause) };
  }
  // 자기 계정을 바꾸면 Center가 그 세션을 지웠다 — 다시 로그인해야 한다.
  const found = await session();
  if (found?.actor === username) {
    (await cookies()).delete(COOKIE_NAME);
    redirect("/login");
  }
  revalidatePath("/accounts");
  return {};
}

/** 자기 비밀번호 바꾸기. 바꾸면 세션이 모두 끝나므로 다시 로그인한다. */
export async function changeOwnPassword(_previous: ActionResult, form: FormData): Promise<ActionResult> {
  const next = String(form.get("new_password") ?? "");
  if (next !== String(form.get("confirm_password") ?? "")) return { error: "새 비밀번호 두 칸이 다릅니다." };
  try {
    await center.changePassword(String(form.get("current_password") ?? ""), next);
  } catch (cause) {
    return { error: message(cause) };
  }
  (await cookies()).delete(COOKIE_NAME);
  redirect("/login?changed=1" as Route);
}
