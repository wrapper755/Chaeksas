"use client";

import { useState, useTransition } from "react";
import { Button, ConfirmDialog, ErrorBanner } from "@chaeksas/ui";
import { cancelJob } from "@/app/actions";
import { PC_RUNNING_REASON, STOP_CONFIRM, type CancelControl } from "@/lib/jobs";

/**
 * CON-05 「취소」·「중지」 (C5 「취소」 표, ADR-0063). 어느 단추인지는 `cancelControl()`이 정한다.
 *
 * - 「취소」 — 대기·전달됨·대기열. 대기는 바로 「취소됨」이 되고, 전달됨·대기열은 **현장에
 *   물어본다** — 화면은 「취소 요청함 — 다음 하트비트에 반영」을 보이고, 그사이 시작됐으면
 *   「취소 못 함 — 이미 시작됨」이 붙는다.
 * - 「중지...」 — 도는 서버 실행. **한 일은 되돌리지 않아** 확인 창을 거친다(기본 「취소」).
 *   Center는 202로 받고 화면은 「중지 요청함 — 다음 하트비트에 반영」, 실행기가 닫으면 「취소됨」.
 * - 도는 PC 실행 — 단추를 **끄고 까닭을 적는다** (목록은 툴팁, 상세는 글 한 줄).
 *
 * 진행 글은 목록이 Center의 `cancel_requested`·`cancel_result`에서 다시 그린다 (지어내지 않는다).
 */
export function CancelJob({
  jobId,
  control,
  explain = false,
}: {
  jobId: string;
  control: CancelControl;
  /** 끈 단추의 까닭을 글로도 적는다 (상세). */
  explain?: boolean;
}) {
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();

  function apply() {
    start(async () => {
      const result = await cancelJob(jobId);
      setError(result.error ?? null);
      setAsking(false);
    });
  }

  if (control === null) return null;

  return (
    <div className="flex flex-col gap-1">
      {control === "cancel" ? (
        <Button variant="secondary" size="sm" disabled={pending} onClick={apply}>
          취소
        </Button>
      ) : (
        <div>
          <Button
            variant="danger"
            size="sm"
            disabled={pending || control === "pc_running"}
            title={control === "pc_running" ? PC_RUNNING_REASON : undefined}
            onClick={() => setAsking(true)}
          >
            중지...
          </Button>
        </div>
      )}
      {control === "pc_running" && explain ? (
        <p className="text-caption text-text-muted">{PC_RUNNING_REASON}</p>
      ) : null}
      {error ? <ErrorBanner message={error} /> : null}
      <ConfirmDialog
        open={asking}
        title="도는 실행을 멈출까요?"
        description={STOP_CONFIRM}
        confirmLabel="중지"
        danger
        onConfirm={apply}
        onCancel={() => setAsking(false)}
      />
    </div>
  );
}
