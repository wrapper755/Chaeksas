/** 웹 쪽 단위 시험 (CON-02 집계). **화면을 모르는 함수만** 여기서 잰다.
 *
 * 들인 까닭은 09-gaps §4-9다 — 성공률·재생률·확인률·표본을 세는 것이 TypeScript이고 `pnpm
 * typecheck`·`pnpm build`로는 **셈이 틀려도 잡히지 않았다**. 2026-10-11에 「시험 판을 들이지
 * 않는다」로 한 번 정했다가 뒤집은 것이다 (덮어쓰기 흠을 한 번 겪은 자리다).
 *
 * **브라우저도 React도 띄우지 않는다** — 그래서 jsdom·플러그인이 필요 없고 CI에 한 걸음만 는다.
 */
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["apps/*/lib/**/*.test.ts", "packages/*/src/**/*.test.ts"],
    environment: "node",
  },
});
