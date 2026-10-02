import { useId, type InputHTMLAttributes, type ReactNode } from "react";
import { cn } from "../cn";

/**
 * 입력 칸 한 줄 (스타일 가이드 §3).
 *
 * 라벨은 위, 필수는 ` *`, 도움말은 아래 회색, 오류는 아래 `status.failed.fg` 한 줄.
 * 오류가 있으면 `aria-invalid`와 `aria-describedby`로 보조기기에도 알린다.
 */
export interface FieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "id"> {
  label: string;
  required?: boolean;
  help?: string;
  error?: string;
  /** 입력칸 대신 다른 컨트롤을 쓸 때 (선택 상자 등). */
  control?: ReactNode;
}

export function Field({ label, required, help, error, control, className, ...rest }: FieldProps) {
  const id = useId();
  const helpId = `${id}-help`;
  const errorId = `${id}-error`;
  const describedBy = cn(help ? helpId : "", error ? errorId : "").trim() || undefined;

  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <label htmlFor={id} className="text-body-sm font-medium text-text-primary">
        {label}
        {required ? <span aria-hidden> *</span> : null}
        {required ? <span className="sr-only">(필수)</span> : null}
      </label>
      {control ?? (
        <input
          id={id}
          required={required}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          style={{ height: "var(--size-control-md)", borderRadius: "var(--radius-md)" }}
          className={cn(
            "border bg-bg-surface px-3 text-body text-text-primary",
            error ? "border-status-failed-solid" : "border-border-strong",
          )}
          {...rest}
        />
      )}
      {help ? (
        <p id={helpId} className="text-caption text-text-muted">
          {help}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} className="text-caption" style={{ color: "var(--status-failed-fg)" }}>
          {error}
        </p>
      ) : null}
    </div>
  );
}
