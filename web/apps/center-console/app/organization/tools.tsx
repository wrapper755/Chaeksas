"use client";

import { useActionState, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Button, ConfirmDialog, Dialog, ErrorBanner, Field } from "@chaeksas/ui";
import { createOrgItem, removeOrgItem, updateOrgItem, type ActionResult } from "@/app/actions";
import { KIND_LABEL, type OrgKind } from "@/lib/organization";

/**
 * CON-13 조직의 손잡이들 — 고른 자리의 「새 부서...」·「새 직원...」·「멈추기」/「다시 쓰기」와 「...」.
 * 규칙(id 모양·회사 안의 부서인지·가리키는 것이 있는지)은 **Center가 본다** — 틀리면 그 까닭을
 * 창 안에 보이고 닫지 않는다.
 */
const ID_HELP = "영문 소문자·숫자·.·_·- 64자까지, Center 전체에서 하나. 바꿀 수 없습니다";
const SELECT = "h-9 border border-border-strong bg-bg-surface px-2 text-body";
const STOP_SAID = "그 자리 업무는 새 작업을 받지 않습니다. 돌던 실행은 그대로입니다. 「다시 쓰기」로 되돌릴 수 있습니다.";

type Option = { id: string; name: string };

/** 고른 자리 — PUT이 **본문 전체**라 지금 값을 들고 다닌다 (C16). */
export interface OrgItem {
  kind: OrgKind;
  id: string;
  name: string;
  state: string;
  company: string;
  department?: string | null;
}

function DepartmentSelect({ departments, defaultValue }: { departments: Option[]; defaultValue?: string | null }) {
  return (
    <label className="flex flex-col gap-1 text-body-sm">
      부서
      <select name="department" defaultValue={defaultValue ?? ""} className={SELECT}>
        <option value="">없음 (회사에 바로)</option>
        {departments.map((one) => (
          <option key={one.id} value={one.id}>
            {one.name}
          </option>
        ))}
      </select>
    </label>
  );
}

