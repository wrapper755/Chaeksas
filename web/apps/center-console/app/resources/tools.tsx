"use client";

import { useState, useTransition } from "react";
import { Button, ConfirmDialog, ErrorBanner } from "@chaeksas/ui";
import { refreshResources, revokeExtension, unregisterServiceApp } from "@/app/actions";

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
export function UnregisterServiceApp({ appId, users = [] }: { appId: string; users?: string[] }) {
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
        description={`${users.length > 0 ? `쓰는 Bot: ${users.join(", ")} — 쓰는 Bot이 있으면 해제되지 않습니다.` : "쓰는 Bot이 없습니다."} 해제하면 그 주소를 Center가 더 알지 못합니다.`}
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

/**
 * 외부 확장 「등록 해제...」 (CON-07 상세). Center가 철회 봉투에 서명한다 (ADR-0090).
 * **쓰는 Bot이 있어도 막지 않는다** (C13 — 보안 동작이다). 되살릴 수 없어 기본은 「취소」다 (U9).
 */
export function RevokeExtension({ extensionId, version, users }: { extensionId: string; version: string; users: number }) {
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  return (
    <div className="flex flex-col gap-2">
      <div>
        <Button variant="danger" disabled={pending} onClick={() => setAsking(true)}>
          등록 해제...
        </Button>
      </div>
      {error ? <ErrorBanner message={error} /> : null}
      <ConfirmDialog
        open={asking}
        title={`${extensionId} ${version}의 등록을 해제할까요?`}
        description={`${users > 0 ? `이 정의를 쓰는 Bot ${users}개가 실행 불가가 됩니다. ` : ""}되살릴 수 없습니다.`}
        confirmLabel="등록 해제"
        danger
        onConfirm={() =>
          start(async () => {
            // 성공하면 액션이 목록으로 보낸다 — 돌아오는 것은 실패뿐이다.
            setError((await revokeExtension(extensionId, version)).error ?? null);
            setAsking(false);
          })
        }
        onCancel={() => setAsking(false)}
      />
    </div>
  );
}
