// The decision pop-up asks for an open escalation on its campaign's own project pages and shows a count on every other
// page (decision 1 of 2026-11-11), so an escalation a spec leaves open would ask over, or count on, the pages of the
// specs after it. A spec that opens one closes it here
// when it is done: its rows are taken out of the API's read root, the way the specs seed them (software test data).
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

type Row = { id: string; campaignId: string };

/** Take the open escalations `which` picks (all of them by default) out of the DEV tenant's read root. */
export function dropEscalations(which: (row: Row) => boolean = () => true) {
  const file = join(process.env.E2E_DATA_DIR!, "read-root", "dev", "escalations.json");
  if (!existsSync(file)) return;
  const rows = (JSON.parse(readFileSync(file, "utf-8")).escalations ?? []) as Row[];
  writeFileSync(file, JSON.stringify({ escalations: rows.filter((r) => !which(r)) }));
}

/** Add (or replace, by id) one row of the DEV tenant's read root: `campaigns.json` or `escalations.json`. */
export function seedReadRoot(name: "campaigns" | "escalations", row: Record<string, unknown> & { id: string }) {
  const dir = join(process.env.E2E_DATA_DIR!, "read-root", "dev");
  mkdirSync(dir, { recursive: true });
  const file = join(dir, `${name}.json`);
  let rows: Record<string, unknown>[] = [];
  try { rows = JSON.parse(readFileSync(file, "utf-8"))[name] ?? []; } catch { /* first row */ }
  writeFileSync(file, JSON.stringify({ [name]: [...rows.filter((r) => r.id !== row.id), row] }));
}
