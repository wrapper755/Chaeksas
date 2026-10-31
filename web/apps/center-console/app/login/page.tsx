import { BpmMark } from "@chaeksas/ui";
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
    <div className="flex min-h-screen flex-col">
      {/* 화면 폭 전체의 머리 — INNONOW 로고와 문구 (ADR-0120). 어두우면 밝은 판 로고를 쓴다. */}
      <header className="border-b border-border-default bg-bg-surface">
        <div className="mx-auto flex max-w-[1080px] flex-col gap-4 px-6 py-10">
          <picture>
            <source srcSet="/brand/logo-innonow-ivory.png" media="(prefers-color-scheme: dark)" />
            <img src="/brand/logo-innonow-navy.png" alt="INNONOW" width={717} height={120} className="h-7 w-auto" />
          </picture>
          <h1 className="text-display font-bold">AI와 함께, 경영을 실행합니다.</h1>
          <p className="text-body-lg text-text-secondary">Management Transformation in Action.</p>
        </div>
      </header>
      {/* 배경 그림 — BPM 흐름과 AI(신경망)를 떠올리게 한다. Gemini 이미지 모델로 만들었다 (ADR-0120). */}
      <main
        className="flex flex-1 items-center justify-center bg-cover bg-center p-6"
        style={{ backgroundImage: "url(/brand/login-bg.webp)" }}
      >
        <div className="flex w-full max-w-[400px] flex-col gap-6 rounded-xl border border-border-default bg-bg-surface p-8 shadow-sm">
          <BpmMark className="h-8 w-auto self-center text-primary" />
          <LoginForm note={changed === "1" ? "비밀번호를 바꿨습니다. 새 비밀번호로 들어오세요." : undefined} />
        </div>
      </main>
    </div>
  );
}
