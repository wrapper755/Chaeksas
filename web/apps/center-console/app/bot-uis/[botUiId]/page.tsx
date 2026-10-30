import Link from "next/link";
import { redirect } from "next/navigation";
import { DataTable, EmptyState, ErrorBanner, StatusBadge, type Column } from "@chaeksas/ui";
import type { BotUiInfo } from "@chaeksas/api-types/c5-bot-ui-info";
import type { DeploymentInfo } from "@chaeksas/api-types/c5-deployment-info";
import { CenterError, center, session } from "@/lib/center";
import { readinessLabel } from "@/lib/summary";
import { Shell } from "@/components/Shell";
import { BotUiActions, SelectorRegistration } from "../actions-ui";
import type { Route } from "next";
import { fullTime, runtimeLabel, running, statusLabel, time, workerLabel } from "../page";

/**
 * CON-03 PC 현황 — PC 실행기 상세 — 대기열·배포·확장·최근 배치 결정.
 *
 * 대기열·확장은 **PC 실행기가 하트비트로 보고한 그대로**이고 보기 전용이다 (Center 작업을
 * 취소하는 곳은 CON-05다). 배포는 Center가 가진 것, 「준비」는 PC 실행기가 보고한 것이라
 * **두 쪽을 여기서 맞춰 보인다** — 「배포는 했는데 왜 안 도나」가 한 화면에서 풀려야 한다.
 */

/** 배치 결정 사유 코드 → 글 (C2 위반 코드). 모르는 값은 **그대로 보인다** (원칙 10). */
const WHY: Record<string, string> = {
  bad_signature: "서명이 맞지 않음",
  unknown_key: "모르는 서명 키",
  revoked_key: "서명 키 철회됨",
  wrong_kind: "봉투 종류가 다름",
  expired: "유효 기간 지남",
  not_yet: "아직 시작 전",
  wrong_target: "다른 PC용",
  hash_mismatch: "패키지 내용이 다름",
  unsigned_package: "승인 서명 없음",
  unsupported_alg: "모르는 서명 방식",
  float_in_payload: "봉투에 소수가 들어 있음",
};

const SOURCE: Record<string, string> = {
  job: "작업",
  manual: "수동",
  watch: "감시",
  schedule: "일정",
  message: "메시지",
  delegation: "위임",
};

/** 「셀렉터 등록」 한 줄 — 이 PC의 Tool UI가 셀렉터 등록 작업을 올려도 되나 (C15 §올리기). */
function selectorLine(info: BotUiInfo): string {
  if (!info.selector_registration) return "꺼짐 — 이 PC의 Tool UI는 셀렉터를 등록할 수 없습니다.";
  return "켜짐 — 이 PC의 Tool UI가 셀렉터 등록 작업을 올릴 수 있습니다.";
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-h2 font-semibold">{title}</h2>
      {children}
    </section>
  );
}

/**
 * 유효 기간 한 칸 — 「즉시 ~ 무기한」까지 **빈칸 없이** 말하고 **연도를 적는다**.
 * 내일 끝나는 배포와 내년에 끝나는 배포가 같아 보이면 안 된다.
 */
function validity(row: DeploymentInfo): string {
  const from = row.not_before ? fullTime(row.not_before) : "즉시";
  return `${from} ~ ${row.expires_at ? fullTime(row.expires_at) : "무기한"}`;
}

/**
 * 보고된 확장 하나의 상태 (C4 `ExtensionState` → `status_map` 「확장」, ADR-0043).
 *
 * **`off`가 참이면 「꺼짐」, 아니면 「호환 안 됨」이다** — `enabled`는 「지금 쓰이는가」라서 둘을
 * 가르지 못한다. 옛 PC 실행기는 `off`를 보내지 않으므로 없으면 흠으로 읽는다 (원칙 3).
 */
function extensionState(row: NonNullable<BotUiInfo["extensions"]>[number]): string {
  if (row.enabled !== false) return "켜짐";
  return row.off ? "꺼짐" : "호환 안 됨";
}

/**
 * 그 배포가 이 PC에서 **돌 준비가 됐는가** — PC 실행기가 보고한 `readiness`에서 찾는다 (C4).
 * 아직 보고가 없으면 「확인 전」이 아니라 **없는 것으로 둔다** (모르는 것을 안다고 하지 않는다).
 *
 * 가르는 것은 `lib/summary.ts`의 `readinessLabel` **하나**다 — CON-12가 같은 일을 하므로
 * 베끼면 갈라진다 (점검 코드를 이름으로 어림하다 「확장 없음」을 놓친 적이 있다).
 */
function readinessOf(row: DeploymentInfo, info: BotUiInfo): string | null {
  const found = (info.readiness ?? []).find(
    (one) => one.bpm_process_id === row.bpm_process_id && one.version === row.version,
  );
  return readinessLabel(found)?.label ?? null;
}

