import { Enrollments } from "@/components/Enrollments";
import type { EnrollmentInfo } from "@chaeksas/api-types/c5-enrollment-info";
import Link from "next/link";
import { DataTable, EmptyState, ErrorBanner, StatusBadge, type Column } from "@chaeksas/ui";
import type { DeploymentInfo } from "@chaeksas/api-types/c5-deployment-info";
import type { JobInfo } from "@chaeksas/api-types/c5-job-info";
import type { ServerRunnerInfo } from "@chaeksas/api-types/c12-server-runner-info";
import { CenterError, center } from "@/lib/center";
import { queueReason, runnerStatus, serverDeployments } from "@/lib/summary";
import { fullTime, time } from "@/app/bot-uis/page";
import { CancelQueuedJob } from "@/app/server-runners/queue-cancel";
import { RestartRunner } from "@/app/server-runners/actions-ui";

/**
 * 서버 실행기 목록·승인 대기·대기열 — CON-02 「BPM 프로세스」의 「서버」 탭이 그린다 (CON-12 「목록」).
 *
 * **목록과 상세로 나눈다** — 「실행 중」·「기다리는 실행」·「BPM 프로세스별 상한」은 **실행기 하나의
 * 것**이라 상세(`/server-runners/<id>`)에 있다.
 *
 * **「대기열」만 여기 있다.** 서버 작업은 **내려가기 전까지 어느 실행기에도 묶이지 않으므로**
 * (C12 — 대기열은 Center가 가진다) 상세에 넣으면 같은 작업이 실행기마다 모두 보여 「어디서
 * 도는 건가」를 거짓으로 말한다.
 */
/** 아직 내려가지 않은 서버 작업의 상태 (C5 — Center 대기열은 `pending`이다). */
const QUEUED_STATE = "pending";

