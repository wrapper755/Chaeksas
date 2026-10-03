"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { svc, SvcError, type KeyCreateInput } from "@/lib/svc";
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

export async function createKey(_previous: ActionResult, form: FormData): Promise<ActionResult> {
  const name = String(form.get("name") ?? "").trim();
  if (!name) return { error: "이름을 입력하세요." };

  // 「모든 작업」이면 `*` 하나로 보낸다 (C11).
  const operations = form.getAll("operations").map(String).filter(Boolean);
  const body: KeyCreateInput = {
    name,
    allowed_operations: operations.length > 0 ? operations : ["*"],
    // 기본은 **결정 수행만** — 운영 Bot용 키가 자율 수행을 하지 않게 (SVC-02).
    allowed_modes: String(form.get("modes") ?? "deterministic") === "both"
      ? ["autonomous", "deterministic"]
      : ["deterministic"],
    extra_scopes: form.getAll("scopes").map(String).filter(Boolean),
  };
  const note = String(form.get("note") ?? "").trim();
  if (note) body.note = note;

  try {
    const created = await svc.createKey(body);
    revalidatePath("/keys");
    // 원문은 화면에 한 번만 보이고, 어디에도 저장하지 않는다.
    return { secret: { name: created.name, key: created.key } };
  } catch (cause) {
    return { error: message(cause) };
  }
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
