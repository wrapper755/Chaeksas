"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Button, ConfirmDialog, ErrorBanner } from "@chaeksas/ui";
import { revokeDeployment } from "@/app/actions";

/**
 * CON-15 「철회...」 — **되살릴 수 없어** 확인 창을 거치고 기본은 「취소」다 (U9).
 * Center가 철회 봉투에 서명하고, 현장은 다음 하트비트에 그 BPM 프로세스를 내린다.
 */
export function RevokeDeployment({ deploymentId, label }: { deploymentId: string; label: string }) {
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const router = useRouter();
  return (
    <div className="flex flex-col gap-1">
      <Button size="sm" variant="danger" disabled={pending} onClick={() => setAsking(true)}>
        철회...
      </Button>
      {error ? <ErrorBanner message={error} /> : null}
      <ConfirmDialog
        open={asking}
        title={`${label} 배포를 철회할까요?`}
        description="현장은 다음 하트비트에 이 BPM 프로세스를 내립니다. 도는 실행은 끝까지 갑니다. 되돌릴 수 없습니다 — 다시 쓰려면 새로 배포하세요."
        confirmLabel="철회"
        danger
        onConfirm={() =>
          start(async () => {
            const result = await revokeDeployment(deploymentId);
            setAsking(false);
            setError(result.error ?? null);
            if (!result.error) router.refresh();
          })
        }
        onCancel={() => setAsking(false)}
      />
    </div>
  );
}
