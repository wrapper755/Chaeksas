"use client";

import { useActionState, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Button, ConfirmDialog, Dialog, ErrorBanner, Field } from "@chaeksas/ui";
import { changeOwnPassword, createAccount, updateAccount, type ActionResult } from "@/app/actions";

/**
 * CON-14 관리자 계정의 손잡이들. 화면은 **필요한 것만** 보인다 — 줄마다 「...」 하나이고
 * 할 수 있는 일은 그 안에 있다. 비밀번호 규칙(12자 이상·영문과 숫자)은 칸의 도움말로 말하고
 * 지키는지는 **Center가 본다** (한 자리에서만 판정한다).
 */
const RULE = "12자 이상, 영문과 숫자를 모두 넣습니다.";

const ROLE_SELECT = "h-9 border border-border-strong bg-bg-surface px-2 text-body";

export function NewAccount({ companies = [] }: { companies?: Array<{ id: string; name: string }> }) {
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const [result, action, pending] = useActionState<ActionResult, FormData>(async (previous, form) => {
    const made = await createAccount(previous, form);
    if (!made.error) {
      setOpen(false);
      router.refresh();
    }
    return made;
  }, {});
  return (
    <>
      <Button variant="primary" onClick={() => setOpen(true)}>
        새 계정...
      </Button>
      <Dialog open={open} title="새 계정" onClose={() => setOpen(false)}>
        <form action={action} className="flex flex-col gap-3">
          {result.error ? <ErrorBanner message={result.error} /> : null}
          <Field label="아이디" name="username" required autoComplete="off" autoCapitalize="none" help="영문 소문자·숫자·.·_·- 3~32자" />
          <Field label="처음 비밀번호" name="password" type="password" required autoComplete="new-password" help={RULE} />
          <label className="flex flex-col gap-1 text-body-sm">
            역할
            <select name="role" defaultValue="admin" className={ROLE_SELECT}>
              <option value="admin">Center 관리자</option>
              <option value="company_admin">회사 관리자</option>
              <option value="viewer">보기 전용</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-body-sm">
            회사
            <select name="company" defaultValue="" className={ROLE_SELECT}>
              <option value="">없음 (Center 전체)</option>
              {companies.map((one) => (
                <option key={one.id} value={one.id}>
                  {one.name}
                </option>
              ))}
            </select>
            <span className="text-text-muted">
              회사 관리자는 회사가 꼭 있고, Center 관리자는 비웁니다. 보기 전용은 회사를 고르면 그 회사만 봅니다.
            </span>
          </label>
          <div className="flex justify-end">
            <Button type="submit" variant="primary" disabled={pending}>
              만들기
            </Button>
          </div>
        </form>
      </Dialog>
    </>
  );
}

type Ask = "role" | "disable" | "enable" | "password" | "own";

export function AccountMenu({
  username,
  role,
  disabled,
  self,
}: {
  username: string;
  role: string;
  disabled: boolean;
  self: boolean;
}) {
  const [menu, setMenu] = useState(false);
  const [asking, setAsking] = useState<Ask | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const router = useRouter();
  const nextRole = role === "admin" ? "viewer" : "admin";

  const run = (change: { role?: string; disabled?: boolean; password?: string }) =>
    start(async () => {
      const result = await updateAccount(username, change);
      setError(result.error ?? null);
      if (!result.error) {
        setAsking(null);
        router.refresh();
      }
    });

  if (self) {
    // 자기 줄은 할 일이 하나라 메뉴 없이 단추다 (자기 역할·멈춤은 다른 관리자가 한다).
    return (
      <>
        <Button size="sm" variant="secondary" onClick={() => setAsking("own")}>
          비밀번호 바꾸기...
        </Button>
        <OwnPassword open={asking === "own"} onClose={() => setAsking(null)} />
      </>
    );
  }

  // 회사 관리자의 역할은 여기서 바꾸지 않는다 — 「관리자로 바꾸기」가 Center 관리자를 만들면 안 된다 (C16).
  const items: Array<{ ask: Ask; label: string }> = [
        ...(role === "company_admin"
          ? []
          : [{ ask: "role" as Ask, label: nextRole === "admin" ? "관리자로 바꾸기..." : "보기 전용으로 바꾸기..." }]),
        disabled ? { ask: "enable", label: "다시 쓰기" } : { ask: "disable", label: "멈추기..." },
        { ask: "password", label: "비밀번호 새로 정하기..." },
      ];

  return (
    <div className="relative flex flex-col items-start gap-1">
      <Button size="sm" variant="ghost" aria-label={`${username} 계정 동작`} onClick={() => setMenu(!menu)}>
        ...
      </Button>
      {menu ? (
        <ul className="absolute right-0 top-full z-10 flex min-w-[200px] flex-col border border-border-default bg-bg-surface py-1 shadow-md">
          {items.map((item) => (
            <li key={item.ask}>
              <button
                type="button"
                className="w-full px-3 py-2 text-left text-body hover:bg-bg-subtle"
                onClick={() => {
                  setMenu(false);
                  setError(null);
                  // 「다시 쓰기」는 되돌릴 수 있고 해가 없다 — 묻지 않는다 (U9).
                  if (item.ask === "enable") run({ disabled: false });
                  else setAsking(item.ask);
                }}
              >
                {item.label}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {error && asking === null ? <ErrorBanner message={error} /> : null}

      <ConfirmDialog
        open={asking === "role"}
        title={`${username}을 ${nextRole === "admin" ? "관리자" : "보기 전용"}로 바꿀까요?`}
        description="그 계정은 다시 로그인해야 합니다."
        confirmLabel="바꾸기"
        onConfirm={() => run({ role: nextRole })}
        onCancel={() => setAsking(null)}
      />
      <ConfirmDialog
        open={asking === "disable"}
        title={`${username}을 멈출까요?`}
        description="그 계정은 바로 로그아웃되고 다시 들어올 수 없습니다. 기록에 남은 이름은 그대로입니다. 「다시 쓰기」로 되돌릴 수 있습니다."
        confirmLabel="멈추기"
        danger
        onConfirm={() => run({ disabled: true })}
        onCancel={() => setAsking(null)}
      />
      <Dialog open={asking === "password"} title={`${username}의 비밀번호 새로 정하기`} onClose={() => setAsking(null)}>
        <form
          className="flex flex-col gap-3"
          action={(form) => run({ password: String(form.get("password") ?? "") })}
        >
          {error ? <ErrorBanner message={error} /> : null}
          <Field label="새 비밀번호" name="password" type="password" required autoComplete="new-password" help={`${RULE} 그 계정은 다시 로그인해야 합니다.`} />
          <div className="flex justify-end">
            <Button type="submit" variant="primary" disabled={pending}>
              정하기
            </Button>
          </div>
        </form>
      </Dialog>
    </div>
  );
}

function OwnPassword({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [result, action, pending] = useActionState<ActionResult, FormData>(changeOwnPassword, {});
  return (
    <Dialog open={open} title="비밀번호 바꾸기" onClose={onClose}>
      <form action={action} className="flex flex-col gap-3">
        {result.error ? <ErrorBanner message={result.error} /> : null}
        <Field label="지금 비밀번호" name="current_password" type="password" required autoComplete="current-password" />
        <Field label="새 비밀번호" name="new_password" type="password" required autoComplete="new-password" help={RULE} />
        <Field label="새 비밀번호 확인" name="confirm_password" type="password" required autoComplete="new-password" />
        <div className="flex justify-end">
          <Button type="submit" variant="primary" disabled={pending}>
            바꾸기
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
