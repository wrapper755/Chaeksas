"use client";

import { useState, useTransition } from "react";
import { Button, ConfirmDialog, ErrorBanner } from "@chaeksas/ui";
import { setBotUiDisabled, setSelectorRegistration } from "@/app/actions";

/**
 * CON-03 「셀렉터 등록」 — 켜면 이 PC의 Tool UI가 셀렉터 등록 작업을 Center에 올릴 수 있다
 * (C15 §올리기 — 등록 세션은 Bot이 없어 「그 PC에 켜졌나」를 본다). 권한이 **사람이 아니라 PC**에 붙으므로 켤 때 확인 창이고 기본은 「취소」다 (U9).
 */
export function SelectorRegistration({ botUiId, on }: { botUiId: string; on: boolean }) {
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();

  function apply(next: boolean) {
    start(async () => {
      setError((await setSelectorRegistration(botUiId, next)).error ?? null);
      setAsking(false);
    });
  }

  return (
    <div className="flex flex-col gap-2">
      <div>
        {on ? (
          <Button variant="secondary" disabled={pending} onClick={() => apply(false)}>
            끄기
          </Button>
        ) : (
          <Button variant="secondary" disabled={pending} onClick={() => setAsking(true)}>
            켜기...
          </Button>
        )}
      </div>
      {error ? <ErrorBanner message={error} /> : null}
      <ConfirmDialog
        open={asking}
        title="이 PC에서 셀렉터 등록을 허락할까요?"
        description="이 PC를 쓰는 누구나 Tool UI로 셀렉터를 등록·삭제할 수 있게 됩니다."
        confirmLabel="켜기"
        onConfirm={() => apply(true)}
        onCancel={() => setAsking(false)}
      />
    </div>
  );
}

/**
 * CON-03 관리자 모드 단추. 「비활성화」는 **되돌릴 수 있지만 운영에 영향**이 있어 확인 창을
 * 띄우고 기본 단추를 「취소」로 둔다 (U9).
 */
export function BotUiActions({ botUiId, disabled }: { botUiId: string; disabled: boolean }) {
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();

  function apply(next: boolean) {
    start(async () => {
      const result = await setBotUiDisabled(botUiId, next);
      setError(result.error ?? null);
      setAsking(false);
    });
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        {disabled ? (
          <>
            <span className="text-body-sm text-text-muted">비활성화됨 — 새 작업·배포를 보내지 않습니다.</span>
            <Button variant="secondary" disabled={pending} onClick={() => apply(false)}>
              다시 활성화
            </Button>
          </>
        ) : (
          <Button variant="danger" disabled={pending} onClick={() => setAsking(true)}>
            비활성화...
          </Button>
        )}
      </div>
      {error ? <ErrorBanner message={error} /> : null}
      <ConfirmDialog
        open={asking}
        title="이 Bot UI를 비활성화할까요?"
        description="이 PC에 새 작업·배포를 보내지 않습니다. 실행 중인 Bot은 끝까지 돕니다."
        confirmLabel="비활성화"
        onConfirm={() => apply(true)}
        onCancel={() => setAsking(false)}
      />
    </div>
  );
}
