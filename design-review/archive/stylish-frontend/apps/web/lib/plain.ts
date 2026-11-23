// What a person reads, without the project's internal references (the 2026-11-11 audit, item 6). Decision numbers
// ("D-29") and plan sections ("plan §9.4") stay in the record and the documents; on screen they only get in the way.
// The standards a person signs against (MS-01, ICH M15) and every UNVERIFIED mark are kept.

const REFS = /\s*\((?:(?:D-\d+|plan §[\d.]+|§[\d.]+)(?:,\s*)?)+(?:,?\s*ICH M15 §[\d.]+)?\)/g;

/** `demographics stated (D-29)` → `demographics stated`. */
export function plain(text: string): string {
  return text.replace(REFS, "").replace(/\s{2,}/g, " ").trim();
}
