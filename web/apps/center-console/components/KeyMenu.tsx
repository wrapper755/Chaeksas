"use client";

import { useState, useTransition } from "react";
import type { CenterKeyInfo } from "@chaeksas/api-types/c7-center-key-info";
import { Button, ConfirmDialog, ErrorBanner } from "@chaeksas/ui";
import { deleteCenterKey, revokeCenterKey, unbindCenterKey, type ActionResult } from "@/app/actions";
import { keyActions, type KeyAction } from "@/lib/center-keys";

const ACTION_LABEL: Record<KeyAction, string> = {
  revoke: "키 폐기...",
  unbind: "묶음 풀기...",
  delete: "삭제...",
};

/**
 * 키 하나의 「...」 (CON-11 「키 동작」) — **그 키에만** 건다. 폐기된 키는 「삭제...」만 있다(되살리지 않는다).
 * 그 키가 가리키는 것을 보는 화면(Bot·Studio·서버 실행기·일꾼 폴더)이 그린다 — 키만 모아 보는 화면은 없다 (ADR-0124).
 * 확인 창에는 이름·앞자리·연결된 대상을 보여 고른 키가 맞는지 한 번 더 보게 한다.
 */
export function KeyMenu({ row }: { row: CenterKeyInfo }) {
  const { actions } = keyActions(row);
  const [menu, setMenu] = useState(false);
  const [asking, setAsking] = useState<KeyAction | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [working, start] = useTransition();

  function run(action: () => Promise<ActionResult>) {
    start(async () => {
      const done = await action();
      setError(done.error ?? null);
      setAsking(null);
    });
  }

  const what = (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-body">
      <dt className="text-text-secondary">이름</dt>
      <dd>{row.name}</dd>
      <dt className="text-text-secondary">앞자리</dt>
      <dd className="font-mono text-body-sm">{row.prefix ? `${row.prefix}…` : "—"}</dd>
      <dt className="text-text-secondary">연결된 대상</dt>
      <dd>{row.bound_to ? (row.bound_to.name ?? row.bound_to.id) : "등록 전"}</dd>
    </dl>
  );

  return (
    <div className="relative flex flex-col items-start gap-1">
      <Button
        size="sm"
        variant="ghost"
        aria-label={`${row.name} 키 동작`}
        disabled={working}
        onClick={() => setMenu(!menu)}
      >
        ...
      </Button>
      {menu ? (
        <ul className="absolute right-0 top-full z-10 flex min-w-[160px] flex-col border border-border-default bg-bg-surface py-1 shadow-md">
          {actions.map((action) => (
            <li key={action}>
              <button
                type="button"
                className="w-full px-3 py-2 text-left text-body hover:bg-bg-subtle"
                onClick={() => {
                  setMenu(false);
                  setError(null);
                  setAsking(action);
                }}
              >
                {ACTION_LABEL[action]}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {error ? <ErrorBanner message={error} /> : null}

      <ConfirmDialog
        open={asking === "revoke"}
        title="이 키를 폐기할까요?"
        description="이 키를 쓰는 쪽의 요청이 바로 거부됩니다. 실행 중인 프로세스는 끝까지 돕니다. 되돌릴 수 없습니다."
        confirmLabel="폐기"
        onConfirm={() => run(() => revokeCenterKey(row.key_id))}
        onCancel={() => setAsking(null)}
      >
        {what}
      </ConfirmDialog>
      <ConfirmDialog
        open={asking === "unbind"}
        title="PC 묶음을 풀까요?"
        description="다음 등록이 새 PC에 묶입니다. PC를 다시 설치한 경우에만 쓰세요."
        confirmLabel="묶음 풀기"
        danger={false}
        onConfirm={() => run(() => unbindCenterKey(row.key_id))}
        onCancel={() => setAsking(null)}
      >
        {what}
      </ConfirmDialog>
      <ConfirmDialog
        open={asking === "delete"}
        title="이 키를 삭제할까요?"
        description="목록에서 이 키를 지웁니다. 되돌릴 수 없습니다. 실행 기록·결재는 남고, 이 키가 묶였던 PC·서버 자리는 새 키가 이어받을 수 있게 놓입니다."
        confirmLabel="삭제"
        onConfirm={() => run(() => deleteCenterKey(row.key_id))}
        onCancel={() => setAsking(null)}
      >
        {what}
      </ConfirmDialog>
    </div>
  );
}
