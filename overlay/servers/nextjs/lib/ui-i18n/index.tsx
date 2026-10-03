"use client";

// Added for the Lingzhiji fork, 2026-10-03. This preference is local UI state only.
import { useCallback, useEffect, useSyncExternalStore } from "react";
import { translateUiText, type UiLocale } from "./messages";

export const UI_LANGUAGE_STORAGE_KEY = "lingzhiji.ui-language";
export const DEFAULT_UI_LOCALE: UiLocale = "zh-CN";
let memoryLocale: UiLocale | null = null;
const listeners = new Set<() => void>();

export function getUiLocale(): UiLocale {
  if (typeof window === "undefined") return DEFAULT_UI_LOCALE;
  if (memoryLocale !== null) return memoryLocale;
  try {
    const stored = window.localStorage.getItem(UI_LANGUAGE_STORAGE_KEY);
    if (stored === "en" || stored === "zh-CN") memoryLocale = stored;
  } catch {
    // Private browsing and storage policies must not prevent using the app.
  }
  return memoryLocale ?? DEFAULT_UI_LOCALE;
}

export function setUiLocale(locale: UiLocale): void {
  if (locale !== "en" && locale !== "zh-CN") return;
  memoryLocale = locale;
  try { window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, locale); } catch { /* Session-only fallback. */ }
  if (typeof document !== "undefined") document.documentElement.lang = locale;
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  const onStorage = (event: StorageEvent) => {
    if (event.key === UI_LANGUAGE_STORAGE_KEY || event.key === null) {
      memoryLocale = event.newValue === "en" ? "en" : DEFAULT_UI_LOCALE;
      listener();
    }
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

export function useUiLocale(): UiLocale {
  return useSyncExternalStore(subscribe, getUiLocale, () => DEFAULT_UI_LOCALE);
}

export function useUiText() {
  const locale = useUiLocale();
  return useCallback((source: string) => translateUiText(source, locale), [locale]);
}

/** Use only for known UI messages, never generated slide/chat/user content. */
export function uiText(source: string): string {
  return translateUiText(source, getUiLocale());
}

export function UiText({ text }: { text: string }) {
  const t = useUiText();
  return <>{t(text)}</>;
}

export function UiLocaleDocument() {
  const locale = useUiLocale();
  useEffect(() => { document.documentElement.lang = locale; }, [locale]);
  return null;
}

export function UiLanguageControl({ compact = false }: { compact?: boolean }) {
  const locale = useUiLocale();
  const t = useUiText();
  return (
    <label className={`inline-flex ${compact ? "flex-col" : "flex-row"} items-center gap-1.5 text-xs text-slate-600`}>
      <span>{t("Interface language")}</span>
      <select
        aria-label={t("Interface language")}
        title={t("Only changes this browser’s interface. Presentation language and provider settings stay unchanged.")}
        value={locale}
        onChange={(event) => setUiLocale(event.target.value as UiLocale)}
        className="rounded-md border border-slate-200 bg-white px-2 py-1 text-xs text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
        data-testid="ui-language-select"
      >
        <option value="zh-CN">中文</option>
        <option value="en">EN</option>
      </select>
    </label>
  );
}
