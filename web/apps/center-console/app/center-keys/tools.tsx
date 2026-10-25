"use client";

import { useActionState, useState, useTransition } from "react";
import type { CenterKeyInfo } from "@chaeksas/api-types/c7-center-key-info";
import { Button, ConfirmDialog, Dialog, ErrorBanner, Field } from "@chaeksas/ui";
import { createCenterKey, revokeCenterKey, unbindCenterKey, type ActionResult } from "@/app/actions";
import { keyActions, type KeyAction } from "@/lib/center-keys";

/** CON-11 관리자 모드 — 새 키. 폐기·묶음 풀기는 줄마다의 「...」에 있다 (`KeyMenu`). */
export function KeyTools() {
  const [creating, setCreating] = useState(false);
  const [kind, setKind] = useState("integration");
  const [result, create, pending] = useActionState<ActionResult, FormData>(createCenterKey, {});
  // 결과는 `useActionState`가 쥐고 있어 지울 수 없다 — 닫은 키를 기억해 그 창만 내린다.
  const [dismissed, setDismissed] = useState<string | null>(null);
  const showing = Boolean(result.secret) && result.secret?.key !== dismissed;
  function closeSecret() {
    setDismissed(result.secret?.key ?? null);
    setCreating(false);
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="primary" onClick={() => setCreating(true)}>
          새 키...
        </Button>
      </div>

      <Dialog
        open={creating && !showing}
        title="새 Center API 키"
        onClose={() => setCreating(false)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setCreating(false)}>
              취소
            </Button>
            <Button variant="primary" type="submit" form="new-key" disabled={pending}>
              {pending ? "발급 중..." : "발급"}
            </Button>
          </>
        }
      >
        <form id="new-key" action={create} className="flex flex-col gap-4">
          {result.error ? <ErrorBanner message={result.error} /> : null}
          <Field label="이름" name="name" required help="사람이 알아볼 이름 (예: 재무팀 PC-03)." />
          <label className="flex flex-col gap-1 text-body-sm font-medium">
            종류
            <select
              name="type"
              value={kind}
              onChange={(event) => setKind(event.target.value)}
              className="border border-border-strong bg-bg-surface px-3 text-body"
              style={{ height: "var(--size-control-md)", borderRadius: "var(--radius-md)" }}
            >
              {/* Bot UI용·서버 실행기용·Studio용은 여기서 발급하지 않는다 — 등록 승인이 만든다 (ADR-0092·0093). */}
              <option value="integration">연동용</option>
              <option value="relay">대리 답용</option>
            </select>
          </label>
          {kind === "relay" ? (
            // ADR-0081 — Center는 이름이 참인지 증명하지 못한다. 발급이 곧 그 신뢰다.
            <p className="text-caption text-text-secondary">
              이 키를 가진 쪽은 결재 담당자의 이름을 대면 그 사람 대신 답할 수 있습니다. 사람 확인은 그쪽이 합니다.
            </p>
          ) : null}
          <p className="text-caption text-text-muted">만료는 기본 1년입니다.</p>
        </form>
      </Dialog>

      {/* 발급 직후 — **원문을 한 번만** 보여 준다 (C7·CON-11). */}
      <Dialog
        open={showing}
        title="키를 발급했습니다"
        onClose={closeSecret}
        footer={
          <Button variant="primary" onClick={closeSecret}>
            닫기
          </Button>
        }
      >
        <p className="text-body">
          이 키는 <strong>다시 볼 수 없습니다.</strong> 지금 복사해 연동하는 시스템에 넣으세요.
        </p>
        <p className="mt-2 font-mono text-body-sm break-all" style={{ userSelect: "all" }}>
          {result.secret?.key}
        </p>
      </Dialog>

    </div>
  );
}

const ACTION_LABEL: Record<KeyAction, string> = {
  revoke: "키 폐기...",
  unbind: "묶음 풀기...",
};

/**
 * CON-11 줄 끝의 「...」 — **그 줄의 키에만** 건다. 할 것이 없는 줄(폐기됨·만료)은 끄고 까닭을
 * 툴팁으로 말한다. 확인 창에는 이름·앞자리·연결된 대상을 보여 고른 키가 맞는지 한 번 더 보게 한다.
 */
export function KeyMenu({ row }: { row: CenterKeyInfo }) {
  const { actions, reason } = keyActions(row);
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
      <dd className="font-mono text-body-sm">{row.prefix}…</dd>
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
        disabled={actions.length === 0 || working}
        disabledReason={reason ?? undefined}
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
        description="이 키를 쓰는 쪽의 요청이 바로 거부됩니다. 실행 중인 Bot은 끝까지 돕니다. 되돌릴 수 없습니다."
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
    </div>
  );
}
