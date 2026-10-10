"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Button, ConfirmDialog, ErrorBanner } from "@chaeksas/ui";
import { deletePackage } from "@/app/actions";

/**
 * CON-02 관리자 「삭제...」 — **지울 버전을 골라** 지운다.
 *
 * CON-06의 「삭제...」와 **같은 서버 액션**을 쓴다 (C5 `DELETE /packages`) — 배포나 다른
 * 패키지가 참조하면 409 `in_use`라 **아무것도 지워지지 않고** 막은 쪽을 그 자리에 보인다.
 * 되돌릴 수 없으므로 확인 창을 거치고 **기본은 「취소」**다 (U9).
 */
export function DeleteVersion({ rows }: { rows: Array<{ id: string; version: string }> }) {
  const [chosen, setChosen] = useState("");
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const router = useRouter();

  // `id@version`을 가른다 — 한 자리에서만 쪼개 **빈 값이 액션으로 가지 않게** 한다.
  const [packageId = "", version = ""] = chosen ? chosen.split("@") : [];

  return (
    <div className="flex flex-col gap-2 border-t border-border-default pt-3">
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-body-sm">
          삭제할 버전
          <select
            value={chosen}
            onChange={(event) => setChosen(event.target.value)}
            className="h-9 border border-border-default bg-bg-surface px-2"
          >
            <option value="">(고르세요)</option>
            {rows.map((row) => (
              <option key={`${row.id}@${row.version}`} value={`${row.id}@${row.version}`}>
                {row.id}@{row.version}
              </option>
            ))}
          </select>
        </label>
        <Button variant="danger" disabled={!chosen || pending} onClick={() => setAsking(true)}>
          삭제...
        </Button>
      </div>
      {error ? <ErrorBanner message={error} /> : null}
      <ConfirmDialog
        open={asking}
        title={`${packageId} ${version}을 지울까요?`}
        description="되돌릴 수 없습니다. 살아 있는 배포나 다른 패키지가 참조하면 지워지지 않습니다."
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
            setChosen("");
            setError(null);
            router.refresh();
          })
        }
        onCancel={() => setAsking(false)}
      />
    </div>
  );
}
