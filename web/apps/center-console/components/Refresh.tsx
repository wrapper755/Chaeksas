"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";
import { Button } from "@chaeksas/ui";

/**
 * CON-00 위 막대 「새로 고침」 — 지금 화면을 Center에서 다시 읽는다. 브라우저는 다시 그려 달라고만
 * 하고 Center를 부르는 것은 서버 쪽이다(`router.refresh()` — 토큰은 여기 오지 않는다).
 */
export function Refresh() {
  const router = useRouter();
  const [pending, start] = useTransition();
  return (
    <Button variant="ghost" size="sm" disabled={pending} onClick={() => start(() => router.refresh())}>
      {pending ? "읽는 중..." : "새로 고침"}
    </Button>
  );
}
