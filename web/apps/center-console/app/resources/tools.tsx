"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";
import { Button } from "@chaeksas/ui";

/**
 * 「새로 고침」 — 바로 다시 읽는다. Center는 바깥 기능을 읽으러 가지 않으므로(ADR-0102) 콘솔이
 * Center의 목록을 다시 받을 뿐이다 — 상태는 일꾼이 가져갈 때 바뀐다.
 */
export function RefreshResources() {
  const router = useRouter();
  const [pending, start] = useTransition();
  return (
    <Button variant="secondary" disabled={pending} onClick={() => start(() => router.refresh())}>
      {pending ? "읽는 중..." : "새로 고침"}
    </Button>
  );
}
