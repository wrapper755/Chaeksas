"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";
import { Button } from "@chaeksas/ui";

/** SVC-00 위 막대의 「새로 고침」. 서버 구성요소를 다시 그린다 (값을 브라우저에 캐시하지 않는다). */
export function Refresh() {
  const router = useRouter();
  const [working, start] = useTransition();
  return (
    <Button variant="secondary" size="sm" disabled={working} onClick={() => start(() => router.refresh())}>
      {working ? "새로 고치는 중..." : "새로 고침"}
    </Button>
  );
}
