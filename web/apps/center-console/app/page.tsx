import { redirect } from "next/navigation";

/** 첫 화면. 로그인했으면 메뉴 맨 위 「운영 현황 › 프로세스」(CON-02)로 보낸다 (ADR-0121). */
export default function Home() {
  redirect("/bots");
}
