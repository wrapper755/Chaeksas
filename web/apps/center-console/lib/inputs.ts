import type { ManifestInput } from "@chaeksas/api-types/c5-package-info";

/** 부르는 쪽이 넣는 입력만 — **값 출처**(`source`)가 있는 입력은 Center가 넣는다 (C1·C14, ADR-0099).
 *
 * CON-05 「새 작업」이 칸을 그릴 때와 서버 액션이 값을 읽을 때 **같은 것**을 쓴다. 그 칸을 그리면
 * 사람이 적은 값을 Center가 `input_not_from_caller`로 거절한다.
 */
export function fromCaller(inputs: readonly ManifestInput[]): ManifestInput[] {
  return inputs.filter((one) => !one.source || one.source === "caller");
}
