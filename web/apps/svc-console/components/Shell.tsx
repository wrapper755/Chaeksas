import Link from "next/link";
import { Button, StatusBadge } from "@chaeksas/ui";
import type { AdminStatus } from "@chaeksas/api-types/c11-admin-status";
import { logout } from "@/app/actions";
import { Refresh } from "./Refresh";

/**
 * SVC-00 공통 틀 — 왼쪽 탐색 + 위 막대(앱 이름·버전·상태·새로 고침) + 본문.
 *
 * 탐색은 **공통 세 화면 + 접속한 앱의 고유 메뉴**다. 고유 메뉴는 `app_id`로 고른다 — 콘솔 한 벌이
 * 모든 서비스 앱을 그리기 때문이다. 아직 없는 화면은 **끄고 이유를 가까이에 적는다** (U3).
 */

type NavItem =
  | { label: string; href: "/status" | "/keys" | "/usage"; later?: never }
  | { label: string; href?: never; later: string };

const COMMON: NavItem[] = [
  { label: "상태", href: "/status" },
  { label: "API 키", href: "/keys" },
  { label: "사용 기록", href: "/usage" },
];

/**
 * 앱 고유 메뉴. 확장이 기여하는 화면이고(`console.pages`, ADR-0018) 실제 구현은 M4다 —
 * 지금은 어떤 메뉴가 생길지만 보인다.
 */
const APP_PAGES: Record<string, NavItem[]> = {
  "ui-automation": [
    { label: "개요", later: "M4" },
    { label: "셀렉터", later: "M4" },
    { label: "모니터링", later: "M4" },
  ],
};

/** 앱 상태 한 마디 (status_map 「서비스 앱」). 의존이 하나라도 성치 않으면 「저하」다. */
export function appState(status: AdminStatus | null): string {
  if (!status) return "응답 없음";
  const bad = (status.dependencies ?? []).some((found) => found.status !== "ok");
  return bad ? "저하" : "정상";
}

export function Shell({
  status,
  actor,
  appUrl,
  current,
  children,
}: {
  status: AdminStatus | null;
  actor: string;
  appUrl: string;
  current: string;
  children: React.ReactNode;
}) {
  const nav = [...COMMON, ...(status ? (APP_PAGES[status.app_id] ?? []) : [])];
  return (
    <div className="flex min-h-screen">
      <nav
        aria-label="주요 탐색"
        className="shrink-0 border-r border-border-default bg-bg-surface p-3"
        style={{ width: "var(--size-nav-width)" }}
      >
        <p className="px-2 pb-3 text-h3 font-bold">{status?.name ?? "서비스 앱"}</p>
        <ul className="flex flex-col gap-1">
          {nav.map((item) => (
            <li key={item.label}>
              {item.later ? (
                <span
                  className="flex items-center justify-between rounded-md px-3 py-2 text-body text-text-muted"
                  title={`${item.later}에서 만듭니다.`}
                >
                  {item.label}
                  <span className="text-caption">{item.later}</span>
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
          <div className="flex min-w-0 items-center gap-3">
            <p className="truncate text-body-sm text-text-secondary">
              {status ? `${status.name} ${status.version}` : "앱"} · <span className="font-mono">{appUrl}</span>
            </p>
            <StatusBadge group="서비스 앱" label={appState(status)} />
          </div>
          <div className="flex items-center gap-3">
            <Refresh />
            <span className="text-body-sm">
              관리자<span className="text-text-muted"> · {actor}</span>
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
