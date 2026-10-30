import { redirect } from "next/navigation";

/** 서버 실행기 목록은 CON-02 「BPM 프로세스 현황」의 「서버」 탭으로 옮겼다 — 옛 주소는 그리로 넘긴다. */
export default function ServerRunnersPage() {
  redirect("/bots?tab=server");
}