export default async function BotUiPage({ params }: { params: Promise<{ botUiId: string }> }) {
  const found = await session();
  if (!found) redirect("/login");
  const { botUiId } = await params;
  const wanted = decodeURIComponent(botUiId);

  let info: BotUiInfo | null = null;
  let deployments: DeploymentInfo[] = [];
  let failure: string | null = null;
  try {
    info = (await center.botUis()).find((row) => row.bot_ui_id === wanted) ?? null;
    deployments = await center.deployments({ botUi: wanted, active: true });
  } catch (cause) {
    failure = cause instanceof CenterError ? cause.message : "알 수 없는 오류가 생겼습니다";
  }

  const queue = info?.queue?.items ?? [];
  const extensions = info?.extensions ?? [];
  const results = info?.deployment_results ?? [];

  // 순서는 **보고된 차례 그대로**다 (C4 — `items`는 순서대로 온다).
  const numbered = queue.map((item, index) => ({ ...item, order: index + 1 }));

  const queueColumns: Array<Column<(typeof numbered)[number]>> = [
    { key: "order", header: "순서", width: "7ch", align: "right" },
    {
      key: "bpm_process_id",
      header: "BPM 프로세스",
      cell: (row) => `${row.bpm_process_id}${row.version ? `@${row.version}` : ""}`,
    },
    { key: "source", header: "출처", width: "10ch", cell: (row) => SOURCE[row.source] ?? row.source },
    { key: "requested_at", header: "요청 시각", width: "16ch", cell: (row) => time(row.requested_at) },
    { key: "expires_at", header: "만료", width: "16ch", cell: (row) => (row.expires_at ? time(row.expires_at) : "—") },
  ];

  const deployColumns: Array<Column<DeploymentInfo>> = [
    {
      key: "deployment_id",
      header: "배포 id",
      width: "26ch",
      mono: true,
      // 철회는 「배포」 화면 한 곳에서 한다 (같은 단추는 한 곳).
      cell: (row) => (
        <Link className="underline" href={`/deployments#${row.deployment_id}` as Route}>
          {row.deployment_id}
        </Link>
      ),
    },
    { key: "bpm_process_id", header: "BPM 프로세스" },
    { key: "version", header: "버전", width: "10ch", mono: true },
    { key: "validity", header: "유효 기간", width: "26ch", cell: validity },
    {
      key: "ready",
      header: "준비",
      width: "18ch",
      cell: (row) => {
        const label = info ? readinessOf(row, info) : null;
        if (!label) return "보고 없음";
        return <StatusBadge group="BPM 프로세스 준비" label={label} />;
      },
    },
  ];

  const extensionColumns: Array<Column<(typeof extensions)[number]>> = [
    { key: "id", header: "확장", mono: true },
    { key: "version", header: "버전", width: "12ch", mono: true },
    {
      key: "enabled",
      header: "상태",
      width: "12ch",
      // **「꺼짐」과 「호환 안 됨」을 가른다** (ADR-0043) — `off`는 사람이 껐다는 뜻이고,
      // `enabled: false`에 `off`가 없으면 고쳐야 할 흠이다 (E1·E3~E6). 뭉치면 운영자가
      // 「켜세요」와 「고치세요」 중 틀린 쪽을 안내한다.
      cell: (row) => <StatusBadge group="확장" label={extensionState(row)} />,
    },
  ];

  const resultColumns: Array<Column<(typeof results)[number]>> = [
    { key: "at", header: "시각", width: "16ch", cell: (row) => time(row.at) },
    {
      key: "result",
      header: "결과",
      width: "12ch",
      cell: (row) => (
        <StatusBadge group="배치 결정" label={row.result === "applied" ? "적용" : row.result === "rejected" ? "거부" : row.result} />
      ),
    },
    { key: "deployment_id", header: "배포 id", width: "22ch", mono: true },
    {
      key: "bpm_process_id",
      header: "패키지",
      cell: (row) => `${row.bpm_process_id}@${row.version}`,
    },
    { key: "reason", header: "사유", cell: (row) => (row.reason ? (WHY[row.reason] ?? row.reason) : "—") },
  ];

  return (
    <Shell mode={found.mode} actor={found.actor} current="/bot-uis">
      <header className="mb-4">
        <h1 className="text-h1 font-bold">{info?.name ?? wanted}</h1>
        <p className="text-body text-text-secondary">
          <Link className="underline" href="/bot-uis">
            PC 현황
          </Link>
          으로 돌아가기
        </p>
      </header>

      {failure ? <ErrorBanner message={failure} /> : null}

      {!info && !failure ? (
        <EmptyState title="그 PC 실행기가 없습니다." hint="목록에서 다시 고르세요." />
      ) : null}

      {info ? (
        <div className="flex flex-col gap-6">
          {/* 오프라인이면 아래 값이 지금 상태가 아니다 — 언제 기준인지 먼저 말한다 (U8). */}
          {!info.online ? (
            <p className="text-body-sm text-text-muted">
              {info.last_seen_at
                ? `오프라인입니다 — 실행·대기열·Worker는 마지막 보고 ${time(info.last_seen_at)} 기준입니다.`
                : "아직 하트비트를 받지 못했습니다 — 실행·대기열은 비어 있습니다."}
            </p>
          ) : null}
          {info.disabled ? (
            <ErrorBanner message="비활성화됨 — 이 PC에 새 작업·배포를 보내지 않습니다. 실행 중인 BPM 프로세스는 끝까지 돕니다." />
          ) : null}

          <Section title="요약">
            <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-body sm:grid-cols-4">
              <dt className="text-text-muted">온라인</dt>
              <dd>
                <StatusBadge group="온라인" label={info.online ? "온라인" : "오프라인"} />
              </dd>
              <dt className="text-text-muted">상태</dt>
              <dd>{info.status ? <StatusBadge group="BPM 프로세스" label={statusLabel(info.status)} /> : "—"}</dd>
              <dt className="text-text-muted">실행 중</dt>
              <dd>{running(info)}</dd>
              <dt className="text-text-muted">Worker 프로세스</dt>
              <dd>
                {info.worker ? (
                  <StatusBadge group="Worker 프로세스" label={workerLabel(info.worker.state)} />
                ) : (
                  "—"
                )}
              </dd>
              <dt className="text-text-muted">Worker 예약</dt>
              <dd className="font-mono">{info.worker?.reserved_for ?? "—"}</dd>
              <dt className="text-text-muted">OS</dt>
              <dd>{info.os}</dd>
              <dt className="text-text-muted">버전</dt>
              <dd className="font-mono">
                PC 실행기 {info.versions.bot_ui} · core {info.versions.core}
                {info.versions.worker ? ` · Worker ${info.versions.worker}` : ""}
                {/* 어디서 도는지 (C4 `versions.build`, ADR-0067) — 없으면 묶지 않은 것이다. */}
                {info.versions.build
                  ? ` · 묶음 ${info.versions.build.commit.slice(0, 12)} · ${fullTime(info.versions.build.built_at)}`
                  : " · 개발 체크아웃"}
              </dd>
              <dt className="text-text-muted">런타임</dt>
              <dd>{runtimeLabel(info)}</dd>
              <dt className="text-text-muted">마지막 하트비트</dt>
              <dd>{time(info.last_seen_at)}</dd>
              <dt className="text-text-muted">처음 등록</dt>
              <dd>{time(info.registered_at)}</dd>
              <dt className="text-text-muted">Center API 키</dt>
              <dd className="font-mono">
                {info.key ? `${info.key.prefix}…` : "—"}
                {info.key?.expires_at ? ` (${fullTime(info.key.expires_at)}까지)` : " (무기한)"}
              </dd>
            </dl>
          </Section>

          <Section title="대기열">
            {numbered.length === 0 ? (
              <p className="text-body-sm text-text-muted">대기열이 비어 있습니다.</p>
            ) : (
              <DataTable
                columns={queueColumns}
                rows={numbered}
                rowKey={(row) => row.queue_id}
                caption="대기열"
              />
            )}
            <p className="text-caption text-text-muted">
              보기 전용입니다 — Center 작업을 취소하려면 「작업 지시」에서 하세요.
            </p>
          </Section>

          <Section title="배포">
            {deployments.length === 0 ? (
              <p className="text-body-sm text-text-muted">
                이 PC 실행기에 걸린 활성 배포가 없습니다. 「배포」에서 배포하세요.
              </p>
            ) : (
              <DataTable
                columns={deployColumns}
                rows={deployments}
                rowKey={(row) => row.deployment_id}
                caption="활성 배포"
              />
            )}
          </Section>

          <Section title="확장">
            {extensions.length === 0 ? (
              <p className="text-body-sm text-text-muted">이 PC가 보고한 확장이 없습니다.</p>
            ) : (
              <DataTable
                columns={extensionColumns}
                rows={extensions}
                rowKey={(row) => row.id}
                caption="설치된 확장"
              />
            )}
          </Section>

          <Section title="셀렉터 등록">
            <p className="text-body-sm">{selectorLine(info)}</p>
            {found.mode === "admin" ? (
              <SelectorRegistration botUiId={info.bot_ui_id} on={info.selector_registration ?? false} />
            ) : null}
          </Section>

          <Section title="최근 배치 결정">
            {results.length === 0 ? (
              <p className="text-body-sm text-text-muted">PC 실행기가 올린 배치 결정이 아직 없습니다.</p>
            ) : (
              <DataTable
                columns={resultColumns}
                rows={results}
                rowKey={(row, index) => `${row.deployment_id}-${row.at}-${index}`}
                caption="최근 배치 결정"
              />
            )}
          </Section>

          {found.mode === "admin" ? (
            <Section title="관리">
              <BotUiActions botUiId={info.bot_ui_id} disabled={info.disabled ?? false} />
            </Section>
          ) : null}
        </div>
      ) : null}
    </Shell>
  );
}
