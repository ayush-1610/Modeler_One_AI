// The one list of work on Inputs (plan docs/plans/2026-11-14-inputs-task-first.md §2 rule 1, slice 2), as pure functions
// on what the API answered for the two seeded projects (e2e/fixtures/inputs-work/*.json: /inputs, /client-review,
// /delivery, the client files and, for exampleamide, the cards of its subjects signed on the delivery; `exampleamide`,
// nine messy files, and `clientamide`, the filled client-data template; captured 2026-11-14 with the stub engine, trimmed
// to the fields the model reads). No browser: the join, the alias
// question, blinding and the counts are checked on the data themselves. Software test data, never a model.
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

import {
  NEW, NO_TARGET, areaHead, assignBody, buildWork, collisions, columnSummary, destinationKey, heldBy, layoutRows, linkRows, looseGroups, nextText,
  normLabel, notReadRows, onDelivery, prefixAlias, targetProblem, type WorkSources,
} from "../lib/inputsWork";
import { checkLabel, placeText, stepReason } from "../lib/words";

const load = (name: string): WorkSources => JSON.parse(readFileSync(join(__dirname, "fixtures", "inputs-work", `${name}.json`), "utf8"));
const copy = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
/** exampleamide with the delivery's values, tables and notes as the API answers them (`exampleamide-batch.json`: the
 *  seed's /delivery trimmed to what To do's batch tables read, its files named by this fixture's ids). */
function batch(): WorkSources {
  const sources = load("exampleamide");
  const more = JSON.parse(readFileSync(join(__dirname, "fixtures", "inputs-work", "exampleamide-batch.json"), "utf8"));
  const page = sources.delivery!;
  page.unassigned = more.unassigned;
  for (const f of page.deliveries.flatMap((d) => d.files)) Object.assign(f, more.files.find((x: { sha256: string }) => x.sha256 === f.sha256));
  for (const s of page.subjects) Object.assign(s, more.subjects.find((x: { subject: string }) => x.subject === s.subject));
  page.analytes = more.analytes;
  return sources;
}

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
    expect(asked.where.tab).toBe("todo");                                      // asked on its file's row of the link table
    expect(asked.area).toBe("files");                                          // and counted with the file's work
    expect(asked.where.anchor).toMatch(/^link-fl-/);
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
  // Client files counts what is settled there: its layouts, links (the two "Same study?" among them), numbers not read
  expect(model.byArea.files).toBe(model.items.filter((i) => i.open && /^(layout|link|alias|notread):/.test(i.id)).length);
  expect(areaHead(model, "files", 9)).toBe(`9 files · ${model.byArea.files} to decide`);
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
  // what its card holds is withheld with it: neither read nor counted
  const own = before.items.filter((i) => i.open && i.area === "studies" && i.subjects.includes("study:230-25"));
  expect(own.map((i) => i.id).sort()).toEqual(["confirm:study:230-25", "fact:study:230-25", "need:study:230-25:REQ-sys.demographics"]);
  expect(model.byArea.studies).toBe(before.byArea.studies - own.length);
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
  // 230-25 is signed on the delivery, or confirmed with the sheet form: whichever comes first is what loads (plan
  // §2.2.1), so the sheet form's confirmation makes it done, and its card is not counted any more
  const confirm = model.items.find((i) => i.id === `confirm:${card.key}`)!;
  expect(confirm.label).toBe("Study 230-25");
  expect(confirm.status).toBe("done");
  expect(confirm.inModel).toBe("Confirmed by dev-user on 14 Nov 2026, 18:15; in the model.");
  expect(model.items.filter((i) => i.open && i.subjects.includes(card.key))).toHaveLength(0);
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
  expect(placeText("s:'Sheet1'!A4:M12")).toBe("sheet Sheet1, cells A4 to M12");
  expect(placeText("p:3/w:34-42@56.00")).toBe("page 3");
});

