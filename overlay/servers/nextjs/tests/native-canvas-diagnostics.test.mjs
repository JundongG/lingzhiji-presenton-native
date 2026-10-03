// Native local diagnostic tests. SPDX-License-Identifier: Apache-2.0
import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";
import { build } from "esbuild";

const root = "app/(presentation-generator)/presentation";
let directory, serialize;
test.before(async () => {
  directory = await mkdtemp(path.join(tmpdir(), "native-diagnostics-"));
  const output = path.join(directory, "helper.mjs");
  await build({ entryPoints: [`${root}/utils/nativeCanvasDiagnostics.ts`], outfile: output, bundle:true, platform:"node", format:"esm", logLevel:"silent" });
  ({serializeNativeCanvasDiagnostics: serialize} = await import(pathToFileURL(output).href));
});
test.after(async () => { await rm(directory, {recursive:true, force:true}); });
const data = () => ({
  id:"current-deck", version:"v2-standard", generation_mode:"standard", title:"预算评审", theme:{colors:{primary:"#123456"}},
  slides:[{id:"database-slide", index:0, content:{private:"not exported"}, ui:{id:"cover-layout", components:[{id:"title-component", elements:[{id:"title-element", type:"text", runs:[{text:"Q4 150 → 168；普通内容 https://example.com 保留"}]}]}]}}],
  owner_id:"owner-secret", file_paths:["/private/input.docx"], instructions:"private instructions", api_key:"do-not-export", config:{provider:"private"},
});

test("Only current title/theme/index/ui are serialized; canvas identifiers and text stay exact", () => {
  const input=data(), original=JSON.stringify(input), output=JSON.parse(serialize("current-deck",input));
  assert.deepEqual(Object.keys(output),["schema_version","title","theme","slides"]);
  assert.equal(output.schema_version,"presenton.native-canvas-diagnostics.v1");
  assert.deepEqual(Object.keys(output.slides[0]),["index","ui"]);
  assert.equal(output.slides[0].ui.id,"cover-layout");
  assert.equal(output.slides[0].ui.components[0].id,"title-component");
  assert.equal(output.slides[0].ui.components[0].elements[0].id,"title-element");
  assert.equal(output.slides[0].ui.components[0].elements[0].runs[0].text,input.slides[0].ui.components[0].elements[0].runs[0].text);
  assert.equal(JSON.stringify(input),original);
  for (const secret of ["owner-secret","/private/input.docx","private instructions","do-not-export","database-slide"]) assert.equal(JSON.stringify(output).includes(secret),false);
});

test("Mismatched, missing, Smart and legacy presentations are rejected", () => {
  for (const input of [null,{...data(),id:"another-deck"},{...data(),type:"smart"},{...data(),generation_mode:"smart"},{...data(),version:"v1-standard"}]) {
    assert.throws(()=>serialize("current-deck",input));
  }
});

test("Unknown credential and private metadata fields are stripped recursively", () => {
  const input=data(); input.slides[0].ui.metadata={owner_id:"bad-owner", file_paths:["bad-path"], instructions:"bad-instructions", password:"bad-pass", apiKey:"bad-api", private_key:"bad-private", signingKey:"bad-signing", encryption_key:"bad-encryption", nested:{access_token:"bad-token", cookie:"bad-cookie", AWS_SECRET_ACCESS_KEY:"bad-key", useful:"keep"}};
  input.theme.credentials={value:"bad-value"};
  const json=serialize("current-deck",input), output=JSON.parse(json);
  assert.equal(json.includes("bad-"),false);
  assert.equal(output.slides[0].ui.metadata.nested.useful,"keep");
});

test("Private, external, signed, file and inline asset references are redacted", () => {
  for (const ref of ["/app_data/images/users/user/image.png","https://host/image.png?signature=secret","/static/image.png?token=secret","file:///private/image.png","data:image/png;base64,secret","blob:secret","/home/user/image.png","C:\\Users\\user\\image.png"]) {
    const input=data(); input.slides[0].ui.elements=[{type:"image", data:ref}];
    const output=JSON.parse(serialize("current-deck",input));
    assert.match(output.slides[0].ui.elements[0].data,/^\[redacted/);
  }
  const input=data(); input.slides[0].ui.elements=[{type:"image",data:"/static/images/placeholder.jpg"}];
  assert.equal(JSON.parse(serialize("current-deck",input)).slides[0].ui.elements[0].data,"/static/images/placeholder.jpg");
});

test("Unrelated top-level settings are never read and serialization makes no request", () => {
  const input=data(); Object.defineProperty(input,"settings",{get(){assert.fail("Do not read settings")}});
  const originalFetch=globalThis.fetch; globalThis.fetch=()=>assert.fail("No diagnostic network request");
  try { assert.ok(serialize("current-deck",input)); } finally { globalThis.fetch=originalFetch; }
});

test("Missing canvas, cycles and oversized payloads fail safely", () => {
  assert.throws(()=>serialize("current-deck",{...data(),slides:[{index:0,ui:null}]}),/no loaded canvas UI/);
  const cyclic=data(); cyclic.slides[0].ui.children=[cyclic.slides[0].ui];
  assert.throws(()=>serialize("current-deck",cyclic),/circular/);
  assert.throws(()=>serialize("current-deck",{...data(),title:"x".repeat(6*1024*1024)}),/safe size/);
});

test("Header provides visible read-only diagnostics and user-gesture native download", async () => {
  const source=await readFile(`${root}/components/PresentationHeader.tsx`,"utf8");
  assert.match(source,/Native canvas diagnostics JSON/);
  assert.match(source,/<textarea[\s\S]*?readOnly[\s\S]*?value=\{canvasDiagnostics\?\.json/);
  assert.match(source,/serializeNativeCanvasDiagnostics\(presentation_id, presentationData\)/);
  assert.match(source,/href=\{nativeExportResult\.url\}[\s\S]*?download=\{nativeExportResult\.fileName\}/);
  assert.match(source,/Download native PPTX/);
  assert.match(source,/url\?\.startsWith\("blob:"\)/);
  assert.match(source,/!nativeMountedRef\.current \|\| nativePresentationIdRef\.current !== presentation_id/);
  assert.match(source,/setNativeExportResult\(null\)/);
  const native=source.slice(source.indexOf("const handleExportNativePptx"),source.indexOf("const handleExportPdf"));
  assert.equal(native.includes("60_000"),false);
  assert.match(native,/duration: Infinity/);
  assert.equal((native.match(/notify\.dismiss\(toastId\)/g) || []).length,2);
  const diagnostics=source.slice(source.indexOf("const handleCanvasDiagnostics"),source.indexOf("const downloadCanvasDiagnostics"));
  assert.doesNotMatch(diagnostics,/fetch\(|flushSave\(|localStorage|trackEvent/);
});
