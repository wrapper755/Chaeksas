/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `GET /resources/extension-folder` — Center가 **마지막으로 뜰 때** 확장 폴더를 읽은 결과 (ADR-0121).
 */
export interface ExtensionFolderScan {
  configured?: boolean;
  dir?: string | null;
  items?: ExtensionFolderItem[];
  problem?: string | null;
  scanned_at?: string | null;
  [k: string]: unknown;
}
/**
 * 확장 폴더의 파일 하나를 읽은 결과 (ADR-0121). 읽지 못했으면 `id`·`version`이 없다.
 *
 * `revoked`는 파일이 **폴더에서 빠져** 거둔 것이라 `file`이 없다. 일꾼이면 `id`가 일꾼 이름이다.
 */
export interface ExtensionFolderItem {
  code?: string | null;
  file?: string | null;
  id?: string | null;
  kind?: string;
  message?: string | null;
  outcome: string;
  version?: string | null;
  [k: string]: unknown;
}