test("what holds up a card signed on the delivery is counted: its facts, required items and failed checks, once each", () => {
  const model = buildWork(load("exampleamide"));
  expect(model.checking).toBe(0);
  const row = (id: string) => model.items.find((i) => i.id === id)!;
  // 230-23: the facts no file states on one row (the route as a gap and as a check, once), the demographics no one settled,
  // the values above the range; the layout its urine table waits for is counted once, with the layouts
  expect(row("fact:study:230-23").label).toBe("Study 230-23 · not stated: the route, the number of subjects, what the study is for");
  expect(row("fact:study:230-23").status).toBe("missing");
  // it opens on the study's card, in Clinical studies (slice 3)
  expect(row("fact:study:230-23").where).toEqual({ tab: "studies", anchor: "delivery-gap-route", subject: "study/st-8" });
  expect(row("confirm:study:230-23").where).toEqual({ tab: "studies", anchor: "study-card-study:230-23", subject: "study/st-8" });
  expect(row("need:study:230-23:REQ-sys.demographics").label).toMatch(/^Study 230-23 · not in the files: Demographics of every study/);
  expect(row("check:study:230-23:ck-965b759af642").status).toBe("to_decide");
  expect(model.items.some((i) => i.id.startsWith("check:") && /mapping/.test(i.label))).toBe(false);
  // 230-25: the dose as DOSE_MISSING and as the record's need, once; the product's dissolution method, to decide
  expect(row("fact:study:230-25").label).toBe("Study 230-25 · not stated: the route, the dose, what the study is for, the number of subjects");
  expect(model.items.filter((i) => i.id.startsWith("check:product:Exampleamide IR tablet:")).map((i) => i.label))
    .toEqual(["Product Exampleamide IR tablet: batch L2301, medium phosphate buffer, ph 6.8: no apparatus stated",
              "Product Exampleamide IR tablet: batch L2301, medium HCl buffer, ph 1.2: no apparatus stated"]);
  // each counts in its subject's area, and every count still agrees
  expect(model.counts.missing + model.counts.to_confirm + model.counts.to_decide).toBe(model.counts.open);
  const areas = (["compound", "formulations", "studies", "individuals", "settings", "files"] as const).reduce((n, t) => n + model.byArea[t], 0);
  expect(areas).toBe(model.counts.open);
  expect(areaHead(model, "studies")).toBe("8 studies · 13 missing · 8 to confirm · 1 to decide");
  expect(onDelivery(model, "studies").map((x) => `${x.subject.label} ${x.open.length}`)).toEqual(["230-23 3", "231-24 3", "230-25 2", "230-26 3"]);
  // the confirm row says what holds it, in the order it is done; the clean-up is said once, as the gate
  const confirm = row("confirm:study:230-23");
  expect(confirm.detail).toContain("first 3 items on its card (2 missing · 1 to decide) and the delivery clean-up; then the spot check and the signature");
  expect(confirm.detail).toContain("or confirm it with the sheet form on Clinical studies (1 thing first): whichever is confirmed first is what loads");
  expect(confirm.gate).toBe("10 table layouts to check · 6 files to link · 8 files with numbers not read");
  // the facts its sheet does not say are not asked a second time: the delivery's facts row asks for them once, and the
  // sheet form asks them inside its own path when the person chooses it (slice 3, after its review)
  expect(model.items.some((i) => i.id.startsWith("draft:") && i.subjects.includes("study:230-23"))).toBe(false);
  // a card not read yet: its row says it is being checked, and only what is known is counted
  const sources = load("exampleamide");
  delete sources.cards!["study/st-11"];
  const partial = buildWork(sources);
  expect(partial.checking).toBe(1);
  expect(partial.items.find((i) => i.id === "confirm:study:231-24")!.detail).toContain("checking what holds it…");
  expect(partial.items.some((i) => i.id.startsWith("fact:study:231-24"))).toBe(false);
  // "once the delivery is cleaned up" only where the clean-up is all that holds it
  const clean = load("exampleamide");
  Object.assign(clean.cards!["product/pr-14"]!, { requirements: [], checks: [], spot_check: { state: "complete" } });
  expect(buildWork(clean).items.find((i) => i.id === "confirm:product:Comparamide tablet")!.detail)
    .toBe("from messy-delivery.xlsx · first the delivery clean-up; then the signature");
});

