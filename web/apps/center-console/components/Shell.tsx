import Link from "next/link";
import type { Route } from "next";
import { BpmMark, Button } from "@chaeksas/ui";
import { logout } from "@/app/actions";
import type { Mode } from "@/lib/session";
import { Refresh } from "./Refresh";

/**
 * CON-00 공통 틀 — 화면 폭 전체의 남색 위 막대 + 그 아래 남색 왼쪽 탐색 + 본문 (NowView와 같은 틀).
 *
 * 폭·높이는 토큰을 쓴다 (`nav.width` 224, `topbar.height` 48). 남색은 `.chrome`이 토큰을 바꿔 끼운다. 아직 없는 화면은 **끄고 이유를
 * 가까이에 적는다** (U3) — 「M3에서」처럼.
 */

/**
 * 탐색 한 줄. **아직 없는 화면에는 `href`가 없다** — 끄고 이유(`later`)를 말풍선에 보인다 (U3).
 * 그래야 타입 라우트(`typedRoutes`)가 없는 주소를 잡아 준다.
 *
 * **`later`에 마일스톤 이름을 적지 않는다** — 지나간 마일스톤을 가리키면 다음 사람이 「그쪽
 * 몫이구나」로 읽고 넘어간다. 공백 번호(`docs/09-gaps.md`)를 적는다.
 *
 * **아직 오지 않은 마일스톤은 예외다.** 「서버 실행」(CON-12)은 C12·서버 실행기가 통째로 M7
 * 몫이라 공백 목록에 줄이 없다 — 가리킬 공백 번호가 없으니 마일스톤을 적는다. 규칙이 막으려던
 * 것은 **끝난** 마일스톤을 가리켜 「남의 몫」으로 읽히는 쪽이다.
 */
type NavItem =
  // `Route`로 적는다 — 리터럴 **합집합**을 `Link`에 넘기면 타입 라우트가 그중 하나로만
  // 좁혀 보고 나머지를 거부한다 (화면을 더할 때마다 깨졌다).
  | { label: string; href: Route; later?: never; adminOnly?: boolean }
  | { label: string; href?: never; later: string; adminOnly?: boolean };

/** 꺼진 줄에 붙는 짧은 표시. 이유는 말풍선에 있다. */
const LATER_BADGE = "아직";

/**
 * 상위 메뉴 다섯 (CON-00 [N]). **지금 화면이 든 것만 펼쳐** 열리고 누르면 접고 편다 — `<details>`라
 * JS가 없어도 된다.
 */
const NAV: Array<{ label: string; items: NavItem[] }> = [
  {
    label: "운영 현황",
    items: [
      { label: "프로세스", href: "/bots" },
      { label: "앱", href: "/bot-uis" },
    ],
  },
  {
    // 같은 둘(프로세스·앱)을 「지금 모습」(위)과 「지나온 이력」(여기)으로 가른다 (ADR-0121).
    label: "로그",
    items: [
      { label: "프로세스", href: "/runs" },
      { label: "앱", href: "/app-logs" },
    ],
  },
  {
    label: "업무",
    items: [
      { label: "결재함", href: "/approvals" },
      { label: "작업 지시", href: "/jobs" },
    ],
  },
  {
    label: "배포·자원",
    items: [
      { label: "공통 패키지", href: "/packages" },
      { label: "배포", href: "/deployments" },
      { label: "리소스", href: "/resources" },
    ],
  },
  {
    label: "관리",
    items: [
      // 계정을 보는 것도 관리자의 일이다 (C5 `GET /accounts`) — 보기 전용에는 줄이 없다.
      { label: "관리자 계정", href: "/accounts", adminOnly: true },
    ],
  },
];

