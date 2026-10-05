/* 생성 파일: packages/contracts/schemas에서 만든다. 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * 서비스 앱 하나 (확장의 서버 부분).
 */
export interface ServiceAppResource {
  app_id: string;
  base_url?: string | null;
  category?: string | null;
  checked_at?: string | null;
  console_url?: string | null;
  extension_id?: string | null;
  manifest_at?: string | null;
  name?: string | null;
  operations?: Operation[];
  status?: string;
  status_reasons?: string[];
  used_by?: string[];
  version?: string | null;
  [k: string]: unknown;
}
/**
 * 작업 하나. Studio가 이것만 보고 서비스 앱 태스크 편집기(STU-14)를 만든다.
 */
export interface Operation {
  description?: string | null;
  fallback?: string;
  input_schema?: {
    [k: string]: unknown;
  } | null;
  modes?: string[];
  name: string;
  output_schema?: {
    [k: string]: unknown;
  } | null;
  required_scopes?: string[];
  server_ok?: boolean;
  timeout_s?: number;
  [k: string]: unknown;
}
