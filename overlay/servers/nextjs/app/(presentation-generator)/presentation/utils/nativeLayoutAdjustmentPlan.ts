// SPDX-License-Identifier: Apache-2.0
// Explicit-action-only planning. It never dispatches, saves, or replaces loaded UI.
import type { PresentationData } from "@/store/slices/presentationGeneration";
import { upgradeNativeEditableUi } from "./nativeEditableLayout";

export type NativeLayoutPlan = {
  presentationId: string;
  sourceSlides: PresentationData["slides"];
  ok: boolean;
  updates: { index: number; ui: Record<string, unknown> }[];
  warnings: string[];
  slideCount: number;
  changeCount: number;
};

export function prepareNativeLayoutAdjustment(id: string, data: PresentationData | null): NativeLayoutPlan {
  const rejected = (warnings: string[]): NativeLayoutPlan => ({ presentationId: id, sourceSlides: data?.slides,
    ok: false, updates: [], warnings, slideCount: data?.slides?.length || 0, changeCount: 0 });
  if (!data || data.id !== id || data.version !== "v2-standard" || data.generation_mode === "smart" || data.type === "smart") {
    return rejected(["The currently loaded Standard canvas presentation is required."]);
  }
  if (!Array.isArray(data.slides) || !data.slides.length) return rejected(["No loaded slides are available."]);
  const updates: NativeLayoutPlan["updates"] = [];
  const warnings: string[] = [];
  let changeCount = 0;
  data.slides.forEach((slide: { ui?: unknown }, index: number) => {
    const result = upgradeNativeEditableUi(slide?.ui);
    if (!result.ok) warnings.push(...result.warnings.map((warning) => `Slide ${index + 1}: ${warning}`));
    else if (result.changed) {
      updates.push({ index, ui: result.ui as Record<string, unknown> });
      changeCount += result.changes.length;
    }
  });
  // Discard all prospective changes if even one page is unsupported/over capacity.
  if (warnings.length) return rejected(warnings);
  return { presentationId: id, sourceSlides: data.slides, ok: true, updates, warnings,
    slideCount: data.slides.length, changeCount };
}
