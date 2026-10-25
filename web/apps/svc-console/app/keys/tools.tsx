"use client";

import { useState, useTransition } from "react";
import type { AdminKeyInfo } from "@chaeksas/api-types/c11-admin-key-info";
import { Button, ConfirmDialog, ErrorBanner } from "@chaeksas/ui";
import { revokeKey } from "@/app/actions";

/**
 * SVC-02 쓰기 — **비상 폐기**뿐이다 (ADR-0094). 키는 Center가 배포와 함께 짓고 이 앱에는 해시만
 * 온다 — 그래서 「새 키」가 없다. 관리 API의 발급은 자동화·시험용으로 남고 화면에는 없다.
 */
export function KeyTools({ rows }: { rows: AdminKeyInfo[] }) {
  const active = rows.filter((row) => row.state === "active");
  const [chosen, setChosen] = useState<string>("");
  const [asking, setAsking] = useState<AdminKeyInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [working, start] = useTransition();
  const picked = active.find((row) => row.name === chosen) ?? null;
  const fromCenter = asking?.issued_by === "center";

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-2 text-body-sm">
          <span className="text-text-muted">폐기할 키</span>
          <select
            value={chosen}
            onChange={(event) => setChosen(event.target.value)}
            className="h-9 border border-border-strong bg-bg-surface px-2 text-body"
          >
            <option value="">고르세요</option>
            {active.map((row) => (
              <option key={row.name} value={row.name}>
                {row.name} ({row.prefix}…)
              </option>
            ))}
          </select>
        </label>
        <Button
          variant="danger"
          disabled={!picked || working}
          disabledReason={active.length === 0 ? "폐기할 수 있는 키가 없습니다." : "폐기할 키를 고르세요."}
          onClick={() => picked && setAsking(picked)}
        >
          폐기...
        </Button>
      </div>

      {error ? <ErrorBanner message={error} /> : null}

      <ConfirmDialog
        open={Boolean(asking)}
        title="이 키를 폐기할까요?"
        description={`「${asking?.name ?? ""}」을 쓰는 Bot의 호출이 바로 거부됩니다. 기록에는 이름이 남습니다.${
          fromCenter
            ? " Center가 다시 발급하지 않습니다 — 이 Bot을 다시 쓰려면 Center에서 배포를 철회하고 다시 배포하세요."
            : ""
        }`}
        confirmLabel="폐기"
        danger
        onConfirm={() =>
          asking &&
          start(async () => {
            const done = await revokeKey(asking.name);
            setError(done.error ?? null);
            setAsking(null);
            setChosen("");
          })
        }
        onCancel={() => setAsking(null)}
      />
    </div>
  );
}
