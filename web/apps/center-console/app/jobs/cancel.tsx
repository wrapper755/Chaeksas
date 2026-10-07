"use client";

import { useState, useTransition } from "react";
import { Button, ErrorBanner } from "@chaeksas/ui";
import { cancelJob } from "@/app/actions";

/**
 * CON-05 「취소」 — 대기·전달됨·대기열 작업만 (C5 「취소」 표).
 *
 * 대기는 바로 「취소됨」이 되고, 전달됨·대기열은 **현장에 물어본다** — 화면은 「취소 요청함 —
 * 다음 하트비트에 반영」을 보이고, 그사이 시작됐으면 「취소 못 함 — 이미 시작됨」이 붙는다.
 * 그 글은 목록이 Center의 `cancel_requested`·`cancel_result`에서 다시 그린다 (지어내지 않는다).
 */
export function CancelJob({ jobId }: { jobId: string }) {
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();

  function apply() {
    start(async () => {
      const result = await cancelJob(jobId);
      setError(result.error ?? null);
    });
  }

  return (
    <div className="flex flex-col gap-1">
      <Button variant="secondary" size="sm" disabled={pending} onClick={apply}>
        취소
      </Button>
      {error ? <ErrorBanner message={error} /> : null}
    </div>
  );
}
