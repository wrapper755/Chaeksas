"use client";

import { useState, useTransition } from "react";
import { Button, ConfirmDialog, ErrorBanner } from "@chaeksas/ui";
import { markRunnerLost, restartRunner, setRunnerPaused } from "@/app/actions";

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

/**
 * 목록 줄의 「재시작...」 (CON-02 「서버」 탭, ADR-0117) — 관리자만.
 *
 * 요청해 두었으면 끄고(상태가 「재시작 중」이다), 오프라인이면 끄고 까닭을 툴팁에 적는다 — 하트비트로만
 * 전해지는 지시라 오프라인 실행기에는 닿지 않는다.
 */
export function RestartRunner({
  runnerId,
  name,
  online,
  requested,
  running,
}: {
  runnerId: string;
  name: string;
  online: boolean;
  requested: boolean;
  running: number;
}) {
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();

  function apply() {
    start(async () => {
      const result = await restartRunner(runnerId);
      setError(result.error ?? null);
      setAsking(false);
    });
  }

  return (
    <div className="flex flex-col gap-1">
      <Button
        variant="secondary"
        size="sm"
        disabled={pending || requested || !online}
        title={
          requested
            ? "재시작을 요청해 두었습니다."
            : !online
              ? "오프라인인 실행기에는 재시작을 전할 수 없습니다."
              : undefined
        }
        onClick={() => setAsking(true)}
      >
        재시작...
      </Button>
      {error ? <ErrorBanner message={error} /> : null}
      <ConfirmDialog
        open={asking}
        title={`「${name}」을 재시작할까요?`}
        description={`새 작업을 받지 않고, 도는 실행 ${running}건이 끝나면 스스로 끝납니다. Center와 함께 배포된 실행기는 compose가 다시 띄웁니다. 기다리는 실행은 이어 갑니다.`}
        confirmLabel="재시작"
        onConfirm={apply}
        onCancel={() => setAsking(false)}
      />
    </div>
  );
}
