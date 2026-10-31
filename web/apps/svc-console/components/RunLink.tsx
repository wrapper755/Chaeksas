import { centerRunUrl } from "@/lib/center-link";

/**
 * 「실행 id」 칸 — 이을 수 있으면 CON-01 실행 상세로 가는 링크, 아니면 글자 그대로 (ADR-0075).
 *
 * Center 콘솔은 **다른 주소**라 Next.js `Link`가 아니라 보통 `<a>`다. `text`는 보이는 글
 * `runId`는 잇는 대상이다.
 */
export function RunLink({ base, runId, text }: { base: string; runId: string | null; text: string }) {
  const href = centerRunUrl(base, runId);
  if (!href) return <>{text}</>;
  return (
    <a className="underline" href={href} title="Center 콘솔의 실행 상세(CON-01)">
      {text}
    </a>
  );
}
