/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `GET /admin/v1/overview` — UIA-01 개요 한 벌.
 */
export interface ConsoleOverview {
  checks?: DeployCheck[];
  counts?: SelectorCounts;
  generated_at?: string | null;
  llm?: LlmInfo;
  revision?: number;
  /**
   * 이 계약의 schema 번호
   */
  schema: number;
  sessions?: SessionCounts;
  [k: string]: unknown;
}
/**
 * 「배포 전 확인」 한 줄 (UIA-01).
 *
 * **C11 앱이 자기 힘으로 볼 수 있는 것만** 둔다 — 모델 연결, 등록 담당자 키(`registry_write`),
 * 등록된 화면. (허용 주소·인증 설정은 외부 확장 어댑터의 개념이고(C13 §4) 이 앱에는 없다.)
 *
 * **막는 것이 아니라 알려 주는 것이다** — `warn`이어도 앱은 돈다.
 */
export interface DeployCheck {
  detail?: string | null;
  id: string;
  label: string;
  level?: string;
  [k: string]: unknown;
}
/**
 * 「관리 중인 셀렉터」 (UIA-01) — 레지스트리를 센 것.
 */
export interface SelectorCounts {
  active?: number;
  deprecated?: number;
  elements?: number;
  locators?: number;
  pages?: number;
  unverified?: number;
  [k: string]: unknown;
}
/**
 * 「LLM」 (UIA-01). **주소·키는 보이지 않는다** (C11 §모델 연결).
 *
 * 계획과 치유가 **같은 모델 하나**를 쓴다 (앱 설정이 하나다) — 둘을 따로 적지 않는다.
 */
export interface LlmInfo {
  configured?: boolean;
  last_status?: string;
  max_healing_attempts?: number;
  model?: string;
  [k: string]: unknown;
}
/**
 * 「최근 UI 세션」 (UIA-01)과 UIA-03 요약 — **보고가 도착한 것만** 센다.
 *
 * **「진행 중」은 없다.** C8 보고는 세션이 **끝날 때** 한 번 오므로 앱은 도는 세션을 모른다
 * (지금 무엇이 도는지는 현장의 BUI-09가 안다). 없는 수를 0으로 보이면 「아무것도 안 돈다」로
 * 읽히므로 칸 자체를 두지 않는다.
 *
 * `test`는 셀렉터 시험(BUI-08, C8 `origin: test`)이고 **나머지 수에 들어가지 않는다** —
 * 시험이 운영 통계를 흔들지 않는다 (C8·C9).
 */
export interface SessionCounts {
  escalated?: number;
  failed?: number;
  healed?: number;
  succeeded?: number;
  test?: number;
  today?: number;
  total?: number;
  [k: string]: unknown;
}
