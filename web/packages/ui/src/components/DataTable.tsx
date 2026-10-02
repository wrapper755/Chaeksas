import type { ReactNode } from "react";
import { cn } from "../cn";
import { EmptyState } from "./EmptyState";

/**
 * 표 (스타일 가이드 §3).
 *
 * - 머리 고정, 줄 높이는 토큰(`row.default` 36 / `row.compact` 32).
 * - 숫자 열은 오른쪽 정렬 + `tabular-nums`, id 열은 mono로 짧게 (툴팁에 전체, U2).
 * - **업무 값 열은 기본으로 접는다** (U10) — `business: true`인 열은 `showBusiness`일 때만 보인다.
 * - 정렬·필터 상태를 주소(URL)에 남기는 일은 화면의 몫이다 (여기서는 다루지 않는다).
 */
export interface Column<T> {
  key: string;
  header: string;
  /** 칸 내용. 없으면 `row[key]`를 문자열로 보인다. */
  cell?: (row: T) => ReactNode;
  align?: "left" | "right";
  /** id·키처럼 mono로 보일 열. */
  mono?: boolean;
  /** 업무 값 열 (기본 접음, U10). */
  business?: boolean;
  width?: string;
}

export interface DataTableProps<T> {
  columns: Array<Column<T>>;
  rows: T[];
  rowKey: (row: T) => string;
  density?: "default" | "compact";
  showBusiness?: boolean;
  /** 줄이 없을 때 — 다음에 할 일을 말한다 (U12). */
  empty?: { title: string; hint?: string; action?: ReactNode };
  caption?: string;
  className?: string;
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  density = "default",
  showBusiness = false,
  empty,
  caption,
  className,
}: DataTableProps<T>) {
  const shown = columns.filter((c) => showBusiness || !c.business);
  const rowHeight = density === "compact" ? "var(--size-row-compact)" : "var(--size-row-default)";

  if (rows.length === 0 && empty) {
    return <EmptyState title={empty.title} hint={empty.hint} action={empty.action} />;
  }

  return (
    <div
      className={cn("overflow-auto border border-border-default bg-bg-surface", className)}
      style={{ borderRadius: "var(--radius-lg)" }}
    >
      <table className="w-full border-collapse text-body">
        {caption ? <caption className="sr-only">{caption}</caption> : null}
        <thead className="sticky top-0 z-10 bg-bg-subtle">
          <tr>
            {shown.map((c) => (
              <th
                key={c.key}
                scope="col"
                style={{ width: c.width, height: rowHeight }}
                className={cn(
                  "border-b border-border-default px-3 text-body-sm font-semibold text-text-secondary",
                  c.align === "right" ? "text-right" : "text-left",
                )}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={rowKey(row)} className="hover:bg-bg-subtle">
              {shown.map((c) => (
                <td
                  key={c.key}
                  style={{ height: rowHeight }}
                  className={cn(
                    "border-b border-border-default px-3",
                    c.align === "right" && "text-right tabular-nums",
                    c.mono && "font-mono text-body-sm",
                  )}
                >
                  {c.cell ? c.cell(row) : String((row as Record<string, unknown>)[c.key] ?? "")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
