"use server";

import type { Route } from "next";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { center, CenterError } from "@/lib/center";
import { COOKIE_NAME, seal, type Mode } from "@/lib/session";

/**
 * 쓰기 동작 — 모두 **콘솔 서버에서** 돈다 (Server Action). 브라우저는 토큰을 모른다.
 *
 * 서명이 필요한 동작(패키지 승인·배포·철회)은 콘솔에서 하지 않는다 → Admin (CON-00).
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
  const token = String(form.get("token") ?? "").trim();
  const mode = (String(form.get("mode") ?? "read") === "admin" ? "admin" : "read") as Mode;
  const actor = String(form.get("actor") ?? "").trim() || (mode === "admin" ? "관리자" : "보기 전용");
  if (!token) return { error: "토큰을 입력하세요." };

  const store = await cookies();
  store.set(COOKIE_NAME, seal({ mode, token, actor }), {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
  });
  try {
    await center.check();
  } catch (cause) {
    store.delete(COOKIE_NAME);
    return { error: message(cause) };
  }
  redirect("/bot-uis");
}

export async function logout(): Promise<void> {
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
 * 결재 답하기 (CON-04). **일반 `<form>`이 부른다** — JS 없이도 답할 수 있다.
 *
 * 폼 칸의 타입은 **Center에 저장된 것**을 다시 읽어 맞춘다 (브라우저가 보낸 글자를 믿고
 * 타입을 정하지 않는다). 틀린 답은 Center가 칸마다 돌려주고, 그 자리로 되돌아가 보인다.
 */
export async function answerApproval(form: FormData): Promise<void> {
  const requestId = String(form.get("request_id") ?? "");
  const actor = String(form.get("actor") ?? "").trim();
  // 타입 라우트는 질의 문자열이 붙은 주소를 리터럴로 요구한다 — 한 자리에서 만든다.
  const back = (query: string): Route =>
    `/approvals/${encodeURIComponent(requestId)}?${query}` as Route;
  if (!actor) {
    redirect(back(`error=${encodeURIComponent("답하는 사람을 적으세요.")}`));
  }

  let answer: Record<string, unknown>;
  try {
    const found = await center.approval(requestId);
    answer = readAnswer(found.form?.fields ?? [], form);
  } catch (cause) {
    redirect(back(`error=${encodeURIComponent(message(cause))}`));
  }

  try {
    await center.answerApproval(requestId, answer, actor);
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
    const declared = shown ? ((await center.packageInfo(bot, shown)).manifest?.inputs ?? []) : [];
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
 * **정의 파일과 Admin 서명 봉투를 함께** 올린다 — 서명 없이는 등록되지 않는다 (C2).
 * 봉투는 `chk-admin sign-extension`이 만든다. C13 검사 결과는 Center가 칸별 사유와 함께
 * 돌려주므로 그것을 그대로 보인다.
 */
export async function registerExtension(form: FormData): Promise<void> {
  const back = (query: string): Route => `/resources?${query}` as Route;
  let definition: unknown;
  let envelope: unknown;
  try {
    definition = await jsonFile(form, "definition", "확장 정의 파일");
    envelope = await jsonFile(form, "envelope", "서명 봉투 파일");
  } catch (cause) {
    const said = cause instanceof Error ? cause.message : "파일을 읽지 못했습니다.";
    redirect(back(`tab=extension&error=${encodeURIComponent(said)}`));
  }

  try {
    await center.registerExtension(definition, envelope);
  } catch (cause) {
    redirect(back(`tab=extension&error=${encodeURIComponent(violations(cause))}`));
  }
  revalidatePath("/resources", "layout");
  redirect(back("tab=extension&extension=1"));
}

/** 등록 해제 — **봉투가 필요하다** (`extension_revoke`, `chk-admin revoke-extension`). */
export async function revokeExtension(form: FormData): Promise<void> {
  const extensionId = String(form.get("extension_id") ?? "");
  const back = (query: string): Route =>
    `/resources/extensions/${encodeURIComponent(extensionId)}?${query}` as Route;
  let envelope: unknown;
  try {
    envelope = await jsonFile(form, "envelope", "해제 봉투 파일");
  } catch (cause) {
    const said = cause instanceof Error ? cause.message : "파일을 읽지 못했습니다.";
    redirect(back(`error=${encodeURIComponent(said)}`));
  }
  try {
    await center.revokeExtension(envelope);
  } catch (cause) {
    redirect(back(`error=${encodeURIComponent(violations(cause))}`));
  }
  revalidatePath("/resources", "layout");
  redirect("/resources?tab=extension&revoked=1" as Route);
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
    redirect(back(`tab=service_app&error=${encodeURIComponent("API 주소를 적으세요.")}`));
  }
  try {
    await center.registerServiceApp(baseUrl);
  } catch (cause) {
    redirect(back(`tab=service_app&error=${encodeURIComponent(message(cause))}`));
  }
  revalidatePath("/resources", "layout");
  redirect(back("tab=service_app&registered=1"));
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

export async function unbindCenterKey(keyId: string): Promise<ActionResult> {
  try {
    await center.unbindCenterKey(keyId);
  } catch (cause) {
    return { error: message(cause) };
  }
  revalidatePath("/center-keys");
  return {};
}
