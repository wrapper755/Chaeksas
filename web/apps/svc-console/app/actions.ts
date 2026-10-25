"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { svc, SvcError } from "@/lib/svc";
import { COOKIE_NAME, seal } from "@/lib/session";

/**
 * 쓰기 동작 — 모두 **콘솔 서버에서** 돈다 (Server Action). 브라우저는 토큰을 모른다.
 */

export interface ActionResult {
  error?: string;
  /** 발급한 키 원문 — **이 응답에만 실린다** (SVC-02). */
  secret?: { name: string; key: string };
}

function message(cause: unknown): string {
  return cause instanceof SvcError ? cause.message : "알 수 없는 오류가 생겼습니다";
}

export async function login(_previous: ActionResult, form: FormData): Promise<ActionResult> {
  const token = String(form.get("token") ?? "").trim();
  const actor = String(form.get("actor") ?? "").trim() || "관리자";
  if (!token) return { error: "관리자 토큰을 입력하세요." };

  const store = await cookies();
  store.set(COOKIE_NAME, seal({ token, actor }), {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
  });
  try {
    await svc.status();
  } catch (cause) {
    store.delete(COOKIE_NAME);
    return { error: message(cause) };
  }
  redirect("/status");
}

export async function logout(): Promise<void> {
  (await cookies()).delete(COOKIE_NAME);
  redirect("/login");
}

export async function revokeKey(name: string): Promise<ActionResult> {
  try {
    await svc.revokeKey(name);
  } catch (cause) {
    return { error: message(cause) };
  }
  revalidatePath("/keys");
  return {};
}
