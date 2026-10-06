import Link from "next/link";
import { redirect } from "next/navigation";
import { Button, ErrorBanner, StatusBadge } from "@chaeksas/ui";
import type { ApprovalInfo, FormField } from "@chaeksas/api-types/c6-approval-info";
import { CENTER_URL, CenterError, center, session } from "@/lib/center";
import { Shell } from "@/components/Shell";
import { answerApproval } from "@/app/actions";
import { WithdrawApproval } from "../withdraw";
import { STATE_LABEL, WITHDRAW_LABEL, time, where } from "../page";

/**
 * CON-04 결재함 (상세) — 검토 자료와 답하기.
 *
 * **값이 보이는 유일한 곳이다** (C6 §`review`는 원칙 6의 예외). 그래서 접어 둔다 (U10).
 *
 * 「답하기」는 **일반 `<form>` + 서버 액션**이다 — JS 없이도 답할 수 있고, 폼과 맞지 않는
 * 답은 Center가 칸 이름과 함께 돌려주어 그 자리에 보인다 (C6 `answer_invalid`).
 */

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-h2 font-semibold">{title}</h2>
      {children}
    </section>
  );
}

/** 검토 자료 한 칸 — 목록은 글머리표로, 그 밖은 글자로 (CMN-01과 같은 규칙, C6). */
function Shown({ value }: { value: unknown }) {
  if (Array.isArray(value)) {
    return (
      <ul className="list-disc pl-5">
        {value.map((one, index) => (
          <li key={index}>{typeof one === "object" ? JSON.stringify(one) : String(one)}</li>
        ))}
      </ul>
    );
  }
  if (value !== null && typeof value === "object") {
    return <code className="text-body-sm">{JSON.stringify(value)}</code>;
  }
  return <>{String(value)}</>;
}

/** 폼 칸 하나 → 입력 칸 (C6 `type`). 모르는 종류는 글 칸이다. */
function Field({ field, bad }: { field: FormField; bad: boolean }) {
  const border = bad ? "border-status-failed-solid" : "border-border-strong";
  const common = `h-9 border px-2 text-body bg-bg-surface ${border}`;
  // 계약의 `default`는 아무 타입이나 올 수 있다 (C6) — 칸 종류에 맞춰 읽는다.
  const preset: unknown = field.default;
  return (
    <label className="flex flex-col gap-1 text-body-sm">
      <span className={bad ? "text-status-failed-fg" : "text-text-muted"}>
        {field.label}
        {field.required ? " *" : ""}
      </span>
      {field.type === "bool" ? (
        <input type="checkbox" name={field.key} defaultChecked={preset === true} className="size-5" />
      ) : field.type === "choice" ? (
        <select name={field.key} className={common} defaultValue={preset == null ? "" : String(preset)}>
          <option value="">(고르세요)</option>
          {(field.choices ?? []).map((one) => (
            <option key={String(one)} value={String(one)}>
              {String(one)}
            </option>
          ))}
        </select>
      ) : (
        <input
          type={field.type === "number" ? "number" : "text"}
          name={field.key}
          step={field.type === "number" ? "any" : undefined}
          defaultValue={preset == null ? "" : String(preset)}
          className={common}
        />
      )}
    </label>
  );
}