test("two versions of one layout are two rows; the clean-up says why it is not counted when nothing it holds can be signed", () => {
  const model = buildWork(load("exampleamide"));
  const versions = model.items.filter((i) => i.id.startsWith("layout:mp-caadd2de9d39@"));
  expect(versions.map((i) => [i.id, i.where.anchor])).toEqual([
    ["layout:mp-caadd2de9d39@1", "todo-layout-mp-caadd2de9d39"], ["layout:mp-caadd2de9d39@2", "todo-layout-mp-caadd2de9d39-v2"]]);
  // the products signed and loaded, every study signed on the delivery blinded: the clean-up stays in its groups, not
  // counted, and says why (it counts again once the plan is signed)
  const landed = { current: true, landed: { at: "2026-11-14T18:15:00Z" } } as never;
  const blinded = load("exampleamide");
  for (const s of blinded.delivery!.subjects.filter((x) => x.confirm_on === "delivery")) {
    if (s.subject_type === "study") s.blinded = true;
    else s.confirmation = landed;
  }
  const held = buildWork(blinded);
  const layout = held.items.find((i) => i.id === "layout:mp-9c55440c25bd@1")!;
  expect(layout.group).toBe("layouts");
  expect(layout.open).toBe(false);
  expect(layout.why).toBe("It holds up only blinded studies (230-23, 231-24, 230-25, 230-26): it counts once the plan is signed and the study can be confirmed.");
  expect(held.items.filter((i) => i.group === "tidy")).toHaveLength(0);
  expect(held.items.filter((i) => i.open && i.area === "files")).toHaveLength(0);
  // every one signed and loaded: the clean-up is for the delivery record, and says so
  const signed = load("exampleamide");
  for (const s of signed.delivery!.subjects) if (s.confirm_on === "delivery") s.confirmation = landed;
  const done = buildWork(signed);
  const tidy = done.items.find((i) => i.id === "layout:mp-9c55440c25bd@1")!;
  expect(tidy.group).toBe("tidy");
  expect(tidy.why).toBe("Every study and product it held up is confirmed.");
  // a delivery whose subjects are all confirmed with the sheet form (the template project)
  const template = buildWork(load("clientamide")).items.find((i) => i.group === "tidy")!;
  expect(template.why).toBe("Its studies and products are confirmed with the sheet form: it holds up nothing.");
});

