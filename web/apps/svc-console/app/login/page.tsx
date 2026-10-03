"use client";

import { useActionState } from "react";
import { Button, ErrorBanner, Field } from "@chaeksas/ui";
import { login, type ActionResult } from "@/app/actions";

/**
 * 로그인 (SVC-00 「관리자 토큰(앱 설정)으로 들어간다」). OIDC는 나중이다.
 *
 * 토큰은 **콘솔 서버가 암호화된 httpOnly 쿠키에 담아 들고** 브라우저에 내려가지 않는다.
 */
export default function LoginPage() {
  const [result, action, pending] = useActionState<ActionResult, FormData>(login, {});
  return (
    <main className="mx-auto flex min-h-screen max-w-[480px] flex-col justify-center gap-4 p-6">
      <h1 className="text-h1 font-bold">서비스 앱 관리 콘솔</h1>
      <p className="text-body text-text-secondary">
        앱 설정의 관리자 토큰으로 들어갑니다. 이 콘솔에는 보기 전용이 없습니다 — API 키를 다루기 때문입니다.
      </p>
      {result.error ? <ErrorBanner message={result.error} /> : null}
      <form action={action} className="flex flex-col gap-4">
        <Field
          label="관리자 토큰"
          name="token"
          type="password"
          required
          autoComplete="off"
          help="앱 서버의 CHK_SVC_<APP>__ADMIN_TOKEN."
        />
        <Field label="이름" name="actor" help="화면에 보일 이름입니다 (비우면 「관리자」)." />
        <Button type="submit" variant="primary" disabled={pending}>
          {pending ? "확인 중..." : "들어가기"}
        </Button>
      </form>
    </main>
  );
}
