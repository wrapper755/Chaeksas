"use client";

import { useActionState } from "react";
import { Button, ErrorBanner, Field } from "@chaeksas/ui";
import { login, type ActionResult } from "@/app/actions";

/** 아이디·비밀번호 두 칸과 「로그인」 하나 (CON-00). 역할은 계정이 정한다. */
export function LoginForm({ note }: { note?: string }) {
  const [result, action, pending] = useActionState<ActionResult, FormData>(login, {});
  return (
    <>
      {note && !result.error ? <p className="text-body text-text-secondary">{note}</p> : null}
      {result.error ? <ErrorBanner message={result.error} /> : null}
      <form action={action} className="flex flex-col gap-4">
        <Field label="아이디" name="username" required autoComplete="username" autoCapitalize="none" />
        <Field label="비밀번호" name="password" type="password" required autoComplete="current-password" />
        <Button type="submit" variant="primary" disabled={pending} className="self-end">
          {pending ? "확인 중..." : "로그인"}
        </Button>
      </form>
    </>
  );
}
