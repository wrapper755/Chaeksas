/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `POST /api/v1/server-runner/register`.
 *
 * `server_runner_id`를 본문에 넣지 않는다 — **신원은 Center API 키로 정한다** (C4와 같다).
 * 키 묶기도 같다: 키 하나 ↔ 서버 하나 ↔ 실행기 행 하나.
 */
export interface ServerRunnerRegisterRequest {
  extensions?: ExtensionState[];
  machine_id: string;
  max_concurrency?: number;
  name: string;
  os: string;
  /**
   * 이 계약의 schema 번호
   */
  schema: number;
  versions: RunnerVersions;
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
/**
 * C4 `Versions`와 **칸이 다르다** — 서버에는 Worker가 없다.
 */
export interface RunnerVersions {
  core: string;
  server_runner: string;
  [k: string]: unknown;
}
