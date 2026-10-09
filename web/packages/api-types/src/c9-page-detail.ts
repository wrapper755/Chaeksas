/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `GET /admin/v1/pages/{page_id}` — UIA-02 화면 하나 (대체된 것 포함).
 */
export interface PageDetail {
  app?: string | null;
  elements?: ElementRow[];
  locators?: LocatorRow[];
  name?: string;
  page_id: string;
  platform?: string;
  revision?: number;
  /**
   * 이 계약의 schema 번호
   */
  schema: number;
  strategies?: StrategyStat[];
  updated_at?: string | null;
  url_pattern?: string | null;
  warnings?: string[];
  [k: string]: unknown;
}
/**
 * UIA-02 「선행 조건·화면 이동」 한 줄 — 요소 하나가 아는 것 (C9 `catalog`·`elements`).
 */
export interface ElementRow {
  actions?: string[];
  concepts?: string[];
  depends_on?: string[];
  description?: string | null;
  kind?: string | null;
  name?: string | null;
  navigates_to?: string | null;
  role?: string | null;
  semantic_key: string;
  [k: string]: unknown;
}
/**
 * UIA-02 표의 한 줄 — 로케이터 하나와 그 성적.
 *
 * **셀렉터(물리 정보)가 나간다** — 관리자 토큰으로만 오는 길이다 (C9 §관리 콘솔이 읽는 길).
 */
export interface LocatorRow {
  control_type?: string | null;
  fail?: number;
  healed?: boolean;
  last_success_at?: string | null;
  name?: string | null;
  rank: number;
  semantic_key: string;
  status?: string;
  streak?: number;
  success?: number;
  success_rate?: number | null;
  supersedes?: string[];
  type: string;
  value: string;
  [k: string]: unknown;
}
/**
 * UIA-02 「전략별 성공·실패」 — 전략 하나의 합.
 */
export interface StrategyStat {
  fail?: number;
  success?: number;
  type: string;
  [k: string]: unknown;
}
