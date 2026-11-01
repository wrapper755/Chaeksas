/* 생성 파일: 계약 스키마에서 만든다 (플랫폼 + 확장이 소유한 것). 직접 고치지 말고
   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,
   그다음 `pnpm --filter @chaeksas/api-types generate`. */

/**
 * **작업의 주인** — Center가 서버 작업을 내려줄 때 붙인다 (C12 `JobDispatch.place`). 저장하지 않는다.
 *
 * 실행하는 쪽이 출처가 `company.*`·`department.*`·`staff.*`인 입력의 값으로 푼다
 * (`core.engine.sourced_inputs`). 그 자리에 없는 것(회사 자리 업무의 직원)은 비어 있다.
 */
export interface PlaceIdentity {
  company: OrgRef;
  department?: OrgRef | null;
  staff?: OrgRef | null;
  [k: string]: unknown;
}
/**
 * 조직 하나를 가리키는 id와 이름 — 실행하는 쪽이 값 출처로 푼다.
 */
export interface OrgRef {
  id: string;
  name: string;
  [k: string]: unknown;
}
