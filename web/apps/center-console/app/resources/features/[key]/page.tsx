import Link from "next/link";
import { redirect } from "next/navigation";
import { Button, ErrorBanner, StatusBadge } from "@chaeksas/ui";
import { CENTER_PUBLIC_URL, CenterError, session } from "@/lib/center";
import type { AddressView, FeatureRow } from "@/lib/features";
import { Shell } from "@/components/Shell";
import { putAppKey, resetExtensionAddress, setExtensionAddress, setServiceAppUrl } from "@/app/actions";
import { loadFeatures } from "../../load";
import { time } from "../../page";
import { DeleteAppKey, RevokeExtension, UnregisterServiceApp } from "../../tools";

/**
 * CON-07 상세 (기능 하나). 맨 위는 「쓸 수 있나」와 「할 일」이고, 그 아래에는 **사람이 고칠 수
 * 있는 것만** 둔다 — 서버 주소·관리 콘솔·id·등록 해제. 등급·연결 방식·기여·작업 목록·로컬
 * 런타임은 보이지 않는다 (고칠 것이 없거나, 설계할 때 쓰는 것이라 Studio에 있다).
 */
function keyLine(slot: { set: boolean; setAt: string | null; setBy: string | null }): string {
  if (!slot.set) return "없음";
  return `넣음 (${slot.setAt ? time(slot.setAt) : "—"}, ${slot.setBy ?? "—"})`;
}

/** 외부 기능 「서버 주소」 옆에 붙는 출처 (ADR-0097). */
function addressNote(address: AddressView): string {
  if (address.source === "center") {
    return `Center에서 바꿈 (${address.setAt ? time(address.setAt) : "—"}, ${address.setBy ?? "—"})`;
  }
  if (address.source === "outside") return "기본값 — Center에서 바꾼 주소를 지금 정의가 허용하지 않습니다";
  return "기본값";
}

