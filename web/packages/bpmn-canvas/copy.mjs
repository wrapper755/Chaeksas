// bpmn-js 배포본 → `apps/studio/.../web/vendor/` (ADR-0029).
// 그리고 **자동 배치 도우미 하나를 묶는다** (`src/auto-layout.mjs` → `bpmn-auto-layout.min.js`,
// ADR-0088) — ESM 패키지라 그대로 복사할 배포본이 없다. 모델러·뷰어는 묶지 않는다.
//
//   node copy.mjs            복사한다
//   node copy.mjs --check    쓰지 않고 검사만 (어긋나면 1로 끝난다 — CI가 쓴다)
//
// **복사본은 커밋한다.** 파이썬 쪽(시험·PyInstaller)이 Node 없이 돌아야 하기 때문이다.
// 버전은 이 패키지의 package.json 한 곳에만 있다.

import { readFile, writeFile, mkdir, readdir, rm, stat } from "node:fs/promises";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "../../..");
const OUT = join(ROOT, "apps/studio/src/chaeksas/studio/web/vendor");
const require = createRequire(import.meta.url);
const DIST = join(dirname(require.resolve("bpmn-js/package.json")), "dist");

/**
 * 가져올 것 — 모델러 한 벌, **읽기 전용 뷰어 한 벌**, 그것들이 쓰는 CSS·글꼴.
 * 소스맵은 빼고 가져온다 (크기).
 *
 * 뷰어는 STU-03 「열기 (읽기 전용)」이 쓴다 ([ADR-0051](../../../docs/decisions/0051-shared-process-conveniences.md)) —
 * 모델러의 팔레트를 가려 흉내 내지 않고 **정말 못 고치는 배포본**을 싣는다. 같은 npm
 * 패키지가 주므로 판은 아래 package.json 한 곳에 그대로 있다.
 */
const FILES = [
  "bpmn-modeler.production.min.js",
  "bpmn-navigated-viewer.production.min.js",
  "assets/diagram-js.css",
  "assets/bpmn-js.css",
  "assets/bpmn-font/css/bpmn-embedded.css",
];
const FONT_DIR = "assets/bpmn-font/font";

async function listFonts() {
  const names = await readdir(join(DIST, FONT_DIR));
  return names.filter((n) => !n.endsWith(".map")).map((n) => `${FONT_DIR}/${n}`);
}

/** 자동 배치 도우미를 IIFE 하나로 (전역 `ChkAutoLayout`, ADR-0088). 같은 판이면 같은 바이트다. */
async function autoLayout() {
  const { build } = await import("esbuild");
  const done = await build({
    entryPoints: [join(HERE, "src/auto-layout.mjs")],
    absWorkingDir: HERE,
    bundle: true,
    format: "iife",
    globalName: "ChkAutoLayout",
    platform: "browser",
    target: "es2020",
    minify: true,
    charset: "utf8",
    write: false,
    logLevel: "silent",
  });
  return Buffer.from(done.outputFiles[0].contents);
}

async function outputs() {
  const version = JSON.parse(await readFile(require.resolve("bpmn-js/package.json"), "utf8")).version;
  const layoutVersion = JSON.parse(
    // `exports`가 package.json을 내보내지 않아 그 폴더에서 바로 읽는다.
    await readFile(join(HERE, "node_modules/bpmn-auto-layout/package.json"), "utf8"),
  ).version;
  const wanted = [...FILES, ...(await listFonts())];
  const out = new Map();
  for (const name of wanted) {
    out.set(name, await readFile(join(DIST, name)));
  }
  out.set("bpmn-auto-layout.min.js", await autoLayout());
  out.set(
    "VERSION.txt",
    Buffer.from(
      `bpmn-js ${version}\n` +
        `bpmn-auto-layout ${layoutVersion} (src/auto-layout.mjs를 esbuild로 묶었다, ADR-0088)\n` +
        "이 폴더는 생성물이다 (ADR-0029). 직접 고치지 말고 web/packages/bpmn-canvas의\n" +
        "package.json에서 판을 올린 뒤 `pnpm --filter @chaeksas/bpmn-canvas build`.\n",
      "utf8",
    ),
  );
  return out;
}

async function same(path, body) {
  try {
    await stat(path);
  } catch {
    return false;
  }
  return Buffer.compare(await readFile(path), body) === 0;
}

const check = process.argv.includes("--check");
const out = await outputs();

// 더 이상 쓰지 않는 파일은 지운다 (판을 올리며 글꼴 이름이 바뀔 수 있다).
let existing = [];
try {
  const walk = async (dir) => {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) await walk(full);
      else existing.push(relative(OUT, full).split("\\").join("/"));
    }
  };
  await walk(OUT);
} catch {
  existing = [];
}
const orphans = existing.filter((name) => !out.has(name));

if (check) {
  const stale = [];
  for (const [name, body] of out) {
    if (!(await same(join(OUT, name), body))) stale.push(name);
  }
  for (const name of [...stale, ...orphans]) console.log("다름:", name);
  if (stale.length || orphans.length) process.exit(1);
  console.log(`bpmn-js 배포본 ${out.size}개가 최신이다.`);
} else {
  for (const name of orphans) await rm(join(OUT, name));
  for (const [name, body] of out) {
    await mkdir(dirname(join(OUT, name)), { recursive: true });
    await writeFile(join(OUT, name), body);
  }
  console.log(`bpmn-js 배포본 ${out.size}개 → apps/studio/.../web/vendor`);
}
