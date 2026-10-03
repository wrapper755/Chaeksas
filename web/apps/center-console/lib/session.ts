import "server-only";

import { createCipheriv, createDecipheriv, randomBytes, scryptSync } from "node:crypto";

/**
 * 로그인 세션 — **암호화된 httpOnly 쿠키** (ADR-0017 §1).
 *
 * 토큰은 브라우저에 내려가지 않는다. 쿠키에는 암호문만 들어가고, 복호화는 콘솔 서버에서만
 * 한다 (`server-only` — 실수로 클라이언트 번들에 들어가면 빌드가 깨진다).
 *
 * OIDC는 나중이다 (ADR-0017). 지금은 Center의 관리자·읽기 토큰을 그대로 받아 둔다.
 */

/** 쓰기 모드 (CON-00 「보기 전용」 / 「관리자」). */
export type Mode = "admin" | "read";

export interface Session {
  mode: Mode;
  /** Center에 보낼 토큰. **서버 안에서만 쓴다.** */
  token: string;
  /** 화면에 보일 사용자 이름 (C5 `X-CHK-Actor`로도 보낸다). */
  actor: string;
}

export const COOKIE_NAME = "chk_console_session";
const ALGORITHM = "aes-256-gcm";

function key(): Buffer {
  const secret = process.env.CHK_CONSOLE__SESSION_SECRET;
  if (!secret || secret.length < 16) {
    // 비밀이 없으면 세션을 만들 수 없다 — 약한 기본값을 쓰지 않는다 (CLAUDE.md §5).
    throw new Error("CHK_CONSOLE__SESSION_SECRET이 없거나 너무 짧다 (16자 이상)");
  }
  return scryptSync(secret, "chaeksas-console", 32);
}

export function seal(session: Session): string {
  const iv = randomBytes(12);
  const cipher = createCipheriv(ALGORITHM, key(), iv);
  const body = Buffer.concat([cipher.update(JSON.stringify(session), "utf8"), cipher.final()]);
  return [iv, cipher.getAuthTag(), body].map((part) => part.toString("base64url")).join(".");
}

export function open(sealed: string | undefined): Session | null {
  if (!sealed) return null;
  const [iv, tag, body] = sealed.split(".");
  if (!iv || !tag || !body) return null;
  try {
    const decipher = createDecipheriv(ALGORITHM, key(), Buffer.from(iv, "base64url"));
    decipher.setAuthTag(Buffer.from(tag, "base64url"));
    const plain = Buffer.concat([decipher.update(Buffer.from(body, "base64url")), decipher.final()]);
    return JSON.parse(plain.toString("utf8")) as Session;
  } catch {
    // 비밀이 바뀌었거나 쿠키가 손상됐다 — 로그인하지 않은 것으로 본다.
    return null;
  }
}
