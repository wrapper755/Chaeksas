/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `POST /api/v1/bot-ui/enroll` — 키가 없을 때 **등록 요청** (C4 §등록 요청과 승인, 인증 없음).
 *
 * `RegisterRequest`와 같은 칸에 `public_key`가 **필수**다 — 승인된 키를 이것으로 봉해 내려 준다.
 */
export interface EnrollRequest {
  machine_id: string;
  name: string;
  os: string;
  public_key: string;
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
 *
 * **`enabled`와 `off`는 다른 것을 말한다** ([ADR-0043](../../../../../docs/decisions/0043-turned-off-extensions.md)):
 * `off`는 **사람이 껐다**(멀쩡한데 일부러 안 쓴다), `enabled=false`인데 `off`가 아니면 **흠이
 * 있다**(정의·판이 맞지 않는다). 화면이 「꺼짐」과 「호환 안 됨」을 가르는 자리다. 뜻을 바꾸지
 * 않고 칸을 더한 것이라 옛 Bot UI가 보낸 값(`off` 없음)도 그대로 읽힌다.
 */
export interface ExtensionState {
  definition_hash?: string | null;
  enabled?: boolean;
  id: string;
  off?: boolean;
  version: string;
  [k: string]: unknown;
}
export interface Versions {
  bot_ui: string;
  build?: BuildStamp | null;
  core: string;
  worker?: string | null;
  [k: string]: unknown;
}
/**
 * 묶은 산출물의 표시 (C4 `versions.build`, [ADR-0067](../../../../../docs/decisions/0067-build-stamp.md)).
 *
 * **있으면 묶은 것에서 돈다.** 없으면 묶지 않은 것(소스·`uv sync`)이다 — 「모른다」가 아니다.
 * 판 자체는 `Versions.bot_ui`에 있다(빌드가 찍은 것).
 */
export interface BuildStamp {
  built_at: string;
  commit: string;
  [k: string]: unknown;
}
