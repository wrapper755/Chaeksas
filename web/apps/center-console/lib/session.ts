import "server-only";

import { createCipheriv, createDecipheriv, randomBytes, scryptSync } from "node:crypto";

/**
 * 로그인 세션 — **암호화된 httpOnly 쿠키** (ADR-0017 §1).
 *
 * 토큰은 브라우저에 내려가지 않는다. 쿠키에는 암호문만 들어가고, 복호화는 콘솔 서버에서만
 * 한다 (`server-only` — 실수로 클라이언트 번들에 들어가면 빌드가 깨진다).
 *
 * 들어오는 길은 **관리자 계정**이다 (ADR-0090). Center가 아이디·비밀번호를 확인하고 준 세션
 * 토큰을 받아 둔다. 역할(`mode`)과 이름(`actor`)은 그 응답에서 온다 — 사람이 고르지 않는다.
 */

/** 역할 (CON-00 「보기 전용」 / 「관리자」) — 계정이 정한다. */
export type Mode = "admin" | "read";

export interface Session {
  mode: Mode;
  /** Center 세션 토큰 (`bpm_ses_…`). **서버 안에서만 쓴다.** */
  token: string;
  /** 계정 아이디 — 위 막대에 보이고, Center 기록의 「누가」가 된다. */
  actor: string;
  /**
   * 이 계정이 보는 회사 (C16). **있으면 회사 관리자·회사 보기 전용**이다 — Center가 목록을 그 회사로
   * 거르고, 콘솔은 Center 관리자만의 메뉴(관리자 계정)를 가린다. 없으면 Center 전체다.
   */
  company?: string | null;
}

export const COOKIE_NAME = "chk_console_session";
const ALGORITHM = "aes-256-gcm";

function key(): Buffer {
  const secret = process.env.BPM_CONSOLE__SESSION_SECRET;
  if (!secret || secret.length < 16) {
    // 비밀이 없으면 세션을 만들 수 없다 — 약한 기본값을 쓰지 않는다 (CLAUDE.md §5).
    throw new Error("BPM_CONSOLE__SESSION_SECRET이 없거나 너무 짧다 (16자 이상)");
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
