// 생성 파일: design/tokens.json에서 만든다. 직접 고치지 말고 원본을 고친 뒤 scripts/gen_tokens.py (design/bpm-mark.svg)

/** BPM 흐름 마크 (스타일 가이드 §6-1, ADR-0118). `label`이 없으면 장식이라 읽지 않는다. */
export function BpmMark({ label, className }: { label?: string; className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 96 28"
      className={className}
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      {label ? <title>{label}</title> : null}
      <circle cx="8" cy="14" r="6" fill="none" stroke="currentColor" strokeWidth="1.8" />
      <line x1="14" y1="14" x2="24" y2="14" stroke="currentColor" strokeWidth="1.8" />
      <rect x="24" y="5" width="24" height="18" rx="4" fill="currentColor" />
      <line x1="48" y1="14" x2="57" y2="14" stroke="currentColor" strokeWidth="1.8" />
      <path d="M66 5 L75 14 L66 23 L57 14 Z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
      <line x1="75" y1="14" x2="82" y2="14" stroke="currentColor" strokeWidth="1.8" />
      <circle cx="88" cy="14" r="6" fill="none" stroke="currentColor" strokeWidth="3.5" />
    </svg>
  );
}
