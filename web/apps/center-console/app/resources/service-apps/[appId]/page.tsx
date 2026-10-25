import type { Route } from "next";
import { redirect } from "next/navigation";
import { center } from "@/lib/center";

/**
 * 옛 주소 — CON-07 상세는 이제 **기능 하나**다 (`/resources/features/<key>`). 서비스 앱이 어느
 * 기능의 서버인지는 manifest의 `extension`이 말하므로 그것으로 보낸다. 주소 바꾸기의 결과
 * (`moved`·`error`)는 그대로 넘긴다.
 */
export default async function ServiceAppRedirect({
  params,
  searchParams,
}: {
  params: Promise<{ appId: string }>;
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const appId = decodeURIComponent((await params).appId);
  const asked = await searchParams;
  let key = `app:${appId}`;
  try {
    const found = await center.serviceApp(appId);
    if (found.extension_id) key = found.extension_id;
  } catch {
    // 못 읽으면 확장 없는 앱으로 본다 — 상세가 「없다」고 말해 준다.
  }
  const query = new URLSearchParams(
    Object.entries(asked).filter(([, value]) => Boolean(value)) as [string, string][],
  ).toString();
  redirect(`/resources/features/${encodeURIComponent(key)}${query ? `?${query}` : ""}` as Route);
}
