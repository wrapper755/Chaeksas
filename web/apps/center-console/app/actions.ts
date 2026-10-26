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
  /** 발급한 키 원문 — **이 응답에만 실린다** (CON-11). */
  secret?: { name: string; key: string };
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
    seal({ mode: made.role === "admin" ? "admin" : "read", token: made.token, actor: made.username }),
    {
      httpOnly: true,
      sameSite: "lax",
      secure: process.env.NODE_ENV === "production",
      path: "/",
      // Center 세션과 **같이 끝난다** — 끝난 세션을 들고 있으면 화면마다 「로그인이 끝났습니다」가 뜬다.
      expires: new Date(made.expires_at),
    },
  );
  redirect("/bot-uis");
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
  const picked = `bot=${encodeURIComponent(bot)}&bot_ui=${encodeURIComponent(botUi)}&version=${encodeURIComponent(version)}`;
  const back = (query: string): Route => `/jobs/new?${picked}&${query}` as Route;

  let inputs: Record<string, unknown>;
  try {
    // 입력 칸은 **그 Bot UI에 배포된 버전**의 매니페스트로 그렸다 (`version`을 비워 보내도).
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
      target: { type: "bot_ui", id: botUi },
      inputs,
      // 비우면 그 Bot UI에 배포된 버전으로 Center가 채운다 (C5).
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

/** 올린 파일을 JSON으로 읽는다. 사람이 고른 파일이라 **왜 안 되는지 한 줄로** 말한다. */
async function jsonFile(form: FormData, field: string, label: string): Promise<unknown> {
  const found = form.get(field);
  if (!(found instanceof File) || found.size === 0) {
    throw new Error(`${label}을 고르세요.`);
  }
  try {
    return JSON.parse(await found.text());
  } catch {
    throw new Error(`${label}이 JSON이 아닙니다 (${found.name}).`);
  }
}

/**
 * 외부 확장 등록 (CON-07 「확장 추가」).
 *
 * **정의 파일 하나**를 올린다. C13 검사(E1~E8)를 지나면 Center가 서명해 둔다 (ADR-0090) —
 * 검사 결과는 Center가 칸별 사유와 함께 돌려주므로 그것을 그대로 보인다.
 */
export async function registerExtension(form: FormData): Promise<void> {
  const back = (query: string): Route => `/resources?${query}` as Route;
  let definition: unknown;
  try {
    definition = await jsonFile(form, "definition", "확장 정의 파일");
  } catch (cause) {
    const said = cause instanceof Error ? cause.message : "파일을 읽지 못했습니다.";
    redirect(back(`error=${encodeURIComponent(said)}`));
  }

  try {
    await center.registerExtension(definition);
  } catch (cause) {
    redirect(back(`error=${encodeURIComponent(violations(cause))}`));
  }
  revalidatePath("/resources", "layout");
  redirect(back("extension=1"));
}

/** 등록 해제 — 확인 창을 거쳐서만 온다. **되살릴 수 없다.** */
export async function revokeExtension(extensionId: string, version: string): Promise<ActionResult> {
  try {
    await center.revokeExtension(extensionId, version);
  } catch (cause) {
    return { error: violations(cause) };
  }
  revalidatePath("/resources", "layout");
  redirect("/resources?revoked=1" as Route);
}

/** C13 검사 위반을 **칸별 사유까지** 한 줄로 (E3은 어디가 틀렸는지가 요점이다). */
function violations(cause: unknown): string {
  if (!(cause instanceof CenterError)) return message(cause);
  const found = cause.body?.detail?.violations;
  if (!Array.isArray(found) || found.length === 0) return cause.message;
  const said = (found as Array<{ rule?: string; message?: string }>)
    .slice(0, 5)
    .map((one) => `[${one.rule ?? "?"}] ${one.message ?? ""}`)
    .join(" · ");
  return `${cause.message} — ${said}`;
}

/**
 * 서비스 앱 등록 (CON-07). **일반 `<form>`이 부른다** — JS 없이도 등록된다.
 *
 * `app_id`를 사람이 적지 않는다 — **앱이 자기 manifest로 정한다** (C11). 주소만 받는다.
 */
export async function registerServiceApp(form: FormData): Promise<void> {
  const baseUrl = String(form.get("base_url") ?? "").trim();
  const back = (query: string): Route => `/resources?${query}` as Route;
  if (!baseUrl) {
    redirect(back(`error=${encodeURIComponent("API 주소를 적으세요.")}`));
  }
  try {
    await center.registerServiceApp(baseUrl);
  } catch (cause) {
    redirect(back(`error=${encodeURIComponent(message(cause))}`));
  }
  revalidatePath("/resources", "layout");
  redirect(back("registered=1"));
}

/** 주소 바꾸기 — **환경별 주소의 유일한 출처**다 (C7 `PUT`). */
export async function setServiceAppUrl(form: FormData): Promise<void> {
  const appId = String(form.get("app_id") ?? "");
  const baseUrl = String(form.get("base_url") ?? "").trim();
  const back = (query: string): Route =>
    `/resources/service-apps/${encodeURIComponent(appId)}?${query}` as Route;
  if (!baseUrl) {
    redirect(back(`error=${encodeURIComponent("API 주소를 적으세요.")}`));
  }
  try {
    await center.setServiceAppUrl(appId, baseUrl);
  } catch (cause) {
    redirect(back(`error=${encodeURIComponent(message(cause))}`));
  }
  revalidatePath("/resources", "layout");
  redirect(back("moved=1"));
}

/**
 * 외부 기능 「주소 바꾸기...」 (CON-07 상세 「서버 주소」, C7 §외부 확장 주소, ADR-0097). 정의의 허용
 * 호스트 밖이면 Center가 422로 거절하고 그 까닭을 그 자리에 보인다.
 */
export async function setExtensionAddress(form: FormData): Promise<void> {
  const extensionId = String(form.get("extension_id") ?? "");
  const baseUrl = String(form.get("base_url") ?? "").trim();
  const back = (query: string): Route =>
    `/resources/features/${encodeURIComponent(extensionId)}?${query}` as Route;
  if (!baseUrl) redirect(back(`error=${encodeURIComponent("API 주소를 적으세요.")}`));
  try {
    await center.setExtensionAddress(extensionId, baseUrl);
  } catch (cause) {
    redirect(back(`error=${encodeURIComponent(message(cause))}`));
  }
  revalidatePath("/resources", "layout");
  redirect(back("moved=1"));
}

/** 「기본값으로 되돌리기」 — 되돌릴 수 있는 일이라 확인 창 없이 바로 한다. */
export async function resetExtensionAddress(form: FormData): Promise<void> {
  const extensionId = String(form.get("extension_id") ?? "");
  const back = (query: string): Route =>
    `/resources/features/${encodeURIComponent(extensionId)}?${query}` as Route;
  try {
    await center.deleteExtensionAddress(extensionId);
  } catch (cause) {
    redirect(back(`error=${encodeURIComponent(message(cause))}`));
  }
  revalidatePath("/resources", "layout");
  redirect(back("reset=1"));
}

/**
 * 외부 앱 키 「키 넣기...」·「바꾸기...」 (CON-07 상세, C7 §외부 앱 키). **원문은 다시 보이지 않는다** —
 * 돌아가는 주소에 싣지 않고, Center 응답에도 없다.
 */
export async function putAppKey(form: FormData): Promise<void> {
  const extensionId = String(form.get("extension_id") ?? "");
  const slot = String(form.get("slot") ?? "") === "test" ? "test" : "run";
  const key = String(form.get("key") ?? "").trim();
  const back = (query: string): Route =>
    `/resources/features/${encodeURIComponent(extensionId)}?${query}` as Route;
  if (!key) redirect(back(`error=${encodeURIComponent("키를 넣으세요.")}`));
  try {
    await center.setAppKey(extensionId, slot, key);
  } catch (cause) {
    redirect(back(`error=${encodeURIComponent(message(cause))}`));
  }
  revalidatePath("/resources", "layout");
  redirect(back(`key_saved=${slot}`));
}

export async function deleteAppKey(extensionId: string, slot: "run" | "test"): Promise<ActionResult> {
  try {
    await center.deleteAppKey(extensionId, slot);
  } catch (cause) {
    return { error: message(cause) };
  }
  revalidatePath("/resources", "layout");
  return {};
}

/** CON-03 「셀렉터 등록」 켜기·끄기 (ADR-0094 §6). 키는 Center가 그 PC에 내려 주고 거둔다. */
export async function setSelectorRegistration(botUiId: string, on: boolean): Promise<ActionResult> {
  try {
    await center.setSelectorRegistration(botUiId, on);
  } catch (cause) {
    return { error: message(cause) };
  }
  revalidatePath(`/bot-uis/${botUiId}`);
  return {};
}

export async function unregisterServiceApp(appId: string): Promise<ActionResult> {
  try {
    await center.unregisterServiceApp(appId);
  } catch (cause) {
    // 「쓰는 Bot이 있다」면 그 목록까지 보여 준다 (C7 `in_use`).
    if (cause instanceof CenterError && Array.isArray(cause.body?.detail?.used_by)) {
      const used = (cause.body.detail.used_by as string[]).join(", ");
      return { error: `${cause.message} — ${used}` };
    }
    return { error: message(cause) };
  }
  revalidatePath("/resources", "layout");
  // 해제한 기능의 상세는 더 없다 — 목록으로 돌아간다.
  redirect("/resources" as Route);
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
  // CON-02도 같은 패키지 표를 읽는다 (Bot·버전별 준비도) — 지운 줄이 그대로 남으면 안 된다.
  revalidatePath("/bots", "layout");
  return {};
}

export async function refreshResources(): Promise<ActionResult> {
  try {
    await center.refreshResources();
  } catch (cause) {
    return { error: message(cause) };
  }
  revalidatePath("/resources", "layout");
  return {};
}

export async function createCenterKey(_previous: ActionResult, form: FormData): Promise<ActionResult> {
  const name = String(form.get("name") ?? "").trim();
  const type = String(form.get("type") ?? "bot_ui");
  if (!name) return { error: "이름을 입력하세요." };
  try {
    const created = await center.createCenterKey({ name, type });
    revalidatePath("/center-keys");
    // 원문은 화면에 한 번만 보이고, 어디에도 저장하지 않는다.
    return { secret: { name: created.name, key: created.key } };
  } catch (cause) {
    return { error: message(cause) };
  }
}

export async function revokeCenterKey(keyId: string): Promise<ActionResult> {
  try {
    await center.revokeCenterKey(keyId);
  } catch (cause) {
    return { error: message(cause) };
  }
  revalidatePath("/center-keys");
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
): Promise<ActionResult> {
  try {
    if (decision === "approve") await center.approveEnrollment(enrollmentId, text.trim() || undefined);
    else await center.rejectEnrollment(enrollmentId, text.trim() || undefined);
  } catch (cause) {
    return { error: message(cause) };
  }
  revalidatePath("/bot-uis", "layout");
  revalidatePath("/server-runners", "layout");
  revalidatePath("/bots");
  revalidatePath("/center-keys");
  return {};
}

/** CON-11 「삭제...」 — 폐기된 키의 행을 지운다 (C7 `purge`, ADR-0095). */
export async function deleteCenterKey(keyId: string): Promise<ActionResult> {
  try {
    await center.purgeCenterKey(keyId);
  } catch (cause) {
    return { error: message(cause) };
  }
  revalidatePath("/center-keys");
  return {};
}

export async function unbindCenterKey(keyId: string): Promise<ActionResult> {
  try {
    await center.unbindCenterKey(keyId);
  } catch (cause) {
    return { error: message(cause) };
  }
  revalidatePath("/center-keys");
  return {};
}

/**
 * 가상 직원 등록 (CON-13 「새 가상 직원」). **일반 `<form>`이 부른다** — JS 없이도 된다.
 *
 * 거부되면 Center의 사유를 **주소에 실어** 목록으로 돌아간다 — 「결재 없는 일괄 기동」(B16)이면
 * 그 판과 메시지까지 (C5 `intake_not_gated`의 `detail.violations`).
 */
export async function createVirtualWorker(form: FormData): Promise<void> {
  const supervisors = String(form.get("supervisors") ?? "")
    .split(",")
    .map((one) => one.trim())
    .filter(Boolean);
  try {
    await center.createVirtualWorker({
      id: String(form.get("id") ?? "").trim(),
      name: String(form.get("name") ?? "").trim(),
      supervisors,
      intake: String(form.get("intake") ?? "").trim(),
      state: "active",
    });
  } catch (cause) {
    const found = cause instanceof CenterError ? cause.body?.detail : undefined;
    const violations = (found as { violations?: Record<string, string[]> } | undefined)?.violations;
    const detail = violations
      ? " — " + Object.entries(violations).map(([version, said]) => `${version}: ${said.join(" / ")}`).join(" · ")
      : "";
    redirect(`/virtual-workers?error=${encodeURIComponent(message(cause) + detail)}` as Route);
  }
  revalidatePath("/virtual-workers");
  redirect("/virtual-workers" as Route);
}

/** 멈추기·다시 쓰기 (CON-13) — **상태만** 바꾼다. 멈춤은 새 작업을 막지 않는다 (C5). */
export async function setVirtualWorkerState(id: string, state: string): Promise<ActionResult> {
  try {
    const now = await center.virtualWorker(id);
    await center.updateVirtualWorker(id, {
      id,
      name: now.name,
      supervisors: now.supervisors ?? [],
      intake: now.intake,
      state,
    });
  } catch (cause) {
    return { error: message(cause) };
  }
  revalidatePath("/virtual-workers", "layout");
  return {};
}

/** 등록 해제 (CON-13) — **등록만** 지운다. 실행·작업 기록은 남는다. */
export async function deleteVirtualWorker(id: string): Promise<ActionResult> {
  try {
    await center.deleteVirtualWorker(id);
  } catch (cause) {
    return { error: message(cause) };
  }
  revalidatePath("/virtual-workers", "layout");
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

  if (!botId || !version) fail("배포할 Bot과 버전을 고르세요.");
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
    if (targets.length === 0) fail("배포할 Bot UI를 하나 이상 고르세요.");
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
