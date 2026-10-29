import Link from "next/link";
import { redirect } from "next/navigation";
import { DataTable, EmptyState, ErrorBanner, StatusBadge, type Column } from "@chaeksas/ui";
import type { DeploymentInfo } from "@chaeksas/api-types/c5-deployment-info";
import type { ServerRunnerInfo } from "@chaeksas/api-types/c12-server-runner-info";
import { CenterError, center, session } from "@/lib/center";
import { botLimitRows, elapsed, runnerStatus, serverDeployments } from "@/lib/summary";
import { Shell } from "@/components/Shell";
import { fullTime, time } from "../../bot-uis/page";
import { ServerRunnerActions } from "../actions-ui";

/**
 * CON-12 서버 실행 (상세) — 서버 실행기·실행 중·기다리는 실행·Bot별 상한.
 *
 * 「실행 중」·「기다리는 실행」·「확장」·「준비」는 **실행기가 하트비트로 보고한 그대로**이고
 * (C12), 「Bot별 상한」의 상한은 **배포 봉투**에 적힌 것이다 (C5). 두 쪽을 여기서 맞춰 보인다 —
 * 「배포는 했는데 왜 안 도나」가 한 화면에서 풀려야 한다 (CON-03과 같은 결).
 *
 * **「대기열」은 여기 없다** — 서버 작업은 내려가기 전까지 어느 실행기에도 묶이지 않으므로
 * (C12) 상세에 넣으면 같은 작업이 실행기마다 모두 보인다. 목록 쪽에 한 번만 있다.
 */

/** 배치 결정 사유 코드 → 글 (C2 위반 코드). 모르는 값은 **그대로 보인다** (원칙 10). */
const WHY: Record<string, string> = {
  bad_signature: "서명이 맞지 않음",
  unknown_key: "모르는 서명 키",
  revoked_key: "서명 키 철회됨",
  wrong_kind: "봉투 종류가 다름",
  expired: "유효 기간 지남",
  not_yet: "아직 시작 전",
  wrong_target: "다른 대상용",
  hash_mismatch: "패키지 내용이 다름",
  unsigned_package: "승인 서명 없음",
  unsupported_alg: "모르는 서명 방식",
  float_in_payload: "봉투에 소수가 들어 있음",
};

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-h2 font-semibold">{title}</h2>
      {children}
    </section>
  );
}

/**
 * 보고된 확장 하나의 상태 (C12 `ExtensionState` → `status_map` 「확장」, ADR-0043).
 *
 * **`off`가 참이면 「꺼짐」, 아니면 「호환 안 됨」이다** — 뭉치면 운영자가 「켜세요」와
 * 「고치세요」 중 틀린 쪽을 안내한다.
 */
function extensionState(row: NonNullable<ServerRunnerInfo["extensions"]>[number]): string {
  if (row.enabled !== false) return "켜짐";
  return row.off ? "꺼짐" : "호환 안 됨";
}

/**
 * 「기다리는 것」 — C12 `waiting[]`의 **짝 칸**으로 적는다 (짝 칸은 비울 수 없다).
 *
 * 타이머의 울릴 시각은 **연도까지** 적는다 — 「01-01」로는 내일인지 내년인지 모른다.
 * 모르는 `waiting_for`는 그대로 보인다 (열린 문자열이다 — 원칙 10).
 */
function waitingFor(row: NonNullable<ServerRunnerInfo["waiting"]>[number]): string {
  if (row.waiting_for === "approval") return `결재 ${row.request_id ?? ""}`.trim();
  if (row.waiting_for === "message") {
    const keys = row.correlation ? Object.entries(row.correlation) : [];
    const shown = keys.map(([key, value]) => `${key}=${String(value)}`).join(", ");
    return `메시지 ${row.message_name ?? ""}${shown ? ` (${shown})` : ""}`.trim();
  }
  if (row.waiting_for === "timer") return `타이머 ${fullTime(row.until)}`;
  // **PC 위임**의 짝 칸은 작업 id다 (ADR-0062) — 그 작업이 CON-05에 있다.
  if (row.waiting_for === "delegation") return `PC 위임 ${row.job_id ?? ""}`.trim();
  return row.waiting_for;
}

