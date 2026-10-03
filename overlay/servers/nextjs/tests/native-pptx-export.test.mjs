// Native PPTX beta add-on tests. SPDX-License-Identifier: Apache-2.0
import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";
import { build } from "esbuild";

const root = "app/(presentation-generator)/presentation";
let directory, native, useAutoSave, PresentationGenerationApi;
const sample = (text = "Saved") => ({
  id: "deck-id", title: "Deck", n_slides: 1, version: "v2-standard", generation_mode: "standard",
  slides: [{ id: "slide-id", index: 0, ui: { elements: [{ type: "text", text }] } }],
});
const pptxResponse = () => new Response("PPTX bytes", { headers: { "content-type": native.NATIVE_PPTX_CONTENT_TYPE } });

// Run the actual hook with deterministic React/Redux adapters. No browser,
// database, provider or timer wait is needed to exercise save serialization.
const adapter = `
const h = () => globalThis.__nativeSaveHarness;
export const useRef = value => { const i=h().cursor++; return h().refs[i] ||= { current:value }; };
export const useState = value => { const ref=useRef(value); return [ref.current, value => {ref.current=value}]; };
export const useCallback = fn => fn;
export const useEffect = fn => {h().effects.push(fn)};
export const useDispatch = () => () => {};
export const useSelector = selector => selector(h().state);
export const useStore = () => ({ getState: () => h().state });
export const addToHistory = payload => payload;
export const PresentationGenerationApi = {
 updatePresentationContent: value => h().saveContent(value),
 updatePresentationSlide: value => h().saveSlide(value),
};`;

test.before(async () => {
  directory = await mkdtemp(path.join(tmpdir(), "presenton-native-export-"));
  const helper = path.join(directory, "helper.mjs");
  await build({ entryPoints: [`${root}/utils/nativePptxExport.ts`], outfile: helper, bundle: true, platform: "node", format: "esm", logLevel: "silent" });
  native = await import(pathToFileURL(helper).href);
  const saveApi = path.join(directory, "save-api.mjs");
  await build({ entryPoints: ["app/(presentation-generator)/services/api/presentation-generation.ts"], outfile: saveApi, bundle: true, platform: "node", format: "esm", logLevel: "silent" });
  ({ PresentationGenerationApi } = await import(pathToFileURL(saveApi).href));
  const hook = path.join(directory, "hook.mjs");
  await build({
    entryPoints: [`${root}/hooks/useAutoSave.tsx`], outfile: hook,
    bundle: true, platform: "node", format: "esm", logLevel: "silent",
    plugins: [{ name: "deterministic-hook-adapters", setup(builder) {
      builder.onResolve({ filter: /^(react|react-redux)$|services\/api\/presentation-generation$|slices\/undoRedoSlice$/ }, () => ({ path: "adapter", namespace: "test" }));
      builder.onLoad({ filter: /.*/, namespace: "test" }, () => ({ contents: adapter, loader: "js" }));
    } }],
  });
  ({ useAutoSave } = await import(pathToFileURL(hook).href));
});
test.after(async () => { await rm(directory, { recursive: true, force: true }); });
test.afterEach(() => {
  globalThis.__nativeSaveHarness?.cleanups.forEach(cleanup => cleanup?.());
  delete globalThis.__nativeSaveHarness;
});

function setupHook() {
  const h = globalThis.__nativeSaveHarness = {
    refs: [], cursor: 0, effects: [], cleanups: [], saved: [],
    state: { presentationGeneration: { presentationData: sample(), isStreaming: false, isLoading: false, isLayoutLoading: false } },
    saveContent: async value => { h.saved.push(["metadata", value]); },
    saveSlide: async value => { h.saved.push(["slide", value]); },
  };
  h.render = (options = {}) => {
    h.cleanups.forEach(cleanup => cleanup?.()); h.cleanups = []; h.cursor = 0; h.effects = [];
    const hook = useAutoSave({ debounceMs: 60_000, ...options });
    h.cleanups = h.effects.map(effect => effect());
    return hook;
  };
  h.setData = data => { h.state.presentationGeneration.presentationData = data; };
  return h;
}

const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};

