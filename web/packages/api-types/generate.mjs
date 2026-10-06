// 계약 JSON Schema → TypeScript 타입 (ADR-0017, 계약 README 원칙 5).
//
//   node generate.mjs            쓴다
//   node generate.mjs --check    쓰지 않고 검사만 (어긋나면 1로 끝난다 — CI가 쓴다)
//
// 원본은 `packages/contracts/schemas/*.json`이고, 그것도 생성물이다
// (`uv run python scripts/gen_schemas.py`). **손으로 타입을 쓰지 않는다.**
//
// 열쇠 이름이 겹치는 타입이 있어(C5·C7의 `MissingResource`) 묶음 하나로 내보내지 않는다.
// 쓰는 쪽은 계약별 경로로 가져온다: `import type { Manifest } from "@chaeksas/api-types/c1-manifest"`.

import { readdir, readFile, writeFile, mkdir } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { compile } from "json-schema-to-typescript";

const HERE = dirname(fileURLToPath(import.meta.url));
const SCHEMA_DIR = resolve(HERE, "../../../packages/contracts/schemas");
const OUT_DIR = join(HERE, "src");
const BANNER = [
  "/* 생성 파일: packages/contracts/schemas에서 만든다. 직접 고치지 말고",
  "   계약 모델을 고친 뒤 `uv run python scripts/gen_schemas.py`,",
  "   그다음 `pnpm --filter @chaeksas/api-types generate`. */",
].join("\n");

/**
 * 열쇠가 **이름의 모음**인 자리. 이 한 겹은 스키마가 아니라 「이름 → 스키마」 표다.
 *
 * 여기를 스키마로 착각하면 `title`이라는 **필드**를 스키마의 `title`로 보고 지운다 —
 * C6 `ApprovalInfo.title`이 생성된 타입에서 조용히 사라져 있었다.
 */
const NAME_MAPS = new Set(["properties", "$defs", "definitions", "patternProperties"]);

/**
 * 필드에 붙은 `title`을 떼어 낸다.
 *
 * pydantic은 필드마다 `"title": "Content Hash"`를 넣는데, 생성기가 그것을 보고 필드마다 타입
 * 별명(`ContentHash`, `Id1`, `Kind1` …)을 만든다. 모델 이름(최상위와 `$defs`의 열쇠)만 남기면
 * 중첩 모델은 그대로 인터페이스가 되고 나머지는 제자리에 적힌다.
 */
function stripFieldTitles(node, keepTitle) {
  if (Array.isArray(node)) {
    for (const item of node) stripFieldTitles(item, false);
    return node;
  }
  if (node === null || typeof node !== "object") return node;
  if (!keepTitle) delete node.title;
  for (const [key, value] of Object.entries(node)) {
    if (NAME_MAPS.has(key) && value && typeof value === "object" && !Array.isArray(value)) {
      // 이 한 겹의 열쇠는 이름이다 — 표 자체의 `title`을 지우지 않는다.
      // `$defs`의 열쇠는 모델 이름이라 그 스키마의 title은 남긴다 (인터페이스 이름이 된다).
      const keep = key === "$defs" || key === "definitions";
      for (const inner of Object.values(value)) stripFieldTitles(inner, keep);
      continue;
    }
    stripFieldTitles(value, false);
  }
  return node;
}

/** 파일 이름 → 모듈 이름 (`c1-manifest` → `C1Manifest`). */
function moduleName(stem) {
  return stem
    .split("-")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join("");
}

async function outputs() {
  const files = (await readdir(SCHEMA_DIR)).filter((f) => f.endsWith(".json")).sort();
  if (files.length === 0) throw new Error(`계약 스키마가 없다: ${SCHEMA_DIR}`);

  const out = new Map();
  const stems = [];
  for (const file of files) {
    const stem = file.replace(/\.json$/, "");
    stems.push(stem);
    const schema = JSON.parse(await readFile(join(SCHEMA_DIR, file), "utf8"));
    // 이름은 모델 이름(`title`)을 쓴다 — 계약 문서·파이썬 모델과 같은 이름이어야 찾기 쉽다.
    const name = schema.title ?? moduleName(stem);
    stripFieldTitles(schema, true);
    const ts = await compile(schema, name, {
      bannerComment: BANNER,
      additionalProperties: true, // 받는 쪽은 관대하게 (계약 원칙 3) — 모르는 필드를 허용한다
      style: { printWidth: 110, singleQuote: false },
      $refOptions: { resolve: { external: false } },
    });
    out.set(join(OUT_DIR, `${stem}.ts`), ts);
  }

  const index = [
    BANNER,
    "",
    "/** 생성된 계약 모듈 목록. 타입은 계약별 경로로 가져온다 (이름이 겹치는 것이 있다). */",
    "export const CONTRACT_MODULES = [",
    ...stems.map((s) => `  "${s}",`),
    "] as const;",
    "",
    "export type ContractModule = (typeof CONTRACT_MODULES)[number];",
    "",
  ].join("\n");
  out.set(join(OUT_DIR, "index.ts"), index);
  return out;
}

const check = process.argv.includes("--check");
const out = await outputs();

if (check) {
  const stale = [];
  for (const [path, text] of out) {
    let current = null;
    try {
      current = await readFile(path, "utf8");
    } catch {
      /* 없으면 다름 */
    }
    if (current !== text) stale.push(path);
  }
  for (const path of stale) console.log("다름:", path);
  if (stale.length > 0) {
    console.log("계약 타입이 스키마와 다르다 — `pnpm gen:api-types`를 돌린다.");
    process.exit(1);
  }
  console.log(`계약 타입 ${out.size}개가 최신이다.`);
} else {
  await mkdir(OUT_DIR, { recursive: true });
  for (const [path, text] of out) await writeFile(path, text, "utf8");
  console.log(`계약 타입 ${out.size}개 → web/packages/api-types/src`);
}
