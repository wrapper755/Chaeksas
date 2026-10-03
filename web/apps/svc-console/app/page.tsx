import { redirect } from "next/navigation";

/** 첫 화면. 공통 첫 화면은 상태(SVC-01)다. */
export default function Home() {
  redirect("/status");
}