export default async function ApprovalPage({
  params,
  searchParams,
}: {
  params: Promise<{ requestId: string }>;
  searchParams: Promise<{ error?: string; fields?: string; answered?: string }>;
}) {
  const found = await session();
  if (!found) redirect("/login");
  const { requestId } = await params;
  const asked = await searchParams;
  const wanted = decodeURIComponent(requestId);
  const bad = new Set((asked.fields ?? "").split(",").filter(Boolean));

  let info: ApprovalInfo | null = null;
  let failure: string | null = null;
  try {
    info = await center.approval(wanted);
  } catch (cause) {
    failure = cause instanceof CenterError ? cause.message : "알 수 없는 오류가 생겼습니다";
  }

  const fields = info?.form?.fields ?? [];
  const review = Object.entries(info?.review ?? {});
  const canAnswer = found.mode === "admin" && info?.state === "open";

  return (
    <Shell mode={found.mode} actor={found.actor} centerUrl={CENTER_URL} current="/approvals">
      <header className="mb-4">
        <h1 className="text-h1 font-bold">{info?.title ?? "결재 요청"}</h1>
        <p className="text-body text-text-secondary">
          <Link className="underline" href="/approvals">
            결재함
          </Link>
          으로 돌아가기
        </p>
      </header>

      {failure ? <ErrorBanner message={failure} /> : null}
      {asked.answered ? (
        <p className="mb-4 text-body text-status-completed-fg">
          답을 보냈습니다. 실행하는 쪽이 다음 하트비트에 받아 갑니다.
        </p>
      ) : null}

      {info ? (
        <div className="flex flex-col gap-6">
          {/* 거절은 되돌림이다 — 요청은 다시 「대기」이고, 왜 거절됐는지가 위에 선다 (C6). */}
          {info.delivery_accepted === false && info.delivery_reason ? (
            <ErrorBanner
              message={`Bot UI가 이전 답을 거절했습니다: ${info.delivery_reason} — 고쳐서 다시 답하세요`}
            />
          ) : null}

          <Section title="요약">
            <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-body sm:grid-cols-4">
              <dt className="text-text-muted">상태</dt>
              <dd>
                <StatusBadge group="결재" label={STATE_LABEL[info.state] ?? info.state} />
              </dd>
              <dt className="text-text-muted">실행하는 곳</dt>
              <dd>{where(info)}</dd>
              <dt className="text-text-muted">Bot</dt>
              <dd>
                {info.bpm_process_id}@{info.version}
              </dd>
              <dt className="text-text-muted">노드</dt>
              <dd className="font-mono">{info.node_id}</dd>
              <dt className="text-text-muted">실행 id</dt>
              <dd className="font-mono">
                <Link className="underline" href={`/runs/${encodeURIComponent(info.run_id)}`}>
                  {info.run_id}
                </Link>
              </dd>
              <dt className="text-text-muted">요청 시각</dt>
              <dd>{time(info.created_at)}</dd>
              <dt className="text-text-muted">시한</dt>
              <dd>{time(info.expires_at)}</dd>
              <dt className="text-text-muted">전달됨</dt>
              <dd>{info.delivered ? "실행하는 쪽이 받아 갔습니다" : "아직"}</dd>
            </dl>
            {info.description ? <p className="text-body text-text-secondary">{info.description}</p> : null}
          </Section>

          {/* **값이 보이는 유일한 곳**이다 (C6). 접어 둔다 (U10). */}
          <Section title="결재에 필요한 값">
            {review.length === 0 ? (
              <p className="text-body-sm text-text-muted">올라온 검토 자료가 없습니다.</p>
            ) : (
              <details>
                <summary className="cursor-pointer text-body-sm text-text-muted">
                  업무 데이터 {review.length}개 — 펼쳐 보기
                </summary>
                <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-body">
                  {review.map(([name, value]) => (
                    <div key={name} className="contents">
                      <dt className="text-text-muted">{name}</dt>
                      <dd>
                        <Shown value={value} />
                      </dd>
                    </div>
                  ))}
                </dl>
              </details>
            )}
          </Section>

          {info.state === "answered" ? (
            <Section title="답">
              <p className="text-body">
                {JSON.stringify(info.answer)}{" "}
                <span className="text-text-muted">
                  ({info.answered_by} — 자칭, 신원 검증 없음 · {time(info.answered_at)})
                </span>
              </p>
            </Section>
          ) : null}

          {info.state === "withdrawn" ? (
            <Section title="회수">
              <p className="text-body">
                회수됨 — {WITHDRAW_LABEL[info.withdraw_reason ?? ""] ?? info.withdraw_reason ?? "사유 없음"}
              </p>
            </Section>
          ) : null}

          {canAnswer ? (
            <Section title="답하기">
              {asked.error ? <ErrorBanner message={asked.error} /> : null}
              <form action={answerApproval} className="flex max-w-xl flex-col gap-3">
                <input type="hidden" name="request_id" value={info.request_id} />
                {fields.length === 0 ? (
                  <>
                    {/* 폼이 없으면 「승인 / 반려」다 (C6 `decision`). **거절도 답이다.** */}
                    <fieldset className="flex gap-4 text-body">
                      <legend className="text-body-sm text-text-muted">결정 *</legend>
                      <label className="flex items-center gap-2">
                        <input type="radio" name="decision" value="approve" defaultChecked />
                        승인
                      </label>
                      <label className="flex items-center gap-2">
                        <input type="radio" name="decision" value="reject" />
                        반려
                      </label>
                    </fieldset>
                    <label className="flex flex-col gap-1 text-body-sm">
                      <span className="text-text-muted">메모</span>
                      <input
                        type="text"
                        name="comment"
                        className="h-9 border border-border-strong bg-bg-surface px-2 text-body"
                      />
                    </label>
                  </>
                ) : (
                  fields.map((field) => (
                    <Field key={field.key} field={field} bad={bad.has(field.key)} />
                  ))
                )}
                <label className="flex flex-col gap-1 text-body-sm">
                  <span className="text-text-muted">답하는 사람 (자칭 — 신원 검증 없음) *</span>
                  <input
                    type="text"
                    name="actor"
                    required
                    defaultValue={found.actor}
                    className="h-9 border border-border-strong bg-bg-surface px-2 text-body"
                  />
                </label>
                <div className="flex gap-2">
                  <Button type="submit" variant="primary">
                    답 보내기
                  </Button>
                </div>
              </form>
              <WithdrawApproval requestId={info.request_id} />
            </Section>
          ) : found.mode !== "admin" && info.state === "open" ? (
            <p className="text-body-sm text-text-muted">
              답하려면 「관리자」 모드로 들어오세요 — 지금은 보기 전용입니다.
            </p>
          ) : null}
        </div>
      ) : null}
    </Shell>
  );
}
