"use client";

import { useActionState } from "react";
import { Button, ErrorBanner, Field } from "@chaeksas/ui";
import { login, type ActionResult } from "@/app/actions";

/**
 * 로그인 (CON-00 「쓰기 권한」). OIDC는 나중이고, 지금은 Center 토큰을 받는다.
 *
 * 토큰은 **콘솔 서버가 암호화된 httpOnly 쿠키에 담아 들고** 브라우저에 내려가지 않는다.
 */
export default function LoginPage() {
  const [result, action, pending] = useActionState<ActionResult, FormData>(login, {});
  return (
    <main className="mx-auto flex min-h-screen max-w-[480px] flex-col justify-center gap-4 p-6">
      <h1 className="text-h1 font-bold">Center 콘솔</h1>
      <p className="text-body text-text-secondary">
        Center 토큰으로 들어갑니다. 관리자 토큰이면 쓰기 단추가 보이고, 읽기 토큰이면 보기 전용입니다.
      </p>
      {result.error ? <ErrorBanner message={result.error} /> : null}
      <form action={action} className="flex flex-col gap-4">
        <Field
          label="토큰"
          name="token"
          type="password"
          required
          autoComplete="off"
          help="서버의 CHK_CENTER__ADMIN_TOKEN 또는 CHK_CENTER__READ_TOKEN."
        />
        <Field label="이름" name="actor" help="실행 기록에 남을 이름입니다 (비우면 모드 이름)." />
        <fieldset className="flex flex-col gap-2">
          <legend className="text-body-sm font-medium">모드</legend>
          <label className="flex items-center gap-2 text-body">
            <input type="radio" name="mode" value="admin" defaultChecked /> 관리자 (쓰기)
          </label>
          <label className="flex items-center gap-2 text-body">
            <input type="radio" name="mode" value="read" /> 보기 전용
          </label>
        </fieldset>
        <Button type="submit" variant="primary" disabled={pending}>
          {pending ? "확인 중..." : "들어가기"}
        </Button>
      </form>
    </main>
  );
}
