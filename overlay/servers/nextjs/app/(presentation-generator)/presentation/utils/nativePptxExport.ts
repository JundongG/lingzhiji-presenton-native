// Native PPTX beta add-on (2026-10-03). SPDX-License-Identifier: Apache-2.0
import type { PresentationData } from "@/store/slices/presentationGeneration";
import { getApiUrl, resolveBackendAssetUrl } from "@/utils/api";

export const NATIVE_PPTX_CONTENT_TYPE =
  "application/vnd.openxmlformats-officedocument.presentationml.presentation";

export const canExportNativePptx = (data: PresentationData | null | undefined) =>
  !!data && data.version === "v2-standard" &&
  data.generation_mode !== "smart" && data.type !== "smart" &&
  data.slides.length > 0 &&
  data.slides.every((slide: { ui?: unknown }) => !!slide.ui && typeof slide.ui === "object" && !Array.isArray(slide.ui));

/** Save failure must stop the download: never silently export an older deck. */
export async function saveAndRequestNativePptx({
  presentationId, commitEditor, flushSave, request = fetch, delivery = "bytes",
}: {
  presentationId: string;
  commitEditor: () => void | Promise<void>;
  flushSave: () => Promise<PresentationData>;
  request?: typeof fetch;
  delivery?: "bytes" | "file";
}): Promise<
  { delivery: "bytes"; blob: Blob; title: string; warnings: string[] } |
  { delivery: "file"; url: string; fileName: string; expiresAt: number; title: string; warnings: string[] }
> {
  await commitEditor();
  const saved = await flushSave();
  if (saved.id !== presentationId || !canExportNativePptx(saved)) {
    throw new Error("Native PPTX (beta) requires saved Standard canvas slides.");
  }
  const response = await request(
    getApiUrl(`/api/v1/ppt/presentation/${encodeURIComponent(presentationId)}/export/native-pptx`),
    { method: "POST", credentials: "include", cache: "no-store",
      ...(delivery === "file" ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify({ delivery: "file" }) } : {}),
    },
  );
  if (!response.ok) {
    let detail = `Native PPTX export failed (${response.status}).`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch { /* A non-JSON gateway error still gets a useful status. */ }
    throw new Error(detail);
  }
  if (delivery === "file") {
    const body: unknown = await response.json();
    const file = body as { url?: unknown; file_name?: unknown; expires_at?: unknown; warnings?: unknown };
    if (!file || typeof file.url !== "string" ||
        !/^\/app_data\/exports\/users\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\/native-pptx\/[0-9a-f]{32}\.pptx$/.test(file.url) ||
        typeof file.file_name !== "string" || /[\r\n/\\]/.test(file.file_name) || !file.file_name.endsWith(".pptx") ||
        typeof file.expires_at !== "number" || !Number.isFinite(file.expires_at)) {
      throw new Error("Native export returned an invalid private download link.");
    }
    const warnings = Array.isArray(file.warnings) ? file.warnings.map((warning) =>
      typeof warning === "string" ? warning : JSON.stringify(warning)) : [];
    return { delivery: "file", url: resolveBackendAssetUrl(file.url), fileName: file.file_name,
      expiresAt: file.expires_at, title: saved.title || "Presentation", warnings };
  }
  if (!response.headers.get("content-type")?.includes(NATIVE_PPTX_CONTENT_TYPE)) {
    throw new Error("Native PPTX export did not return a PowerPoint file.");
  }
  let warnings: string[] = [];
  try {
    const parsed: unknown = JSON.parse(response.headers.get("x-native-pptx-warnings") || "[]");
    if (Array.isArray(parsed)) warnings = parsed.map((warning) =>
      typeof warning === "string" ? warning : JSON.stringify(warning));
  } catch { /* Invalid advisory headers must not corrupt the file. */ }
  const omitted = Number(response.headers.get("x-native-pptx-warnings-truncated") || "0");
  if (Number.isSafeInteger(omitted) && omitted > 0) {
    warnings.push(`${omitted} additional export warnings could not fit in the download response. Review the file before use.`);
  }
  return { delivery: "bytes", blob: await response.blob(), title: saved.title || "Presentation", warnings };
}
