// SPDX-License-Identifier: Apache-2.0
// Independent add-on: pure, explicit-only layout upgrade; no I/O or persistence.
import configuration from "./nativeEditableLayout.v2.json";

type Obj = Record<string, unknown>;
type Rule = { match: Record<string, string | null>; patch: Obj };
type LayoutRule = { components: { id: string; elements: Rule[] }[] };
export type NativeLayoutFitIssue = { path: string; estimatedHeight: number; availableHeight: number };
export type NativeLayoutUpgradeResult = {
  ok: boolean; ui: unknown; changed: boolean; changes: string[]; warnings: string[]; version: number;
};
export const NATIVE_EDITABLE_LAYOUT_VERSION = configuration.version;
const layouts = configuration.layouts as Record<string, LayoutRule>;
const record = (v: unknown): v is Obj => !!v && typeof v === "object" && !Array.isArray(v);
const numeric = (v: unknown, fallback: number) => typeof v === "number" && Number.isFinite(v) ? v : fallback;

/** Refuse unknown, renamed, duplicated or structurally customized roles. */
function targets(ui: unknown): { element: Obj; rule: Rule; path: string }[] | null {
  if (!record(ui) || typeof ui.id !== "string" || !Object.hasOwn(layouts, ui.id) ||
      numeric(ui.native_layout_version, 0) > NATIVE_EDITABLE_LAYOUT_VERSION || !Array.isArray(ui.components)) return null;
  const layout = layouts[ui.id];
  if (ui.components.length !== layout.components.length) return null;
  const found: { element: Obj; rule: Rule; path: string }[] = [];
  for (const componentRule of layout.components) {
    const candidates = ui.components.map((component, index) => ({ component, index }))
      .filter(({ component }) => record(component) && component.id === componentRule.id);
    if (candidates.length !== 1) return null;
    const { component, index } = candidates[0];
    if (!record(component) || !Array.isArray(component.elements) || component.elements.length !== componentRule.elements.length) return null;
    for (const rule of componentRule.elements) {
      const matches = component.elements.map((element, elementIndex) => ({ element, elementIndex }))
        .filter(({ element }) => record(element) && Object.entries(rule.match).every(([key, value]) => element[key] === value));
      if (matches.length !== 1) return null;
      const { element, elementIndex } = matches[0];
      if (!record(element) || (element.font != null && !record(element.font))) return null;
      found.push({ element, rule, path: `components[${index}].elements[${elementIndex}]` });
    }
  }
  return found;
}
export function canUpgradeNativeEditableUi(ui: unknown): boolean { return targets(ui) !== null; }

function textOf(runs: unknown): string | null {
  if (!Array.isArray(runs)) return null;
  let text = "";
  for (const run of runs) {
    if (!record(run) || typeof run.text !== "string" || (run.type != null && run.type !== "text")) return null;
    text += run.text;
  }
  // Measurement only. Original Markdown strings and styled runs are not changed.
  return text.replace(/\*\*(.*?)\*\*/gs, "$1").replace(/__(.*?)__/gs, "$1")
    .replace(/\*(.*?)\*/gs, "$1").replace(/_(.*?)_/gs, "$1");
}
function estimatedLines(text: string, width: number, size: number, spacing: number): number {
  let lines = 1, used = 0;
  for (const glyph of text.replace(/\r\n?/g, "\n")) {
    if (glyph === "\n") { lines++; used = 0; continue; }
    const units = /\p{Mark}/u.test(glyph) ? 0 : glyph === "\t" ? 4.2 : 1.05;
    const advance = units * size + (units ? spacing : 0);
    if (used > 0 && used + advance > width) { lines++; used = 0; }
    used += advance;
  }
  return lines;
}
/** Conservative CJK-aware capacity diagnostic; browser shaping still needs QA. */
export function inspectNativeEditableTextFit(ui: unknown): NativeLayoutFitIssue[] {
  const found = targets(ui);
  if (!found) return [];
  const issues: NativeLayoutFitIssue[] = [];
  for (const { element, path } of found) {
    if (element.type !== "text" && element.type !== "text-list") continue;
    if (!record(element.size)) { issues.push({ path, estimatedHeight: Infinity, availableHeight: 0 }); continue; }
    const width = numeric(element.size.width, 0), height = numeric(element.size.height, 0);
    const font = record(element.font) ? element.font : {};
    let size = numeric(font.size, 18), lineHeight = numeric(font.line_height, numeric(font.lineHeight, 1.15));
    let spacing = Math.max(0, numeric(font.letter_spacing, numeric(font.letterSpacing, 0)));
    const items = element.type === "text" ? [element.runs] : element.items;
    if (!Array.isArray(items) || width <= 0 || height <= 0) { issues.push({ path, estimatedHeight: Infinity, availableHeight: height }); continue; }
    for (const runs of items) if (Array.isArray(runs)) for (const run of runs) {
      if (record(run) && record(run.font)) {
        size = Math.max(size, numeric(run.font.size, size));
        lineHeight = Math.max(lineHeight, numeric(run.font.line_height, numeric(run.font.lineHeight, lineHeight)));
        spacing = Math.max(spacing, numeric(run.font.letter_spacing, numeric(run.font.letterSpacing, spacing)));
      }
    }
    const textWidth = width - (element.type === "text-list" && element.marker !== "none" ? size + numeric(element.marker_gap, 6) : 0);
    let required = 0;
    for (const runs of items) {
      const text = textOf(runs);
      if (text === null || textWidth <= 0 || size <= 0 || lineHeight <= 0 || lineHeight > 2) { required = Infinity; break; }
      required += estimatedLines(text, textWidth, size, spacing) * size * lineHeight;
    }
    if (element.type === "text-list") required += Math.max(0, items.length - 1) * numeric(element.gap, 0);
    if (required > height + .1) issues.push({ path, estimatedHeight: required, availableHeight: height });
  }
  return issues;
}
function patchRecord(target: Obj, patch: Obj, path: string, changes: string[]) {
  for (const [key, value] of Object.entries(patch)) {
    if (record(value)) {
      if (!record(target[key])) target[key] = {};
      patchRecord(target[key] as Obj, value, `${path}.${key}`, changes);
    } else if (JSON.stringify(target[key]) !== JSON.stringify(value)) {
      target[key] = structuredClone(value);
      changes.push(`${path}.${key}`);
    }
  }
}
/**
 * Call only after explicit user action, then use the normal slide save flow.
 * Never run during GET/hydration/rendering/autosave. No text/data is rewritten.
 * Failure returns the original input with no partial edits.
 */
