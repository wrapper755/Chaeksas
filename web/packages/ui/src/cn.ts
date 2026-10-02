/** 클래스 이름 잇기. 작은 일이라 의존성을 두지 않는다 (거짓 값은 버린다). */
export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}
