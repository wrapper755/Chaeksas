import type { Route } from "next";

import type { ConsolePage } from "./console-pages.generated";
import { CONSOLE_PAGES } from "./console-pages.generated";

/**
 * 확장이 기여한 콘솔 화면(C13 `console.pages`) → **이 콘솔 안의 경로** (ADR-0042 §2).
 *
 * 화면 모듈은 Next.js 번들에 들어가야 하므로 **여기 적힌 것만** 열린다 — 브라우저가 바깥 주소로
 * 동적 `import()`를 여는 길을 내지 않는다 (ADR-0017). 그래서 모노레포 안 내장·사내 확장만
 * 화면을 올릴 수 있다 (외부 확장은 코드 기여 금지, C13 E1).
 *
 * 화면을 하나 만들면 `app/`에 경로를 더하고 여기 한 줄을 적는다. **목록 자체는 손으로 적지
 * 않는다** — `console-pages.generated.ts`가 확장 정의에서 온다.
 *
 * 값이 `Route`라서 **없는 경로를 적으면 타입 검사에서 걸린다** (Next의 typedRoutes) — 끊긴
 * 링크를 화면에 내보내지 않는다.
 */
export const CONSOLE_MODULES: Record<string, Route> = {
  // 예: "ui-automation/overview": "/ext/ui-automation/overview",
};

/** 아직 화면이 없는 줄에 붙일 사유 (U3 — 없는 것은 끄고 이유를 가까이 적는다). */
export const NO_MODULE = "이 화면은 아직 없습니다 (docs/09-gaps.md §4-7).";

export interface PageLink {
  label: string;
  /** 열 수 있는 화면이면 경로, 아직 없으면 `null`. */
  href: Route | null;
  module: string;
}

/**
 * 그 확장이 기여한 화면들 — **줄은 기여에서 오고, 열리는지는 레지스트리가 정한다.**
 *
 * `extension`이 없으면(확장의 서버 부분이 아닌 앱) 빈 목록이다. 전에는 콘솔에 세 줄이 손으로
 * 적혀 있어서 확장을 더해도 줄이 생기지 않았다.
 */
export function pagesOf(extensionId: string | null | undefined): PageLink[] {
  if (!extensionId) return [];
  return (CONSOLE_PAGES[extensionId] ?? []).map((page: ConsolePage) => ({
    label: page.label,
    href: CONSOLE_MODULES[page.module] ?? null,
    module: page.module,
  }));
}