export async function ServerRunners({ admin }: { admin: boolean }) {
  let rows: ServerRunnerInfo[] = [];
  let enrollments: EnrollmentInfo[] = [];
  let queue: JobInfo[] = [];
  let deployments: DeploymentInfo[] = [];
  let failure: string | null = null;
  try {
    rows = await center.serverRunners();
    // 「승인 대기」 — 등록 요청이 있을 때만 목록 위에 보인다 (C12 §등록 요청과 승인, ADR-0092).
    enrollments = await center.enrollments("server_runner");
    // 대기열은 **종류로** 좁힌다 — 아직 대상이 없는 작업이라 `target_id`로는 못 찾는다 (C12).
    queue = await center.jobs({ state: QUEUED_STATE, target_type: "server_runner" });
    // 「BPM 프로세스별 상한 n」의 n은 **배포 봉투**에 있다 (C12 규칙 3). 활성 배포를 한 번 읽고
    // **서버 것만** 남긴다 — 같은 BPM 프로세스가 PC에도 배포돼 있으면 PC 봉투의 상한을 보일 수 있다.
    deployments = serverDeployments(await center.deployments({ active: true }));
  } catch (cause) {
    failure = cause instanceof CenterError ? cause.message : "알 수 없는 오류가 생겼습니다";
  }

  const columns: Array<Column<ServerRunnerInfo>> = [
    {
      key: "online",
      header: "온라인",
      width: "12ch",
      // 색만으로 뜻을 전하지 않는다 — 글자를 함께 쓴다 (스타일 가이드 §7).
      cell: (row) => <StatusBadge group="온라인" label={row.online ? "온라인" : "오프라인"} />,
    },
    {
      key: "name",
      header: "이름",
      cell: (row) => (
        <Link className="underline" href={`/server-runners/${encodeURIComponent(row.server_runner_id)}`}>
          {row.name}
        </Link>
      ),
    },
    {
      key: "status",
      header: "상태",
      width: "12ch",
      cell: (row) => <StatusBadge group="서버 실행기" label={runnerStatus(row)} />,
    },
    {
      key: "capacity",
      header: "실행 중 / 상한",
      width: "14ch",
      align: "right",
      mono: true,
      // **기다리는 실행은 세지 않는다** (ADR-0054 §5) — 일꾼을 놓았으므로 자리를 쥐지 않는다.
      cell: (row) => `${row.capacity.running} / ${row.capacity.max}`,
    },
    {
      key: "waiting",
      header: "기다리는 실행",
      width: "13ch",
      align: "right",
      cell: (row) => `${(row.waiting ?? []).length}건`,
    },
    {
      key: "queued",
      header: "대기열",
      width: "9ch",
      align: "right",
      cell: (row) => `${row.queued ?? 0}건`,
    },
    { key: "os", header: "OS", width: "20ch" },
    {
      key: "versions",
      header: "버전",
      width: "10ch",
      mono: true,
      cell: (row) => row.versions?.server_runner ?? "—",
    },
    {
      key: "last_heartbeat_at",
      header: "마지막 하트비트",
      width: "16ch",
      cell: (row) => time(row.last_heartbeat_at),
    },
    {
      key: "key",
      header: "API 키",
      width: "26ch",
      mono: true,
      // 만료는 **연도까지** 적는다 — 「01-01」로는 내일인지 내년인지 모른다 (CON-03과 같다).
      cell: (row) =>
        row.key_prefix
          ? `${row.key_prefix}… ${row.key_expires_at ? `(${fullTime(row.key_expires_at)}까지)` : "(무기한)"}`
          : "—",
    },
    // 「재시작...」 (ADR-0117) — 같이 배포된 실행기에서 사람이 할 일은 상태를 보고 재시작하는 것뿐이다.
    ...(admin
      ? [
          {
            key: "restart",
            header: "",
            width: "12ch",
            cell: (row: ServerRunnerInfo) => (
              <RestartRunner
                runnerId={row.server_runner_id}
                name={row.name}
                online={row.online}
                requested={Boolean(row.restart_requested_at)}
                running={row.capacity.running}
              />
            ),
          },
        ]
      : []),
  ];

  const queueColumns: Array<Column<JobInfo>> = [
    {
      key: "job_id",
      header: "작업 id",
      width: "26ch",
      mono: true,
      cell: (row) => (
        <Link className="underline" href={`/jobs/${encodeURIComponent(row.job_id)}`}>
          {row.job_id}
        </Link>
      ),
    },
    {
      key: "bpm_process_id",
      header: "서버 BPM 프로세스",
      cell: (row) => `${row.bpm_process_id}@${row.version ?? "(배포된 버전)"}`,
    },
    { key: "requested_at", header: "요청 시각", width: "16ch", cell: (row) => time(row.requested_at) },
    {
      key: "reason",
      header: "대기 이유",
      width: "18ch",
      cell: (row) => queueReason(row, rows, deployments),
    },
    {
      key: "expires_at",
      header: "만료",
      width: "16ch",
      cell: (row) => (row.expires_at ? fullTime(row.expires_at) : "—"),
    },
    // 쓰기 단추는 **관리자 모드에서만** 보인다 (CON-00 「쓰기 권한」).
    ...(admin
      ? [
          {
            key: "cancel",
            header: "",
            width: "12ch",
            cell: (row: JobInfo) => <CancelQueuedJob jobId={row.job_id} bot={row.bpm_process_id} />,
          },
        ]
      : []),
  ];

  const online = rows.filter((row) => row.online).length;

  return (
    <div className="flex flex-col gap-6">
      <section className="flex flex-col gap-3">
        <h2 className="text-h2 font-semibold">
          서버 실행기{rows.length > 0 ? ` · ${online}/${rows.length} 온라인` : ""}
        </h2>

        {failure ? <ErrorBanner message={failure} /> : null}

        <Enrollments rows={enrollments} where="서버 실행기 로그" canDecide={admin} />

        {rows.length === 0 && !failure ? (
          <EmptyState
            title="등록된 서버 실행기가 없습니다."
            hint="Center와 함께 배포된 실행기는 뜨면 스스로 들어옵니다 — 들어오지 않으면 실행기 로그를 보세요."
          />
        ) : rows.length > 0 ? (
          <DataTable
            columns={columns}
            rows={rows}
            rowKey={(row) => row.server_runner_id}
            caption="서버 실행기 목록"
          />
        ) : null}
      </section>

      <section className="flex flex-col gap-2">
        <h2 className="text-h2 font-semibold">대기열</h2>
        {queue.length === 0 ? (
          <p className="text-body-sm text-text-muted">기다리는 작업이 없습니다.</p>
        ) : (
          <DataTable
            columns={queueColumns}
            rows={queue}
            rowKey={(row) => row.job_id}
            caption="Center 대기열"
          />
        )}
        <p className="text-caption text-text-muted">
          대기열은 Center가 가집니다 — 내려가기 전까지 어느 실행기에도 묶이지 않습니다.
        </p>
      </section>
    </div>
  );
}
