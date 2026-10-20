"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Button, ConfirmDialog, ErrorBanner } from "@chaeksas/ui";
import { deleteVirtualWorker, setVirtualWorkerState } from "@/app/actions";

/** CON-13 관리자 모드 — 멈추기·다시 쓰기, 등록 해제. 해제는 확인 창, 기본 「취소」 (U9). */
export function WorkerTools({ id, state }: { id: string; state: string }) {
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const router = useRouter();
  const stopped = state === "stopped";

  return (
    <div className="mt-4 flex flex-col gap-2">
      <div className="flex flex-wrap gap-2">
        <Button
          variant="secondary"
          disabled={pending}
          onClick={() =>
            start(async () => setError((await setVirtualWorkerState(id, stopped ? "active" : "stopped")).error ?? null))
          }
        >
          {stopped ? "다시 쓰기" : "멈추기"}
        </Button>
        <Button variant="danger" disabled={pending} onClick={() => setAsking(true)}>
          등록 해제...
        </Button>
      </div>
      {error ? <ErrorBanner message={error} /> : null}
      <ConfirmDialog
        open={asking}
        title="이 가상 직원의 등록을 해제할까요?"
        description="등록만 지웁니다. 실행·작업 기록은 남습니다."
        confirmLabel="등록 해제"
        onConfirm={() =>
          start(async () => {
            const done = await deleteVirtualWorker(id);
            setAsking(false);
            if (done.error) setError(done.error);
            else router.push("/virtual-workers");
          })
        }
        onCancel={() => setAsking(false)}
      />
    </div>
  );
}
