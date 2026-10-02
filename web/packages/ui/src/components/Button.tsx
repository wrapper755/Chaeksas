import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn } from "../cn";

/**
 * 단추 (스타일 가이드 §3).
 *
 * - `primary`는 **영역마다 하나**다. 창을 여는 단추는 글자 끝에 「...」를 붙인다 (문구 규칙).
 * - 할 일이 없으면 끄고, **왜 꺼졌는지 가까이에 적는다** (U3). `disabledReason`은 그 보조다 —
 *   화면이 문장으로도 적어야 한다.
 */
export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

const VARIANT: Record<ButtonVariant, string> = {
  primary: "bg-primary text-primary-fg hover:bg-primary-hover border border-transparent",
  secondary: "bg-bg-surface text-text-primary border border-border-strong hover:bg-bg-subtle",
  ghost: "bg-transparent text-text-primary border border-transparent hover:bg-bg-subtle",
  danger: "bg-status-failed-solid text-danger-fg hover:brightness-95 border border-transparent",
};

const HEIGHT: Record<ButtonSize, string> = {
  sm: "var(--size-control-sm)",
  md: "var(--size-control-md)",
  lg: "var(--size-control-lg)",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** 꺼진 이유 (U3). 화면에도 적되, 마우스·보조기기에도 알린다. */
  disabledReason?: string;
  children: ReactNode;
}

export function Button({
  variant = "secondary",
  size = "md",
  disabledReason,
  disabled,
  className,
  children,
  ...rest
}: ButtonProps) {
  const off = disabled ?? false;
  return (
    <button
      type="button"
      disabled={off}
      title={off ? disabledReason : undefined}
      aria-disabled={off || undefined}
      style={{ height: HEIGHT[size], borderRadius: "var(--radius-md)" }}
      className={cn(
        "inline-flex items-center justify-center gap-2 px-4 text-body font-medium whitespace-nowrap",
        "transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        VARIANT[variant],
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}
