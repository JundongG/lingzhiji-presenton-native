// SPDX-License-Identifier: Apache-2.0
// Materialize the versioned Native Editable layout configuration into its template.
// Run after editing the configuration: node scripts/update_native_editable_template.mjs
// This changes repository template files only; it never touches saved user decks.
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const nextjs = path.join(root, "servers/nextjs");
const require = createRequire(path.join(nextjs, "package.json"));
const { build } = require("esbuild");
const directory = await mkdtemp(path.join(tmpdir(), "presenton-template-layout-"));
try {
  const helperFile = path.join(directory, "native-layout.mjs");
  await build({ entryPoints: [path.join(nextjs, "app/(presentation-generator)/presentation/utils/nativeEditableLayout.ts")],
    outfile: helperFile, bundle: true, platform: "node", format: "esm", logLevel: "silent" });
  const { upgradeNativeEditableUi, NATIVE_EDITABLE_LAYOUT_VERSION } = await import(pathToFileURL(helperFile).href);
  const filename = path.join(root, "templates/native_editable/template.json");
  const template = JSON.parse(await readFile(filename, "utf8"));
  if (template.id !== "native_editable" || !Array.isArray(template.layouts)) throw new Error("Expected the bounded Native Editable template");
  template.layouts = template.layouts.map(layout => {
    const result = upgradeNativeEditableUi(layout);
    if (!result.ok) throw new Error(`${layout.id}: ${result.warnings.join("; ")}`);
    return result.ui;
  });
  template.merged_components = template.layouts.flatMap(layout => layout.components.map(component => ({
    id: component.id, description: component.description, variants: [structuredClone(component)],
  })));
  template.native_layout_version = NATIVE_EDITABLE_LAYOUT_VERSION;
  await writeFile(filename, JSON.stringify(template, null, 2) + "\n");
  console.log(`Materialized Native Editable layout version ${NATIVE_EDITABLE_LAYOUT_VERSION}`);
} finally {
  await rm(directory, { recursive: true, force: true });
}