test("Native request follows editor commit and completed save; credentials are included", async () => {
  const order = [], save = deferred();
  const operation = native.saveAndRequestNativePptx({ presentationId: "deck-id",
    commitEditor: () => { order.push("commit"); },
    flushSave: async () => { order.push("save"); return await save.promise; },
    request: async (url, options) => { order.push("request"); assert.match(url, /deck-id\/export\/native-pptx$/); assert.equal(options.credentials, "include"); assert.equal(options.method, "POST"); return pptxResponse(); },
  });
  await Promise.resolve(); assert.deepEqual(order, ["commit", "save"]);
  save.resolve(sample("Current editor"));
  const result = await operation;
  assert.deepEqual(order, ["commit", "save", "request"]);
  assert.equal(await result.blob.text(), "PPTX bytes");
});

test("Both save API requests include credentials for a direct backend origin", async () => {
  const previousFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options) => { calls.push({url, options}); return Response.json({}); };
  try {
    await PresentationGenerationApi.updatePresentationContent({id:"deck-id", title:"Renamed"});
    await PresentationGenerationApi.updatePresentationSlide(sample().slides[0]);
  } finally { globalThis.fetch = previousFetch; }
  assert.equal(calls.length, 2);
  for (const {options} of calls) {
    assert.equal(options.method, "PATCH");
    assert.equal(options.credentials, "include");
  }
});

test("File delivery requests a private HTTP link and validates the response", async () => {
  const url = "/app_data/exports/users/11111111-1111-1111-1111-111111111111/native-pptx/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.pptx";
  const result = await native.saveAndRequestNativePptx({ presentationId: "deck-id", delivery: "file", commitEditor() {}, flushSave: async () => sample(), request: async (_url, options) => {
    assert.deepEqual(JSON.parse(options.body), {delivery:"file"});
    assert.equal(options.credentials,"include");
    return Response.json({url, file_name:"中文-native.pptx", expires_at:1900000000, warnings:["Review beta styling"]});
  } });
  assert.equal(result.delivery,"file");
  assert.ok(result.url.endsWith(url));
  assert.equal(result.fileName,"中文-native.pptx");
  assert.deepEqual(result.warnings,["Review beta styling"]);
});

test("File delivery rejects external, malformed and non-native links", async () => {
  for (const url of ["https://outside.invalid/file.pptx", "javascript:alert(1)", "/app_data/exports/users/a/native-pptx/x.pptx", "/app_data/exports/users/11111111-1111-1111-1111-111111111111/legacy.pptx"]) {
    await assert.rejects(native.saveAndRequestNativePptx({ presentationId: "deck-id", delivery:"file", commitEditor() {}, flushSave:async()=>sample(), request:async()=>Response.json({url,file_name:"file.pptx",expires_at:1900000000}) }),/invalid private download link/);
  }
});

test("Save failure prevents export request", async () => {
  await assert.rejects(native.saveAndRequestNativePptx({ presentationId: "deck-id", commitEditor() {}, flushSave: async () => { throw new Error("Save rejected"); }, request() { assert.fail("No export after failed save"); } }), /Save rejected/);
});

test("Smart, legacy, absent UI, empty and navigated decks are rejected before request", async () => {
  for (const data of [{...sample(), type:"smart"}, {...sample(), generation_mode:"smart"}, {...sample(), version:"v1-standard"}, {...sample(), slides:[{id:"s"}]}, {...sample(), slides:[]}, {...sample(), id:"new-deck"}]) {
    await assert.rejects(native.saveAndRequestNativePptx({ presentationId: "deck-id", commitEditor() {}, flushSave: async () => data, request() { assert.fail("Unsupported deck requested"); } }), /Standard canvas/);
  }
});

test("Native error preserves exact element path", async () => {
  const detail = "slides[0].ui.elements[2]: image is unsupported";
  await assert.rejects(native.saveAndRequestNativePptx({ presentationId: "deck-id", commitEditor() {}, flushSave: async () => sample(), request: async () => Response.json({detail}, {status:422}) }), error => error.message === detail);
});

