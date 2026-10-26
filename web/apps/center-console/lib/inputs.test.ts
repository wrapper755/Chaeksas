/** CON-05 「새 작업」의 입력 칸 (`lib/inputs.ts`) — 값 출처가 있는 입력은 그리지 않는다 (ADR-0099). */
import { describe, expect, it } from "vitest";
import { fromCaller } from "./inputs";

describe("fromCaller", () => {
  it("값 출처가 없거나 caller인 입력만 남긴다", () => {
    const found = fromCaller([
      { name: "인입", type: "list", required: true },
      { name: "메모", type: "string", source: "caller" },
      { name: "감독자", type: "list", required: true, source: "virtual_worker.supervisors" },
    ]);
    expect(found.map((one) => one.name)).toEqual(["인입", "메모"]);
  });
});
