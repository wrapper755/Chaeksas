/**
 * 업무 자리를 글로 (C16, ADR-0127) — **화면을 모르는 함수**라 vitest가 잰다.
 *
 * 자리는 매니페스트의 `place`이고 Center는 **보여 주기만** 한다 (CON-02 「승인...」 확인 창·상세).
 * 이름은 Center에서 읽은 부서·직원 목록에서 찾고, 없으면 id 그대로 보인다(지어내지 않는다).
 */

export interface WorkPlace {
  scope: string;
  department?: string | null;
  staff?: string | null;
}

export function workPlaceLabel(
  place: WorkPlace | null | undefined,
  names: { departments?: Record<string, string>; staff?: Record<string, string> } = {},
): string {
  if (!place || place.scope === "company") return "회사 공통";
  if (place.scope === "department" && place.department) {
    return `부서: ${names.departments?.[place.department] ?? place.department}`;
  }
  if (place.scope === "staff" && place.staff) return `직원: ${names.staff?.[place.staff] ?? place.staff}`;
  return place.scope; // 모르는 범위 — 받은 그대로 (원칙 10)
}

/** 승인 창에 덧붙이는 한 줄 — 「회사: 기본 회사 · 업무 자리: 부서: 구매팀」. */
export function placeLine(company: string | null | undefined, place: string): string {
  return `회사: ${company ?? "—"} · 업무 자리: ${place}`;
}

/** 목록 → id·이름 표 (부서·직원·회사 공통). */
export function namesOf(rows: Array<{ id: string; name: string }> | undefined): Record<string, string> {
  return Object.fromEntries((rows ?? []).map((one) => [one.id, one.name]));
}
