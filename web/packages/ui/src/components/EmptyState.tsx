import type { ReactNode } from "react";
import { cn } from "../cn";

/**
 * 빈 상태 (스타일 가이드 §3). **다음에 할 일을 말한다** (U12).
 *
 * 「설치된 Bot이 없습니다. Center에서 배포하면 여기에 나타납니다.」
 */
export interface EmptyStateProps {
  title: string;
  hint?: string;
  action?: ReactNode;
  className?: string;
}

export function EmptyState({ title, hint, action, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center gap-2 border border-border-default bg-bg-surface px-6 py-12 text-center",
        className,
      )}
      style={{ borderRadius: "var(--radius-lg)" }}
    >
      <p className="text-body font-medium text-text-primary">{title}</p>
      {hint ? <p className="text-body-sm text-text-muted">{hint}</p> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}
