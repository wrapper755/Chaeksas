/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * 일꾼 폴더의 `<이름>.key.json` — 연동용·대리 답용 키를 **Center가 뜰 때** 들인다 (C7 §폴더 키, ADR-0123).
 *
 * 설치가 원문을 짓고 Center에는 **해시만** 둔다. 권한은 CON-11에서 발급한 같은 종류의 키와 같고, 만료·회전이
 * 없다(공개키가 없다). 키의 자리는 파일 이름이 정한다 — `name`은 CON-11에 보이는 키 이름이다.
 */
export interface FolderKey {
  name: string;
  token_sha256: string;
  type: string;
  [k: string]: unknown;
}
