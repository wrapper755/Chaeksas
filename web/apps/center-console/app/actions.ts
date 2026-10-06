"use server";

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
