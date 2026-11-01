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

// ─────────────────── CON-13 조직 화면 ───────────────────

export type OrgKind = "company" | "department" | "staff";

/** 화면이 쓰는 종류 이름 (CON-13 [H]). */
export const KIND_LABEL: Record<OrgKind, string> = { company: "회사", department: "부서", staff: "직원" };

/**
 * `?node=` 값 — 「<종류>:<id>」. id는 종류마다 따로 하나라(C16) 종류를 함께 적어야 회사와 부서의
 * 같은 id가 섞이지 않는다. 모르는 모양은 `null`(첫 회사를 고른다).
 */
export function parseNode(raw: string | null | undefined): { kind: OrgKind; id: string } | null {
  const at = (raw ?? "").indexOf(":");
  if (at <= 0) return null;
  const kind = raw!.slice(0, at);
  const id = raw!.slice(at + 1);
  if (!id || !(kind in KIND_LABEL)) return null;
  return { kind: kind as OrgKind, id };
}

export function nodeParam(kind: OrgKind, id: string): string {
  return `${kind}:${id}`;
}

interface Named {
  id: string;
  name: string;
  state?: string | null;
}

export interface TreeCompany<C extends Named, D extends Named & { company: string }, S extends Named> {
  company: C;
  departments: Array<{ department: D; staff: S[] }>;
  /** 부서 없는 직원 — 회사 바로 아래 (CON-13 [T]). */
  staff: S[];
}

/** 회사 > 부서 > 직원 나무. 이름 순이다. 회사를 못 찾는 부서·직원은 버리지 않고 그 회사 줄이 없으면 안 보인다. */
export function orgTree<
  C extends Named,
  D extends Named & { company: string },
  S extends Named & { company: string; department?: string | null },
>(companies: C[], departments: D[], staff: S[]): Array<TreeCompany<C, D, S>> {
  const byName = <T extends Named>(a: T, b: T) => a.name.localeCompare(b.name, "ko") || a.id.localeCompare(b.id);
  return [...companies].sort(byName).map((company) => {
    const mine = departments.filter((one) => one.company === company.id).sort(byName);
    const ids = new Set(mine.map((one) => one.id));
    const people = staff.filter((one) => one.company === company.id).sort(byName);
    return {
      company,
      departments: mine.map((department) => ({
        department,
        staff: people.filter((one) => one.department === department.id),
      })),
      // 부서 칸이 비었거나 그 회사의 부서가 아니면 회사 바로 아래.
      staff: people.filter((one) => !one.department || !ids.has(one.department)),
    };
  });
}

/** 「멈춤」/「사용 중」 — `status_map` 「조직」 묶음. 모르는 값은 그대로 (원칙 10). */
export function orgStateLabel(state: string | null | undefined): string {
  if (!state || state === "active") return "사용 중";
  return state === "stopped" ? "멈춤" : state;
}

/** 「등록 해제...」를 끌 까닭 (CON-13 [H]). 다 알지는 못한다 — 남은 것은 Center 409 `in_use`가 말한다. */
export const REMOVE_BLOCKED = "직원·업무·작업이 가리키고 있어 해제할 수 없습니다 — 멈추세요.";

export function removeBlocked(detail: {
  staff?: number | null;
  work?: unknown[] | null;
  recent_runs?: unknown[] | null;
}): string | null {
  const used = (detail.staff ?? 0) > 0 || (detail.work ?? []).length > 0 || (detail.recent_runs ?? []).length > 0;
  return used ? REMOVE_BLOCKED : null;
}

/**
 * 「시작 방법」 한 칸 — 매니페스트 `triggers` (C1 `Trigger`: 메시지·신호는 `name`, 일정은 `expression`).
 * `none`(작업 지시로만 시작)은 적지 않는다 — 다 그렇게 시작할 수 있다.
 */
export function triggersLabel(triggers: Array<Record<string, string>> | null | undefined): string {
  const said = (triggers ?? []).map((one) => {
    if (one.kind === "none") return "";
    if (one.kind === "timer") return `일정 ${one.expression ?? ""}`.trim();
    if (one.kind === "message") return `메시지 ${one.name ?? ""}`.trim();
    if (one.kind === "signal") return `신호 ${one.name ?? ""}`.trim();
    return one.kind ?? ""; // 모르는 종류 — 받은 그대로 (원칙 10)
  });
  return said.filter(Boolean).join(", ") || "—";
}

/** 이름 한 칸 — 이름을 모르면 **id 그대로**, 칸이 비면 「—」 (CON-01의 회사·부서·직원 열). */
export function orgName(id: string | null | undefined, names: Record<string, string>): string {
  return id ? (names[id] ?? id) : "—";
}
