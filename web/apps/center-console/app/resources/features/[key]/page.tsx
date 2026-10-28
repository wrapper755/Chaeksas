import Link from "next/link";
import { redirect } from "next/navigation";
import { ErrorBanner, StatusBadge } from "@chaeksas/ui";
import { CenterError, session } from "@/lib/center";
import type { FeatureRow } from "@/lib/features";
import { Shell } from "@/components/Shell";
import { loadFeatures } from "../../load";
import { time } from "../../page";
import { RevokeExtension } from "../../tools";

/**
 * CON-07 상세 (기능 하나). 맨 위는 「쓸 수 있나」와 「할 일」이고, 그 아래에는 **사람이 판단하거나
 * 고칠 수 있는 것만** 둔다 — 일꾼·관리 콘솔·id·등록 해제(외부). 주소·키는 일꾼의 설정에만 있어
 * 이 화면에 없다 (C15, ADR-0102). 등급·연결 방식·기여·작업 목록·로컬 런타임도 보이지 않는다.
 */
export default async function FeaturePage({
  params,
  searchParams,
}: {
  params: Promise<{ key: string }>;
  searchParams: Promise<{ error?: string }>;
}) {
  const found = await session();
  if (!found) redirect("/login");
  const { key } = await params;
  const asked = await searchParams;
  const wanted = decodeURIComponent(key);

  let row: FeatureRow | null = null;
  let version = "";
  let failure: string | null = null;
  try {
    const got = await loadFeatures();
    row = got.rows.find((one) => one.key === wanted) ?? null;
    version = got.input.extensions.find((one) => one.id === wanted)?.version ?? "";
    if (!row) failure = "그런 기능이 없습니다.";
  } catch (cause) {
    failure = cause instanceof CenterError ? cause.message : "알 수 없는 오류가 생겼습니다";
  }
  const admin = found.mode === "admin";

  return (
    <Shell mode={found.mode} actor={found.actor} current="/resources">
      <p className="mb-2 text-body-sm">
        <Link className="underline" href="/resources">
          리소스
        </Link>
      </p>
      {failure ? <ErrorBanner message={failure} /> : null}
      {asked.error ? <ErrorBanner message={asked.error} /> : null}

      {row ? (
        <div className="flex flex-col gap-6">
          <header className="flex flex-col gap-2">
            <h1 className="text-h1 font-bold">{row.name}</h1>
            <span>
              <StatusBadge group="기능" label={row.usable} />
            </span>
            {row.todos.length > 0 ? (
              <ul className="flex list-disc flex-col gap-1 pl-5 text-body">
                {row.todos.map((todo) => (
                  <li key={todo.kind}>
                    {todo.href ? (
                      <Link className="underline" href={todo.href as never}>
                        {todo.text}
                      </Link>
                    ) : (
                      todo.text
                    )}
                  </li>
                ))}
              </ul>
            ) : null}
          </header>

          <dl className="grid max-w-2xl grid-cols-[12rem_1fr] gap-x-4 gap-y-2 text-body">
            {row.consumers !== null ? (
              <>
                <dt className="text-text-muted">일꾼</dt>
                <dd>
                  {row.consumers > 0 ? `${row.consumers}개` : "들인 일꾼이 없습니다"}
                  {row.checkedAt ? (
                    <span className="ml-2 text-caption text-text-muted">마지막으로 가져간 때 {time(row.checkedAt)}</span>
                  ) : null}
                  {row.consumers === 0 ? (
                    <Link className="ml-2 underline" href="/resources#consumer-enrollments">
                      일꾼 승인 대기
                    </Link>
                  ) : null}
                </dd>
              </>
            ) : null}
            {row.serviceAppId ? (
              <>
                <dt className="text-text-muted">관리 콘솔</dt>
                <dd>
                  {row.consoleUrl ? (
                    <a className="underline" href={row.consoleUrl} target="_blank" rel="noreferrer">
                      관리 콘솔 열기
                    </a>
                  ) : (
                    "—"
                  )}
                </dd>
              </>
            ) : null}
            <dt className="text-text-muted">id</dt>
            <dd className="font-mono text-caption">{row.id}</dd>
          </dl>

          {admin && row.external ? (
            <section className="flex flex-col gap-2">
              <h2 className="text-h2 font-semibold">등록 해제</h2>
              <RevokeExtension extensionId={row.id} version={version} users={row.usedBy.length} />
            </section>
          ) : null}
        </div>
      ) : null}
    </Shell>
  );
}
