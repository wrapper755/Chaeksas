"use client";

import type { ServiceAppManifest } from "@chaeksas/api-types/c11-service-app-manifest";
import { Button, DataTable, EmptyState, Field, StatusBadge, type Column } from "@chaeksas/ui";

/**
 * 서비스 앱 관리 콘솔 (ADR-0017 §1). **아직 뼈대다.**
 *
 * 한 벌로 모든 서비스 앱의 콘솔을 그린다 — 접속한 앱의 `/manifest`(C11)를 읽어 `app_id`에 맞는
 * 메뉴만 켜고, 앱 고유 화면(UIA-01~03)은 확장의 `console.pages` 모듈로 붙인다.
 * 실제 화면(SVC-00~03)은 `service_kit`의 관리 API가 생기는 M2에 만든다.
 */

/** 보기용 값이다 (앱의 `/manifest`에서 온 것이 아니다). 타입은 계약 C11에서 생성했다. */
const SAMPLE: ServiceAppManifest = {
  schema: 1,
  app_id: "ui-automation",
  name: "UI 자동화",
  version: "0.1.0",
  category: "system",
  console_url: "http://localhost:8001",
  operations: [
    { name: "plan", description: "화면 계획 받기", modes: ["autonomous", "deterministic"], server_ok: true },
    { name: "heal", description: "치유 제안", modes: ["autonomous"], server_ok: true },
    { name: "report", description: "세션 보고", modes: ["autonomous", "deterministic"], server_ok: true },
  ],
};

type Operation = NonNullable<ServiceAppManifest["operations"]>[number];

const COLUMNS: Array<Column<Operation>> = [
  { key: "name", header: "작업", mono: true, width: "16ch" },
  { key: "description", header: "설명" },
  {
    key: "modes",
    header: "수행 모드",
    width: "22ch",
    cell: (row) => (row.modes ?? []).join(", "),
  },
];

export default function Page() {
  return (
    <main className="mx-auto flex max-w-[1280px] flex-col gap-6 p-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-h1 font-bold">{SAMPLE.name} 관리 콘솔</h1>
        <p className="text-body text-text-secondary">
          뼈대입니다. 접속한 서비스 앱의 <code className="font-mono">/manifest</code>를 읽어 메뉴를 켜는 일은
          M2에 만듭니다.
        </p>
        <div className="flex items-center gap-2">
          <StatusBadge group="서비스 앱" label="정상" />
          <span className="font-mono text-caption text-text-muted">
            {SAMPLE.app_id}@{SAMPLE.version}
          </span>
        </div>
      </header>

      <section className="flex flex-col gap-2">
        <h2 className="text-h2 font-semibold">작업</h2>
        <DataTable
          columns={COLUMNS}
          rows={SAMPLE.operations ?? []}
          rowKey={(row) => row.name}
          density="compact"
          caption="보기용 작업 목록"
        />
      </section>

      <section className="flex flex-col gap-2">
        <h2 className="text-h2 font-semibold">API 키</h2>
        <EmptyState
          title="발급된 키가 없습니다."
          hint="「키 발급...」으로 만들면 원문을 한 번만 보여 줍니다."
          action={<Button variant="primary">키 발급...</Button>}
        />
        <Field
          label="키 이름"
          help="운영·개발처럼 쓰임을 적습니다. 키 원문은 발급 직후 한 번만 보입니다."
          placeholder="bot-ui-운영"
        />
      </section>
    </main>
  );
}