test("the link table: one row per file, suggested from its own labels, the alias asked first, arms that keep two files apart", () => {
  const sources = batch();
  const model = buildWork(sources);
  const items = model.items.filter((i) => /^(link|alias):/.test(i.id));
  const rows = linkRows(items, sources.delivery, model.subjects);
  // the 366 values of 6 files: one row each (not one form per table and its facts)
  expect(rows.map((r) => r.item.id)).toEqual(items.map((i) => i.id));
  expect(rows.reduce((n, r) => n + r.values.length, 0)).toBe(366);
  expect(rows).toHaveLength(6);
  const row = (name: string) => rows.find((r) => r.file === name)!;
  const reference = row("230-23 Fasting Reference.xlsx"), test230 = row("230-23 Fasting Test.xlsx");
  expect(reference.holds).toBe("individual PK table, 76 values · dose 50 mg · fasted · LLOQ 0.5 ng/mL");
  expect(reference.item.where).toEqual({ tab: "todo", anchor: `link-${reference.fileId}` });
  // "Same study as 230-23?": nothing filled until answered; Yes fills 230-23 and an arm that keeps the two files apart
  expect(reference.suggested).toBeNull();
  expect(reference.alias!.study.label).toBe("230-23");
  expect(reference.alias!.target).toMatchObject({ study: "st-8", arm: NEW, newArm: "Reference" });
  expect(test230.alias!.target).toMatchObject({ study: "st-8", arm: NEW, newArm: "Test" });
  expect(reference.pairs).toContain("001 · I");
  // the two files in one arm of one study collide on their subjects and periods; each in its own arm, they do not
  const studies = sources.delivery!.subjects;
  const same = { ...NO_TARGET, study: "st-8" };
  expect(collisions([{ row: reference, target: same }, { row: test230, target: same }], studies)).toEqual([
    { files: ["230-23 Fasting Reference.xlsx", "230-23 Fasting Test.xlsx"], study: "230-23", example: "subject 001, period I",
      keys: [reference.sha, test230.sha] }]);
  expect(collisions([{ row: reference, target: reference.alias!.target }, { row: test230, target: test230.alias!.target }], studies)).toEqual([]);
  // and against what the study already holds in that arm (its card, when read)
  expect(collisions([{ row: reference, target: same }], studies, { "st-8": [{ arm: "", analyte: "", pair: "001 · I" }] })[0].files)
    .toEqual(["230-23 Fasting Reference.xlsx"]);
  // each file naming its analyte, read as an entity of its own (an-1, an-2: one per file, both "Exampleamide"): the same
  // analyte by name, so the two still collide; and against what the study holds of that analyte, by name too
  const named = (r: typeof reference, id: string) => ({ ...r, own: { ...r.own, analyte: { id, label: "Exampleamide" } } });
  const analytes = [{ id: "an-1", label: "Exampleamide" }, { id: "an-2", label: "Exampleamide" }];
  expect(collisions([{ row: named(reference, "an-1"), target: same }, { row: named(test230, "an-2"), target: same }], studies, {}, analytes))
    .toHaveLength(1);
  expect(collisions([{ row: named(reference, "an-1"), target: { ...same, analyte: "an-2" } }, { row: named(test230, "an-2"), target: same }],
                    studies, {}, analytes)).toHaveLength(1);
  expect(collisions([{ row: named(reference, "an-1"), target: same }], studies, { "st-8": [{ arm: "", analyte: "exampleamide", pair: "001 · I" }] }))
    .toHaveLength(1);
  // a dissolution file's values go to a product, with the batch the file names
  const rld = row("Dissolution RLD pH 6.8.xlsx");
  expect(rld.goesTo).toBe("product");
  expect(rld.own.batch).toEqual({ id: "ba-1", label: "B5.501" });
  // what is sent: one call per destination, every value of the file in it
  expect(targetProblem(NO_TARGET)).toBe("Pick a study or a product");
  expect(targetProblem({ ...NO_TARGET, study: NEW })).toBe("Name the new study");
  const body = assignBody(reference.alias!.target, reference.values.map((v) => v.id), "the file names say 230-23");
  expect(body).toMatchObject({ study: "st-8", new_arm: "Reference", why: "the file names say 230-23" });
  expect(body.targets).toHaveLength(79);
  expect(destinationKey(reference.alias!.target)).not.toBe(destinationKey(test230.alias!.target));
  expect(destinationKey({ ...NO_TARGET, study: NEW, newStudy: "ABC-9" })).toBe(destinationKey({ ...NO_TARGET, study: NEW, newStudy: " abc-9 " }));
});

