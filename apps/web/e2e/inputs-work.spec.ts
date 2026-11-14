// The one list of work on Inputs (plan docs/plans/2026-11-14-inputs-task-first.md §2 rule 1, slice 2), as pure functions
// on what the API answered for the two seeded projects (e2e/fixtures/inputs-work/*.json: /inputs, /client-review,
// /delivery and the client files of `exampleamide`, nine messy files, and `clientamide`, the filled client-data template;
// captured 2026-11-14 with the stub engine, trimmed to the fields the model reads). No browser: the join, the alias
// question, blinding and the counts are checked on the data themselves. Software test data, never a model.
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

import { buildWork, nextText, normLabel, prefixAlias, type WorkSources } from "../lib/inputsWork";
import { checkLabel, placeText, stepReason } from "../lib/words";

const load = (name: string): WorkSources => JSON.parse(readFileSync(join(__dirname, "fixtures", "inputs-work", `${name}.json`), "utf8"));
const copy = <T,>(x: T): T => JSON.parse(JSON.stringify(x));

test("exampleamide: one card per study and product, joined on the API's groups or the exact label, never on a prefix", () => {
  const model = buildWork(load("exampleamide"));
  const cards = Object.fromEntries(model.subjects.map((s) => [s.key, s]));
  expect(model.subjects).toHaveLength(12);
  // the template subject: joined on `legacy_groups`, confirmed with the sheet form
  expect(cards["study:CL-01"].path).toBe("sheet-form");
  expect(cards["study:CL-01"].row?.legacy_groups).toEqual(["study:CL-01"]);
  // the exact normalised label: the delivery's 230-23 and the sheet form's "Study 230-23" are one card, signed on the delivery
  expect(cards["study:230-23"].path).toBe("delivery");
  expect(cards["study:230-23"].groups.map((g) => g.id)).toEqual(["study:230-23"]);
  expect(cards["product:Brand 10 mg"].groups.map((g) => g.id)).toEqual(["product:Brand 10 mg"]);
  // a name that only starts with a delivery study's stays its own card, and is asked about
  for (const alias of ["230-23-REF", "230-23-TEST"]) {
    expect(cards[`study:${alias}`].row).toBeNull();
    const asked = model.items.find((i) => i.id === `alias:study:${alias}`)!;
    expect(asked.label).toMatch(/^Same study as 230-23\? /);
    expect(asked.status).toBe("to_decide");
    expect(asked.where.tab).toBe("files");                                     // where its file's values are linked
    expect(asked.where.anchor).toMatch(/^delivery-unassigned-/);
    expect(model.items.some((i) => i.id.startsWith("link:") && i.files[0] === asked.files[0])).toBe(false);   // asked once
  }
  // the two delivery-only studies, and nothing merged across kinds or between two delivery subjects
  expect(cards["study:230-25"].groups).toHaveLength(0);
  const rows = model.subjects.filter((s) => s.row).map((s) => `${s.row!.subject_type}/${s.row!.subject}`);
  expect(new Set(rows).size).toBe(rows.length);
  for (const s of model.subjects) for (const g of s.groups) expect(g.kind).toBe(s.kind);
  // the sheets whose product is not stated are not cards: each asks for it
  expect(model.items.filter((i) => i.id.startsWith("draft:") && i.area === "formulations")).toHaveLength(4);
});

test("exampleamide: the counts agree everywhere, and Next is the first open item in the order the work is done", () => {
  const model = buildWork(load("exampleamide"));
  const open = model.items.filter((i) => i.open);
  expect(model.counts.open).toBe(open.length);
  expect(model.counts.missing + model.counts.to_confirm + model.counts.to_decide).toBe(model.counts.open);
  const areas = (["compound", "formulations", "studies", "individuals", "settings", "files"] as const).reduce((n, t) => n + model.byArea[t], 0);
  expect(areas).toBe(model.counts.open);
  expect(model.byArea.todo).toBe(model.counts.open);
  expect(model.counts.to_confirm).toBe(12);                                  // one per card
  expect(model.items.filter((i) => i.open && i.group === "layouts")).toHaveLength(10);
  expect(model.next).toBe(open[0]);
  expect(model.next!.group).toBe("ready");                                   // a quick win first: a card with nothing open
  expect(nextText(model)).toMatch(/^Next: Confirm (study|product) /);
  // a file's own work, on its row: the layouts, its values to link, its numbers not read, the facts its sheets lack
  const reference = model.items.find((i) => i.id === "alias:study:230-23-REF")!.files[0];
  expect(model.byFile[reference].map((i) => i.id.split(":")[0]).sort()).toEqual(["alias", "draft", "layout", "notread"]);
  // nothing is in the model while nothing is confirmed (the client's data are proposed)
  expect(model.inModel).toEqual({ studies: 0, formulations: 0, values: 0 });
  expect(model.counts.done).toBe(0);
});

