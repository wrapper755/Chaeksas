/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `POST /api/v1/bot-ui/register` — 처음 한 번, 그리고 이름·버전이 바뀔 때.
 *
 * `bot_ui_id`를 본문에 넣지 않는다. **신원은 Center API 키로 정한다.**
 */
export interface RegisterRequest {
  machine_id: string;
  name: string;
  os: string;
  runtimes?: Runtimes | null;
  /**
   * 이 계약의 schema 번호
   */
  schema: number;
  versions: Versions;
  [k: string]: unknown;
}
export interface Runtimes {
  browsers?: string[];
  desktop_backend?: string | null;
  extensions?: ExtensionState[];
  [k: string]: unknown;
}
/**
 * 설치된 확장 하나 (C13).
 */
export interface ExtensionState {
  definition_hash?: string | null;
  enabled?: boolean;
  id: string;
  version: string;
  [k: string]: unknown;
}
export interface Versions {
  bot_ui: string;
  core: string;
  worker?: string | null;
  [k: string]: unknown;
}
