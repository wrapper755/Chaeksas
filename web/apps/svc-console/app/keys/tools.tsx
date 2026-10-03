"use client";

import { useActionState, useState, useTransition } from "react";
import type { AdminKeyInfo } from "@chaeksas/api-types/c11-admin-key-info";
import { Button, ConfirmDialog, Dialog, ErrorBanner, Field } from "@chaeksas/ui";
import { createKey, revokeKey, type ActionResult } from "@/app/actions";

/**
 * SVC-02 쓰기 — 새 키, 폐기.
 *
 * 「허용 작업」 칸은 **앱이 선언한 작업**(`/admin/v1/status`)으로 만든다 — 손으로 적은 목록을 두면
 * 앱마다 틀린다. 추가 권한은 앱 고유라서 `app_id`로 고른다.
 */

/** 앱 고유 추가 권한 (C11 `extra_scopes`). */
const EXTRA_SCOPES: Record<string, Array<{ value: string; label: string; help: string }>> = {
  "ui-automation": [
    {
      value: "registry_write",
      label: "레지스트리 쓰기",
      help: "UI 셀렉터 등록 담당자용 — 셀렉터를 고칠 수 있습니다.",
    },
  ],
};

export function KeyTools({
  rows,
  operations,
  appId,
}: {
  rows: AdminKeyInfo[];
  operations: string[];
  appId?: string;
}) {
  const [creating, setCreating] = useState(false);
  const [result, create, pending] = useActionState<ActionResult, FormData>(createKey, {});
  const [asking, setAsking] = useState<AdminKeyInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [working, start] = useTransition();

  const active = rows.filter((row) => row.state === "active");
  const scopes = appId ? (EXTRA_SCOPES[appId] ?? []) : [];

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
          onClick={() => setAsking(active[0]!)}
        >
          키 폐기...
        </Button>
        {active.length > 0 ? (
          <span className="text-caption text-text-muted">
            («폐기»는 목록 첫 줄에 적용됩니다 — 줄 고르기는 다음에 붙입니다)
          </span>
        ) : null}
      </div>

      {error ? <ErrorBanner message={error} /> : null}

      <Dialog
        open={creating && !result.secret}
        title="새 API 키"
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
          <Field label="이름" name="name" required help="BPM 프로세스의 키 참조 이름과 같게 (예: finance-invoice)." />

          <fieldset className="flex flex-col gap-2">
            <legend className="text-body-sm font-medium">허용 작업</legend>
            <p className="text-caption text-text-muted">하나도 고르지 않으면 모든 작업을 허용합니다.</p>
            {operations.length === 0 ? (
              <p className="text-body-sm text-text-muted">앱이 선언한 작업을 읽지 못했습니다 — 모든 작업으로 만듭니다.</p>
            ) : (
              operations.map((name) => (
                <label key={name} className="flex items-center gap-2 text-body">
                  <input type="checkbox" name="operations" value={name} /> <span className="font-mono">{name}</span>
                </label>
              ))
            )}
          </fieldset>

          <fieldset className="flex flex-col gap-2">
            <legend className="text-body-sm font-medium">허용 모드</legend>
            <label className="flex items-center gap-2 text-body">
              <input type="radio" name="modes" value="deterministic" defaultChecked /> 결정 수행 (운영 Bot용)
            </label>
            <label className="flex items-center gap-2 text-body">
              <input type="radio" name="modes" value="both" /> 자율·결정 수행 (Studio 개발용)
            </label>
          </fieldset>

          {scopes.length > 0 ? (
            <fieldset className="flex flex-col gap-2">
              <legend className="text-body-sm font-medium">추가 권한</legend>
              {scopes.map((scope) => (
                <label key={scope.value} className="flex items-start gap-2 text-body">
                  <input type="checkbox" name="scopes" value={scope.value} className="mt-1" />
                  <span>
                    {scope.label}
                    <span className="block text-caption text-text-muted">{scope.help}</span>
                  </span>
                </label>
              ))}
            </fieldset>
          ) : null}

          <Field label="메모" name="note" help="무엇에 쓰는 키인지 (선택)." />
          <p className="text-caption text-text-muted">만료는 기본 1년입니다.</p>
        </form>
      </Dialog>

      {/* 발급 직후 — **원문을 한 번만** 보여 준다 (SVC-02). */}
      <Dialog
        open={Boolean(result.secret)}
        title="키를 발급했습니다"
        onClose={() => setCreating(false)}
        footer={
          <Button variant="primary" onClick={() => setCreating(false)}>
            닫기
          </Button>
        }
      >
        <p className="text-body">
          이 키는 <strong>다시 볼 수 없습니다.</strong> 지금 복사해 Bot UI 「서비스 앱 키」(또는 Studio 설정)에
          참조 이름 <span className="font-mono">{result.secret?.name}</span>으로 넣으세요.
        </p>
        <p className="mt-2 font-mono text-body-sm break-all" style={{ userSelect: "all" }}>
          {result.secret?.key}
        </p>
      </Dialog>

      <ConfirmDialog
        open={Boolean(asking)}
        title="이 키를 폐기할까요?"
        description={`「${asking?.name ?? ""}」을 쓰는 Bot의 호출이 바로 거부됩니다. 기록에는 이름이 남습니다.`}
        confirmLabel="폐기"
        onConfirm={() =>
          asking &&
          start(async () => {
            const done = await revokeKey(asking.name);
            setError(done.error ?? null);
            setAsking(null);
          })
        }
        onCancel={() => setAsking(null)}
      />
    </div>
  );
}
