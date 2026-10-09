// 생성 파일: 확장 정의(C13 `console.pages`)에서 만든다.
// 직접 고치지 말고 `uv run python scripts/gen_console_pages.py` (ADR-0042).

export interface ConsolePage {
  id: string;
  label: string;
  module: string;
}

/**
 * 확장이 기여한 앱 고유 화면 — **확장 id로 묶는다.**
 *
 * 콘솔은 접속한 앱의 `/admin/v1/status`가 말하는 `extension.id`로 자기 줄을 고른다 (C11).
 * `module`을 실제 화면으로 잇는 것은 `console-modules.ts`이고, 없는 모듈은 **끄고 이유를
 * 가까이에 적는다** (U3).
 */
export const CONSOLE_PAGES: Record<string, ConsolePage[]> = {
  "ui-automation": [
    {
      "id": "overview",
      "label": "개요",
      "module": "ui-automation/overview"
    },
    {
      "id": "selectors",
      "label": "셀렉터",
      "module": "ui-automation/selectors"
    },
    {
      "id": "monitoring",
      "label": "모니터링",
      "module": "ui-automation/monitoring"
    }
  ]
};
