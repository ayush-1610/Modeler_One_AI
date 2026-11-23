// The decision pop-up asks for every open escalation on every page (the review inbox is gone, 2026-11-11), so an
// escalation a spec leaves open would sit over the pages of the specs after it. A spec that opens one closes it here
// when it is done: its rows are taken out of the API's read root, the way the specs seed them (software test data).
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

type Row = { id: string; campaignId: string };

/** Take the open escalations `which` picks (all of them by default) out of the DEV tenant's read root. */
export function dropEscalations(which: (row: Row) => boolean = () => true) {
  const file = join(process.env.E2E_DATA_DIR!, "read-root", "dev", "escalations.json");
  if (!existsSync(file)) return;
  const rows = (JSON.parse(readFileSync(file, "utf-8")).escalations ?? []) as Row[];
  writeFileSync(file, JSON.stringify({ escalations: rows.filter((r) => !which(r)) }));
}
