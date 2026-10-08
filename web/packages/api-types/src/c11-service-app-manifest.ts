/* 생성 파일: packages/contracts/schemas에서 만든다. 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `GET /manifest` — 인증 없음 (비밀이 없다). Center가 리소스 목록에 쓴다 (C7).
 */
export interface ServiceAppManifest {
  app_id: string;
  category: string;
  console_url: string;
  extension?: ExtensionRef | null;
  name: string;
  operations?: Operation[];
  resources?: ResourceCatalog[];
  /**
   * 이 계약의 schema 번호
   */
  schema: number;
  version: string;
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
/**
 * 이 앱이 **자기 기여 자원 카탈로그**를 어디서 주는지 (C7 §리소스 모으는 방식).
 *
 * 확장 정의(C13 `contributes.resources`)에도 같은 것이 있지만, **내장·사내 확장의 정의는
 * Center에 없다** — 설치 파일에 들어 있고 Center는 실행하는 쪽의 보고로 `{id, version}`만
 * 안다. 그래서 **서버 부분이 자기 카탈로그를 알린다**: 서버 쪽 자원을 가장 잘 아는 것이
 * 서버 부분이고, Center는 이미 `/manifest`를 읽고 있어 길을 새로 내지 않는다.
 *
 * `catalog_url`은 이 앱의 `base_url` 기준 상대 경로다 (주소의 유일한 출처는 Center의 리소스
 * 등록이다 — C13 `service.base_url`). 응답 형식은 C13 §5 `Catalog`다.
 */
export interface ResourceCatalog {
  catalog_url: string;
  label?: string | null;
  type: string;
  [k: string]: unknown;
}
