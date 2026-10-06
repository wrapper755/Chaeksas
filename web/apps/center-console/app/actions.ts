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
