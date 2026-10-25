import "server-only";
import type { DeploymentInfo } from "@chaeksas/api-types/c5-deployment-info";
import type { PackageInfo } from "@chaeksas/api-types/c5-package-info";
import type { ExtensionResource } from "@chaeksas/api-types/c7-extension-resource";
import type { RuntimeResource } from "@chaeksas/api-types/c7-runtime-resource";
import type { ServiceAppResource } from "@chaeksas/api-types/c7-service-app-resource";
import { center } from "@/lib/center";
import { type FeatureInput, type FeatureRow, featureRows } from "@/lib/features";

/**
 * CON-07 「기능」의 재료 넷을 Center에서 읽어 줄을 짓는다 — 목록과 상세가 **같은 것**을 본다.
 * 셈은 화면을 모르는 `lib/features.ts`가 한다 (vitest가 잰다).
 */
export async function loadFeatures(): Promise<{ rows: FeatureRow[]; input: FeatureInput; fetchedAt: string }> {
  const [extensions, serviceApps, runtimes, packages, deployments] = await Promise.all([
    center.resources<ExtensionResource>("extension"),
    center.resources<ServiceAppResource>("service_app"),
    center.resources<RuntimeResource>("runtime"),
    center.packages() as Promise<PackageInfo[]>,
    center.deployments({ active: true }) as Promise<DeploymentInfo[]>,
  ]);
  const input: FeatureInput = {
    extensions: extensions.items,
    serviceApps: serviceApps.items,
    runtimes: runtimes.items,
    packages,
    deployments,
  };
  return { rows: featureRows(input), input, fetchedAt: extensions.fetched_at };
}
