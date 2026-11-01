/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `GET /companies…` — 셈은 읽을 때 센다.
 */
export interface CompanyInfo {
  bot_uis?: number;
  created_at: string;
  departments?: number;
  id: string;
  name: string;
  processes?: number;
  staff?: number;
  state?: string;
  studios?: number;
  updated_at: string;
  [k: string]: unknown;
}
