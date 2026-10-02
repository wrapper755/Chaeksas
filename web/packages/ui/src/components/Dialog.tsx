"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { Button } from "./Button";

/**
 * 대화상자 (스타일 가이드 §3).
 *
 * **제목은 동사로** 쓴다 (「키를 폐기할까요?」). 브라우저의 `<dialog>`를 쓴다 — 포커스 가두기와
 * `Esc`를 브라우저가 해 준다.
 *
 * > 뼈대: 펼침 메뉴·팝오버처럼 더 복잡한 것은 shadcn/ui(Radix) 코드를 저장소에 복사해 토큰으로
 * > 맞춘다 (ADR-0017). 실제 화면이 생기는 M2에 함께 들여온다.
 */
export interface DialogProps {
  open: boolean;
  /** 제목 — 동사로. */
  title: string;
  description?: string;
  children?: ReactNode;
  /** 아래 단추들. 위험 확인은 `ConfirmDialog`를 쓴다. */
  footer?: ReactNode;
  onClose: () => void;
  width?: number;
}

export function Dialog({ open, title, description, children, footer, onClose, width = 480 }: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (open && !node.open) node.showModal();
    if (!open && node.open) node.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClose={onClose}
      style={{ borderRadius: "var(--radius-xl)", boxShadow: "var(--shadow-lg)", maxWidth: `${width}px` }}
      className="m-auto w-full border border-border-default bg-bg-surface p-6 text-text-primary backdrop:bg-black/40"
    >
      <h2 className="text-h3 font-semibold">{title}</h2>
      {description ? <p className="mt-2 text-body-lg text-text-secondary">{description}</p> : null}
      {children ? <div className="mt-4">{children}</div> : null}
      {footer ? <div className="mt-6 flex justify-end gap-2">{footer}</div> : null}
    </dialog>
  );
}

export interface ConfirmDialogProps {
  open: boolean;
  /** 제목 — 동사로 묻는다 (「키를 폐기할까요?」). */
  title: string;
  description?: string;
  /** 되돌릴 수 없는 동작의 단추 글자 (「폐기」). */
  confirmLabel: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * 확인 창. **되돌릴 수 없는 동작이면 기본 단추가 「취소」다** (U9) — 엔터를 눌러 지우는 일이
 * 없게 한다. 위험 단추는 `danger`.
 */
export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  danger = true,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  return (
    <Dialog
      open={open}
      title={title}
      description={description}
      onClose={onCancel}
      footer={
        <>
          {/* 기본 단추(엔터)가 「취소」다 — 순서상 먼저 두고 autoFocus를 준다. */}
          <Button variant="secondary" autoFocus onClick={onCancel}>
            취소
          </Button>
          <Button variant={danger ? "danger" : "primary"} onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </>
      }
    />
  );
}
