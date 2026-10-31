/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `GET /resources/consumer-folder` — Center가 **마지막으로 뜰 때** 일꾼 폴더를 읽은 결과 (ADR-0122).
 */
export interface ConsumerFolderScan {
  configured?: boolean;
  dir?: string | null;
  items?: ConsumerFolderItem[];
  problem?: string | null;
  scanned_at?: string | null;
  [k: string]: unknown;
}
/**
 * 일꾼 폴더의 한 줄 (ADR-0122). 일꾼이면 `id`가 일꾼 이름이고, 읽지 못했으면 없다.
 *
 * `revoked`는 **빠져서** 거둔 것이라 `file`이 없다 — 일꾼(파일이 빠졌다)이나, 맡은 일꾼이 없어진 외부 확장이다.
 */
export interface ConsumerFolderItem {
  code?: string | null;
  file?: string | null;
  id?: string | null;
  kind?: string;
  message?: string | null;
  outcome: string;
  version?: string | null;
  [k: string]: unknown;
}
