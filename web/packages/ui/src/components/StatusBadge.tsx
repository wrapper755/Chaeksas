import { cn } from "../cn";
import { statusToken, type StatusGroup, type StatusToken } from "../status-map";

/**
 * 상태 배지 — 점 + 글자 (스타일 가이드 §3).
 *
 * **글자를 생략하지 않는다.** 색만으로 뜻을 전하지 않기 때문이다 (§7).
 * 색은 `status_map`이 정한다 — 화면이 색을 고르지 않는다. 표기는 그 묶음에 있는 것만 쓴다.
 * 모르는 표기(계약의 상태 값은 열린 문자열이다)는 `neutral`로 보인다.
 */
export interface StatusBadgeProps {
  /** 어느 묶음의 상태인가 (`"Bot"`, `"작업"` …). `status_map`의 열쇠다. */
  group: StatusGroup;
  /** 화면에 그대로 보일 표기 (`"실행 중"`). */
  label: string;
  className?: string;
}

export function StatusBadge({ group, label, className }: StatusBadgeProps) {
  const token: StatusToken = statusToken(group, label) ?? "neutral";
  return (
    <span
      className={cn("inline-flex items-center gap-2 px-2 py-1 text-caption whitespace-nowrap", className)}
      style={{
        color: `var(--status-${token}-fg)`,
        backgroundColor: `var(--status-${token}-bg)`,
        borderRadius: "var(--radius-full)",
      }}
    >
      <span
        aria-hidden
        className="inline-block size-2 shrink-0"
        style={{ backgroundColor: `var(--status-${token}-solid)`, borderRadius: "var(--radius-full)" }}
      />
      {label}
    </span>
  );
}
