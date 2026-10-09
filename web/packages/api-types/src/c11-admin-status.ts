/* 생성 파일: packages/contracts/schemas에서 만든다. 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `GET /admin/v1/status` (SVC-01). **관리자 토큰으로만** 부른다.
 */
export interface AdminStatus {
  app_id: string;
  category: string;
  center?: CenterRegistration;
  console_url?: string | null;
  dependencies?: Dependency[];
  extension?: ExtensionRef | null;
  name: string;
  operations?: OperationStatus[];
  /**
   * 이 계약의 schema 번호
   */
  schema: number;
  started_at: string;
  uptime_s?: number;
  version: string;
  [k: string]: unknown;
}
/**
 * Center 리소스 목록(C7)에 올라가 있나 (SVC-01 「Center 등록」).
 */
export interface CenterRegistration {
  base_url?: string | null;
  last_reported_at?: string | null;
  registered?: boolean;
  [k: string]: unknown;
}
/**
 * 바깥 의존 하나 (SVC-01 「의존」) — 예: Neo4j, LLM 게이트웨이.
 */
export interface Dependency {
  detail?: string | null;
  name: string;
  status: string;
  [k: string]: unknown;
}
/**
 * 이 서비스 앱이 어느 확장의 서버 부분인가 (C13). 내장·사내 확장이면 넣는다.
 */
export interface ExtensionRef {
  id: string;
  version: string;
  [k: string]: unknown;
}
/**
 * 작업 하나의 선언 + 최근 통계 (SVC-01 「작업」). 수는 앱 안의 사용 기록에서 센다.
 */
export interface OperationStatus {
  calls_24h?: number;
  description?: string | null;
  error_rate?: number;
  errors_24h?: number;
  fallback?: string;
  modes?: string[];
  name: string;
  server_ok?: boolean;
  [k: string]: unknown;
}
