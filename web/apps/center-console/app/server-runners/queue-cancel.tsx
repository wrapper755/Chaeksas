"use client";

import { useState, useTransition } from "react";
import { Button, ConfirmDialog, ErrorBanner } from "@chaeksas/ui";
import { cancelJob } from "@/app/actions";

/**
 * CON-12 대기열의 「취소...」 — **CON-05와 같은 길**이다 (같은 서버 액션, C5 `DELETE /jobs/{id}`).
 *
 * 여기 줄은 아직 내려가지 않은 작업뿐이라 취소가 **바로** 끝난다 (「전달됨」부터는 현장에
 * 물어본다 — 그 글은 CON-05가 `cancel_requested`로 그린다). 그래도 확인 창을 띄우는 까닭은
 * 되돌릴 길이 없어서다 — 다시 돌리려면 작업을 새로 만들어야 한다.
 */
export function CancelQueuedJob({ jobId, bot }: { jobId: string; bot: string }) {
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();

  function apply() {
    start(async () => {
      const result = await cancelJob(jobId);
      setError(result.error ?? null);
      setAsking(false);
    });
  }

  return (
    <div className="flex flex-col gap-1">
      <Button variant="secondary" size="sm" disabled={pending} onClick={() => setAsking(true)}>
        취소...
      </Button>
      {error ? <ErrorBanner message={error} /> : null}
      <ConfirmDialog
        open={asking}
        title="이 작업을 취소할까요?"
        description={`${bot}은(는) 돌지 않습니다. 되돌리려면 작업을 새로 만들어야 합니다.`}
        confirmLabel="취소하기"
        onConfirm={apply}
        onCancel={() => setAsking(false)}
      />
    </div>
  );
}
