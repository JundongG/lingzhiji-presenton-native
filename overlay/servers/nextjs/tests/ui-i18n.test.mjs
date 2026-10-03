// Lingzhiji UI language tests. SPDX-License-Identifier: Apache-2.0
import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";
import { build } from "esbuild";

let directory, modulePath, sequence = 0;
test.before(async () => {
  directory = await mkdtemp(path.join(tmpdir(), "lingzhiji-ui-"));
  modulePath = path.join(directory, "ui.mjs");
  await build({ entryPoints: ["lib/ui-i18n/index.tsx"], outfile: modulePath, bundle: true, platform: "node", format: "esm", logLevel: "silent", plugins: [{ name: "hook-adapter", setup(builder) {
    builder.onResolve({ filter: /^react$/ }, () => ({ path: "adapter", namespace: "test" }));
    builder.onLoad({ filter: /.*/, namespace: "test" }, () => ({ contents: "export const useCallback = f => f; export const useEffect = f => f(); export const useSyncExternalStore = (subscribe, getSnapshot, getServerSnapshot) => { globalThis.__uiSubscribe = subscribe; return typeof window === 'undefined' ? getServerSnapshot() : getSnapshot(); };", loader: "js" }));
  } }] });
});
test.after(async () => { await rm(directory, { recursive: true, force: true }); });
test.afterEach(() => { delete globalThis.window; delete globalThis.document; delete globalThis.__uiSubscribe; });
const load = () => import(`${pathToFileURL(modulePath).href}?case=${++sequence}`);
function browser(initial = {}) {
  const data = new Map(Object.entries(initial)), listeners = new Set();
  globalThis.window = { localStorage: { getItem: k => data.get(k) ?? null, setItem: (k, v) => data.set(k, v) }, addEventListener: (_, fn) => listeners.add(fn), removeEventListener: (_, fn) => listeners.delete(fn) };
  globalThis.document = { documentElement: { lang: "zh-CN" } };
  return { data, emit: e => listeners.forEach(fn => fn(e)), listeners };
}

test("server snapshot defaults to Chinese and unknown model IDs are unchanged", async () => {
  const ui = await load();
  assert.equal(ui.getUiLocale(), "zh-CN");
  assert.equal(ui.uiText("Generate presentation"), "生成演示文稿");
  assert.equal(ui.uiText("gpt-5.4"), "gpt-5.4");
  assert.equal(ui.uiText("OPENAI_API_KEY"), "OPENAI_API_KEY");
  assert.equal(ui.uiText("User-authored content"), "User-authored content");
  assert.equal(ui.uiText("Generate"), "生成演示");
  assert.equal(ui.uiText("Turn prompts or documents into presentations with AI"), "用 AI 将提示词或文档变成演示文稿");
  for (const source of ["constructor", "toString", "__proto__"]) {
    assert.equal(ui.uiText(source), source);
  }
});

test("English preference is read without changing provider/account storage", async () => {
  const { data } = browser({ "lingzhiji.ui-language": "en", provider: "ollama", account: "unchanged" });
  const ui = await load();
  assert.equal(ui.getUiLocale(), "en");
  assert.equal(ui.uiText("Settings"), "Settings");
  ui.setUiLocale("zh-CN");
  assert.equal(ui.uiText("Settings"), "设置");
  assert.equal(data.get("provider"), "ollama");
  assert.equal(data.get("account"), "unchanged");
  assert.equal(document.documentElement.lang, "zh-CN");
  ui.setUiLocale("en");
  assert.equal(ui.uiText("Settings"), "Settings");
  assert.equal(document.documentElement.lang, "en");
});

test("storage failure leaves a usable session-only language switch", async () => {
  browser({ "lingzhiji.ui-language": "zh-CN" });
  const ui = await load();
  assert.equal(ui.getUiLocale(), "zh-CN");
  window.localStorage.setItem = () => { throw new Error("storage denied"); };
  ui.setUiLocale("en");
  assert.equal(ui.getUiLocale(), "en");
  window.localStorage.getItem = () => { throw new Error("storage denied"); };
  ui.setUiLocale("zh-CN");
  assert.equal(ui.getUiLocale(), "zh-CN");
});

test("subscribers update, cross-tab changes work, and cleanup removes listeners", async () => {
  const state = browser();
  const ui = await load();
  ui.useUiText();
  let updates = 0;
  const cleanup = globalThis.__uiSubscribe(() => { updates++; });
  ui.setUiLocale("en");
  assert.equal(updates, 1);
  state.emit({ key: "lingzhiji.ui-language", newValue: "zh-CN" });
  assert.equal(ui.uiText("Save"), "保存");
  assert.equal(updates, 2);
  state.emit({ key: "provider", newValue: "different" });
  assert.equal(updates, 2);
  cleanup(); assert.equal(state.listeners.size, 0);
});

test("malformed locale is ignored and known chat/error copy is translated", async () => {
  browser(); const ui = await load();
  ui.setUiLocale("fr"); assert.equal(ui.getUiLocale(), "zh-CN");
  assert.equal(ui.uiText("Ask anything.\nType / to get Quick prompts."), "输入你的问题或修改需求。\n输入 / 查看快捷提示词。");
  assert.equal(ui.uiText("Generation failed"), "生成失败");
  assert.equal(ui.uiText("Could not save settings"), "无法保存设置");
});

test("model language, values, endpoint and config definitions were not changed by UI localization", async () => {
  const type = await readFile("app/(presentation-generator)/upload/type.ts", "utf8");
  assert.ok(type.includes('ChineseSimplified = "Chinese (Simplified - 中文, 汉语)"'));
  const ui = await readFile("lib/ui-i18n/index.tsx", "utf8");
  assert.doesNotMatch(ui, /fetch\(|react-redux|dispatch\(/);
  assert.match(ui, /lingzhiji\.ui-language/);
  const controls = await readFile("app/(presentation-generator)/upload/components/ConfigurationSelects.tsx", "utf8");
  assert.match(controls, /value=\{language\}/);
  assert.ok(controls.includes('onConfigChange("language", value)'));
});