export function upgradeNativeEditableUi(ui: unknown): NativeLayoutUpgradeResult {
  const reject = (message: string): NativeLayoutUpgradeResult => ({ ok: false, ui, changed: false, changes: [], warnings: [message], version: NATIVE_EDITABLE_LAYOUT_VERSION });
  if (!targets(ui)) return reject("此页不符合已知的 Native Editable 布局结构，未作更改");
  let next: unknown;
  try { next = structuredClone(ui); } catch { return reject("此页不是可复制的画布数据，未作更改"); }
  const found = targets(next)!;
  const changes: string[] = [];
  for (const { element, rule, path } of found) {
    patchRecord(element, rule.patch, path, changes);
    if (record(rule.patch.font)) {
      if (record(element.font) && Object.hasOwn(element.font, "lineHeight") && Object.hasOwn(rule.patch.font, "line_height")) {
        patchRecord(element.font, { lineHeight: rule.patch.font.line_height }, `${path}.font`, changes);
      }
      const items = element.type === "text" ? [element.runs] : element.type === "text-list" ? element.items : [];
      if (!Array.isArray(items)) return reject("文字段落结构无法安全调整，原文未改动");
      for (let itemIndex = 0; itemIndex < items.length; itemIndex++) {
        const runs = items[itemIndex];
        if (!Array.isArray(runs)) return reject("文字段落结构无法安全调整，原文未改动");
        for (let runIndex = 0; runIndex < runs.length; runIndex++) {
          const run = runs[runIndex];
          if (!record(run) || typeof run.text !== "string" || (run.type != null && run.type !== "text")) return reject("此页包含未支持的文字内容，原文未改动");
          if (run.font != null && !record(run.font)) return reject("文字样式结构无法安全调整，原文未改动");
          if (record(run.font)) {
            const overrides: Obj = {};
            for (const key of ["size", "line_height"]) if (Object.hasOwn(rule.patch.font, key) && Object.hasOwn(run.font, key)) overrides[key] = rule.patch.font[key];
            if (Object.hasOwn(run.font, "lineHeight") && Object.hasOwn(rule.patch.font, "line_height")) {
              overrides.lineHeight = rule.patch.font.line_height;
              overrides.line_height = rule.patch.font.line_height;
            }
            patchRecord(run.font, overrides, `${path}.${element.type === "text" ? "runs" : `items[${itemIndex}]`}[${runIndex}].font`, changes);
          }
        }
      }
    }
  }
  const issues = inspectNativeEditableTextFit(next);
  if (issues.length) return reject(`调整后仍有${issues.length}个文字框超过安全容量，未应用。请保留原文并选择更大版式或拆分页面`);
  if (!record(next)) return reject("画布结构无效，未作更改");
  if (next.native_layout_version !== NATIVE_EDITABLE_LAYOUT_VERSION) {
    next.native_layout_version = NATIVE_EDITABLE_LAYOUT_VERSION;
    changes.push("native_layout_version");
  }
  return { ok: true, ui: next, changed: changes.length > 0, changes, warnings: [], version: NATIVE_EDITABLE_LAYOUT_VERSION };
}
