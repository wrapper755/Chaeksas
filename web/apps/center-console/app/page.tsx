"use client";

import { useState } from "react";
import type { PackageInfo } from "@chaeksas/api-types/c5-package-info";
import { CONTRACT_MODULES } from "@chaeksas/api-types";
import {
  Button,
  ConfirmDialog,
  DataTable,
  EmptyState,
  ErrorBanner,
  Field,
  StatusBadge,
  type Column,
} from "@chaeksas/ui";

/**
 * Center 콘솔 (ADR-0017). **아직 뼈대다** — 토큰·구성요소·계약 타입이 이어졌는지 보는 페이지다.
 *
 * 실제 화면(CON-00 공통 틀, CON-03 Bot UI 현황, CON-11 Center API 키 …)은 Center API가 생기는
 * M2에 만든다 (`docs/06-screens/center-console.md`, `docs/05-roadmap.md`).
 */

/** 보기용 값이다 (서버에서 온 것이 아니다). 타입은 계약 C5에서 생성한 것을 쓴다. */
const SAMPLE: PackageInfo[] = [
  {
    id: "invoice-check",
    version: "1.4.0",
    kind: "bpm_process",
    name: "세금계산서 확인",
    status: "승인됨",
    run_location: "server",
    content_hash: "sha256:0000000000000000000000000000000000000000000000000000000000000000",
    uploaded_at: "2026-10-03T09:12:00+09:00",
    uploaded_by: "studio@설계자-pc",
  },
  {
    id: "erp-order-entry",
    version: "0.9.2",
    kind: "bpm_process",
    name: "ERP 주문 입력",
    status: "후보",
    run_location: "pc",
    content_hash: "sha256:1111111111111111111111111111111111111111111111111111111111111111",
    uploaded_at: "2026-10-03T08:40:00+09:00",
    uploaded_by: "studio@설계자-pc",
  },
];

const COLUMNS: Array<Column<PackageInfo>> = [
  { key: "id", header: "id", mono: true, width: "22ch" },
  { key: "name", header: "이름" },
  { key: "version", header: "버전", mono: true, width: "10ch" },
  {
    key: "status",
    header: "상태",
    width: "14ch",
    cell: (row) => <StatusBadge group="패키지" label={row.status} />,
  },
  { key: "run_location", header: "실행 위치", width: "10ch" },
];

export default function Page() {
  const [confirming, setConfirming] = useState(false);
  const [keyRef, setKeyRef] = useState("");

  return (
    <main className="mx-auto flex max-w-[1280px] flex-col gap-6 p-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-h1 font-bold">Center 콘솔</h1>
        <p className="text-body text-text-secondary">
          뼈대입니다. 디자인 토큰·공용 구성요소·계약 타입이 이어졌는지 보는 페이지이고, 실제 화면은 M2에
          만듭니다.
        </p>
      </header>

      <section className="flex flex-col gap-2">
        <h2 className="text-h2 font-semibold">상태 표기</h2>
        <p className="text-body-sm text-text-muted">
          색은 <code className="font-mono">design/tokens.json</code>의 <code className="font-mono">status_map</code>이
          정합니다. 화면이 색을 고르지 않습니다.
        </p>
        <div className="flex flex-wrap gap-2">
          <StatusBadge group="Bot" label="실행 중" />
          <StatusBadge group="Bot" label="결재 대기" />
          <StatusBadge group="Bot UI" label="연결 끊김" />
          <StatusBadge group="실행·노드" label="재생됨" />
          <StatusBadge group="실행·노드" label="실패" />
          <StatusBadge group="확장" label="호환 안 됨" />
        </div>
      </section>

      <section className="flex flex-col gap-2">
        <h2 className="text-h2 font-semibold">패키지</h2>
        <DataTable
          columns={COLUMNS}
          rows={SAMPLE}
          rowKey={(row) => `${row.id}@${row.version}`}
          caption="보기용 패키지 목록"
        />
      </section>

      <section className="flex flex-col gap-2">
        <h2 className="text-h2 font-semibold">구성요소</h2>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="primary">배포...</Button>
          <Button variant="secondary">새로 고침</Button>
          <Button variant="ghost">상세</Button>
          <Button variant="danger" onClick={() => setConfirming(true)}>
            키 폐기...
          </Button>
          <Button variant="secondary" disabled disabledReason="승인된 패키지만 배포할 수 있습니다.">
            배포 (꺼짐)
          </Button>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <Field
            label="서비스 앱 키 참조"
            required
            help="BPM 프로세스 속성에 쓰는 참조 이름입니다. 키 값은 넣지 않습니다."
            value={keyRef}
            onChange={(e) => setKeyRef(e.target.value)}
            placeholder="erp-writer"
          />
          <Field
            label="이름"
            error="같은 이름이 이미 있습니다 — 다른 이름을 쓰세요."
            defaultValue="erp-writer"
          />
        </div>

        <ErrorBanner
          message="Center에 닿지 못했습니다 — 주소와 포트를 확인하세요"
          code="center_unreachable"
          details={"GET http://center:8500/api/v1/packages\nconnect ECONNREFUSED"}
          action={<Button variant="secondary">다시 시도</Button>}
        />

        <EmptyState
          title="작업 지시가 없습니다."
          hint="「새 작업...」으로 만들면 여기에 나타납니다."
          action={<Button variant="primary">새 작업...</Button>}
        />
      </section>

      <footer className="text-caption text-text-muted">
        계약 타입 {CONTRACT_MODULES.length}묶음을 <code className="font-mono">packages/contracts/schemas</code>에서
        생성했습니다.
      </footer>

      <ConfirmDialog
        open={confirming}
        title="키를 폐기할까요?"
        description="폐기하면 이 키로 부르던 Bot이 즉시 실패합니다. 되돌릴 수 없습니다."
        confirmLabel="폐기"
        onConfirm={() => setConfirming(false)}
        onCancel={() => setConfirming(false)}
      />
    </main>
  );
}
