/* 생성 파일: packages/contracts/schemas에서 만든다. 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * `kind: "extension"` — 외부 확장 정의 승인 (C13).
 *
 * 정의가 서비스 앱 키를 어느 주소로 보낼지 정하므로 배포와 같은 관문을 둔다.
 * `definition_hash`는 `canonical_json(정의)`의 해시다 (`contracts.extension.definition_hash`).
 */
export interface ExtensionClaim {
  definition_hash: string;
  id: string;
  kind: "extension";
  version: string;
  [k: string]: unknown;
}
