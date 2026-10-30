/** CON-07 「기능」 (`lib/features.ts`) — 「쓸 수 있나」와 「할 일」을 **값으로** 본다.
 *
 * 거듭 보는 것 넷.
 *
 * 1. **쓸 수 없는 것이 맨 위**다.
 * 2. **PC는 그 기능을 쓰는 BPM 프로세스가 배포된 곳만** 센다.
 * 3. **외부 기능은 PC를 세지 않는다** (코드가 없다).
 * 4. 서버 부분이 없다는 것은 **누락 검사**가 말해 준다 — 확장 없이도 줄이 생기고 할 일은 「일꾼을 들이세요」다.
 */
import { describe, expect, it } from "vitest";
import type { DeploymentInfo } from "@chaeksas/api-types/c5-deployment-info";
import type { PackageInfo } from "@chaeksas/api-types/c5-package-info";
import type { ExtensionResource } from "@chaeksas/api-types/c7-extension-resource";
import type { RuntimeResource } from "@chaeksas/api-types/c7-runtime-resource";
import type { ServiceAppResource } from "@chaeksas/api-types/c7-service-app-resource";
import { type FeatureInput, featureRows } from "./features";

function bot(id: string, extensions: string[], missing: Array<{ type: string; id: string }> = []): PackageInfo {
  return {
    id,
    version: "1.0.0",
    kind: "bpm_process",
    manifest: { requires: { extensions: extensions.map((one) => ({ id: one, version: ">=1" })) } },
    missing_resources: missing.map((one) => ({ ...one, reason: "not_registered" })),
  } as unknown as PackageInfo;
}

function deployed(botId: string, target: string, revoked = false): DeploymentInfo {
  return {
    deployment_id: `dep_${botId}_${target}`,
    bpm_process_id: botId,
    version: "1.0.0",
    content_hash: "x",
    signed_at: "2026-10-25T00:00:00+00:00",
    signed_by: "Center",
    target: { type: "bot_ui", id: target },
    revoked_at: revoked ? "2026-10-25T01:00:00+00:00" : null,
  } as DeploymentInfo;
}

function pc(id: string, extensions: Array<{ id: string; enabled?: boolean; off?: boolean }>): RuntimeResource {
  return { host: { type: "bot_ui", id, name: id }, extensions } as unknown as RuntimeResource;
}

const UIA: ExtensionResource = {
  id: "ui-automation",
  name: "UI 자동화",
  tier: "builtin",
  version: "1.0.0",
  status: "ok",
  service_app_id: "ui-automation",
};
const UIA_APP: ServiceAppResource = {
  app_id: "ui-automation",
  extension_id: "ui-automation",
  console_url: "http://localhost:8001",
  status: "ok",
  consumers: 1,
};

function input(over: Partial<FeatureInput> = {}): FeatureInput {
  return { extensions: [], serviceApps: [], runtimes: [], packages: [], deployments: [], ...over };
}

