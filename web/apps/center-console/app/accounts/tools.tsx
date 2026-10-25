"use client";

import { useActionState, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Button, ConfirmDialog, Dialog, ErrorBanner, Field } from "@chaeksas/ui";
import { changeOwnPassword, createAccount, logoutStudios, updateAccount, type ActionResult } from "@/app/actions";

/**
 * CON-14 관리자 계정의 손잡이들. 화면은 **필요한 것만** 보인다 — 줄마다 「...」 하나이고
 * 할 수 있는 일은 그 안에 있다. 비밀번호 규칙(12자 이상·영문과 숫자)은 칸의 도움말로 말하고
 * 지키는지는 **Center가 본다** (한 자리에서만 판정한다).
 */
const RULE = "12자 이상, 영문과 숫자를 모두 넣습니다.";

const ROLE_SELECT = "h-9 border border-border-strong bg-bg-surface px-2 text-body";

export function NewAccount() {
  const [open, setOpen] = useState(false);
  const [role, setRole] = useState("admin");
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
            <select name="role" value={role} onChange={(event) => setRole(event.target.value)} className={ROLE_SELECT}>
              <option value="admin">관리자</option>
              <option value="viewer">보기 전용</option>
            </select>
          </label>
          {role === "viewer" ? (
            // 관리자는 체크 없이 모든 권한을 가진다 (C5 §계정 권한과 Studio 로그인).
            <label className="flex items-center gap-2 text-body-sm">
              <input type="checkbox" name="design" />
              설계 — Studio에서 로그인해 Bot을 올릴 수 있다
            </label>
          ) : null}
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

type Ask = "role" | "disable" | "enable" | "password" | "own" | "design_on" | "design_off" | "studio_logout";

export interface StudioLoginRow {
  key_id: string;
  machine_name: string;
}

export function AccountMenu({
  username,
  role,
  disabled,
  self,
  permissions,
  studioLogins,
}: {
  username: string;
  role: string;
  disabled: boolean;
  self: boolean;
  permissions: string[];
  studioLogins: StudioLoginRow[];
}) {
  const [menu, setMenu] = useState(false);
  const [asking, setAsking] = useState<Ask | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const router = useRouter();
  const nextRole = role === "admin" ? "viewer" : "admin";

  const design = permissions.includes("design");
  // 멈추기·역할 바꾸기·비밀번호 새로 정하기·권한 끄기는 Studio 로그인도 모두 끝낸다 (C5).
  const endsStudio =
    studioLogins.length > 0 ? ` Studio 로그인 ${studioLogins.length}곳도 끝납니다.` : "";
  const run = (change: { role?: string; disabled?: boolean; password?: string; permissions?: string[] }) =>
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

  const items: Array<{ ask: Ask; label: string }> = [
    { ask: "role", label: nextRole === "admin" ? "관리자로 바꾸기..." : "보기 전용으로 바꾸기..." },
    disabled ? { ask: "enable", label: "다시 쓰기" } : { ask: "disable", label: "멈추기..." },
    { ask: "password", label: "비밀번호 새로 정하기..." },
    // 관리자는 모든 권한을 가진다 — 켜고 끌 것이 보기 전용에만 있다.
    ...(role === "viewer"
      ? [design ? { ask: "design_off" as Ask, label: "설계 권한 끄기..." } : { ask: "design_on" as Ask, label: "설계 권한 켜기" }]
      : []),
    ...(studioLogins.length > 0 ? [{ ask: "studio_logout" as Ask, label: "Studio에서 로그아웃시키기..." }] : []),
  ];

  const logoutAll = () =>
    start(async () => {
      const result = await logoutStudios(studioLogins.map((one) => one.key_id));
      setError(result.error ?? null);
      if (!result.error) {
        setAsking(null);
        router.refresh();
      }
    });

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
                  // 「다시 쓰기」·「설계 권한 켜기」는 되돌릴 수 있고 해가 없다 — 묻지 않는다 (U9).
                  if (item.ask === "enable") run({ disabled: false });
                  else if (item.ask === "design_on") run({ permissions: [...permissions, "design"] });
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
        description={`그 계정은 다시 로그인해야 합니다.${endsStudio}`}
        confirmLabel="바꾸기"
        onConfirm={() => run({ role: nextRole })}
        onCancel={() => setAsking(null)}
      />
      <ConfirmDialog
        open={asking === "disable"}
        title={`${username}을 멈출까요?`}
        description={`그 계정은 바로 로그아웃되고 다시 들어올 수 없습니다. 기록에 남은 이름은 그대로입니다. 「다시 쓰기」로 되돌릴 수 있습니다.${endsStudio}`}
        confirmLabel="멈추기"
        danger
        onConfirm={() => run({ disabled: true })}
        onCancel={() => setAsking(null)}
      />
      <ConfirmDialog
        open={asking === "design_off"}
        title={`${username}의 설계 권한을 끌까요?`}
        description="그 계정의 Studio 로그인이 모두 끝납니다."
        confirmLabel="끄기"
        onConfirm={() => run({ permissions: permissions.filter((one) => one !== "design") })}
        onCancel={() => setAsking(null)}
      />
      <ConfirmDialog
        open={asking === "studio_logout"}
        title={`${username}을 Studio에서 로그아웃시킬까요?`}
        description={`${studioLogins.map((one) => one.machine_name).join(", ")}의 Studio가 다음에 Center를 부를 때 「로그인이 끝났습니다」가 됩니다.`}
        confirmLabel="로그아웃시키기"
        danger
        onConfirm={logoutAll}
        onCancel={() => setAsking(null)}
      />
      <Dialog open={asking === "password"} title={`${username}의 비밀번호 새로 정하기`} onClose={() => setAsking(null)}>
        <form
          className="flex flex-col gap-3"
          action={(form) => run({ password: String(form.get("password") ?? "") })}
        >
          {error ? <ErrorBanner message={error} /> : null}
          <Field label="새 비밀번호" name="password" type="password" required autoComplete="new-password" help={`${RULE} 그 계정은 다시 로그인해야 합니다.${endsStudio}`} />
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
