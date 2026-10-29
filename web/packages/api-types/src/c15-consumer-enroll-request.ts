/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `POST /api/v1/consumers/enroll` — 일꾼 들이기 요청 (C15 §일꾼 들이기, ADR-0092 §1과 같은 결).
 *
 * `manifests`는 들일 때 함께 올린다(토픽마다 하나, `app_id` = 토픽) — Center가 앱을 읽으러 가지
 * 않는다 (ADR-0102 §3). 외부 확장 토픽은 비워도 된다(작업 목록은 등록된 정의에서 온다).
 */
export interface ConsumerEnrollRequest {
  machine_id: string;
  manifests?: ServiceAppManifest[];
  name: string;
  os: string;
  public_key: string;
  /**
   * 이 계약의 schema 번호
   */
  schema: number;
  /**
   * @minItems 1
   */
  topics: [string, ...string[]];
  versions: ConsumerVersions;
  [k: string]: unknown;
}
/**
 * 앱이 하는 일 — 일꾼이 `PUT /consumers/self/manifest`로 올리고 Center가 리소스 목록·작업 대조에 쓴다 (C7·C15).
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
 * 이 앱이 **자기 기여 자원 카탈로그**를 내는 종류 (C7 §리소스 모으는 방식).
 *
 * **내장·사내 확장의 정의는 Center에 없어**(설치 파일에 들어 있다) 서버 부분이 자기 카탈로그를
 * 알린다 — 일꾼이 `PUT /consumers/self/catalogs/{type}`으로 올린다 (C15, ADR-0102). 응답 형식은
 * C13 §5 `Catalog`다. `catalog_url`은 옛 manifest를 읽기 위해 남은 칸이고 Center는 그 주소를 부르지 않는다.
 */
export interface ResourceCatalog {
  catalog_url: string;
  label?: string | null;
  type: string;
  [k: string]: unknown;
}
/**
 * 일꾼의 판 — 무엇을 돌리는가는 열린 사전이다 (앱 판·`service_kit` 판 등).
 */
export interface ConsumerVersions {
  consumer: string;
  [k: string]: unknown;
}
