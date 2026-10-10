"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Button, ConfirmDialog, ErrorBanner } from "@chaeksas/ui";
import { deletePackage } from "@/app/actions";

/**
 * CON-06 「삭제...」 — **되돌릴 수 없어** 확인 창을 거치고 기본은 「취소」다 (U9).
 *
 * 참조되면 409 `in_use`라 **아무것도 지워지지 않는다** — 막은 배포·패키지를 그 자리에 보인다.
 * 지워졌으면 이 상세 주소가 404가 되므로 목록으로 보낸다.
 */
export function DeletePackage({ packageId, version }: { packageId: string; version: string }) {
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const router = useRouter();

  return (
    <div className="flex flex-col gap-2">
      <Button variant="danger" disabled={pending} onClick={() => setAsking(true)}>
        삭제...
      </Button>
      {error ? <ErrorBanner message={error} /> : null}
      <ConfirmDialog
        open={asking}
        title={`${packageId}@${version}을 지울까요?`}
        description="되돌릴 수 없습니다. 배포나 다른 패키지가 참조하면 지워지지 않습니다."
        confirmLabel="삭제"
        danger
        onConfirm={() =>
          start(async () => {
            const result = await deletePackage(packageId, version);
            setAsking(false);
            if (result.error) {
              setError(result.error);
              return;
            }
            router.push("/packages");
          })
        }
        onCancel={() => setAsking(false)}
      />
    </div>
  );
}