test("a workbook with one sheet per study: each table its own part, its own suggestion and its own arm check", () => {
  const sources = batch();
  const page = sources.delivery!;
  const files = page.deliveries.flatMap((d) => d.files);
  const ref = files.find((f) => f.name === "230-23 Fasting Reference.xlsx")!;
  // the Reference file's values read again as a two-sheet workbook: Sheet1 titled "Study 230-23", Sheet2 "Study 777-01"
  // (a study no file names yet), the same subjects and periods on both
  const sha = "f".repeat(64);
  const own = page.unassigned.filter((v) => v.file_sha256 === ref.sha256);
  // where each value was read, as the API anchors it (the trimmed fixture leaves the anchors out): the table's cells, the
  // facts on the same sheet
  for (const v of own) v.anchor = `${ref.sha256}@workbook/1.0#s:'Sheet1'!${v.id.includes("#") ? "C5" : "A1"}`;
  const sheet2 = (x: string | null) => x?.replace(/'Sheet1'/g, "'Sheet2'") ?? x;
  const values = [
    ...own.map((v) => ({ ...v, id: v.id.replace(/^tx-[0-9a-f]+/, "tx-aaaa").replace(/^f-/, "f-a"), file_sha256: sha, file: "two-studies.xlsx" })),
    ...own.map((v) => ({ ...v, id: v.id.replace(/^tx-[0-9a-f]+/, "tx-bbbb").replace(/^f-/, "f-b"), file_sha256: sha, file: "two-studies.xlsx",
                         anchor: sheet2(v.anchor) })),
  ];
  const region = ref.regions[0];
  page.deliveries[0].files.push({ ...ref, sha256: sha, file_id: "fl-ffffffffffff", name: "two-studies.xlsx", legacy_sid: null,
    regions: [{ ...region, region_id: "rg-a" }, { ...region, region_id: "rg-b", where: region.where.replace("Sheet1", "Sheet2") }],
    outside: [{ where: "s:'Sheet1'!A1", text: "Study 230-23: plasma concentrations, Reference, 50 mg, fasting", region: "rg-a", counted: false, decision: null, restored: null },
              { where: "s:'Sheet2'!A1", text: "Study 777-01: plasma concentrations, Reference, 50 mg, fasting", region: "rg-b", counted: false, decision: null, restored: null }] });
  page.unassigned.push(...values);
  const model = buildWork(sources);
  const rows = linkRows(model.items.filter((i) => /^(link|alias):/.test(i.id)), page, model.subjects);
  const two = rows.find((r) => r.file === "two-studies.xlsx")!;
  // two parts, each table with the facts read on its sheet; the titles point to different places, so it starts split
  expect(two.parts.map((p) => p.label)).toEqual(["individual PK table, 76 values · sheet Sheet1 · 3 facts", "individual PK table, 76 values · sheet Sheet2 · 3 facts"]);
  expect(two.parts.map((p) => p.values.length)).toEqual([79, 79]);
  expect(two.split).toBe(true);
  expect(two.suggested).toBeNull();
  expect(two.parts[0].suggested).toMatchObject({ why: "its title names study 230-23", target: { study: "st-8" } });
  expect(two.parts[1].suggested).toBeNull();                       // 777-01 is no study yet: never made up
  // a one-table file is one part, its facts with it, and not split
  const reference = rows.find((r) => r.file === "230-23 Fasting Reference.xlsx")!;
  expect(reference.parts.map((p) => p.label)).toEqual(["individual PK table, 76 values · sheet Sheet1 · 3 facts"]);
  expect(reference.split).toBe(false);
  // each part is checked on its own: Sheet1's table into 230-23 beside the Reference file's subjects, not beside its own sheet
  const studies = page.subjects;
  const to = { ...NO_TARGET, study: "st-8" };
  expect(collisions([{ row: two.parts[0], target: to }], studies, { "st-8": [{ arm: "", analyte: "", pair: "001 · I", sha: ref.sha256 }] })[0])
    .toMatchObject({ files: ["two-studies.xlsx, its individual PK table on sheet Sheet1"], keys: [`${sha}#tx-aaaa`] });
  expect(collisions([{ row: two.parts[0], target: to }, { row: two.parts[1], target: to }], studies)).toEqual([]);   // one file's tables
  expect(collisions([{ row: two.parts[0], target: to }], studies, { "st-8": [{ arm: "", analyte: "", pair: "001 · I", sha }] })).toEqual([]);
  expect(heldBy({ tables: [{ file_sha256: ref.sha256, values: own.slice(0, 1) }] })).toEqual([{ arm: "", analyte: "", pair: "001 · I", sha: ref.sha256 }]);
});

