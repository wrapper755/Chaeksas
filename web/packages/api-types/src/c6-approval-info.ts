/* 생성 파일: packages/contracts/schemas에서 만든다. 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `GET /api/v1/approvals` — 콘솔(CON-04 결재함)이 읽는 모양.
 */
export interface ApprovalInfo {
  answer?: {
    [k: string]: unknown;
  } | null;
  answered_at?: string | null;
  answered_by?: string | null;
  bpm_process_id: string;
  created_at: string;
  delivered?: boolean;
  delivery_accepted?: boolean | null;
  delivery_reason?: string | null;
  description?: string | null;
  expires_at?: string | null;
  form?: Form | null;
  host: ApprovalHost;
  layer: string;
  node_id: string;
  node_instance: number;
  request_id: string;
  review?: {
    [k: string]: unknown;
  };
  run_id: string;
  /**
   * 이 계약의 schema 번호
   */
  schema: number;
  state: string;
  version: string;
  withdraw_reason?: string | null;
  [k: string]: unknown;
}
/**
 * 답의 모양. 없으면 「승인 / 반려」 두 단추다.
 */
export interface Form {
  fields?: FormField[];
  [k: string]: unknown;
}
/**
 * 결재 폼의 칸 하나. STU-04 결재 「출력」 표와 같은 모양이다.
 */
export interface FormField {
  choices?: unknown[] | null;
  default?: {
    [k: string]: unknown;
  };
  key: string;
  label: string;
  required?: boolean;
  type: string;
  [k: string]: unknown;
}
/**
 * 이 결재를 올린 쪽.
 */
export interface ApprovalHost {
  id: string;
  name?: string | null;
  type: string;
  [k: string]: unknown;
}