export default async function FeaturePage({
  params,
  searchParams,
}: {
  params: Promise<{ key: string }>;
  searchParams: Promise<{ error?: string; moved?: string; reset?: string; key_saved?: string }>;
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
    <Shell mode={found.mode} actor={found.actor} centerUrl={CENTER_PUBLIC_URL} current="/resources">
      <p className="mb-2 text-body-sm">
        <Link className="underline" href="/resources">
          리소스
        </Link>
      </p>
      {failure ? <ErrorBanner message={failure} /> : null}
      {asked.error ? <ErrorBanner message={asked.error} /> : null}
      {asked.moved ? <p className="mb-4 text-body text-status-completed-fg">주소를 바꿨습니다.</p> : null}
      {asked.reset ? <p className="mb-4 text-body text-status-completed-fg">기본값으로 되돌렸습니다.</p> : null}
      {asked.key_saved ? (
        <p className="mb-4 text-body text-status-completed-fg">
          {asked.key_saved === "test"
            ? "시험용 키를 넣었습니다 — Studio가 다음에 청할 때 받습니다."
            : "키를 넣었습니다 — 쓰는 Bot이 배포된 곳에 내려 줍니다."}
        </p>
      ) : null}

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
            {row.serviceAppId ? (
              <>
                <dt className="text-text-muted">서버 주소</dt>
                <dd className="font-mono">
                  {row.serverUrl ?? "—"}
                  {row.checkedAt ? (
                    <span className="ml-2 text-caption text-text-muted">확인 {time(row.checkedAt)}</span>
                  ) : null}
                </dd>
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
            {row.address ? (
              <>
                <dt className="text-text-muted">서버 주소</dt>
                <dd>
                  <span className="font-mono">{row.address.url || "—"}</span>
                  <span className="ml-2 text-caption text-text-muted">{addressNote(row.address)}</span>
                  {row.checkedAt ? (
                    <span className="ml-2 text-caption text-text-muted">확인 {time(row.checkedAt)}</span>
                  ) : null}
                </dd>
              </>
            ) : null}
            {row.appKey ? (
              <>
                <dt className="text-text-muted">외부 앱 키</dt>
                <dd>{keyLine(row.appKey.run)}</dd>
                <dt className="text-text-muted">시험용 키</dt>
                <dd>
                  {row.appKey.test.set ? keyLine(row.appKey.test) : "없음 — Studio 시험 실행이 이 앱을 부르지 못합니다"}
                  <span className="ml-2 text-caption text-text-muted">Studio 시험 실행에만 가고 현장에는 가지 않습니다</span>
                </dd>
              </>
            ) : null}
            {row.serviceAppId && row.trust ? (
              <>
                <dt className="text-text-muted">Center 발급</dt>
                <dd>{row.trust === "trusted" ? "받음" : row.trust === "unknown" ? "확인 전" : `받지 않음 — ${row.trust}`}</dd>
              </>
            ) : null}
            <dt className="text-text-muted">id</dt>
            <dd className="font-mono text-caption">{row.id}</dd>
          </dl>

          {admin && row.appKey ? (
            <section id="app-key" className="flex flex-col gap-4">
              {(["run", "test"] as const).map((slot) => (
                <div key={slot} className="flex flex-col gap-2">
                  <h2 className="text-h2 font-semibold">
                    {slot === "run"
                      ? row.appKey?.run.set
                        ? "키 바꾸기"
                        : "키 넣기"
                      : row.appKey?.test.set
                        ? "시험용 키 바꾸기"
                        : "시험용 키 넣기"}
                  </h2>
                  <p className="text-body-sm text-text-muted">
                    {slot === "run"
                      ? "Center가 암호화해 두고, 쓰는 Bot이 배포된 곳에 내려 줍니다. 넣은 뒤에는 다시 보이지 않습니다. Studio 시험 실행에는 이 키를 주지 않습니다 — 시험용 키는 따로 넣습니다."
                      : "Studio 시험 실행에만 쓰입니다. 운영 데이터에 닿지 않는 시험용 키(시험 계정)를 넣으세요."}
                  </p>
                  <form action={putAppKey} className="flex max-w-xl flex-wrap items-end gap-2">
                    <input type="hidden" name="extension_id" value={row.id} />
                    <input type="hidden" name="slot" value={slot} />
                    <label className="flex flex-1 flex-col gap-1 text-body-sm">
                      <span className="text-text-muted">키 *</span>
                      <input
                        type="password"
                        name="key"
                        required
                        autoComplete="off"
                        className="h-9 border border-border-strong bg-bg-surface px-2 text-body"
                      />
                    </label>
                    <Button type="submit" variant="primary">
                      저장
                    </Button>
                  </form>
                  {(slot === "run" ? row.appKey?.run.set : row.appKey?.test.set) ? (
                    <div>
                      <DeleteAppKey extensionId={row.id} slot={slot} users={row.usedBy.length} />
                    </div>
                  ) : null}
                </div>
              ))}
            </section>
          ) : null}

          {admin && row.address ? (
            <section id="address" className="flex flex-col gap-2">
              <h2 className="text-h2 font-semibold">주소 바꾸기</h2>
              <form action={setExtensionAddress} className="flex max-w-xl flex-wrap items-end gap-2">
                <input type="hidden" name="extension_id" value={row.id} />
                <label className="flex flex-1 flex-col gap-1 text-body-sm">
                  <span className="text-text-muted">API 주소 *</span>
                  <input
                    type="url"
                    name="base_url"
                    required
                    defaultValue={row.address.url}
                    className="h-9 border border-border-strong bg-bg-surface px-2 text-body"
                  />
                </label>
                <Button type="submit" variant="primary">
                  저장
                </Button>
              </form>
              <p className="text-body-sm text-text-muted">
                허용 호스트: {row.address.allowedHosts.join(", ") || "—"} (정의 밖 호스트는 받지 않습니다)
              </p>
              {row.address.source !== "default" ? (
                <form action={resetExtensionAddress}>
                  <input type="hidden" name="extension_id" value={row.id} />
                  <Button type="submit" variant="secondary">
                    기본값으로 되돌리기
                  </Button>
                </form>
              ) : null}
            </section>
          ) : null}

          {admin && row.serviceAppId ? (
            <section className="flex flex-col gap-2">
              <h2 className="text-h2 font-semibold">서버 주소 바꾸기</h2>
              <p className="text-body-sm text-text-muted">
                주소는 여기서만 바꿉니다 — 현장은 이 주소만 씁니다 (C7).
              </p>
              <form action={setServiceAppUrl} className="flex max-w-xl flex-wrap items-end gap-2">
                <input type="hidden" name="app_id" value={row.serviceAppId} />
                <label className="flex flex-1 flex-col gap-1 text-body-sm">
                  <span className="text-text-muted">API 주소 *</span>
                  <input
                    type="url"
                    name="base_url"
                    required
                    defaultValue={row.serverUrl ?? ""}
                    className="h-9 border border-border-strong bg-bg-surface px-2 text-body"
                  />
                </label>
                <Button type="submit" variant="primary">
                  주소 바꾸기
                </Button>
              </form>
            </section>
          ) : null}

          {admin && (row.external || row.serviceAppId) ? (
            <section className="flex flex-col gap-2">
              <h2 className="text-h2 font-semibold">등록 해제</h2>
              {row.external ? (
                <RevokeExtension extensionId={row.id} version={version} users={row.usedBy.length} />
              ) : row.serviceAppId ? (
                <UnregisterServiceApp appId={row.serviceAppId} users={row.usedBy} />
              ) : null}
            </section>
          ) : null}
        </div>
      ) : null}
    </Shell>
  );
}
