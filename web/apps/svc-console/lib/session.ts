import "server-only";

import { createCipheriv, createDecipheriv, randomBytes, scryptSync } from "node:crypto";

/**
 * 로그인 세션 — **암호화된 httpOnly 쿠키** (ADR-0017 §1).
 *
 * Center 콘솔과 같은 방식이고 **모드가 하나다**: 서비스 앱 관리 콘솔은 관리자만 들어온다
 * (SVC-00 「키 발급·폐기는 로그인한 관리자만」). 보기 전용 토큰은 서비스 앱에 없다.
 *
 * 토큰은 브라우저에 내려가지 않는다. 복호화는 콘솔 서버에서만 한다 (`server-only` — 실수로
 * 클라이언트 번들에 들어가면 빌드가 깨진다).
 */

export interface Session {
  /** 앱에 보낼 관리자 토큰. **서버 안에서만 쓴다.** */
  token: string;
  /** 화면에 보일 사용자 이름. */
  actor: string;
}

export const COOKIE_NAME = "chk_svc_console_session";
const ALGORITHM = "aes-256-gcm";

function key(): Buffer {
  const secret = process.env.CHK_SVC_CONSOLE__SESSION_SECRET;
  if (!secret || secret.length < 16) {
    // 비밀이 없으면 세션을 만들 수 없다 — 약한 기본값을 쓰지 않는다 (CLAUDE.md §5).
    throw new Error("CHK_SVC_CONSOLE__SESSION_SECRET이 없거나 너무 짧다 (16자 이상)");
  }
  return scryptSync(secret, "chaeksas-svc-console", 32);
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
