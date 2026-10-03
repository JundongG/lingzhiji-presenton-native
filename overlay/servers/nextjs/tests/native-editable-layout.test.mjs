// SPDX-License-Identifier: Apache-2.0
// Actual model-generated synthetic UI regression; original text is never shortened.
import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";
import { build } from "esbuild";
const root = "app/(presentation-generator)/presentation/utils";
let helper, baseline, template, configuration, directory;
test.before(async () => {
  directory = await mkdtemp(path.join(tmpdir(), "presenton-native-layout-"));
  const file = path.join(directory, "helper.mjs");
  await build({ entryPoints: [`${root}/nativeEditableLayout.ts`], outfile: file, bundle: true, platform: "node", format: "esm", logLevel: "silent" });
  helper = await import(pathToFileURL(file).href);
  baseline = JSON.parse(await readFile("../fastapi/tests/fixtures/native_editable_real_model_before_v2.json", "utf8"));
  template = JSON.parse(await readFile("../../templates/native_editable/template.json", "utf8"));
  configuration = JSON.parse(await readFile(`${root}/nativeEditableLayout.v2.json`, "utf8"));
});
test.after(async () => { await rm(directory, { recursive: true, force: true }); });
const original = index => structuredClone(baseline.slides[index].ui);
function preservationProjection(value) {
  if (Array.isArray(value)) return value.map(preservationProjection);
  if (!value || typeof value !== "object") return value;
  const ignored = new Set(["position", "size", "points", "alignment", "gap", "marker_gap", "max_length", "min_length", "max_items", "min_items", "max_item_length", "min_item_length", "native_layout_version"]);
  return Object.fromEntries(Object.entries(value).filter(([key]) => !ignored.has(key)).map(([key, child]) => {
    if (key === "font" && child && typeof child === "object") child = Object.fromEntries(Object.entries(child).filter(([field]) => field !== "size" && field !== "line_height"));
    return [key, preservationProjection(child)];
  }));
}