test("clientamide: five sheet-form cards, and the delivery's clean-up blocks nothing", () => {
  const model = buildWork(load("clientamide"));
  expect(model.subjects.map((s) => s.path)).toEqual(Array(5).fill("sheet-form"));
  expect(model.subjects.every((s) => s.row && s.groups.length === 1)).toBe(true);   // joined on `legacy_groups`
  const tidy = model.items.filter((i) => i.group === "tidy");
  expect(tidy.filter((i) => i.id.startsWith("layout:"))).toHaveLength(5);
  expect(tidy.filter((i) => i.id.startsWith("notread:")).map((i) => i.weight).reduce((a, b) => a + b, 0)).toBe(45);
  expect(tidy.every((i) => !i.open)).toBe(true);
  expect(model.counts.to_confirm).toBe(5);
  expect(model.counts.to_decide).toBe(2);                                    // the EX-101 dose and n, asked once
  expect(model.items.filter((i) => i.issue).map((i) => i.issue!.issue)).toEqual(["study:EX-101|dose_mg", "study:EX-101|n"]);
  expect(model.next!.label).toBe("Study CL-1");
});

test("a blinded study is left out of Next and of the counts, and its row says why", () => {
  const sources = load("exampleamide");
  const before = buildWork(sources);
  const blinded = copy(sources);
  for (const s of blinded.delivery!.subjects) if (s.label === "230-25") s.blinded = true;
  const model = buildWork(blinded);
  const row = model.items.find((i) => i.id === "confirm:study:230-25")!;
  expect(row.open).toBe(false);
  expect(row.blocked).toMatch(/^Blinded/);
  expect(model.counts.to_confirm).toBe(before.counts.to_confirm - 1);
  expect(model.byArea.studies).toBe(before.byArea.studies - 1);
  expect(model.items.filter((i) => i.open).includes(row)).toBe(false);
});

test("the API's legacy_groups join wins over the label, and a confirmed card is done with who and when", () => {
  const sources = copy(load("exampleamide"));
  const row = sources.delivery!.subjects.find((s) => s.label === "230-25")!;
  row.legacy_groups = ["study:Nichols2012-IV"];
  const nichols = sources.review!.groups.find((g) => g.id === "study:Nichols2012-IV")!;
  nichols.state = "confirmed";
  nichols.confirmed_by = "dev-user";
  nichols.confirmed_at = "2026-11-14T18:15:00Z";
  const model = buildWork(sources);
  const card = model.subjects.find((s) => s.row?.label === "230-25")!;
  expect(card.groups.map((g) => g.id)).toEqual(["study:Nichols2012-IV"]);
  expect(card.aliases).toEqual(["Nichols2012-IV"]);
  expect(model.subjects.filter((s) => s.groups.some((g) => g.id === "study:Nichols2012-IV"))).toHaveLength(1);
  // 230-25 is signed on the delivery: the sheet form's confirmation does not make it done
  const confirm = model.items.find((i) => i.id === `confirm:${card.key}`)!;
  expect(confirm.label).toBe("Study 230-25");
  expect(confirm.status).toBe("to_confirm");
  const confirmed = copy(load("clientamide"));
  const cl1 = confirmed.review!.groups.find((g) => g.id === "study:CL-1")!;
  Object.assign(cl1, { state: "confirmed", confirmed_by: "dev-user", confirmed_at: "2026-11-14T18:15:00Z" });
  const done = buildWork(confirmed).items.find((i) => i.id === "confirm:study:CL-1")!;
  expect(done.status).toBe("done");
  expect(done.inModel).toBe("Confirmed by dev-user on 14 Nov 2026, 18:15; in the model.");
});

test("the words: a prefix is a prefix, the checks and the step bar in plain words, places as a person reads them", () => {
  const rows = load("exampleamide").delivery!.subjects;
  expect(prefixAlias("230-23-REF", rows)?.label).toBe("230-23");
  expect(prefixAlias("230-23", rows)).toBeNull();
  expect(prefixAlias("230-235", rows)).toBeNull();                           // 230-23 then a digit is another study
  expect(normLabel("Study  230-23")).toBe("230-23");
  expect(checkLabel("S0 completeness (MS-01 §2.2)", ["phys.mw", "bind.fu"], false)).toBe("Minimum compound data (2 missing)");
  expect(checkLabel("every planned simulation builds (software)")).toBe("All planned simulations build");
  expect(stepReason("S0 completeness (MS-01 §2.2)")).toBe("compound values missing");
  expect(stepReason("The inputs changed since they were last checked: check them again")).toMatch(/^The inputs changed/);
  expect(placeText("s:'Sheet1'!A4:M12")).toBe("Sheet1 · A4:M12");
  expect(placeText("p:3/w:34-42@56.00")).toBe("page 3");
});
