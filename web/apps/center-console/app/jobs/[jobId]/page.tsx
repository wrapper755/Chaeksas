import Link from "next/link";
import { redirect } from "next/navigation";
import { ErrorBanner, StatusBadge } from "@chaeksas/ui";
import type { JobInfo } from "@chaeksas/api-types/c5-job-info";
import type { BotUiInfo } from "@chaeksas/api-types/c5-bot-ui-info";
import { CENTER_URL, CenterError, center, session } from "@/lib/center";
import { Shell } from "@/components/Shell";
import { CancelJob } from "../cancel";
import {
  CANCELLABLE,
  STATE_LABEL,
  botLabel,
  delegatedFrom,
  location,
  reason,
  stateNote,
  targetName,
  time,
} from "../labels";

/**
 * CON-05 작업 지시 (상세).
 *
 * 입력은 **업무 데이터**라 접어 둔다 (U10). 「전체 JSON」에도 입력은 넣지 않는다 — 한 번
 * 펼쳤다고 값이 함께 보이면 접어 둔 뜻이 없다.
 */

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="text-text-muted">{label}</dt>
      <dd>{children}</dd>
    </>
  );
}

export default async function JobPage({
  params,
  searchParams,
}: {
  params: Promise<{ jobId: string }>;
  searchParams: Promise<{ created?: string }>;
}) {
  const found = await session();
  if (!found) redirect("/login");
  const { jobId } = await params;
  const asked = await searchParams;

  let job: JobInfo | null = null;
  let botUis: BotUiInfo[] = [];
  let failure: string | null = null;
  try {
    job = await center.job(decodeURIComponent(jobId));
    botUis = await center.botUis();
  } catch (cause) {
    failure = cause instanceof CenterError ? cause.message : "알 수 없는 오류가 생겼습니다";
  }

  const note = job ? stateNote(job, botUis) : null;
  const from = job ? delegatedFrom(job) : null;
  const withoutInputs = job ? Object.fromEntries(Object.entries(job).filter(([key]) => key !== "inputs")) : {};

  return (
    <Shell mode={found.mode} actor={found.actor} centerUrl={CENTER_URL} current="/jobs">
      <header className="mb-4">
        <h1 className="text-h1 font-bold">작업 {job?.job_id ?? ""}</h1>
        <p className="text-body text-text-secondary">
          <Link className="underline" href="/jobs">
            작업 지시
          </Link>
          로 돌아가기
        </p>
      </header>

      {failure ? <ErrorBanner message={failure} /> : null}
      {asked.created ? (
        <p className="mb-4 text-body text-status-completed-fg">
          작업을 만들었습니다. Bot UI가 다음 하트비트에 받아 갑니다.
        </p>
      ) : null}

      {job ? (
        <div className="flex flex-col gap-6">
          <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-body sm:grid-cols-4">
            <Row label="상태">
              <div className="flex flex-col gap-1">
                <StatusBadge group="작업" label={STATE_LABEL[job.state] ?? job.state} />
                {note ? <span className="text-body-sm text-text-muted">{note}</span> : null}
              </div>
            </Row>
            <Row label="실행 위치">{location(job)}</Row>
            <Row label="Bot UI">{targetName(job, botUis)}</Row>
            <Row label="Bot">{botLabel(job)}</Row>
            <Row label="요청자">
              {from ? (
                <Link className="underline" href={`/runs/${encodeURIComponent(from)}`}>
                  서버 Bot ({from})
                </Link>
              ) : (
                job.requested_by
              )}
            </Row>
            <Row label="요청 시각">{time(job.requested_at)}</Row>
            <Row label="만료">{time(job.expires_at)}</Row>
            <Row label="전달 시각">{time(job.dispatched_at)}</Row>
            <Row label="실행 id">
              {job.run_id ? (
                <Link className="font-mono underline" href={`/runs/${encodeURIComponent(job.run_id)}`}>
                  {job.run_id}
                </Link>
              ) : (
                "—"
              )}
            </Row>
            <Row label="실행 상태">{job.run_status ?? "—"}</Row>
            <Row label="거절 사유">{job.state === "rejected" ? reason(job) : "—"}</Row>
            <Row label="메모">{job.note ?? "—"}</Row>
          </dl>

          {found.mode === "admin" && CANCELLABLE.has(job.state) && !job.cancel_requested ? (
            <div>
              <CancelJob jobId={job.job_id} />
            </div>
          ) : null}

          <details className="border border-border-default p-3">
            <summary className="cursor-pointer text-body font-medium">입력 (업무 데이터)</summary>
            {Object.keys(job.inputs ?? {}).length === 0 ? (
              <p className="mt-2 text-body-sm text-text-muted">입력이 없습니다.</p>
            ) : (
              <dl className="mt-2 grid grid-cols-[max-content_1fr] gap-x-6 gap-y-1 text-body">
                {Object.entries(job.inputs).map(([key, value]) => (
                  <Row key={key} label={key}>
                    <code className="text-body-sm">
                      {typeof value === "string" ? value : JSON.stringify(value)}
                    </code>
                  </Row>
                ))}
              </dl>
            )}
          </details>

          <details className="border border-border-default p-3">
            <summary className="cursor-pointer text-body font-medium">전체 JSON (입력 제외)</summary>
            <pre className="mt-2 overflow-x-auto text-body-sm">{JSON.stringify(withoutInputs, null, 2)}</pre>
          </details>
        </div>
      ) : null}
    </Shell>
  );
}
