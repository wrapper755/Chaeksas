"use client";

import { useState, useTransition } from "react";
import type { EnrollmentInfo } from "@chaeksas/api-types/c5-enrollment-info";
import { Button, DataTable, Dialog, ErrorBanner, Field, StatusBadge, type Column } from "@chaeksas/ui";
import { decideEnrollment } from "@/app/actions";

/**
 * 「승인 대기」 (CON-03·CON-12, C5 §등록 승인, ADR-0092) — **요청이 있을 때만** 목록 위에 보인다.
 *
 * 사람이 하는 일은 하나다: 현장 화면(서버는 로그)의 **요청 코드**가 이 줄과 같은지 보고 들인다.
 * 키는 Center가 만들어 봉해 두므로 여기에 키가 나오지 않는다.
 *
 * 일꾼(C15)은 여기 오지 않는다 — 일꾼 폴더의 파일로만 들어온다 (ADR-0122).
 */
export function Enrollments({
  rows,
  where,
  canDecide,
  nameHelp = "사람이 알아볼 이름. 비우면 요청이 보낸 이름을 씁니다.",
  title = "승인 대기",
  id,
  companies,
}: {
  rows: EnrollmentInfo[];
  /** 확인 창 첫 줄이 가리키는 자리 — 「현장 화면」(PC 실행기) / 「서버 실행기 로그」. */
  where: string;
  canDecide: boolean;
  /** 승인 창 「이름」 칸의 도움말 — Studio는 그 이름이 「누가」라서 다르게 말한다 (CON-11). */
  nameHelp?: string;
  /** 섹션 제목. */
  title?: string;
  /** 다른 화면이 이 섹션으로 걸 때의 앵커. */
  id?: string;
  /**
   * 들일 회사의 고를 거리 (C16 — PC 실행기·Studio는 회사 소유다). 주면 승인 창에 「회사」가 생기고
   * **고르지 않으면 승인하지 않는다**. 서버 실행기는 Center 공용이라 주지 않는다.
   */
  companies?: Array<{ id: string; name: string }>;
}) {
  const [asking, setAsking] = useState<{ kind: "approve" | "reject"; row: EnrollmentInfo } | null>(null);
  const [text, setText] = useState("");
  const [company, setCompany] = useState(companies?.length === 1 ? companies[0].id : "");
  const [error, setError] = useState<string | null>(null);
  const [working, start] = useTransition();

  if (rows.length === 0) return null;

  function open(kind: "approve" | "reject", row: EnrollmentInfo) {
    setText(kind === "approve" ? row.name : "");
    setAsking({ kind, row });
  }

  function decide() {
    if (!asking) return;
    const { kind, row } = asking;
    start(async () => {
      const done = await decideEnrollment(row.enrollment_id, kind, text, companies ? company : undefined);
      setError(done.error ?? null);
      setAsking(null);
    });
  }

  const columns: Array<Column<EnrollmentInfo>> = [
    { key: "code", header: "요청 코드", width: "13ch", mono: true, cell: (row) => <strong>{row.code}</strong> },
    { key: "name", header: "이름" },
    { key: "os", header: "OS", width: "18ch" },
    {
      key: "versions",
      header: "버전",
      width: "12ch",
      mono: true,
      cell: (row) =>
        String(
          row.versions?.bot_ui ??
            row.versions?.server_runner ??
            row.versions?.studio ??
            row.versions?.consumer ??
            Object.values(row.versions ?? {})[0] ??
            "—",
        ),
    },
    { key: "remote_addr", header: "요청한 곳", width: "16ch", mono: true, cell: (row) => row.remote_addr ?? "—" },
    { key: "requested_at", header: "요청 시각", width: "12ch", cell: (row) => clock(row.requested_at) },
    { key: "expires_at", header: "남은 시간", width: "10ch", cell: (row) => left(row.expires_at) },
    {
      key: "existing",
      header: where === "서버 실행기 로그" ? "이 서버의 자리" : "이 PC의 자리",
      cell: (row) => (row.existing ? `「${row.existing.name}」을 이어받음` : "새로"),
    },
    {
      key: "state",
      header: "상태",
      width: "10ch",
      cell: () => <StatusBadge group="등록 요청" label="대기" />,
    },
  ];
  if (canDecide) {
    columns.push({
      key: "actions",
      header: "",
      width: "20ch",
      cell: (row) => (
        <span className="flex gap-2">
          <Button variant="primary" disabled={working} onClick={() => open("approve", row)}>
            승인...
          </Button>
          <Button variant="secondary" disabled={working} onClick={() => open("reject", row)}>
            거절...
          </Button>
        </span>
      ),
    });
  }

  const row = asking?.row;
  return (
    <section id={id} className="mb-6 flex flex-col gap-2">
      <h2 className="text-h2 font-semibold">{title}</h2>
      <p className="text-body-sm text-text-secondary">승인을 기다리는 요청 {rows.length}건</p>
      {error ? <ErrorBanner message={error} /> : null}
      <DataTable columns={columns} rows={rows} rowKey={(one) => one.enrollment_id} caption={title} />

      <Dialog
        open={asking?.kind === "approve"}
        title="이 요청을 승인할까요?"
        onClose={() => setAsking(null)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setAsking(null)}>
              취소
            </Button>
            <Button variant="primary" disabled={working || (companies !== undefined && !company)} onClick={decide}>
              승인
            </Button>
          </>
        }
      >
        <p className="text-body">
          {where}의 요청 코드가 <strong className="font-mono">{row?.code}</strong>인지 확인하세요.
        </p>
        {row?.existing ? (
          <p className="mt-2 text-body-sm text-text-secondary">
            {where === "Studio 설정 창"
              ? `이 PC는 이미 「${row.existing.name}」으로 들어와 있습니다. 승인하면 그 옛 키는 폐기됩니다.`
              : `이미 「${row.existing.name}」으로 등록되어 있습니다. 승인하면 그 자리(배포·실행 기록)를 이어받고 옛 키는 폐기됩니다.`}
          </p>
        ) : null}
        <Field
          className="mt-4"
          label="이름"
          value={text}
          onChange={(event) => setText(event.target.value)}
          help={nameHelp}
        />
        {companies ? (
          <label className="mt-4 flex flex-col gap-1 text-body-sm">
            회사
            <select
              value={company}
              onChange={(event) => setCompany(event.target.value)}
              className="h-9 border border-border-strong bg-bg-surface px-2 text-body"
            >
              <option value="">고르세요</option>
              {companies.map((one) => (
                <option key={one.id} value={one.id}>
                  {one.name}
                </option>
              ))}
            </select>
            <span className="text-text-muted">이 장비가 속할 회사입니다. 그 회사의 BPM 프로세스만 다룹니다.</span>
          </label>
        ) : null}
      </Dialog>

      <Dialog
        open={asking?.kind === "reject"}
        title="이 요청을 거절할까요?"
        onClose={() => setAsking(null)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setAsking(null)}>
              취소
            </Button>
            <Button variant="danger" disabled={working} onClick={decide}>
              거절
            </Button>
          </>
        }
      >
        <Field
          label="사유"
          value={text}
          maxLength={200}
          onChange={(event) => setText(event.target.value)}
          help="선택. 요청한 쪽 화면에 그대로 보입니다 (200자까지)."
        />
      </Dialog>
    </section>
  );
}

function clock(value: string): string {
  const at = new Date(value);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(at.getMonth() + 1)}-${pad(at.getDate())} ${pad(at.getHours())}:${pad(at.getMinutes())}`;
}

function left(value: string): string {
  const minutes = Math.max(0, Math.round((new Date(value).getTime() - Date.now()) / 60000));
  return minutes >= 60 ? `${Math.floor(minutes / 60)}시간` : `${minutes}분`;
}
