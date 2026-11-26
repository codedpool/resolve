/** Helpers for approval payloads and the names of uploaded images. */

const NAMES_KEY = "evidence_names";

export function rememberEvidenceName(id, name) {
  try {
    const names = JSON.parse(sessionStorage.getItem(NAMES_KEY) || "{}");
    names[id] = name;
    sessionStorage.setItem(NAMES_KEY, JSON.stringify(names));
  } catch {
    // Names are a convenience. The card falls back to the file type and a short id.
  }
}

export function evidenceNames() {
  try {
    return JSON.parse(sessionStorage.getItem(NAMES_KEY) || "{}");
  } catch {
    return {};
  }
}

/** The server sends the payload as text. It is JSON for run approvals and a bare evidence id for image approvals. */
export function parsePayload(raw) {
  if (raw && typeof raw === "object") return raw;
  const text = String(raw || "").trim();
  if (text.startsWith("{")) {
    try {
      return JSON.parse(text);
    } catch {
      return {};
    }
  }
  return text ? { evidence_id: text } : {};
}

export function imageFor(approval, payload, evidence = [], names = {}) {
  const match =
    evidence.find((item) => item.vision_approval_id === approval.id) ||
    evidence.find((item) => item.id === payload.evidence_id);
  const id = match?.id || payload.evidence_id || "";
  const known = names[id] || payload.filename || payload.name;
  const label = known || (match ? `Your uploaded ${match.type} (${id.slice(0, 8)})` : id ? `Your uploaded file (${id.slice(0, 8)})` : "Your uploaded file");
  return { id, label };
}
