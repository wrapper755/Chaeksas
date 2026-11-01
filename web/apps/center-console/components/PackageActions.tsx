"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Button, ConfirmDialog, ErrorBanner } from "@chaeksas/ui";
import { approvePackage, deprecatePackage, revokePackage, type ActionResult } from "@/app/actions";

/**
 * 패키지 한 판의 승인 단추 (CON-02 줄·CON-06 상세). **서명은 Center가 한다** (ADR-0090) —
 * 여기서는 누르기만 한다. 상태마다 할 수 있는 것만 보인다:
 *
 * | 상태 | 단추 |
 * | --- | --- |
 * | 후보 | 「승인...」 |
 * | 승인됨 | 「승인 철회...」·「지원 종료...」 |
 * | 지원 종료 | 「승인...」(새 배포를 다시 연다)·「승인 철회...」 |
 * | 철회 | 없다 — 되살아나지 않는다 |
 *
 * 모두 확인 창을 거치고 기본은 「취소」다 (U9).
 */
type Ask = "approve" | "revoke" | "deprecate";

const ASK: Record<Ask, { label: string; title: string; description: string; confirm: string; danger?: boolean }> = {
  approve: {
    label: "승인...",
    title: "승인할까요?",
    description: "승인하면 이 판을 배포할 수 있습니다. 승인한 사람으로 이 계정이 남습니다.",
    confirm: "승인",
  },
  revoke: {
    label: "승인 철회...",
    title: "승인을 철회할까요?",
    description: "이 판의 배포가 모두 무효가 되고 현장에서 실행 불가가 됩니다. 되돌릴 수 없습니다.",
    confirm: "철회",
    danger: true,
  },
  deprecate: {
    label: "지원 종료...",
    title: "지원을 종료할까요?",
    description: "새 배포만 막습니다. 이미 배포된 것은 그대로 돕니다. 다시 승인하면 풀립니다.",
    confirm: "지원 종료",
  },
};

const ACTIONS: Record<Ask, (id: string, version: string) => Promise<ActionResult>> = {
  approve: approvePackage,
  revoke: revokePackage,
  deprecate: deprecatePackage,
};

function asksFor(status: string): Ask[] {
  if (status === "candidate") return ["approve"];
  if (status === "approved") return ["revoke", "deprecate"];
  if (status === "deprecated") return ["approve", "revoke"];
  return [];
}

export function PackageActions({
  packageId,
  version,
  status,
  place,
}: {
  packageId: string;
  version: string;
  status: string;
  /**
   * 「회사: … · 업무 자리: …」 — 승인 창에 **보여 주기만** 한다 (ADR-0127). 자리는 Studio가 올릴 때
   * 골라 매니페스트에 실었고, 틀렸으면 승인하지 않고 Studio에서 다시 올린다.
   */
  place?: string;
}) {
  const [asking, setAsking] = useState<Ask | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const router = useRouter();
  const asks = asksFor(status);
  if (asks.length === 0) return <span className="text-text-muted">—</span>;
  const shown = asking ? ASK[asking] : null;

  return (
    <div className="flex flex-col gap-1">
      <div className="flex gap-2 whitespace-nowrap">
        {asks.map((one) => (
          <Button
            key={one}
            size="sm"
            variant={one === "approve" ? "primary" : one === "revoke" ? "danger" : "secondary"}
            disabled={pending}
            onClick={() => setAsking(one)}
          >
            {ASK[one].label}
          </Button>
        ))}
      </div>
      {error ? <ErrorBanner message={error} /> : null}
      <ConfirmDialog
        open={shown !== null}
        title={`${packageId} ${version} — ${shown?.title ?? ""}`}
        description={
          asking === "approve" && place
            ? `${shown?.description ?? ""} ${place}. 자리가 틀렸으면 승인하지 말고 Studio에서 다시 올리세요.`
            : shown?.description
        }
        confirmLabel={shown?.confirm ?? ""}
        danger={shown?.danger}
        onConfirm={() =>
          start(async () => {
            const result = await ACTIONS[asking!](packageId, version);
            setAsking(null);
            setError(result.error ?? null);
            if (!result.error) router.refresh();
          })
        }
        onCancel={() => setAsking(null)}
      />
    </div>
  );
}
