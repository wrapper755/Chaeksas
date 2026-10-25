"use client";

import { useActionState, useState, useTransition } from "react";
import type { CenterKeyInfo } from "@chaeksas/api-types/c7-center-key-info";
import { Button, ConfirmDialog, Dialog, ErrorBanner, Field } from "@chaeksas/ui";
import { createCenterKey, revokeCenterKey, unbindCenterKey, type ActionResult } from "@/app/actions";

/** CON-11 관리자 모드 — 새 키, 폐기, 묶음 풀기. */
export function KeyTools({ rows }: { rows: CenterKeyInfo[] }) {
  const [creating, setCreating] = useState(false);
  const [kind, setKind] = useState("studio");
  const [result, create, pending] = useActionState<ActionResult, FormData>(createCenterKey, {});
  // 결과는 `useActionState`가 쥐고 있어 지울 수 없다 — 닫은 키를 기억해 그 창만 내린다.
  const [dismissed, setDismissed] = useState<string | null>(null);
  const showing = Boolean(result.secret) && result.secret?.key !== dismissed;
  function closeSecret() {
    setDismissed(result.secret?.key ?? null);
    setCreating(false);
  }
  const [asking, setAsking] = useState<{ kind: "revoke" | "unbind"; key: CenterKeyInfo } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [working, start] = useTransition();

  // 승인이 만든 키에는 「묶음 풀기」가 없다 — 다시 설치한 PC는 새 등록 요청을 승인하면 이어받는다 (ADR-0092).
  const bound = rows.filter((row) => row.bound_to && row.state === "active" && !row.enrollment_id);
  const active = rows.filter((row) => row.state === "active");

  function run(action: () => Promise<ActionResult>) {
    start(async () => {
      const done = await action();
      setError(done.error ?? null);
      setAsking(null);
    });
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="primary" onClick={() => setCreating(true)}>
          새 키...
        </Button>
        <Button
          variant="danger"
          disabled={active.length === 0 || working}
          disabledReason="폐기할 수 있는 키가 없습니다."
          onClick={() => setAsking({ kind: "revoke", key: active[0]! })}
        >
          키 폐기...
        </Button>
        <Button
          variant="secondary"
          disabled={bound.length === 0 || working}
          disabledReason="PC에 묶인 키가 없습니다."
          onClick={() => setAsking({ kind: "unbind", key: bound[0]! })}
        >
          묶음 풀기...
        </Button>
        {active.length > 0 ? (
          <span className="text-caption text-text-muted">
            («폐기»·«묶음 풀기»는 목록 첫 줄에 적용됩니다 — 줄 고르기는 다음에 붙입니다)
          </span>
        ) : null}
      </div>

      {error ? <ErrorBanner message={error} /> : null}

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
              {/* Bot UI용·서버 실행기용은 여기서 발급하지 않는다 — 등록 승인이 만든다 (ADR-0092). */}
              <option value="studio">Studio용</option>
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
          이 키는 <strong>다시 볼 수 없습니다.</strong> 지금 복사해 Studio 설정이나 연동하는 시스템에 넣으세요.
        </p>
        <p className="mt-2 font-mono text-body-sm break-all" style={{ userSelect: "all" }}>
          {result.secret?.key}
        </p>
      </Dialog>

      <ConfirmDialog
        open={asking?.kind === "revoke"}
        title="이 키를 폐기할까요?"
        description={`「${asking?.key.name ?? ""}」을 쓰는 Bot UI의 하트비트가 바로 거부됩니다. 실행 중인 Bot은 끝까지 돕니다.`}
        confirmLabel="폐기"
        onConfirm={() => asking && run(() => revokeCenterKey(asking.key.key_id))}
        onCancel={() => setAsking(null)}
      />
      <ConfirmDialog
        open={asking?.kind === "unbind"}
        title="PC 묶음을 풀까요?"
        description={`다음 등록이 새 PC에 묶입니다. PC를 다시 설치한 경우에만 쓰세요 (「${asking?.key.bound_to?.name ?? ""}」).`}
        confirmLabel="묶음 풀기"
        danger={false}
        onConfirm={() => asking && run(() => unbindCenterKey(asking.key.key_id))}
        onCancel={() => setAsking(null)}
      />
    </div>
  );
}
