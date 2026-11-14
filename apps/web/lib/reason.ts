// An escalation's reason as a person reads it (the 2026-11-11 audit, item 5). The runner stores the reason as a code in
// capitals ("ROUNDS_EXHAUSTED"); the escalation dialog and the dashboard show it as a sentence, through one helper, so
// both say the same thing. The code itself stays in the record.

import { plain } from "@/lib/plain";

/** `ROUNDS_EXHAUSTED` → `Rounds exhausted`. */
export function reasonSentence(code: string): string {
  const words = code.replace(/_/g, " ").replace(/\s{2,}/g, " ").trim().toLowerCase();
  return plain(words.charAt(0).toUpperCase() + words.slice(1));
}