export default async function ServerRunnerPage({
  params,
}: {
  params: Promise<{ runnerId: string }>;
}) {
  const found = await session();
  if (!found) redirect("/login");
  const { runnerId } = await params;
  const wanted = decodeURIComponent(runnerId);

  let info: ServerRunnerInfo | null = null;
  let deployments: DeploymentInfo[] = [];
  let failure: string | null = null;
  try {
    // 목록 한 줄이 상세의 재료를 다 들고 있다 (C12 — 실행기별 읽기 경로가 따로 없다).
    info = (await center.serverRunners()).find((row) => row.server_runner_id === wanted) ?? null;
    deployments = serverDeployments(await center.deployments({ active: true }), wanted);
  } catch (cause) {
    failure = cause instanceof CenterError ? cause.message : "알 수 없는 오류가 생겼습니다";
  }

  const running = info?.running ?? [];
  const waiting = info?.waiting ?? [];
  const extensions = info?.extensions ?? [];
  const results = info?.deployment_results ?? [];
  const limits = info ? botLimitRows(info, deployments) : [];
  // 「경과」·「기다린 시간」의 기준은 **그릴 때 한 번** 읽는다 — 줄마다 다시 읽으면 같은
  // 화면의 두 줄이 다른 지금을 쓴다.
  const now = Date.now();

  const runningColumns: Array<Column<(typeof running)[number]>> = [
    {
      key: "run_id",
      header: "실행 id",
      width: "30ch",
      mono: true,
      cell: (row) => (
        <Link className="underline" href={`/runs/${encodeURIComponent(row.run_id)}`}>
          {row.run_id}
        </Link>
      ),
    },
    { key: "bpm_process_id", header: "서버 Bot" },
    { key: "version", header: "버전", width: "10ch", mono: true },
    // 「현재 노드」는 보고가 늦으면 비어 있다 — 0이나 빈 글로 꾸미지 않는다.
    { key: "node_id", header: "현재 노드", width: "20ch", mono: true, cell: (row) => row.node_id ?? "—" },
    { key: "started_at", header: "시작", width: "16ch", cell: (row) => time(row.started_at) },
    {
      key: "elapsed",
      header: "경과",
      width: "12ch",
      align: "right",
      cell: (row) => elapsed(row.started_at, now),
    },
  ];

  const waitingColumns: Array<Column<(typeof waiting)[number]>> = [
    {
      key: "run_id",
      header: "실행 id",
      width: "30ch",
      mono: true,
      cell: (row) => (
        <Link className="underline" href={`/runs/${encodeURIComponent(row.run_id)}`}>
          {row.run_id}
        </Link>
      ),
    },
    { key: "bpm_process_id", header: "서버 Bot" },
    { key: "waiting_for", header: "기다리는 것", cell: waitingFor },
    {
      key: "since",
      header: "기다린 시간",
      width: "14ch",
      align: "right",
      cell: (row) => elapsed(row.since, now),
    },
    {
      key: "link",
      header: "",
      width: "10ch",
      // 결재면 결재함(CON-04), **PC 위임이면 그 작업(CON-05)**으로. 그 밖에는 갈 곳이 없다.
      cell: (row) => {
        if (row.waiting_for === "approval" && row.request_id) {
          return (
            <Link className="underline" href={`/approvals/${encodeURIComponent(row.request_id)}`}>
              결재함
            </Link>
          );
        }
        if (row.waiting_for === "delegation" && row.job_id) {
          return (
            <Link className="underline" href={`/jobs/${encodeURIComponent(row.job_id)}`}>
              작업
            </Link>
          );
        }
        return "—";
      },
    },
  ];

  const limitColumns: Array<Column<(typeof limits)[number]>> = [
    { key: "bot", header: "서버 Bot" },
    { key: "version", header: "배포 버전", width: "12ch", mono: true },
    {
      key: "limit",
      header: "상한",
      width: "10ch",
      align: "right",
      // **배포 봉투에 적힌 값**이고 보기 전용이다. 적혀 있지 않으면 계약의 기본값이 쓰이는데,
      // 그 숫자를 화면에 베껴 적지 않는다 (계약이 바뀌면 화면만 거짓말을 한다).
      cell: (row) => (row.limit === null ? "기본" : String(row.limit)),
    },
    { key: "running", header: "지금 실행 수", width: "13ch", align: "right" },
    {
      key: "readiness",
      header: "준비",
      width: "20ch",
      cell: (row) =>
        row.readiness ? (
          <span
            title={row.readiness.detail.join("\n") || undefined}
          >
            <StatusBadge group="Bot 준비" label={row.readiness.label} />
          </span>
        ) : (
          "보고 없음"
        ),
    },
  ];

  const extensionColumns: Array<Column<(typeof extensions)[number]>> = [
    { key: "id", header: "확장", mono: true },
    { key: "version", header: "버전", width: "12ch", mono: true },
    {
      key: "enabled",
      header: "상태",
      width: "12ch",
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
        <StatusBadge
          group="배치 결정"
          label={row.result === "applied" ? "적용" : row.result === "rejected" ? "거부" : row.result}
        />
      ),
    },
    { key: "deployment_id", header: "배포 id", width: "22ch", mono: true },
    { key: "bpm_process_id", header: "패키지", cell: (row) => `${row.bpm_process_id}@${row.version}` },
    { key: "reason", header: "사유", cell: (row) => (row.reason ? (WHY[row.reason] ?? row.reason) : "—") },
  ];

  return (
    <Shell mode={found.mode} actor={found.actor} current="/bots">
      <header className="mb-4">
        <h1 className="text-h1 font-bold">{info?.name ?? wanted}</h1>
        <p className="text-body text-text-secondary">
          <Link className="underline" href="/bots?tab=server">
            Bot 현황 (서버)
          </Link>
          으로 돌아가기
        </p>
      </header>

      {failure ? <ErrorBanner message={failure} /> : null}

      {!info && !failure ? (
        <EmptyState title="그 서버 실행기가 없습니다." hint="목록에서 다시 고르세요." />
      ) : null}

      {info ? (
        <div className="flex flex-col gap-6">
          {/* 오프라인이면 아래 값이 지금 상태가 아니다 — 언제 기준인지 먼저 말한다 (U8). */}
          {!info.online ? (
            <p className="text-body-sm text-text-muted">
              {info.last_heartbeat_at
                ? `오프라인입니다 — 실행 중·기다리는 실행·확장은 마지막 보고 ${time(info.last_heartbeat_at)} 기준입니다.`
                : "아직 하트비트를 받지 못했습니다 — 실행 중·기다리는 실행은 비어 있습니다."}
            </p>
          ) : null}
          {info.paused ? (
            <ErrorBanner message="일시 중지됨 — 새 작업을 받지 않습니다. 실행 중인 것은 끝까지 돕니다." />
          ) : null}

          <Section title="서버 실행기">
            <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-body sm:grid-cols-4">
              <dt className="text-text-muted">온라인</dt>
              <dd>
                <StatusBadge group="온라인" label={info.online ? "온라인" : "오프라인"} />
              </dd>
              <dt className="text-text-muted">상태</dt>
              <dd>
                <StatusBadge group="서버 실행기" label={runnerStatus(info)} />
              </dd>
              <dt className="text-text-muted">실행 중 / 상한</dt>
              {/* **기다리는 실행은 세지 않는다** (ADR-0054 §5) — 일꾼을 놓았으므로 자리가 빈다. */}
              <dd className="font-mono">
                {info.capacity.running} / {info.capacity.max}
              </dd>
              <dt className="text-text-muted">기다리는 실행</dt>
              <dd>{waiting.length}건</dd>
              <dt className="text-text-muted">대기열</dt>
              <dd>{info.queued ?? 0}건</dd>
              <dt className="text-text-muted">보내지 못한 실행 기록</dt>
              {/* **모르는 것과 0은 다르다** — 보고하지 않았으면 「—」다 (C12에서 선택 칸이다). */}
              <dd>{info.unsent_events === null || info.unsent_events === undefined ? "—" : `${info.unsent_events}건`}</dd>
              <dt className="text-text-muted">OS</dt>
              <dd>{info.os}</dd>
              <dt className="text-text-muted">버전</dt>
              <dd className="font-mono">
                {info.versions
                  ? `실행기 ${info.versions.server_runner} · core ${info.versions.core}`
                  : "보고 없음"}
              </dd>
              <dt className="text-text-muted">마지막 하트비트</dt>
              <dd>{time(info.last_heartbeat_at)}</dd>
              <dt className="text-text-muted">처음 등록</dt>
              <dd>{time(info.registered_at)}</dd>
              <dt className="text-text-muted">Center API 키</dt>
              <dd className="font-mono">
                {info.key_prefix ? `${info.key_prefix}…` : "—"}
                {info.key_expires_at ? ` (${fullTime(info.key_expires_at)}까지)` : " (무기한)"}
              </dd>
            </dl>

            <h3 className="text-body font-semibold">확장</h3>
            {extensions.length === 0 ? (
              <p className="text-body-sm text-text-muted">이 서버가 보고한 확장이 없습니다.</p>
            ) : (
              <DataTable
                columns={extensionColumns}
                rows={extensions}
                rowKey={(row) => row.id}
                caption="설치된 확장"
              />
            )}

            <h3 className="text-body font-semibold">최근 배치 결정</h3>
            {results.length === 0 ? (
              <p className="text-body-sm text-text-muted">실행기가 올린 배치 결정이 아직 없습니다.</p>
            ) : (
              <DataTable
                columns={resultColumns}
                rows={results}
                rowKey={(row, index) => `${row.deployment_id}-${row.at}-${index}`}
                caption="최근 배치 결정"
              />
            )}
          </Section>

          <Section title="실행 중">
            {running.length === 0 ? (
              <p className="text-body-sm text-text-muted">지금 도는 실행이 없습니다.</p>
            ) : (
              <DataTable
                columns={runningColumns}
                rows={running}
                rowKey={(row) => row.run_id}
                caption="실행 중"
              />
            )}
          </Section>

          <Section title="기다리는 실행">
            {waiting.length === 0 ? (
              <p className="text-body-sm text-text-muted">기다리는 실행이 없습니다.</p>
            ) : (
              <DataTable
                columns={waitingColumns}
                rows={waiting}
                rowKey={(row) => row.run_id}
                caption="기다리는 실행"
              />
            )}
            <p className="text-caption text-text-muted">
              기다리는 실행은 일꾼을 놓았으므로 상한에 세지 않습니다 — 결재·메시지·타이머가 오면
              되살아나 이어 갑니다.
            </p>
          </Section>

          <Section title="Bot별 상한">
            {limits.length === 0 ? (
              <p className="text-body-sm text-text-muted">
                이 실행기에 걸린 활성 배포가 없습니다. 「배포」에서 배포하세요.
              </p>
            ) : (
              <DataTable
                columns={limitColumns}
                rows={limits}
                rowKey={(row) => `${row.bot}@${row.version}`}
                caption="Bot별 상한"
              />
            )}
          </Section>

          {found.mode === "admin" ? (
            <Section title="관리">
              <ServerRunnerActions
                runnerId={info.server_runner_id}
                paused={info.paused ?? false}
                online={info.online}
                running={running.length}
                waiting={waiting.length}
              />
            </Section>
          ) : null}
        </div>
      ) : null}
    </Shell>
  );
}
