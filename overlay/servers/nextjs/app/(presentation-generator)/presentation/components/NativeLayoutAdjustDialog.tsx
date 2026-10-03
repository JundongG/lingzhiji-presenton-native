"use client";
// SPDX-License-Identifier: Apache-2.0
// Current-deck, explicit layout adjustment through the existing save/undo flow.
import { useLayoutEffect, useRef, useState } from "react";
import { batch, useDispatch, useStore } from "react-redux";
import type { RootState } from "@/store/store";
import { updateSlideUi, type PresentationData } from "@/store/slices/presentationGeneration";
import { addToHistory } from "@/store/slices/undoRedoSlice";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { notify } from "@/components/ui/sonner";
import { useUiText } from "@/lib/ui-i18n";
import { COMMIT_TEMPLATE_V2_INLINE_TEXT_EVENT } from "@/components/slide-editor/text/TiptapInlineTextEditor";
import { prepareNativeLayoutAdjustment, type NativeLayoutPlan } from "../utils/nativeLayoutAdjustmentPlan";

export default function NativeLayoutAdjustDialog({ presentationId, plan, blocked, setPlan, flushSave }: {
  presentationId: string;
  plan: NativeLayoutPlan | null;
  blocked: boolean;
  setPlan: (plan: NativeLayoutPlan | null) => void;
  flushSave: () => Promise<PresentationData>;
}) {
  const t = useUiText();
  const dispatch = useDispatch();
  const store = useStore<RootState>();
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const gate = useRef({ mounted: true, blocked, presentationId });
  useLayoutEffect(() => {
    gate.current = { mounted: true, blocked, presentationId };
    return () => { gate.current.mounted = false; };
  }, [blocked, presentationId]);

  const apply = async () => {
    if (busyRef.current || blocked || !plan?.ok || !plan.updates.length) return;
    busyRef.current = true; setBusy(true);
    let applied = false;
    try {
      window.dispatchEvent(new Event(COMMIT_TEMPLATE_V2_INLINE_TEXT_EVENT));
      await new Promise<void>((resolve) => window.setTimeout(resolve, 0));
      const saved = await flushSave();
      const state = store.getState().presentationGeneration;
      if (!gate.current.mounted || gate.current.blocked || gate.current.presentationId !== presentationId ||
          state.isStreaming || state.isLoading || state.isLayoutLoading || state.presentationData?.id !== presentationId) return;
      const current = state.presentationData;
      const fresh = prepareNativeLayoutAdjustment(presentationId, current);
      if (!fresh.ok) { setPlan(fresh); return; }
      if (saved.id !== presentationId || current.slides !== plan.sourceSlides) {
        setPlan(fresh);
        notify.error("Review the updated layout", "The presentation changed. Review this preview and apply again.");
        return;
      }
      // Every page passed preflight before any Redux mutation occurs.
      dispatch(addToHistory({ slides: current.slides, actionType: "NATIVE_LAYOUT_BEFORE" }));
      batch(() => fresh.updates.forEach(({ index, ui }) => dispatch(updateSlideUi({ index, ui }))));
      dispatch(addToHistory({ slides: store.getState().presentationGeneration.presentationData!.slides, actionType: "NATIVE_LAYOUT_APPLIED" }));
      applied = true;
      await flushSave();
      if (!gate.current.mounted || gate.current.presentationId !== presentationId) return;
      notify.success("Native layout adjusted", "Layout changes were saved. You can undo this adjustment.");
      setPlan(null);
    } catch (error) {
      if (!gate.current.mounted || gate.current.presentationId !== presentationId) return;
      notify.error(applied ? "Layout save failed" : "Layout adjustment stopped", applied
        ? "Changes remain in this editor. Keep this page open and retry saving; you can also undo."
        : error instanceof Error ? error.message : "The current presentation could not be saved.");
    } finally {
      busyRef.current = false;
      if (gate.current.mounted) setBusy(false);
    }
  };

  return <Dialog open={!!plan && plan.presentationId === presentationId} onOpenChange={(open) => { if (!open && !busy) setPlan(null); }}>
    <DialogContent className="max-w-xl">
      <DialogHeader>
        <DialogTitle>{t("Adjust Native Editable layout")}</DialogTitle>
        <DialogDescription>{t("Review before applying. Only geometry, font size and spacing change. Text, table data, chart values, colors and emphasis are preserved.")}</DialogDescription>
      </DialogHeader>
      {plan?.ok ? <p className="text-sm">{plan.updates.length} / {plan.slideCount} {t("slides will be adjusted")}. {plan.changeCount} {t("layout properties")}</p> : null}
      {plan?.ok && !plan.updates.length ? <p className="text-sm">{t("This presentation already uses the current native layout.")}</p> : null}
      {!!plan?.warnings.length && <ul className="max-h-[40vh] list-disc overflow-auto pl-5 text-sm text-amber-800">{plan.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul>}
      <DialogFooter>
        <Button variant="outline" disabled={busy} onClick={() => setPlan(null)}>{t("Cancel")}</Button>
        <Button disabled={busy || blocked || !plan?.ok || !plan.updates.length} onClick={() => { void apply(); }}>{t(busy ? "Saving..." : "Apply and save")}</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>;
}