describe("featureRows", () => {
  it("서버도 PC도 갖춰졌으면 쓸 수 있고 할 일이 없다", () => {
    const rows = featureRows(
      input({
        extensions: [UIA],
        serviceApps: [UIA_APP],
        packages: [bot("order", ["ui-automation"])],
        deployments: [deployed("order", "bui_00000001")],
        runtimes: [pc("bui_00000001", [{ id: "ui-automation", enabled: true }])],
      }),
    );
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ usable: "쓸 수 있음", todos: [], consumers: 1, usedBy: ["order"] });
  });

  it("PC는 그 BPM 프로세스가 배포된 곳만 센다 — 받지 않은 PC에 없는 것은 할 일이 아니다", () => {
    const rows = featureRows(
      input({
        extensions: [UIA],
        serviceApps: [UIA_APP],
        packages: [bot("order", ["ui-automation"])],
        deployments: [deployed("order", "bui_00000001"), deployed("order", "bui_00000003", true)],
        runtimes: [
          pc("bui_00000001", []),
          pc("bui_00000002", []), // 배포받지 않았다
          pc("bui_00000003", []), // 철회됐다
        ],
      }),
    );
    expect(rows[0]!.usable).toBe("쓸 수 없음");
    expect(rows[0]!.todos.map((one) => one.text)).toEqual(["PC 1대에 없음"]);
  });

  it("꺼짐과 맞지 않는 판을 가른다", () => {
    const rows = featureRows(
      input({
        extensions: [UIA],
        serviceApps: [UIA_APP],
        packages: [bot("order", ["ui-automation"])],
        deployments: [deployed("order", "bui_00000001"), deployed("order", "bui_00000002")],
        runtimes: [
          pc("bui_00000001", [{ id: "ui-automation", off: true, enabled: false }]),
          pc("bui_00000002", [{ id: "ui-automation", enabled: false }]),
        ],
      }),
    );
    expect(rows[0]!.todos.map((one) => one.kind)).toEqual(["off_on_hosts", "wrong_version"]);
  });

  it("서버가 응답하지 않으면 쓸 수 없고, 확인 전이면 확인 전이다", () => {
    const down = featureRows(input({ extensions: [{ ...UIA, status: "unreachable" }], serviceApps: [UIA_APP] }));
    expect(down[0]!.usable).toBe("쓸 수 없음");
    expect(down[0]!.todos[0]!.kind).toBe("server_down");
    const unknown = featureRows(input({ extensions: [{ ...UIA, status: "unknown" }], serviceApps: [UIA_APP] }));
    expect(unknown[0]!.usable).toBe("확인 전");
  });

  it("외부 기능은 PC를 세지 않는다", () => {
    const external: ExtensionResource = { id: "nowview", tier: "external", version: "0.1.0", status: "ok" };
    const rows = featureRows(
      input({
        extensions: [external],
        packages: [bot("order", ["nowview"])],
        deployments: [deployed("order", "bui_00000001")],
        runtimes: [pc("bui_00000001", [])],
      }),
    );
    expect(rows[0]).toMatchObject({ usable: "쓸 수 있음", todos: [], external: true });
  });

  it("서버 부분이 없다는 것은 누락 검사가 말한다 — 확장 줄에도, 아무도 모르는 앱에도", () => {
    const reported: ExtensionResource = { id: "ui-automation", tier: "builtin", version: "1.0.0", status: "n/a" };
    const rows = featureRows(
      input({
        extensions: [reported],
        packages: [
          bot("order", ["ui-automation"], [{ type: "service_app", id: "ui-automation" }]),
          bot("tax", [], [{ type: "service_app", id: "tax-invoice" }]),
        ],
      }),
    );
    expect(rows.map((one) => [one.id, one.todos.map((todo) => todo.kind)])).toEqual([
      ["tax-invoice", ["add_consumer"]],
      ["ui-automation", ["add_consumer"]],
    ]);
  });

  it("쓸 수 없는 것이 맨 위다", () => {
    const ok: ExtensionResource = { id: "a-ok", name: "가", tier: "builtin", version: "1", status: "n/a" };
    const rows = featureRows(input({ extensions: [ok, { ...UIA, status: "unreachable" }], serviceApps: [UIA_APP] }));
    expect(rows.map((one) => one.usable)).toEqual(["쓸 수 없음", "쓸 수 있음"]);
  });

  it("확장 없는 서비스 앱도 같은 표에 한 줄이다", () => {
    const app = { app_id: "tax-invoice", name: "세금계산서", status: "ok", consumers: 2 } as ServiceAppResource;
    const rows = featureRows(input({ serviceApps: [app] }));
    expect(rows[0]).toMatchObject({ key: "app:tax-invoice", usable: "쓸 수 있음", consumers: 2 });
  });

  it("일꾼이 조용하면 할 일이고, 들인 일꾼이 없으면 확인 전이다 (C7 — 상태는 토픽이 말한다)", () => {
    const quiet = { ...UIA_APP, status: "unreachable", checked_at: "2026-10-25T00:00:00+00:00" } as ServiceAppResource;
    const [down] = featureRows(input({ extensions: [{ ...UIA, status: "unreachable" }], serviceApps: [quiet] }));
    expect(down).toMatchObject({ usable: "쓸 수 없음" });
    expect(down?.todos.map((one) => one.kind)).toEqual(["server_down"]);

    const none = { ...UIA_APP, status: "unknown", consumers: 0 } as ServiceAppResource;
    const [unknown] = featureRows(input({ extensions: [{ ...UIA, status: "unknown" }], serviceApps: [none] }));
    expect(unknown).toMatchObject({ usable: "확인 전", todos: [], consumers: 0 });
  });
});
