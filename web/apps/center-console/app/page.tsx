import { redirect } from "next/navigation";

/** 첫 화면. 로그인했으면 Bot UI 현황(CON-03)으로 보낸다 — M2에서 도는 화면이다. */
export default function Home() {
  redirect("/bot-uis");
}
