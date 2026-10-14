"use client";

import { useState, useTransition } from "react";
import { Button, ConfirmDialog, ErrorBanner } from "@chaeksas/ui";
import { markRunnerLost, setRunnerPaused } from "@/app/actions";

/**
 * CON-12 관리자 모드 단추 — 「일시 중지...」/「다시 시작」, 오프라인 실행기의 「유실 처리...」.
 *
 * **「다시 시작」은 묻지 않는다** (되돌릴 수 있고 해가 없다, U9). 「일시 중지」는 운영에 영향이
 * 있어 확인 창을 띄우고, 「유실 처리」는 **되돌릴 수 없어** 기본 단추가 「취소」다.
 *
 * **온라인이면 「유실 처리」를 끄고 까닭을 적는다** — 멀쩡히 도는 실행을 닫는 길을 열어 두지
 * 않는다. 그사이 실행기가 돌아오면 Center가 409 `runner_online`으로 막고(판정은 한 곳이다)
 * 그 사유가 그대로 띠에 보인다.
 */
export function ServerRunnerActions({
  runnerId,
  paused,
  online,
  running,
  waiting,
}: {
  runnerId: string;
  paused: boolean;
  online: boolean;
  running: number;
  waiting: number;
}) {
  const [asking, setAsking] = useState<"pause" | "lost" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();

  function pause(next: boolean) {
    start(async () => {
      const result = await setRunnerPaused(runnerId, next);
      setError(result.error ?? null);
      setAsking(null);
    });
  }

  function lose() {
    start(async () => {
      const result = await markRunnerLost(runnerId);
      setError(result.error ?? null);
      setAsking(null);
    });
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        {paused ? (
          <>
            <span className="text-body-sm text-text-muted">
              일시 중지됨 — 새 작업을 받지 않습니다.
            </span>
            <Button variant="secondary" disabled={pending} onClick={() => pause(false)}>
              다시 시작
            </Button>
          </>
        ) : (
          <Button variant="secondary" disabled={pending} onClick={() => setAsking("pause")}>
            일시 중지...
          </Button>
        )}
        <Button
          variant="danger"
          disabled={pending || online}
          title={online ? "온라인인 실행기는 유실 처리할 수 없습니다." : undefined}
          onClick={() => setAsking("lost")}
        >
          유실 처리...
        </Button>
      </div>
      {online ? (
        <p className="text-caption text-text-muted">
          「유실 처리」는 오프라인인 실행기만 할 수 있습니다 — 지금은 온라인입니다.
        </p>
      ) : null}
      {error ? <ErrorBanner message={error} /> : null}

      <ConfirmDialog
        open={asking === "pause"}
        title="이 서버 실행기를 일시 중지할까요?"
        description="새 실행을 받지 않습니다. 실행 중인 것은 끝까지 돕니다."
        confirmLabel="일시 중지"
        onConfirm={() => pause(true)}
        onCancel={() => setAsking(null)}
      />
      {/* 셈은 **마지막 보고** 기준이다 — 오프라인이라 지금 상태를 아는 길이 없고, 모르는 것을
          안다고 하지 않는다 (U8). */}
      <ConfirmDialog
        open={asking === "lost"}
        title="이 서버 실행기를 유실 처리할까요?"
        description={`이 실행기의 실행 ${running + waiting}건(마지막 보고 기준)을 실패로 닫고 결재를 회수합니다. 되돌릴 수 없습니다.`}
        confirmLabel="유실 처리"
        onConfirm={lose}
        onCancel={() => setAsking(null)}
      />
    </div>
  );
}