test("the second file of a pair is told apart from the first one, already linked; a delivery whose files name no study stays in view", () => {
  // the Reference file linked to 230-23 in a new arm "Reference": the Test file's Yes fills "Test", not the sheet form's "TEST"
  const sources = batch();
  const page = sources.delivery!;
  const ref = page.deliveries.flatMap((d) => d.files).find((f) => f.name === "230-23 Fasting Reference.xlsx")!;
  page.unassigned = page.unassigned.filter((v) => v.file_sha256 !== ref.sha256);
  const st8 = page.subjects.find((s) => s.subject === "st-8")!;
  st8.files.push(ref.sha256);
  st8.arms.push({ id: "arm-21", label: "Reference" });
  let model = buildWork(sources);
  const test230 = linkRows(model.items.filter((i) => /^(link|alias):/.test(i.id)), page, model.subjects).find((r) => r.file === "230-23 Fasting Test.xlsx")!;
  expect(test230.alias!.target).toMatchObject({ study: "st-8", arm: NEW, newArm: "Test" });

  // a delivery of its own whose files name no study yet: its link row is in the link group, shown, not counted, with why
  const alone = batch();
  const tst = alone.delivery!.deliveries.flatMap((d) => d.files).find((f) => f.name === "230-23 Fasting Test.xlsx")!;
  alone.delivery!.deliveries.push({ ...alone.delivery!.deliveries[0], id: "dl-2", files: [{ ...tst, delivery: "dl-2" }] });
  alone.delivery!.deliveries[0].files = alone.delivery!.deliveries[0].files.filter((f) => f !== tst);
  for (const v of alone.delivery!.unassigned.filter((x) => x.file_sha256 === tst.sha256)) v.delivery = "dl-2";
  model = buildWork(alone);
  const item = model.items.find((i) => i.ref === tst.sha256 && /^(link|alias):/.test(i.id))!;
  expect([item.group, item.open, item.why]).toEqual(["link", false,
    "Its files name no study or product yet: it holds up nothing until their values are linked to one."]);
  const fileId = item.files[0];
  expect(model.fileWork[fileId].map((i) => i.id)).toContain(item.id);
  expect((model.byFile[fileId] ?? []).map((i) => i.id)).not.toContain(item.id);
});

test("numbers not read: loose numbers alike said once, by file; the layouts' queue with its not-data readings", () => {
  const sources = batch();
  const model = buildWork(sources);
  const rows = notReadRows(model.items.filter((i) => i.id.startsWith("notread:")), sources.delivery);
  expect(rows.map((r) => r.item.where.anchor)).toEqual(rows.map((r) => `notread-${r.file.file_id}`));
  const tpl = rows.find((r) => r.file.name === "client-template-filled.xlsx")!;
  expect(tpl.loose.map((g) => [g.label, g.place])).toEqual([["3 like “particle_size_d10_um” … “particle_size_d90_um”", "sheet Product, cells F1 to H1"]]);
  expect(rows.find((r) => r.file.name === "Dissolution RLD pH 6.8.xlsx")!.silent.map((r) => r.silent)).toEqual([24]);
  expect(rows.find((r) => r.file.name === "study-report.pdf")!.unread.map((r) => r.kind)).toEqual(["prose"]);
  const vessels = looseGroups(Array.from({ length: 12 }, (_, i) => ({
    where: `s:'Dissolution'!${String.fromCharCode(78 + i)}1`, text: `vessel_${i + 1}`, region: null, counted: true, decision: null, restored: null })));
  expect(vessels.map((g) => [g.label, g.place])).toEqual([["12 like “vessel_1” … “vessel_12”", "sheet Dissolution, cells N1 to Y1"]]);
  expect(looseGroups([{ where: "s:'Notes'!A1", text: null, region: null, counted: true, decision: null, restored: null }])[0].label).toBe("1 loose number (withheld (blinded))");
  // the layouts' queue: one row per version, the not-data reading marked
  const layouts = layoutRows(model.items.filter((i) => i.id.startsWith("layout:")), sources.delivery);
  expect(layouts).toHaveLength(10);
  expect(layouts.filter((l) => l.notData).map((l) => l.mapping.mapping_id)).toEqual(["mp-437e5d2d6afa"]);
  expect(layouts[0].item.where.anchor).toMatch(/^todo-layout-mp-/);
  expect(columnSummary([
    { column: 1, header: "Subject", role: "key", field: "subject" }, { column: 2, header: "Period", role: "key", field: "period" },
    { column: 3, header: "0.5", role: "value", field: "concentration" }, { column: 4, header: "1", role: "value", field: "concentration" },
    { column: 5, header: "24", role: "value", field: "concentration" }, { column: 6, header: "Comment", role: "ignore", field: null },
  ])).toBe("subject ← 'Subject' · period ← 'Period' · concentration ← 3 columns '0.5' … '24' · 1 column not read");
});
