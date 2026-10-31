"use client";

import { useState } from "react";
import { Button } from "@chaeksas/ui";

/**
 * 「<누가> 설정에 적을 Center 주소」 한 줄과 「복사」 (CON-00) — 주소를 적어 넣을 사람이 보는
 * 화면(CON-03·CON-02 「서버」 탭)에만 둔다. https가 아닌 주소에서는 브라우저가 클립보드를 막으므로
 * 그때는 글자를 골라 복사하라고 말한다.
 */
export function CenterAddress({ url, who }: { url: string; who: string }) {
  const [said, setSaid] = useState<string | null>(null);

  async function copy() {
    try {
      await navigator.clipboard.writeText(url);
      setSaid("복사했습니다.");
    } catch {
      setSaid("복사하지 못했습니다 — 글자를 골라 복사하세요.");
    }
  }

  return (
    <p className="mt-1 flex flex-wrap items-center gap-2 text-body-sm text-text-secondary">
      {who} 설정에 적을 Center 주소:
      <span className="font-mono text-text-primary" style={{ userSelect: "all" }}>
        {url}
      </span>
      <Button size="sm" variant="ghost" onClick={copy}>
        복사
      </Button>
      {said ? <span className="text-caption text-text-muted">{said}</span> : null}
    </p>
  );
}