/** 「새 회사...」·「새 부서...」·「새 직원...」 — 만들면 그 자리를 고른다. */
export function NewOrgItem({
  kind,
  company = "",
  departments = [],
  department,
}: {
  kind: OrgKind;
  company?: string;
  departments?: Option[];
  department?: string | null;
}) {
  const [open, setOpen] = useState(false);
  const [result, action, pending] = useActionState<ActionResult, FormData>(createOrgItem, {});
  const label = KIND_LABEL[kind];
  return (
    <>
      <Button variant={kind === "company" ? "primary" : "secondary"} size="sm" onClick={() => setOpen(true)}>
        새 {label}...
      </Button>
      <Dialog open={open} title={`새 ${label}`} onClose={() => setOpen(false)}>
        <form action={action} className="flex flex-col gap-3">
          {result.error ? <ErrorBanner message={result.error} /> : null}
          <input type="hidden" name="kind" value={kind} />
          <input type="hidden" name="company" value={company} />
          <Field label="id" name="id" required autoComplete="off" autoCapitalize="none" help={ID_HELP} />
          <Field label="이름" name="name" required autoComplete="off" />
          {kind === "staff" ? <DepartmentSelect departments={departments} defaultValue={department} /> : null}
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

type Ask = "stop" | "rename" | "move" | "remove";

/** 「멈추기」/「다시 쓰기」와 「...」(이름 바꾸기·부서 옮기기·등록 해제). */
export function OrgItemTools({
  item,
  departments,
  canRename,
  canStop,
  removeBlocked,
}: {
  item: OrgItem;
  departments: Option[];
  canRename: boolean;
  canStop: boolean;
  /** 등록 해제를 끌 까닭 — `null`이면 켠다. 회사에는 등록 해제가 없다(C16). */
  removeBlocked: string | null;
}) {
  const [menu, setMenu] = useState(false);
  const [asking, setAsking] = useState<Ask | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const router = useRouter();
  const stopped = item.state === "stopped";

  const body = (change: Partial<OrgItem>): Record<string, unknown> => {
    const next = { ...item, ...change };
    const out: Record<string, unknown> = { name: next.name, state: next.state };
    if (item.kind !== "company") out.company = next.company;
    if (item.kind === "staff") out.department = next.department || null;
    return out;
  };
  const run = (change: Partial<OrgItem>) =>
    start(async () => {
      const done = await updateOrgItem(item.kind, item.id, body(change));
      setError(done.error ?? null);
      if (!done.error) {
        setAsking(null);
        router.refresh();
      }
    });
  const remove = () =>
    start(async () => {
      if (item.kind === "company") return;
      const done = await removeOrgItem(item.kind, item.id, item.company);
      setError(done.error ?? null);
    });

  const items: Array<{ ask: Ask; label: string; off?: string | null }> = [
    ...(canRename ? [{ ask: "rename" as Ask, label: "이름 바꾸기..." }] : []),
    ...(item.kind === "staff" ? [{ ask: "move" as Ask, label: "부서 옮기기..." }] : []),
    ...(item.kind !== "company" ? [{ ask: "remove" as Ask, label: "등록 해제...", off: removeBlocked }] : []),
  ];
  const label = KIND_LABEL[item.kind];

  return (
    <div className="relative flex flex-wrap items-center gap-2">
      {canStop ? (
        stopped ? (
          // 되돌릴 수 있고 해가 없다 — 묻지 않는다 (U9).
          <Button size="sm" variant="secondary" disabled={pending} onClick={() => run({ state: "active" })}>
            다시 쓰기
          </Button>
        ) : (
          <Button size="sm" variant="secondary" onClick={() => setAsking("stop")}>
            멈추기...
          </Button>
        )
      ) : null}
      {items.length > 0 ? (
        <Button size="sm" variant="ghost" aria-label={`${item.name} ${label} 동작`} onClick={() => setMenu(!menu)}>
          ...
        </Button>
      ) : null}
      {menu ? (
        <ul className="absolute right-0 top-full z-10 flex min-w-[240px] flex-col border border-border-default bg-bg-surface py-1 shadow-md">
          {items.map((one) => (
            <li key={one.ask}>
              <button
                type="button"
                disabled={Boolean(one.off)}
                title={one.off ?? undefined}
                className="w-full px-3 py-2 text-left text-body hover:bg-bg-subtle disabled:cursor-not-allowed disabled:text-text-muted disabled:hover:bg-transparent"
                onClick={() => {
                  setMenu(false);
                  setError(null);
                  setAsking(one.ask);
                }}
              >
                {one.label}
                {one.off ? <span className="block text-body-sm">{one.off}</span> : null}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {error && asking === null ? <ErrorBanner message={error} /> : null}

      <ConfirmDialog
        open={asking === "stop"}
        title={`${label} ${item.name}을 멈출까요?`}
        description={item.kind === "company" ? `${STOP_SAID} 그 회사의 배포·승인도 막힙니다.` : STOP_SAID}
        confirmLabel="멈추기"
        danger
        onConfirm={() => run({ state: "stopped" })}
        onCancel={() => setAsking(null)}
      />
      <ConfirmDialog
        open={asking === "remove"}
        title={`${label} ${item.name}을 등록 해제할까요?`}
        description={error ?? "기록에 남은 id는 그대로입니다. 되돌릴 수 없습니다."}
        confirmLabel="등록 해제"
        danger
        onConfirm={remove}
        onCancel={() => setAsking(null)}
      />
      <Dialog open={asking === "rename"} title={`${label} 이름 바꾸기`} onClose={() => setAsking(null)}>
        <form className="flex flex-col gap-3" action={(form) => run({ name: String(form.get("name") ?? "").trim() })}>
          {error ? <ErrorBanner message={error} /> : null}
          <Field label="이름" name="name" required defaultValue={item.name} autoComplete="off" />
          <div className="flex justify-end">
            <Button type="submit" variant="primary" disabled={pending}>
              바꾸기
            </Button>
          </div>
        </form>
      </Dialog>
      <Dialog open={asking === "move"} title={`${item.name} 부서 옮기기`} onClose={() => setAsking(null)}>
        <form
          className="flex flex-col gap-3"
          action={(form) => run({ department: String(form.get("department") ?? "") || null })}
        >
          {error ? <ErrorBanner message={error} /> : null}
          <DepartmentSelect departments={departments} defaultValue={item.department} />
          <span className="text-body-sm text-text-muted">이미 돈 작업의 자리는 그대로입니다.</span>
          <div className="flex justify-end">
            <Button type="submit" variant="primary" disabled={pending}>
              옮기기
            </Button>
          </div>
        </form>
      </Dialog>
    </div>
  );
}