test("Truncated warning response is disclosed to the user", async () => {
  const result = await native.saveAndRequestNativePptx({ presentationId: "deck-id", commitEditor() {}, flushSave: async () => sample(), request: async () => new Response("PPTX", { headers: { "content-type": native.NATIVE_PPTX_CONTENT_TYPE, "x-native-pptx-warnings": "[]", "x-native-pptx-warnings-truncated": "12" } }) });
  assert.match(result.warnings[0], /12 additional export warnings/);
});

test("Gateway HTML is never downloaded as PPTX", async () => {
  await assert.rejects(native.saveAndRequestNativePptx({ presentationId: "deck-id", commitEditor() {}, flushSave: async () => sample(), request: async () => new Response("<html>login</html>", {headers:{"content-type":"text/html"}}) }), /did not return a PowerPoint/);
});

test("Flush reads immediate Redux edits before effects/debounce run", async () => {
  const h = setupHook(), {flushSave} = h.render();
  const current = {...sample("Just typed"), title:"Just renamed"};
  h.setData(current);
  assert.equal(await flushSave(), current);
  assert.deepEqual(h.saved.map(([kind]) => kind), ["metadata", "slide"]);
  assert.equal(h.saved[1][1].ui.elements[0].text, "Just typed");
});

test("Flush waits for older in-flight save, then saves newer edits; repeat flush stays serialized", async () => {
  const h = setupHook(), {flushSave} = h.render(), first = deferred();
  let active = 0, maxActive = 0;
  h.saveSlide = async slide => {
    active++; maxActive = Math.max(maxActive, active); h.saved.push(["slide", slide]);
    if (h.saved.length === 1) await first.promise;
    active--;
  };
  h.setData(sample("Old in-flight edit"));
  const one = flushSave();
  h.setData(sample("New immediate edit"));
  const two = flushSave();
  assert.equal(h.saved.length, 1);
  first.resolve();
  const [savedOne, savedTwo] = await Promise.all([one, two]);
  assert.equal(maxActive, 1);
  assert.equal(h.saved.length, 2);
  assert.equal(savedOne.slides[0].ui.elements[0].text, "New immediate edit");
  assert.equal(savedTwo, savedOne);
});

test("Flush rejects save errors and a later explicit retry can succeed", async () => {
  const h = setupHook(), {flushSave} = h.render();
  h.setData(sample("Unsaved")); h.saveSlide = async () => {throw new Error("Network save failure")};
  await assert.rejects(flushSave(), /Network save failure/);
  h.saveSlide = async slide => h.saved.push(["slide", slide]);
  assert.equal((await flushSave()).slides[0].ui.elements[0].text, "Unsaved");
});

test("Paused assistant, streaming and loading states block save/export", async () => {
  const h = setupHook(); let hook = h.render({enabled:false});
  await assert.rejects(hook.flushSave(), /Wait for generation or assistant/);
  hook = h.render();
  for (const flag of ["isStreaming", "isLoading", "isLayoutLoading"]) {
    h.state.presentationGeneration[flag] = true;
    await assert.rejects(hook.flushSave(), /Wait for generation or assistant/);
    h.state.presentationGeneration[flag] = false;
  }
  assert.equal(h.saved.length, 0);
});

test("Navigation during save blocks export of stale deck", async () => {
  const h = setupHook(), {flushSave} = h.render(), saving = deferred();
  h.setData(sample("Edit")); h.saveSlide = () => saving.promise;
  const pending = flushSave(); h.setData({...sample(), id:"another-deck"}); saving.resolve();
  await assert.rejects(pending, /presentation changed/);
});

test("Header adds separate Standard-only beta action and keeps existing export handlers", async () => {
  const header = await readFile(`${root}/components/PresentationHeader.tsx`, "utf8");
  assert.match(header, /Native PPTX \(beta\)/);
  assert.match(header, /generationMode === "standard" &&/);
  assert.match(header, /COMMIT_TEMPLATE_V2_INLINE_TEXT_EVENT/);
  assert.match(header, /nativeExportInFlightRef\.current \|\| isExporting/);
  assert.match(header, /handleExportPptx\(\)/);
  assert.match(header, /handleExportPdf\(\)/);
});
