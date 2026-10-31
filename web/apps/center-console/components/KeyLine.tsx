import type { CenterKeyInfo } from "@chaeksas/api-types/c7-center-key-info";
import { StatusBadge } from "@chaeksas/ui";
import { STATE_LABEL } from "@/lib/center-keys";
import { KeyMenu } from "./KeyMenu";

/**
 * 상세 요약의 「API 키」 한 칸 (CON-03 Bot 상세·CON-12 상세) — 앞자리·만료, 그 키의 상태와 관리자면 「...」.
 * 키 동작은 그 키가 가리키는 것을 보는 화면에 있다 (ADR-0124). 키를 찾지 못하면 보고에 실린 앞자리만 보인다.
 */
export function KeyLine({
  prefix,
  until,
  row,
  admin,
}: {
  prefix: string | null | undefined;
  until: string | null;
  row: CenterKeyInfo | null;
  admin: boolean;
}) {
  if (!prefix) return <>—</>;
  return (
    <span className="flex flex-wrap items-center gap-2">
      <span className="font-mono">
        {prefix}… {until ? `(${until}까지)` : "(무기한)"}
      </span>
      {row ? <StatusBadge group="API 키" label={STATE_LABEL[row.state] ?? row.state} /> : null}
      {row && admin ? <KeyMenu row={row} /> : null}
    </span>
  );
}
