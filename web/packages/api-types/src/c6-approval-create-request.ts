/* 생성 파일: packages/contracts/schemas에서 만든다. 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `POST /api/v1/approvals` — 실행하는 쪽이 결재를 올린다.
 *
 * `request_id`는 `run_id`·`node_id`·`node_instance`와 **맞아야 한다**. 어긋나면 답이 엉뚱한
 * 노드로 돌아갈 수 있으므로 모델이 막는다.
 */
export interface ApprovalCreateRequest {
  bpm_process_id: string;
  description?: string | null;
  expires_at?: string | null;
  form?: Form | null;
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
  title?: string | null;
  version: string;
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
