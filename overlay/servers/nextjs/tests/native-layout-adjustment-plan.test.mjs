// Explicit current-deck layout planning integration. SPDX-License-Identifier: Apache-2.0
import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";
import { build } from "esbuild";
const root="app/(presentation-generator)/presentation";
let directory, prepare, fixture;
test.before(async()=>{
  directory=await mkdtemp(path.join(tmpdir(),"native-layout-plan-"));
  const output=path.join(directory,"plan.mjs");
  await build({entryPoints:[`${root}/utils/nativeLayoutAdjustmentPlan.ts`],outfile:output,bundle:true,platform:"node",format:"esm",logLevel:"silent"});
  ({prepareNativeLayoutAdjustment:prepare}=await import(pathToFileURL(output).href));
  fixture=JSON.parse(await readFile("../fastapi/tests/fixtures/native_editable_real_model_before_v2.json","utf8"));
});
test.after(async()=>{await rm(directory,{recursive:true,force:true})});
const deck=()=>({id:"current",version:"v2-standard",generation_mode:"standard",slides:structuredClone(fixture.slides),title:"Current presentation"});

test("Whole-deck preflight uses current live content without mutating it",()=>{
  const current=deck();
  // Inject a fresh chart edit; the planner must never restore a fixture value.
  let located=false;
  function update(value){
    if(Array.isArray(value)) return value.forEach(update);
    if(!value||typeof value!=="object")return;
    if(value.type==="chart"&&value.series?.[0]?.values?.length){value.series[0].values[value.series[0].values.length-1]=41;located=true;}
    Object.values(value).forEach(update);
  }
  update(current.slides);
  assert.ok(located);
  const before=JSON.stringify(current);
  const plan=prepare("current",current);
  assert.equal(plan.ok,true);
  assert.ok(plan.updates.length>0);
  assert.equal(plan.sourceSlides,current.slides);
  assert.equal(JSON.stringify(current),before);
  const chartSlide=plan.updates.find(({ui})=>JSON.stringify(ui).includes('"values"'));
  assert.ok(chartSlide);
  assert.ok(JSON.stringify(chartSlide.ui).includes("41"));
});

test("One unsupported page rejects the whole plan and discards all updates",()=>{
  const current=deck(); current.slides[2].ui.components[0].id="unsupported-customization";
  const before=JSON.stringify(current);
  const result=prepare("current",current);
  assert.equal(result.ok,false); assert.deepEqual(result.updates,[]); assert.equal(result.changeCount,0);
  assert.ok(result.warnings.length); assert.equal(JSON.stringify(current),before);
});

test("Wrong deck, Smart mode and missing data never produce updates",()=>{
  for(const value of [null,{...deck(),id:"elsewhere"},{...deck(),generation_mode:"smart"},{...deck(),slides:[]}]){
    const result=prepare("current",value); assert.equal(result.ok,false); assert.deepEqual(result.updates,[]);
  }
});

test("Adjustment is idempotent after all planned UIs are applied",()=>{
  const current=deck(),first=prepare("current",current);
  for(const {index,ui} of first.updates) current.slides[index].ui=ui;
  const second=prepare("current",current);
  assert.equal(second.ok,true);assert.equal(second.updates.length,0);
});

test("Visible confirm path preflights before Redux, records undo and awaits normal saves",async()=>{
  const component=await readFile(`${root}/components/NativeLayoutAdjustDialog.tsx`,"utf8");
  assert.ok(component.indexOf("if (!fresh.ok)")<component.indexOf("dispatch(addToHistory"));
  assert.match(component,/batch\(\(\) => fresh\.updates\.forEach/);
  assert.match(component,/NATIVE_LAYOUT_BEFORE/);assert.match(component,/NATIVE_LAYOUT_APPLIED/);
  assert.match(component,/await flushSave\(\)/);assert.match(component,/current\.slides !== plan\.sourceSlides/);
  assert.match(component,/Apply and save/); assert.doesNotMatch(component,/fixtures|fetch\(|localStorage/);
  const header=await readFile(`${root}/components/PresentationHeader.tsx`,"utf8");
  assert.match(header,/onClick=\{\(\) => \{[\s\S]*?setNativeLayoutPlan\(prepareNativeLayoutAdjustment/);
  assert.match(header,/NativeLayoutAdjustDialog/);assert.match(header,/UiLanguageControl/);
});
