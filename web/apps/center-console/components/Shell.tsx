import Link from "next/link";
import type { Route } from "next";
import { Button } from "@chaeksas/ui";
import { logout } from "@/app/actions";
import type { Mode } from "@/lib/session";

/**
 * CON-00 공통 틀 — 왼쪽 탐색 + 위 막대 + 본문.
 *
 * 폭·높이는 토큰을 쓴다 (`nav.width` 232, `topbar.height` 56). 아직 없는 화면은 **끄고 이유를
 * 가까이에 적는다** (U3) — 「M3에서」처럼.
 */

/**
 * 탐색 한 줄. **아직 없는 화면에는 `href`가 없다** — 끄고 이유(`later`)를 말풍선에 보인다 (U3).
 * 그래야 타입 라우트(`typedRoutes`)가 없는 주소를 잡아 준다.
 *
 * **`later`에 마일스톤 이름을 적지 않는다** — 지나간 마일스톤을 가리키면 다음 사람이 「그쪽
 * 몫이구나」로 읽고 넘어간다. 공백 번호(`docs/09-gaps.md`)를 적는다.
 */
type NavItem =
  // `Route`로 적는다 — 리터럴 **합집합**을 `Link`에 넘기면 타입 라우트가 그중 하나로만
  // 좁혀 보고 나머지를 거부한다 (화면을 더할 때마다 깨졌다).
  | { label: string; href: Route; later?: never }
  | { label: string; href?: never; later: string };

/** 꺼진 줄에 붙는 짧은 표시. 이유는 말풍선에 있다. */
const LATER_BADGE = "아직";

const NAV: NavItem[] = [
  { label: "실행 로그", href: "/runs" },
  { label: "Bot 현황", later: "CON-02는 아직 없습니다 (docs/09-gaps.md §4-9)." },
  { label: "Bot UI 현황", href: "/bot-uis" },
  { label: "결재함", href: "/approvals" },
  { label: "작업 지시", href: "/jobs" },
  { label: "공통 패키지", href: "/packages" },
  { label: "리소스", href: "/resources" },
  { label: "Center API 키", href: "/center-keys" },
];

export function Shell({
  mode,
  actor,
  centerUrl,
  current,
  children,
}: {
  mode: Mode;
  actor: string;
  centerUrl: string;
  current: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen">
      <nav
        aria-label="주요 탐색"
        className="shrink-0 border-r border-border-default bg-bg-surface p-3"
        style={{ width: "var(--size-nav-width)" }}
      >
        <p className="px-2 pb-3 text-h3 font-bold">Chaeksas</p>
        <ul className="flex flex-col gap-1">
          {NAV.map((item) => (
            <li key={item.label}>
              {item.later ? (
                <span
                  className="flex items-center justify-between rounded-md px-3 py-2 text-body text-text-muted"
                  title={item.later}
                >
                  {item.label}
                  <span className="text-caption">{LATER_BADGE}</span>
                </span>
              ) : (
                <Link
                  href={item.href!}
                  aria-current={current === item.href ? "page" : undefined}
                  className={
                    current === item.href
                      ? "block rounded-md bg-primary-subtle px-3 py-2 text-body font-semibold text-primary"
                      : "block rounded-md px-3 py-2 text-body hover:bg-bg-subtle"
                  }
                >
                  {item.label}
                </Link>
              )}
            </li>
          ))}
        </ul>
      </nav>

      <div className="flex min-w-0 flex-1 flex-col">
        <header
          className="flex shrink-0 items-center justify-between gap-4 border-b border-border-default bg-bg-surface px-6"
          style={{ height: "var(--size-topbar-height)" }}
        >
          <p className="truncate text-body-sm text-text-secondary">
            Center: <span className="font-mono">{centerUrl}</span>
          </p>
          <div className="flex items-center gap-3">
            <span className="text-body-sm">
              {mode === "admin" ? "관리자" : "보기 전용"}
              <span className="text-text-muted"> · {actor}</span>
            </span>
            <form action={logout}>
              <Button type="submit" variant="ghost" size="sm">
                나가기
              </Button>
            </form>
          </div>
        </header>
        <main className="min-w-0 flex-1 p-6">{children}</main>
      </div>
    </div>
  );
}