test("actual original failure has three cover overflow regions, preserved unchanged", () => {
  const before = original(0), saved = structuredClone(before);
  assert.equal(helper.inspectNativeEditableTextFit(before).length, 3);
  assert.equal(before.components[1].elements[2].items.length, 5);
  assert.deepEqual(before, saved);
});
test("actual five slides upgrade without changing text, tables, series or non-layout styling", () => {
  for (let index = 0; index < 5; index++) {
    const before = original(index), saved = structuredClone(before);
    const result = helper.upgradeNativeEditableUi(before);
    assert.equal(result.ok, true, JSON.stringify(result.warnings));
    assert.equal(result.changed, true);
    assert.deepEqual(before, saved);
    assert.deepEqual(preservationProjection(result.ui), preservationProjection(before));
    assert.deepEqual(helper.inspectNativeEditableTextFit(result.ui), []);
  }
  const cover = helper.upgradeNativeEditableUi(original(0)).ui;
  assert.equal(cover.components[0].elements[0].runs[0].text, "星澜实验室跨季度研发计划\n与资源统筹安排");
  assert.equal(cover.components[0].elements[0].__presenton_manual_position, true);
  assert.equal(cover.components[1].elements[2].items.length, 5);
  assert.equal(cover.components[1].elements[1].runs[1].font.bold, true);
  assert.match(cover.components[1].elements[4].runs[0].text, /不含真实信息，不作对外引用。$/);
  const table = helper.upgradeNativeEditableUi(original(1)).ui.components[1].elements[0];
  assert.equal(table.rows[0][2].runs[0].text, "168");
  assert.deepEqual(table, original(1).components[1].elements[0]);
  const chart = helper.upgradeNativeEditableUi(original(2)).ui.components[1].elements[0];
  assert.deepEqual(chart.series[0].values, [12, 18, 25, 32]);
  for (const index of [2, 3, 4]) assert.deepEqual(helper.upgradeNativeEditableUi(original(index)).ui.components[1].elements[0], original(index).components[1].elements[0]);
});
test("nested run font overrides are normalized only for requested size/line-height fields", () => {
  const before = original(0);
  const run = before.components[1].elements[1].runs[0];
  Object.assign(run.font, { size: 96, line_height: 1.9, family: "User Font", color: "#123456", italic: true, underline: true });
  const result = helper.upgradeNativeEditableUi(before);
  assert.equal(result.ok, true);
  const font = result.ui.components[1].elements[1].runs[0].font;
  assert.equal(font.size, 24); assert.equal(font.line_height, 1.15);
  assert.equal(font.family, "User Font"); assert.equal(font.color, "#123456");
  assert.equal(font.italic, true); assert.equal(font.underline, true);
  assert.equal(before.components[1].elements[1].runs[0].font.size, 96);
});
test("legacy line-height aliases are normalized and unhandled wide tracking is rejected", () => {
  const before = original(0), run = before.components[1].elements[1].runs[0];
  delete run.font.line_height; run.font.lineHeight = 1.9;
  const result = helper.upgradeNativeEditableUi(before);
  assert.equal(result.ok, true);
  assert.equal(result.ui.components[1].elements[1].runs[0].font.lineHeight, 1.15);
  assert.equal(result.ui.components[1].elements[1].runs[0].font.line_height, 1.15);
  run.font.letter_spacing = 100;
  const rejected = helper.upgradeNativeEditableUi(before);
  assert.equal(rejected.ok, false); assert.equal(rejected.ui, before);
  assert.equal(run.font.letter_spacing, 100);
});
test("new and old layouts use the same versioned configuration and are idempotent", () => {
  assert.equal(configuration.version, 2);
  for (const layout of template.layouts) {
    const result = helper.upgradeNativeEditableUi(layout);
    assert.equal(result.ok, true);
    // The template updater should have applied this exact configuration.
    assert.equal(result.changed, false, layout.id + ": " + result.changes.join(", "));
    for (const component of layout.components) {
      const merged = template.merged_components.find(value => value.id === component.id);
      assert.deepEqual(merged.variants[0], component);
    }
  }
  const first = helper.upgradeNativeEditableUi(original(0));
  const second = helper.upgradeNativeEditableUi(first.ui);
  assert.equal(second.changed, false); assert.deepEqual(second.ui, first.ui);
});
test("declared future capacities fit conservative all-CJK content", () => {
  for (const source of template.layouts) {
    const layout = structuredClone(source);
    for (const component of layout.components) for (const element of component.elements) {
      if (element.type === "text") element.runs = [{ text: "文".repeat(element.max_length) }];
      if (element.type === "text-list") element.items = Array.from({ length: element.max_items }, () => [{ text: "文".repeat(element.max_item_length) }]);
    }
    assert.deepEqual(helper.inspectNativeEditableTextFit(layout), [], source.id);
  }
});
test("oversized paragraphs or forced newlines fail atomically without removing any text", () => {
  for (const text of ["原文".repeat(500), "原\n".repeat(50)]) {
    const before = original(0); before.components[1].elements[1].runs[0].text = text;
    const saved = structuredClone(before), result = helper.upgradeNativeEditableUi(before);
    assert.equal(result.ok, false); assert.equal(result.changed, false);
    assert.equal(result.ui, before); assert.deepEqual(before, saved);
    assert.equal(result.changes.length, 0); assert.match(result.warnings[0], /容量/);
  }
});
test("unknown, duplicated, renamed, custom and future-version structures are refused", () => {
  const values = [null, {}, { ...original(0), id: "__proto__" }, { ...original(0), id: "other_cover" }, { ...original(0), native_layout_version: 3 }];
  const extra = original(0); extra.components[1].elements.push(structuredClone(extra.components[1].elements[1])); values.push(extra);
  const renamed = original(0); renamed.components[1].elements[1].name = "user_notes"; values.push(renamed);
  const duplicate = original(0); duplicate.components[1].elements[4].name = "summary"; values.push(duplicate);
  for (const value of values) { const result = helper.upgradeNativeEditableUi(value); assert.equal(result.ok, false); assert.equal(result.ui, value); }
});
test("malformed nested runs or formulas fail with the input left intact", () => {
  for (const runs of [3, [{ type: "latex", latex: "x^2" }], [{ text: "Keep", font: [] }]]) {
    const before = original(0); before.components[1].elements[1].runs = runs;
    const saved = structuredClone(before), result = helper.upgradeNativeEditableUi(before);
    assert.equal(result.ok, false); assert.deepEqual(before, saved); assert.equal(result.ui, before);
  }
});
test("circle callout safe rectangle lies inside the enlarged circle", () => {
  const ui = helper.upgradeNativeEditableUi(original(0)).ui;
  const [background, summary, list, circle, callout] = ui.components[1].elements;
  assert.ok(summary.position.y + summary.size.height < list.position.y);
  assert.ok(list.position.y + list.size.height <= background.size.height);
  const [a, b] = circle.points, cx = (a.x + b.x)/2, cy = (a.y + b.y)/2, radius = (b.x-a.x)/2;
  for (const x of [callout.position.x, callout.position.x + callout.size.width]) for (const y of [callout.position.y, callout.position.y + callout.size.height]) {
    assert.ok(Math.hypot(x-cx,y-cy) <= radius);
  }
});
