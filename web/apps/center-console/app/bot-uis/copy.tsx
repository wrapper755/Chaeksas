"use client";

import { useState } from "react";
import { Button } from "@chaeksas/ui";

/**
 * 짧은 값(배포 id)을 복사한다 — Admin 명령에 그대로 붙여 넣는 자리다 (CON-03 「배포」).
 *
 * 눌렀는지 **글자로** 알려 준다 (색·아이콘만으로 말하지 않는다, 스타일 가이드 §7).
 * 클립보드를 쓸 수 없는 환경(비보안 출처)에서는 조용히 넘어가지 않고 그렇게 말한다.
 */
export function CopyButton({ value, label = "복사" }: { value: string; label?: string }) {
  const [said, setSaid] = useState<string | null>(null);

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setSaid("복사함");
    } catch {
      setSaid("복사할 수 없습니다 — 직접 선택하세요");
    }
    setTimeout(() => setSaid(null), 2000);
  }

  return (
    <span className="inline-flex items-center gap-2">
      <Button variant="ghost" onClick={copy} aria-label={`${value} 복사`}>
        {label}
      </Button>
      {said ? (
        <span className="text-caption text-text-muted" role="status">
          {said}
        </span>
      ) : null}
    </span>
  );
}
