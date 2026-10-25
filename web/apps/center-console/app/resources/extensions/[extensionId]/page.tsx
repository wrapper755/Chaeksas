import type { Route } from "next";
import { redirect } from "next/navigation";

/** 옛 주소 — CON-07 상세는 이제 기능 하나다 (`/resources/features/<id>`). */
export default async function ExtensionRedirect({ params }: { params: Promise<{ extensionId: string }> }) {
  const { extensionId } = await params;
  redirect(`/resources/features/${extensionId}` as Route);
}
