// Native canvas diagnostics add-on (2026-10-03). SPDX-License-Identifier: Apache-2.0
// Pure local serialization: no fetch, persistence, credentials, or other state access.

const OMIT_KEYS = new Set([
  "owner", "ownerid", "userid", "accountid", "presentationid", "slideid",
  "filepath", "filepaths", "filename", "config", "configuration", "instructions",
  "instruction", "systemprompt", "prompt", "password", "passwd", "secret",
  "token", "accesstoken", "refreshtoken", "idtoken", "apikey", "authorization",
  "cookie", "cookies", "credential", "credentials", "session", "sessionid",
  "privatekey", "signingkey", "encryptionkey", "sshkey", "clientsecret",
]);
const MAX_NODES = 100_000;
const MAX_JSON_LENGTH = 5 * 1024 * 1024;
const normalizedKey = (key: string) => key.replace(/[^a-z0-9]/gi, "").toLowerCase();
const isRecord = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === "object" && !Array.isArray(value);

const ASSET_KEYS = new Set(["data", "src", "url", "href", "backgroundimage", "imageurl", "asseturl"]);
function safeAssetReference(value: string): string {
  // Resource paths may contain owner IDs or signed credentials. Keep ordinary
  // text runs verbatim: only recognized asset slots receive this redaction.
  if (/^(?:file:|data:|blob:|[A-Za-z]:[\\/])/i.test(value) || (value.startsWith("/") && !value.startsWith("/static/")) || /[?#]/.test(value)) {
    return "[redacted private asset reference]";
  }
  if (/^(?:https?:)?\/\//i.test(value)) return "[redacted external asset reference]";
  return value;
}

/** Only this loaded presentation's canvas content may enter the visible dialog. */
export function serializeNativeCanvasDiagnostics(presentationId: string, data: unknown): string {
  if (!presentationId || !isRecord(data) || data.id !== presentationId) {
    throw new Error("Diagnostics require the currently loaded presentation.");
  }
  if (data.version !== "v2-standard" || data.type === "smart" || data.generation_mode === "smart") {
    throw new Error("Native canvas diagnostics require a Standard canvas presentation.");
  }
  if (!Array.isArray(data.slides) || data.slides.length === 0) {
    throw new Error("No loaded canvas slides are available for diagnostics.");
  }
  let nodes = 0;
  const ancestors = new Set<object>();
  const sanitize = (value: unknown, depth = 0, assetSlot = false): unknown => {
    if (++nodes > MAX_NODES || depth > 64) throw new Error("Canvas diagnostics exceed the safe size limit.");
    if (typeof value === "string") return assetSlot ? safeAssetReference(value) : value;
    if (value === null || typeof value === "boolean") return value;
    if (typeof value === "number") return Number.isFinite(value) ? value : null;
    if (typeof value !== "object") return null;
    if (ancestors.has(value)) throw new Error("Canvas diagnostics contain a circular value.");
    ancestors.add(value);
    try {
      if (Array.isArray(value)) return value.map((item) => sanitize(item, depth + 1));
      const result: Record<string, unknown> = Object.create(null);
      for (const [key, child] of Object.entries(value)) {
        const normalized = normalizedKey(key);
        if (OMIT_KEYS.has(normalized) || /(?:password|secret|credential|token|apikey|authorization|cookie|privatekey|signingkey|encryptionkey|sshkey)/.test(normalized)) continue;
        if (key === "__proto__" || key === "constructor" || key === "prototype") continue;
        result[key] = sanitize(child, depth + 1, ASSET_KEYS.has(normalized));
      }
      return result;
    } finally { ancestors.delete(value); }
  };
  const diagnostic = {
    schema_version: "presenton.native-canvas-diagnostics.v1",
    title: typeof data.title === "string" ? data.title : "Presentation",
    theme: sanitize(data.theme ?? null),
    slides: data.slides.map((slide, index) => {
      if (!isRecord(slide) || !isRecord(slide.ui)) throw new Error(`Slide ${index + 1} has no loaded canvas UI.`);
      return { index: Number.isInteger(slide.index) ? slide.index : index, ui: sanitize(slide.ui) };
    }),
  };
  const json = JSON.stringify(diagnostic, null, 2);
  if (json.length > MAX_JSON_LENGTH) throw new Error("Canvas diagnostics exceed the safe size limit.");
  return json;
}
