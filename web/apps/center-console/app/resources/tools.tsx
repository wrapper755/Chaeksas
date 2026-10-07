"use client";

import { useState, useTransition } from "react";
import { Button, ConfirmDialog, ErrorBanner } from "@chaeksas/ui";
import { refreshResources, unregisterServiceApp } from "@/app/actions";

/** 「새로 고침」 — 간격을 무시하고 서비스 앱을 **바로 다시 읽는다** (C7). */
export function RefreshResources() {
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  return (
    <div className="flex flex-col items-end gap-1">
      <Button
        variant="secondary"
        disabled={pending}
        onClick={() => start(async () => setError((await refreshResources()).error ?? null))}
      >
        {pending ? "읽는 중..." : "새로 고침"}
      </Button>
      {error ? <ErrorBanner message={error} /> : null}
    </div>
  );
}

/**
 * 「등록 해제」 — **쓰는 Bot이 있으면 막히고** 그 목록이 보인다 (C7 `in_use`).
 * 되돌릴 수 있지만 그 Bot들이 실행 불가가 되므로 확인 창을 띄우고 기본은 「취소」다 (U9).
 */
export function UnregisterServiceApp({ appId }: { appId: string }) {
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();

  return (
    <div className="flex flex-col gap-2">
      <Button variant="danger" disabled={pending} onClick={() => setAsking(true)}>
        등록 해제...
      </Button>
      {error ? <ErrorBanner message={error} /> : null}
      <ConfirmDialog
        open={asking}
        title="이 서비스 앱의 등록을 해제할까요?"
        description="이 앱을 쓰는 Bot이 있으면 해제되지 않습니다. 해제하면 그 주소를 Center가 더 알지 못합니다."
        confirmLabel="등록 해제"
        onConfirm={() =>
          start(async () => {
            setError((await unregisterServiceApp(appId)).error ?? null);
            setAsking(false);
          })
        }
        onCancel={() => setAsking(false)}
      />
    </div>
  );
}
