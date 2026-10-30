/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `GET /schedules`의 한 줄 — 타이머로 시작하는 배포 하나의 일정 (C5 §일정, CON-02 「일정」, ADR-0110).
 *
 * 서버 BPM 프로세스는 (BPM 프로세스, 버전)마다 한 줄이고 `target_id`가 없다 (실행기는 Center가 고른다).
 * PC BPM 프로세스는 배포된
 * PC마다 한 줄이다. **센 것은 Center가 쓸 때와 같은 함수다** (`contracts.schedule`) — 화면이 따로 세면
 * 「다음 차례」가 일정과 어긋난다.
 */
export interface ScheduleInfo {
  bpm_process_id: string;
  expression: string;
  last_error?: string | null;
  last_job_id?: string | null;
  last_missed?: number;
  last_slot?: string | null;
  next_at?: string | null;
  problem?: string | null;
  target_id?: string | null;
  target_type: string;
  timezone: string;
  version: string;
  [k: string]: unknown;
}