export function Shell({
  mode,
  actor,
  current,
  children,
}: {
  mode: Mode;
  actor: string;
  current: string;
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen">
      {/* 남색 위 막대 — 화면 폭 전체 (NowView와 같은 틀, 스타일 가이드 §4-1). 이름 대신 마크다 (ADR-0118). */}
      <header
        className="chrome fixed inset-x-0 top-0 z-40 flex items-center gap-3 border-b-2 border-chrome-edge px-5"
        style={{ height: "var(--size-topbar-height)" }}
      >
        <Link href="/" title="첫 화면" className="mr-auto flex items-center rounded-md">
          <BpmMark label="첫 화면" className="h-6 w-auto" />
        </Link>
        <span className="text-body-sm whitespace-nowrap">
          {actor}
          <span className="text-text-muted"> · {mode === "admin" ? "관리자" : "보기 전용"}</span>
        </span>
        <Refresh />
        <form action={logout}>
          <Button type="submit" variant="ghost" size="sm">
            로그아웃
          </Button>
        </form>
      </header>

      <nav
        aria-label="주요 탐색"
        className="chrome chrome-side fixed bottom-0 left-0 z-30 overflow-y-auto p-3"
        style={{ top: "var(--size-topbar-height)", width: "var(--size-nav-width)" }}
      >
        <ul className="flex flex-col gap-1">
          {NAV.map((group) => {
            const items = group.items.filter((item) => !item.adminOnly || mode === "admin");
            if (items.length === 0) return null;
            return (
              <li key={group.label}>
                <details open={items.some((item) => item.href === current)} className="group">
                  <summary className="flex cursor-pointer list-none items-center justify-between rounded-md px-3 py-2 text-body font-semibold hover:bg-bg-subtle [&::-webkit-details-marker]:hidden">
                    {group.label}
                    <span aria-hidden className="text-caption text-text-muted transition-transform group-open:rotate-90">
                      ▸
                    </span>
                  </summary>
                  <ul className="mb-2 ml-4 flex flex-col gap-1 border-l border-border-default pl-2">
                    {items.map((item) => (
                      <li key={item.label}>
                        <NavLink item={item} current={current} />
                      </li>
                    ))}
                  </ul>
                </details>
              </li>
            );
          })}
        </ul>
      </nav>

      <main
        className="page-main min-w-0 p-6"
        style={{
          marginTop: "var(--size-topbar-height)",
          marginLeft: "var(--size-nav-width)",
        }}
      >
        <Crumb current={current} />
        {children}
      </main>
    </div>
  );
}

/**
 * 머리 띠의 맨 위 줄 — 지금 자리 「<상위 메뉴> › <메뉴 줄>」 (CON-00 [H]). 메뉴 줄은 그 목록으로 가는 링크다.
 * 띠(흰 바탕·구분선)는 `.page-crumb`과 바로 뒤의 제목 `<header>`를 공용 스타일이 함께 칠한다 — 화면마다 고치지 않으려고다.
 */
function Crumb({ current }: { current: string }) {
  const group = NAV.find((one) => one.items.some((item) => item.href === current));
  const item = group?.items.find((one) => one.href === current);
  return (
    <nav aria-label="지금 자리" className="page-crumb text-body text-text-secondary">
      {group && item?.href ? (
        <>
          {group.label} ›{" "}
          <Link href={item.href} className="hover:text-text-primary hover:underline">
            {item.label}
          </Link>
        </>
      ) : null}
    </nav>
  );
}

function NavLink({ item, current }: { item: NavItem; current: string }) {
  if (item.later) {
    return (
      <span
        className="flex items-center justify-between rounded-md px-3 py-1.5 text-body-sm text-text-muted"
        title={item.later}
      >
        {item.label}
        <span className="text-caption">{LATER_BADGE}</span>
      </span>
    );
  }
  return (
    <Link
      href={item.href!}
      aria-current={current === item.href ? "page" : undefined}
      className={
        current === item.href
          ? "block rounded-md bg-primary px-3 py-1.5 text-body-sm font-semibold text-primary-fg"
          : "block rounded-md px-3 py-1.5 text-body-sm hover:bg-bg-subtle"
      }
    >
      {item.label}
    </Link>
  );
}
