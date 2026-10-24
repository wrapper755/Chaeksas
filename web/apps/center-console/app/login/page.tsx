import { LoginForm } from "./form";

/**
 * 로그인 (CON-00). **관리자 계정**으로 들어온다 (ADR-0090) — 역할은 계정이 정한다.
 *
 * 세션 토큰은 **콘솔 서버가 암호화된 httpOnly 쿠키에 담아 들고** 브라우저에 내려가지 않는다.
 */
export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ changed?: string }>;
}) {
  const { changed } = await searchParams;
  return (
    <main className="mx-auto flex min-h-screen max-w-[400px] flex-col justify-center gap-4 p-6">
      <h1 className="text-h1 font-bold">Center 콘솔</h1>
      <LoginForm note={changed === "1" ? "비밀번호를 바꿨습니다. 새 비밀번호로 들어오세요." : undefined} />
    </main>
  );
}
