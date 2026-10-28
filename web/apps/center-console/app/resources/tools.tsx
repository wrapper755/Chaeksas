"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { Button, ConfirmDialog, ErrorBanner } from "@chaeksas/ui";
import { revokeExtension } from "@/app/actions";

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
