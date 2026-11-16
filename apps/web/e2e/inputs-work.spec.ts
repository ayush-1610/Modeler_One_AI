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
  NEW, NO_TARGET, aboutText, askLines, blindedText, blindedWhy, analyteChoice, analyteChoices, areaHead, assignBody, buildWork, checkField, collisions,
  columnSummary, destinationKey, formulationsHeld, heldBy, inModel, layoutRows, linkCount, linkPlaces, linkRows, linkTarget, linkWords, linkedPiece,
  looseGroups, markedText, nextText, foldChecks, noLayoutReads, noSampleCells, normLabel, notReadRows, onDelivery, pairsMeet, prefixAlias,
  productFor, releaseAnchor, releaseOf, restoredText, seriesKey,
  targetProblem, type WorkSources,
} from "../lib/inputsWork";
import {
  ASK_FORMULATION, NO_PRODUCT, alreadyDecidedText, bracketed, checkFix, checkGist, checkLabel, constantText, drawText, escapePattern, flagLines,
  formulationLine, formulationParts, formulationProblem, formulationWays, heldText, individualNeeds, individualText, inputsHref, layoutFieldText,
  layoutFindingText, moveText, paramLabel, patternWords, placeText, readinessText, redrawText, rowRuleText, rowsLeftOut, spotGroupText, stepReason,
  stepWhere, todoMessage, unitText, unreadWhy, withheldWhy, anchorPlace, sourceNamed, anchorCell, conditionsInWords, distinctNames, layoutFieldInText,
  regionKindText, valueAbout,
} from "../lib/words";
import { afterAnswer, blindedStudies, changedRows } from "../lib/freshness";

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
  expect(model.inModel).toEqual({ studies: 0, datasets: 0, formulations: 0, values: 0 });
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

test("a study the client review's group says the delivery blinds is blinded on its card and left out of Next", () => {
  // the sheet form's group of a study the delivery blinds (final review INT-2): the card is blinded through it
  const sources = copy(load("exampleamide"));
  const before = buildWork(sources);
  const card = before.subjects.find((s) => s.row?.label === "231-24" && s.groups.length)
    ?? before.subjects.find((s) => s.groups.length && s.kind === "study")!;
  for (const g of sources.review!.groups.filter((x) => card.groups.some((y) => y.id === x.id))) g.blinded = true;
  const model = buildWork(sources);
  const after = model.subjects.find((s) => s.key === card.key)!;
  expect(after.blinded).toBe(true);
  expect(model.items.filter((i) => i.open && i.subjects.includes(card.key))).toEqual([]);
});

test("a decision someone made already is said with who, when and why, never the line's id or a raw place", () => {
  expect(alreadyDecidedText([{ id: "rd-9", by: "dev-user", at: "2026-11-15T10:21:06.462Z", why: "a note about re-assays",
                               where: "s:'Summary'!A10" }]))
    .toBe("dev-user marked sheet Summary, cell A10 as not data on 15 Nov 2026, 10:21: “a note about re-assays”. Restore it to decide again.");
  expect(alreadyDecidedText([{ id: "ov-12", by: "reviewer-b", at: "2026-11-15T10:30:00Z", why: "as written", check_id: "ck-1" }]))
    .toBe("reviewer-b accepted it as is on 15 Nov 2026, 10:30: “as written”. The card is read again to show it.");
  expect(alreadyDecidedText(undefined)).toBeNull();
  expect(alreadyDecidedText([])).toBeNull();
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
  // it opens on the study's card, in Clinical studies (slice 3), at the study's own route (CODE-1: every study whose
  // route is not stated has a route row of its own)
  expect(row("fact:study:230-23").where).toEqual({ tab: "studies", anchor: "delivery-gap-st-8-route", subject: "study/st-8" });
  expect(row("fact:study:230-25").where.anchor).toBe("delivery-gap-st-16-route");
  expect(row("need:study:230-23:REQ-sys.demographics").where.anchor).toBe("delivery-requirement-st-8-REQ-sys.demographics");
  expect(row("need:study:230-25:REQ-sys.demographics").where.anchor).toBe("delivery-requirement-st-16-REQ-sys.demographics");
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

test("a study's individual is chosen before its spot check: its row comes first among the card's open work (round 3)", () => {
  // the review's 230-23: demographics stated (entered on the card), the PK-Sim population and the sex not chosen yet
  const sources = load("exampleamide");
  const card = sources.cards!["study/st-8"]!;
  card.requirements = card.requirements.map((r) => (r.req_id === "REQ-sys.demographics" ? { ...r, status: "found" } : r));
  card.individual = { demographics: null, needs: ["individual_population", "individual_sex"], why: "",
                      stated: ["age_mean", "age_min", "age_max", "weight_mean_kg", "percent_female"] };
  const model = buildWork(sources);
  const row = model.items.find((i) => i.id === "individual:study:230-23")!;
  expect(row.label).toBe("Study 230-23 · choose the study's individual");
  expect(row.detail).toBe("The study's individual needs the PK-Sim population and the sex simulated: give them with the demographics, before the spot check.");
  expect(row.status).toBe("missing");
  expect(row.open).toBe(true);
  // it opens on the study's card, at the individual's line ("Choose the individual…"), the card's own place for it
  expect(row.where).toEqual({ tab: "studies", anchor: "delivery-individual-st-8", subject: "study/st-8" });
  // it is the card's own work, said before the spot check in the order the card is done
  expect(onDelivery(model, "studies").find((x) => x.subject.label === "230-23")!.open.map((i) => i.id)).toContain(row.id);
  expect(model.items.find((i) => i.id === "confirm:study:230-23")!.detail)
    .toContain("first 3 items on its card (2 missing · 1 to decide) and the delivery clean-up; then the spot check and the signature");
  // a spot check recorded already (the review's 230-23): choosing the individual draws it again, said on the row
  card.spot_check = { state: "complete" };
  expect(buildWork(sources).items.find((i) => i.id === row.id)!.detail)
    .toBe("The study's individual needs the PK-Sim population and the sex simulated: give them with the demographics; the spot check is then drawn again.");
  card.spot_check = { state: "none" };
  // chosen (the card names the individual), or the demographics still to give (their own row asks for both at once): no row
  card.individual = { ...card.individual, demographics: { population: "European_ICRP_2002", sex: "FEMALE", age_years: 32 }, needs: [] };
  expect(buildWork(sources).items.some((i) => i.id.startsWith("individual:"))).toBe(false);
  card.individual = { demographics: null, needs: ["individual_population", "individual_sex", "age_mean"], why: "", stated: [] };
  expect(buildWork(sources).items.some((i) => i.id.startsWith("individual:"))).toBe(false);
  card.individual = { demographics: null, needs: ["individual_population"], why: "", stated: ["age_mean"] };
  card.requirements = card.requirements.map((r) => (r.req_id === "REQ-sys.demographics" ? { ...r, status: "missing" } : r));
  expect(buildWork(sources).items.some((i) => i.id.startsWith("individual:"))).toBe(false);
});

test("a fact a failed check asks for is asked, and counted, as a fact: on the card's facts form and on To do's facts row (final review CODE-8 c)", () => {
  expect(checkField({ code: "LANDING_FIELD_MISSING", message: "the study record needs n, which no active value states" })).toBe("n");
  expect(checkField({ code: "DOSE_MISSING", message: null })).toBe("dose");
  expect(checkField({ code: "MATRIX_MISSING", message: "no matrix is stated for the concentrations" })).toBe("matrix");
  expect(checkField({ code: "ABOVE_RANGE", message: "a value above the range" })).toBeNull();
  // a matrix not stated on 230-23: one more fact on its facts row (as its card asks it), not a check to decide
  const sources = load("exampleamide");
  sources.cards!["study/st-8"]!.checks.push({ id: "ck-matrix", code: "MATRIX_MISSING", message: "no matrix is stated for the concentrations",
                                             severity: "fail", overridden: false } as never);
  const model = buildWork(sources);
  expect(model.items.some((i) => i.id === "check:study:230-23:ck-matrix")).toBe(false);
  expect(model.items.find((i) => i.id === "fact:study:230-23")!.label)
    .toBe("Study 230-23 · not stated: the route, the number of subjects, what the study is for, the matrix");
  expect(model.counts.missing + model.counts.to_confirm + model.counts.to_decide).toBe(model.counts.open);
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
  // the table's head, its rows and their buttons count alike: a table's cells are values, a fact read beside it a fact
  // (final review OWN-16: the head said 366 values where the rows said 355 and their facts)
  expect(linkCount(rows.flatMap((r) => r.values))).toBe("355 values and 11 facts");
  expect(linkCount(reference.values)).toBe("76 values and 3 facts");
  expect(linkCount(reference.values.filter((v) => !v.id.includes("#")))).toBe("3 facts");
  expect(linkCount([])).toBe("no value");
  expect(rows.find((r) => r.item.id.startsWith("link:"))!.item.label).toMatch(/^Link the \d+ values( and \d+ facts?)? of .+ to a study or product$/);
  expect(reference.item.where).toEqual({ tab: "todo", anchor: `link-${reference.fileId}` });
  // "Same study as 230-23?": nothing filled until answered; Yes fills 230-23 and an arm that keeps the two files apart
  expect(reference.suggested).toBeNull();
  expect(reference.alias!.study.label).toBe("230-23");
  expect(reference.alias!.target).toMatchObject({ study: "st-8", arm: NEW, newArm: "Reference" });
  expect(test230.alias!.target).toMatchObject({ study: "st-8", arm: NEW, newArm: "Test" });
  expect(reference.pairs).toContain("001 · I · plasma · concentration");
  // the two files in one arm of one study collide on their subjects and periods; each in its own arm, they do not
  const studies = sources.delivery!.subjects;
  const same = { ...NO_TARGET, study: "st-8" };
  expect(collisions([{ row: reference, target: same }, { row: test230, target: same }], studies)).toEqual([
    { files: ["230-23 Fasting Reference.xlsx", "230-23 Fasting Test.xlsx"], study: "230-23", example: "subject 001, period I",
      keys: [reference.sha, test230.sha] }]);
  expect(collisions([{ row: reference, target: reference.alias!.target }, { row: test230, target: test230.alias!.target }], studies)).toEqual([]);
  // and against what the study already holds in that arm (its card, when read)
  expect(collisions([{ row: reference, target: same }], studies, { "st-8": [{ arm: "", analyte: "", pair: "001 · I · plasma · concentration" }] })[0].files)
    .toEqual(["230-23 Fasting Reference.xlsx"]);
  // each file naming its analyte, read as an entity of its own (an-1, an-2: one per file, both "Exampleamide"): the same
  // analyte by name, so the two still collide; and against what the study holds of that analyte, by name too
  const named = (r: typeof reference, id: string) => ({ ...r, own: { ...r.own, analyte: { id, label: "Exampleamide" } } });
  const analytes = [{ id: "an-1", label: "Exampleamide" }, { id: "an-2", label: "Exampleamide" }];
  expect(collisions([{ row: named(reference, "an-1"), target: same }, { row: named(test230, "an-2"), target: same }], studies, {}, analytes))
    .toHaveLength(1);
  expect(collisions([{ row: named(reference, "an-1"), target: { ...same, analyte: "an-2" } }, { row: named(test230, "an-2"), target: same }],
                    studies, {}, analytes)).toHaveLength(1);
  expect(collisions([{ row: named(reference, "an-1"), target: same }], studies, { "st-8": [{ arm: "", analyte: "exampleamide", pair: "001 · I · plasma · concentration" }] }))
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
  expect(collisions([{ row: two.parts[0], target: to }], studies, { "st-8": [{ arm: "", analyte: "", pair: "001 · I · plasma · concentration", sha: ref.sha256 }] })[0])
    .toMatchObject({ files: ["two-studies.xlsx, its individual PK table on sheet Sheet1"], keys: [`${sha}#tx-aaaa`] });
  expect(collisions([{ row: two.parts[0], target: to }, { row: two.parts[1], target: to }], studies)).toEqual([]);   // one file's tables
  expect(collisions([{ row: two.parts[0], target: to }], studies, { "st-8": [{ arm: "", analyte: "", pair: "001 · I · plasma · concentration", sha }] })).toEqual([]);
  expect(heldBy({ tables: [{ file_sha256: ref.sha256, values: own.slice(0, 1) }] })).toEqual([{ arm: "", analyte: "", pair: "001 · I · plasma · concentration", sha: ref.sha256 }]);
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

// --- the final review's linking fixes (plan §5 "Final review fixes: linking") ----------------------------------------------

test("the arm guard: an analyte or a period left out matches any, by name, in the batch and against what the study holds (INT-4)", () => {
  const sources = batch();
  const model = buildWork(sources);
  const rows = linkRows(model.items.filter((i) => /^(link|alias):/.test(i.id)), sources.delivery, model.subjects);
  const reference = rows.find((r) => r.file === "230-23 Fasting Reference.xlsx")!, test230 = rows.find((r) => r.file === "230-23 Fasting Test.xlsx")!;
  const studies = sources.delivery!.subjects;
  const same = { ...NO_TARGET, study: "st-8" };
  const analytes = [{ id: "an-9", label: "Exampleamide" }, { id: "an-10", label: "Exampleamide-M1" }, { id: "an-17", label: "Exampleamide" }];
  const bare = (r: typeof reference) => ({ ...r, own: { ...r.own, analyte: null } });
  // "as the file says" with the file stating none beside a stated analyte: any analyte, so they collide (was missed)
  expect(collisions([{ row: bare(reference), target: same }, { row: bare(test230), target: { ...same, analyte: "an-9" } }], studies, {}, analytes))
    .toHaveLength(1);
  // two ids of one name (an-9 from one file, an-17 from another): one analyte
  expect(collisions([{ row: bare(reference), target: { ...same, analyte: "an-9" } }, { row: bare(test230), target: { ...same, analyte: "an-17" } }],
                    studies, {}, analytes)).toHaveLength(1);
  // another analyte by name (the metabolite): no collision
  expect(collisions([{ row: bare(reference), target: { ...same, analyte: "an-10" } }, { row: bare(test230), target: { ...same, analyte: "an-17" } }],
                    studies, {}, analytes)).toEqual([]);
  // a period left out matches any period: the study's values of subject 001 with no period, beside period I
  const held = { "st-8": [{ arm: "", analyte: "exampleamide", pair: "001 ·  · plasma · concentration", sha: "a".repeat(64) }] };
  expect(collisions([{ row: bare(reference), target: same }], studies, held, analytes)).toEqual([
    { files: ["230-23 Fasting Reference.xlsx"], study: "230-23", example: "subject 001, period I", keys: [reference.sha] }]);
  expect(collisions([{ row: bare(reference), target: { ...same, analyte: "an-10" } }], studies, held, analytes)).toEqual([]);
  expect([pairsMeet("001 · ", "001 · II"), pairsMeet("001 · I", "001 · II"), pairsMeet("002 · ", "001 · "), pairsMeet("001 · I", "001 · I")])
    .toEqual([true, false, false, true]);
});

test("the arm guard compares what the ledger compares and leaves alone what stays where it is (final review INT-4)", () => {
  const sources = batch();
  const model = buildWork(sources);
  const rows = linkRows(model.items.filter((i) => /^(link|alias):/.test(i.id)), sources.delivery, model.subjects);
  const reference = rows.find((r) => r.file === "230-23 Fasting Reference.xlsx")!, test230 = rows.find((r) => r.file === "230-23 Fasting Test.xlsx")!;
  const studies = sources.delivery!.subjects;
  const same = { ...NO_TARGET, study: "st-8" };
  const analytes = [{ id: "an-9", label: "Exampleamide" }, { id: "an-17", label: "Exampleamide" }];
  type Piece = typeof reference;
  /** the same file's values as another file (its sha) gives them, each value changed by `change` */
  const as = (r: Piece, sha: string, name: string, change: (v: Piece["values"][number]) => Piece["values"][number]): Piece => {
    const values = r.values.map((v) => change(copy(v)));
    return { ...linkedPiece(sha, name, values), own: { arm: null, batch: null, analyte: null } } as Piece;
  };
  // a urine file of the same subjects and periods as the plasma file: two series, so one arm takes both
  const urine = as(reference, "u".repeat(64), "230-23 urine.xlsx", (v) => ({ ...v, file_sha256: "u".repeat(64), labels: { ...v.labels, matrix: "Urine" } }));
  expect(urine.pairs).toContain("001 · I · urine · concentration");
  expect(collisions([{ row: reference, target: same }, { row: urine, target: same }], studies, {}, analytes)).toEqual([]);
  const plasmaHeld = { "st-8": reference.values.filter((v) => v.labels.subject).map((v) => ({ arm: "", analyte: "", pair: seriesKey(v), sha: reference.sha })) };
  expect(collisions([{ row: urine, target: same }], studies, plasmaHeld, analytes)).toEqual([]);
  // a demographics table of the same subjects: another field, another series
  const ages = as(reference, "d".repeat(64), "230-23 demographics.xlsx", (v) => ({ ...v, file_sha256: "d".repeat(64), field: "age" }));
  expect(collisions([{ row: ages, target: same }], studies, plasmaHeld, analytes)).toEqual([]);
  // "State it…" on values whose file names their study: they are in st-8 already, so stating their analyte only narrows
  const inStudy = as(test230, test230.sha, test230.file, (v) => ({ ...v, entity: { ...v.entity, study: "st-8" } }));
  const theirs = { "st-8": reference.values.filter((v) => v.labels.subject).map((v) => ({ arm: "", analyte: "exampleamide", pair: seriesKey(v), sha: reference.sha })) };
  expect(collisions([{ row: inStudy, target: { ...same, analyte: "an-9" } }], studies, theirs, analytes)).toEqual([]);
  // the same values not yet in the study are what the guard is for: refused
  const outside = as(test230, test230.sha, test230.file, (v) => v);
  expect(collisions([{ row: outside, target: { ...same, analyte: "an-9" } }], studies, theirs, analytes)).toHaveLength(1);
  // the original bypass stays refused: the Reference and Test files into one arm with two ids of one analyte's name
  const bare = (r: Piece) => ({ ...r, own: { ...r.own, analyte: null } });
  expect(collisions([{ row: bare(reference), target: { ...same, analyte: "an-9" } }, { row: bare(test230), target: { ...same, analyte: "an-17" } }],
                    studies, {}, analytes)).toHaveLength(1);
  // the rule's own words: same subject and field; a period or a matrix left out matches any
  expect([pairsMeet("001 · I · plasma · concentration", "001 · I · urine · concentration"),
          pairsMeet("001 · I ·  · concentration", "001 · I · urine · concentration"),
          pairsMeet("001 · I · plasma · concentration", "001 · I · plasma · age")]).toEqual([false, true, false]);
});

test("one analyte per name in every picker, the one the study uses, and no new analyte of a name that exists (OWN-11)", () => {
  const analytes = [{ id: "an-9", label: "Exampleamide" }, { id: "an-10", label: "Exampleamide-M1" }, { id: "an-17", label: "Exampleamide" }];
  expect(analyteChoices(analytes).map((a) => a.id)).toEqual(["an-9", "an-10"]);
  expect(analyteChoices(analytes, null, ["an-17"]).map((a) => a.id)).toEqual(["an-17", "an-10"]);
  // the file's own first, as it reads it; the study's id of that name sent in its place
  const own = { id: "an-2", label: "exampleamide" };
  expect(analyteChoices([...analytes, own], own).map((a) => a.id)).toEqual(["an-2", "an-10"]);
  const choices = analyteChoices([...analytes, own], own, ["an-9"]);
  expect(choices.map((a) => a.id)).toEqual(["an-9", "an-10"]);
  expect(analyteChoice("an-2", choices, analytes, own)).toBe("an-9");
  expect(analyteChoice("an-17", choices, analytes)).toBe("an-9");
  expect([analyteChoice("", choices, analytes), analyteChoice(NEW, choices, analytes)]).toEqual(["", NEW]);
  expect(targetProblem({ ...NO_TARGET, study: "st-8", analyte: NEW, newAnalyte: " exampleamide " }, analytes))
    .toBe("An analyte named Exampleamide exists already: pick it");
  expect(targetProblem({ ...NO_TARGET, study: "st-8", analyte: NEW, newAnalyte: "M2" }, analytes)).toBeNull();
});

test("a link a re-read did not carry over comes back on its row, filled with where it went and saying why (OWN-1)", () => {
  const sources = batch();
  const page = sources.delivery!;
  const ref = page.deliveries.flatMap((d) => d.files).find((f) => f.name === "230-23 Fasting Reference.xlsx")!;
  const table = page.unassigned.find((v) => v.file_sha256 === ref.sha256 && v.id.includes("#"))!.id.split("#")[0];
  const facts = page.unassigned.filter((v) => v.file_sha256 === ref.sha256 && !v.id.includes("#")).map((v) => v.id);
  const was = { assignment: "as-1", study: "st-8", arm: "arm-21", product: null, batch: null, analyte: null, by: "dev-user",
                at: "2026-11-15T09:25:00Z", why: "the file names say 230-23" };
  page.relink = [{ ...was, targets: [table, ...facts], labels: { study: "230-23", arm: "Reference" }, whole: false }];
  let model = buildWork(sources);
  let row = linkRows(model.items.filter((i) => /^(link|alias):/.test(i.id)), page, model.subjects).find((r) => r.file === ref.name)!;
  // not asked "Same study as 230-23?" again: the row is filled with the earlier link, and says it covered part of the table
  expect(row.alias).toBeNull();
  expect(row.suggested).toMatchObject({ why: "linked before to study 230-23 · arm Reference", target: { study: "st-8", arm: "arm-21" } });
  expect(row.before!.note).toMatch(/^Linked before, in part, to study 230-23 · arm Reference \(by dev-user on .+\)\. Its table was read again/);
  // whole, but made before links were carried over; and a study that has no value left is offered from the link itself
  page.relink = [{ ...was, study: "st-99", arm: null, targets: [table, ...facts], labels: { study: "LOOSE-1" }, whole: true }];
  model = buildWork(sources);
  row = linkRows(model.items.filter((i) => /^(link|alias):/.test(i.id)), page, model.subjects).find((r) => r.file === ref.name)!;
  expect(row.before!.note).toMatch(/^Linked before to study LOOSE-1 \(by dev-user on .+\)\. Its table was read again before links were carried over/);
  expect(row.before!.subjects.map((s) => [s.subject, s.label])).toEqual([["st-99", "LOOSE-1"]]);
  // one table's values sent to two places before the re-read (two partial links): the row says both and fills neither,
  // so they are linked again with a choice, not left looking as if never linked (final review OWN-1)
  page.relink = [{ ...was, targets: [table], labels: { study: "230-23", arm: "Reference" }, whole: false },
                 { ...was, assignment: "as-2", arm: "arm-22", at: "2026-11-15T09:26:00Z", targets: [table],
                   labels: { study: "230-23", arm: "Test" }, whole: false }];
  model = buildWork(sources);
  row = linkRows(model.items.filter((i) => /^(link|alias):/.test(i.id)), page, model.subjects).find((r) => r.file === ref.name)!;
  expect(row.before).not.toBeNull();
  expect([row.before!.target, row.suggested, row.alias]).toEqual([null, null, null]);
  expect(row.before!.why).toBe("linked before to study 230-23 · arm Reference and to study 230-23 · arm Test");
  expect(row.before!.note).toMatch(/^Linked before, in part, to study 230-23 · arm Reference \(by dev-user on .+\) and to study 230-23 · arm Test \(by dev-user on .+\)\. Read again, its values were linked to more than one place/);
  const tablePart = row.parts.find((p) => p.values.some((v) => v.id.startsWith(`${table}#`)))!;
  expect([tablePart.before!.target, tablePart.suggested]).toEqual([null, null]);
  // a link's destination, as the page reads it back
  expect(linkWords({ ...was, labels: { study: "230-23", arm: "Reference" } })).toBe("study 230-23 · arm Reference");
  expect(linkTarget(was)).toEqual({ ...NO_TARGET, study: "st-8", arm: "arm-21" });
  expect(linkedPiece(ref.sha256, ref.name, page.unassigned.filter((v) => v.file_sha256 === ref.sha256)).pairs).toContain("001 · I · plasma · concentration");
});

test("Link elsewhere moves every value a file has in one place: its facts' link and its table's link together (final review INT-5)", () => {
  // the owner's real case: the file's facts (dose, fed state, LLOQ) under the person's link, its table under the reader's
  // link carried over a re-read (or "State it…", which states the table's analyte): two links, one place
  const by = { by: "dev-user", at: "2026-11-15T09:25:00Z", why: "the file names say 230-23" };
  const facts = { assignment: "as-1", targets: ["f-1", "f-2", "f-3"], values: 3, study: "st-8", arm: "arm-21", product: null, batch: null,
                  analyte: null, labels: { study: "230-23", arm: "Reference" }, ...by };
  const table = { ...facts, assignment: "as-14", targets: ["tx-77369134"], values: 76, analyte: "an-9", by: "code",
                  labels: { study: "230-23", arm: "Reference", analyte: "Exampleamide" } };
  const [place, ...more] = linkPlaces([facts, table]);
  expect(more).toEqual([]);
  expect([place.targets, place.values, place.words]).toEqual([["f-1", "f-2", "f-3", "tx-77369134"], 79, "study 230-23 · arm Reference · analyte Exampleamide"]);
  expect(place.target).toEqual({ ...NO_TARGET, study: "st-8", arm: "arm-21", analyte: "an-9" });
  expect(place.links.map((l) => l.assignment)).toEqual(["as-1", "as-14"]);
  // what is sent: one call with both links' targets, so the dose, fed state and LLOQ go with the table
  expect(assignBody({ ...place.target, arm: "arm-22" }, place.targets, "the Test arm")).toMatchObject({
    targets: ["f-1", "f-2", "f-3", "tx-77369134"], study: "st-8", arm: "arm-22", analyte: "an-9" });
  // linked to two places (the table to the Test arm): two lines, each moved on its own, the form saying the other stays
  const apart = linkPlaces([facts, { ...table, arm: "arm-22", labels: { study: "230-23", arm: "Test", analyte: "Exampleamide" } }]);
  expect(apart.map((p) => [p.words, p.values, p.targets])).toEqual([
    ["study 230-23 · arm Reference", 3, ["f-1", "f-2", "f-3"]], ["study 230-23 · arm Test · analyte Exampleamide", 76, ["tx-77369134"]]]);
});

test("a disagreement says whom it is about and when, with its unit, and a card lists them by subject (INT-10)", () => {
  const sources = load("exampleamide");
  const card = sources.cards!["study/st-8"]!;
  card.conflicts = [1, 2].map((t) => ({ id: `cx-${t}`, field: "concentration", kind: "value", time: t, time_unit: "h",
                                         labels: { study: "230-23", subject: "001", period: "I" } }));
  const model = buildWork(sources);
  const differ = model.items.filter((i) => i.id.startsWith("differ:"));
  expect(differ.map((i) => i.label)).toEqual([1, 2].map((t) => `Study 230-23: the files give different values for concentration at ${t} h, subject 001, period I`));
  expect(new Set(differ.map((i) => i.about))).toEqual(new Set(["subject 001, period I"]));
  expect(aboutText({ study: "230-23", arm: "Test", subject: "002" })).toBe("arm Test, subject 002");
});

test("a sheet-form group of a file linked to a study or product joins its card: not a card, a row or a sheet of its own (OWN-4, INT-9)", () => {
  const sources = load("exampleamide");
  const before = buildWork(sources);
  expect(before.subjects.some((s) => s.key === "study:230-23-REF")).toBe(true);
  expect(before.items.some((i) => i.id === "draft:draft|file-0773300f5a31|pH 6.8")).toBe(true);
  // the API names them on the subjects whose files' values they were read from (`legacy_groups`), a sheet too
  const page = sources.delivery!;
  page.subjects.find((s) => s.subject === "st-8")!.legacy_groups = ["study:230-23-REF", "study:230-23-TEST"];
  page.subjects.find((s) => s.subject === "pr-12")!.legacy_groups.push("sheet:file-0773300f5a31|pH 6.8");
  const after = buildWork(sources);
  const study = after.subjects.find((s) => s.row?.subject === "st-8")!;
  expect(study.key).toBe("study:230-23");                                // known by its own name still
  expect(study.groups.map((g) => g.id)).toEqual(["study:230-23", "study:230-23-REF", "study:230-23-TEST"]);   // its own first
  expect(study.aliases).toEqual(["230-23-REF", "230-23-TEST"]);
  expect(after.subjects.some((s) => s.key === "study:230-23-REF" || s.key === "study:230-23-TEST")).toBe(false);
  // no separate confirm, no facts asked again, no alias question for those groups; the sheet joins its product's card
  expect(after.items.filter((i) => /230-23-(REF|TEST)/.test(i.id)).map((i) => i.id)).toEqual([]);
  expect(after.items.some((i) => i.id === "draft:draft|file-0773300f5a31|pH 6.8")).toBe(false);
  expect(after.subjects.find((s) => s.row?.subject === "pr-12")!.groups.map((g) => g.id)).toContain("sheet:file-0773300f5a31|pH 6.8");
  expect(after.counts.missing).toBeLessThan(before.counts.missing);
});

test("a confirmed product says whether its release is set; a tablet study's missing formulation opens the product that can give it (OWN-10)", () => {
  const sources = copy(load("exampleamide"));
  const test10 = sources.review!.groups.find((g) => g.id === "product:Test 10 mg")!;
  Object.assign(test10, { state: "confirmed", confirmed_by: "dev-user", confirmed_at: "2026-11-15T09:19:00Z" });
  // the API's way (round 4): Test 10 mg's dissolution profile can give the release the study names
  sources.inputs!.todo.push({ kind: "formulation", target: "form.*", tab: "formulations",
                              message: "CL-01: the CPF defines no formulation 'Test 10 mg' (form.Test 10 mg.type)",
                              way: { way: "use_profile", products: ["Test 10 mg"], studies: ["CL-01"] } });
  const model = buildWork(sources);
  const card = model.subjects.find((s) => s.label === "Test 10 mg")!;
  expect(releaseOf(card, sources.inputs)).toEqual({ name: null, needed: true });
  expect(releaseOf(model.subjects.find((s) => s.label === "Brand 10 mg")!, sources.inputs)).toEqual({ name: null, needed: false });
  // confirmed is not "in the model" as a formulation: the card says its dissolution is kept and its release is not set
  expect(model.items.find((i) => i.id === `confirm:${card.key}`)!.inModel)
    .toBe("Confirmed by dev-user on 15 Nov 2026, 09:19; in the model. Its dissolution profile is kept; the formulation's release is not set yet.");
  // the tablet study's missing formulation is the card's open work, and opens where its release is set
  const item = model.items.find((i) => i.id === "todo:formulation:form.*")!;
  expect(item.open).toBe(true);
  expect(item.subjects).toEqual([card.key]);
  expect(item.where).toMatchObject({ tab: "formulations", anchor: releaseAnchor(card) });
  expect(item.detail).toBe("Use the dissolution profile of Test 10 mg as its release: “Use this profile as the release” on its card, on "
                           + "Products and dissolution.");
  // once the model holds the formulation under the product's name, its release is set
  sources.inputs!.compound.push({ id: "form.Test 10 mg.type", state: "kept", tab: "formulations" });
  expect(formulationsHeld(sources.inputs)).toEqual(["Test 10 mg"]);
  expect(releaseOf(card, sources.inputs).name).toBe("Test 10 mg");
  sources.inputs!.todo = sources.inputs!.todo.filter((t) => t.kind !== "formulation");
  expect(buildWork(sources).items.find((i) => i.id === `confirm:${card.key}`)!.inModel).toContain("Its release is the formulation “Test 10 mg”.");
  // no product is here at all (the API's way "add_product"): the item stays on Products and dissolution, opening its own
  // row, and names the lever: add the product, or ask the client (round 3, gap 11)
  const none = copy(load("clientamide"));
  none.inputs!.todo.push({ kind: "formulation", target: "form.*", tab: "formulations",
                           message: "CL-1: the study is a solid oral form but the CPF defines no formulation (form.{name}.type)",
                           way: { way: "add_product", products: [], studies: ["CL-1"] } });
  expect(buildWork(none).items.find((i) => i.id === "todo:formulation:form.*")!.where).toEqual({ tab: "formulations", anchor: "todo-formulation-form.*" });
  expect(buildWork(none).items.find((i) => i.id === "todo:formulation:form.*")!.detail).toBe(NO_PRODUCT);
  expect(NO_PRODUCT).toContain("“Add a product”");
  // products with dissolution profiles here (the owner's review project, round 4): the item opens the first one's card at
  // its release, says the products, and is no one card's work while two can give it
  const products = copy(load("exampleamide"));
  products.inputs!.todo.push({ kind: "formulation", target: "form.*", tab: "formulations",
                               message: "CL-01: the study is a solid oral form but the CPF defines no formulation (form.{name}.type)",
                               way: { way: "use_profile", products: ["Test 10 mg", "Brand 10 mg"], studies: ["CL-01"] } });
  const both = buildWork(products);
  const test10card = both.subjects.find((s) => s.label === "Test 10 mg")!;
  const usable = both.items.find((i) => i.id === "todo:formulation:form.*")!;
  expect(usable.detail).not.toBe(NO_PRODUCT);
  expect(usable.detail).toBe("Use a product's dissolution profile as its release: “Use this profile as the release” on its card, on Products and "
                             + "dissolution (Test 10 mg or Brand 10 mg).");
  expect(usable.where).toMatchObject({ tab: "formulations", anchor: releaseAnchor(test10card) });
  expect(usable.subjects).toEqual([]);
  // products here with no profile that can give it: the first product's card, at what to add
  products.inputs!.todo.at(-1)!.way = { way: "add_dissolution", products: ["Exampleamide IR tablet"], studies: ["CL-01"] };
  const noProfile = buildWork(products).items.find((i) => i.id === "todo:formulation:form.*")!;
  expect(noProfile.detail).toContain("add the dissolution file of Exampleamide IR tablet");
  expect(noProfile.where.anchor).toBe(releaseAnchor(productFor(both.subjects, "Exampleamide IR tablet")!));
  // the product is found by any of its names, case and spacing aside
  expect(productFor(both.subjects, "test 10  MG")?.key).toBe(test10card.key);
  expect(productFor(both.subjects, "Comparamide 5 mg")).toBeNull();
  expect(productFor(both.subjects, null)).toBeNull();
});

test("round 4: the lever for a tablet study's formulation follows what the project holds, one source for every page", () => {
  // no product here: add one (its form opens) or ask the client (its line of To do) — the owner job's seed
  const none = formulationWays({ way: "add_product", products: [], studies: ["OJ-101"] });
  expect(none.waiting).toBe("a tablet study has no formulation");
  expect(none.situation).toBe("no product is here");
  expect(none.ways.map((w) => [w.id, w.say, inputsHref("p1", w)])).toEqual([
    ["add", "add a product", "/projects/p1/inputs?tab=formulations&add=product"],
    ["ask", "ask the client", `/projects/p1/inputs?tab=todo&at=${ASK_FORMULATION}`],
  ]);
  expect(none.fix).toBe(NO_PRODUCT);
  // products with a profile (the owner's review project 7bb1): the profile is the lever, opening the first product's card
  // at "Use this profile as the release"; nothing to ask the client, never "add a product"
  const profile = formulationWays({ way: "use_profile", products: ["Test 10 mg", "Brand 10 mg"], studies: ["231-24", "230-23"] });
  expect(profile.ways.map((w) => [w.id, w.say, inputsHref("p1", w)])).toEqual([
    ["release", "use a product's dissolution profile as its release", "/projects/p1/inputs?tab=formulations&release=Test%2010%20mg"],
  ]);
  expect(profile.situation).toBe("the dissolution profiles of Test 10 mg and Brand 10 mg are here");
  for (const said of [profile.fix, profile.situation, ...profile.ways.map((w) => w.say)]) expect(said).not.toMatch(/add a product|Add a product/);
  expect(formulationWays({ way: "use_profile", products: ["A", "B", "C"], studies: [] }).situation)
    .toBe("the dissolution profiles of A, B and C are here");
  // its product's dissolution data not confirmed yet (7bb1's Test 10 mg): the order it is done in, confirm then use
  const unconfirmed = formulationWays({ way: "use_profile", products: ["Test 10 mg", "Brand 10 mg"], studies: [], ready: false });
  expect(unconfirmed.situation).toBe("the dissolution profiles of Test 10 mg and Brand 10 mg are here, their data to confirm first");
  expect(unconfirmed.ways.map((w) => [w.id, w.say, w.query])).toEqual([
    ["release", "confirm a product's dissolution data, then use its profile as its release", "release=Test%2010%20mg"]]);
  expect(unconfirmed.fix).toBe("Confirm the dissolution data of Test 10 mg on its card (“Confirm”), then use its profile as its release (“Use "
                               + "this profile as the release”), on Products and dissolution (or the profile of Brand 10 mg).");
  expect(formulationWays({ way: "use_profile", products: [], studies: [] }).ways[0].query).toBe("release=");
  // products without a profile: their dissolution data, or the client
  const data = formulationWays({ way: "add_dissolution", products: ["Exampleamide IR tablet", "Comparamide tablet"], studies: [] });
  expect(data.ways.map((w) => [w.id, w.say])).toEqual([["dissolution", "add a product's dissolution data"], ["ask", "ask the client"]]);
  expect(data.ways[0].query).toBe("release=Exampleamide%20IR%20tablet");
  expect(data.fix).toContain("add the dissolution file of Exampleamide IR tablet or Comparamide tablet (Add data)");
  // several formulations, a study naming none: choose, at the study's row
  const choose = formulationWays({ way: "choose", products: [], studies: ["230-23"] });
  expect(choose.waiting).toBe("a tablet study does not say which formulation it used");
  expect(inputsHref("p1", choose.ways[0])).toBe("/projects/p1/inputs?tab=formulations&at=formulation-230-23");
  // no lever fits (a formulation not complete): the area only, and To do's item says each problem
  expect(formulationWays(null).ways).toEqual([]);
  expect(formulationWays(undefined).fix).toContain("To do's formulation item says what each tablet study lacks");
  // the step bar, Review & sign and the model checks say the same, from the step's `formulation`
  const at = stepWhere("formulations of solid studies", { way: "use_profile", products: ["Test 10 mg"], studies: [] })!;
  expect(at).toMatchObject({ area: "formulations", name: "Products and dissolution", waiting: "a tablet study has no formulation",
                             situation: "the dissolution profile of Test 10 mg is here" });
  expect(at.ways.map((w) => w.id)).toEqual(["release"]);
  expect(stepReason("formulations of solid studies", { way: "choose", products: [], studies: ["X"] })).toBe("a tablet study does not say which formulation it used");
  expect(checkFix("formulations of solid studies", { way: "add_product", products: [], studies: [] })).toBe(NO_PRODUCT);
  expect(stepWhere("S0 completeness (MS-01 §2.2)")!.ways).toEqual([]);
});

test("a value's flags, its parameter and a formulation in a person's words, never the engine's codes or ids (OWN-5, OWN-8)", () => {
  // the template's condition list arrives split at every comma: one bracket is one condition again, never a stray bracket
  // and "fu,inc" (one condition, written with a comma and no bracket) is one again; either piece alone is said whole
  expect(bracketed(["system (HLM", "hepatocytes", "rCYP)", "fu", "inc"])).toEqual(["system (HLM, hepatocytes, rCYP)", "fu,inc"]);
  expect(bracketed(["protein or cell concentration", "inc", "scaling factors"])).toEqual(["protein or cell concentration", "fu,inc", "scaling factors"]);
  expect(bracketed(["fu", "scaling factors"])).toEqual(["fu,inc", "scaling factors"]);
  expect(bracketed(["system", "inc", "fu", "probe substrate"])).toEqual(["system", "fu,inc", "probe substrate"]);
  expect(bracketed(["hepatocytes", "rCYP)"])).toEqual(["hepatocytes", "rCYP"]);
  expect(bracketed(["system (HLM"])).toEqual(["system (HLM)"]);
  const lines = flagLines(["needs_conversion: no storage unit known for elim; enter the PK-Sim value by hand", "condition_missing: system (HLM",
                           "condition_missing: hepatocytes", "condition_missing: rCYP)", "condition_missing: inc", "value_not_in_quote"]);
  expect(lines).toEqual(["Filed under no elimination pathway: choose the pathway it belongs to",
                         "The source does not state: system (HLM, hepatocytes, rCYP); fu,inc", "The value is not in the quoted sentence"]);
  expect(flagLines(["condition_missing: fu", "condition_missing: inc"])).toEqual(["The source does not state: fu,inc"]);
  expect(flagLines(["refiled: from elim; a new name can change what the number means, so a person confirms the converted value",
                    "needs_conversion: an absolute clearance needs the body weight to become ml/min/kg"]))
    .toEqual(["Filed under a new parameter (it was filed as an elimination pathway): check the converted value before you accept it",
              "Not converted: an absolute clearance needs the body weight to become ml/min/kg"]);
  for (const line of [...lines, ...flagLines(["species_mismatch: rat", "conflict >2-fold with ev-1"])]) {
    expect(line).not.toMatch(/needs_conversion|condition_missing|species_mismatch|\bev-|\belim\b|_/);
  }
  // a held value's sentence: the placeholder asks for its pathway; another names its parameter, never its id
  expect(todoMessage("review", "ev-1a2b: elim = 21.0 L/h is held until a person accepts or corrects it (needs_conversion: no storage unit known for elim)"))
    .toBe("21.0 L/h is filed under no elimination pathway: it is used once it is filed under one (below).");
  expect(todoMessage("review", "ev-9: phys.logp = 2.1 Log Units is held until a person accepts or corrects it (value_not_in_quote)"))
    .toBe("Lipophilicity = 2.1 waits for your check before it is used: why is said under its source.");
  // a parameter by its label, a family's member by what its id says; a unit as a person writes it
  expect(["phys.logp", "phys.mw", "phys.pka.base.0", "phys.pka.acid.1", "bind.fu", "elim", "elim.hepatic.total.plasma_clearance",
          "elim.hepatic.CYP3A4.clspec", "form.Test 10 mg.type", "form.Test 10 mg.weibull.t50"].map(paramLabel))
    .toEqual(["Lipophilicity", "Molecular weight", "pKa, basic", "pKa, acidic (group 2)", "Fraction unbound in plasma", "An elimination pathway",
              "Hepatic plasma clearance (total)", "Specific clearance by CYP3A4 (CLspec)", "Test 10 mg: release model",
              "Test 10 mg: Dissolution time (50% dissolved)"]);
  expect([unitText("Log Units"), unitText("ml/min/kg"), unitText(null)]).toEqual(["", "ml/min/kg", ""]);
  // a formulation in one line; why a tablet study has none, without the CPF's ids
  expect(formulationLine("Test 10 mg", { type: { value: "Weibull", unit: null }, "weibull.t50": { value: 18.0004, unit: "min" },
                                         "weibull.shape": { value: 1.3, unit: null } })).toBe("Test 10 mg · release Weibull · t50 18 min · shape 1.3");
  expect(formulationLine("Brand 10 mg", {})).toBe("Brand 10 mg · release not set");
  expect(formulationProblem("CL-01: the study is a solid oral form but the CPF defines no formulation (form.{name}.type)"))
    .toBe("CL-01: a tablet or capsule study, and the model holds no formulation yet");
  expect(formulationProblem("CL-01: the CPF defines no formulation 'Test 10 mg' (form.Test 10 mg.type)"))
    .toBe("CL-01: the model holds no formulation “Test 10 mg”");
  expect(formulationProblem("CL-01: Weibull formulation 'T' needs form.T.weibull.t50, form.T.weibull.shape (the in-vitro dissolution fit)"))
    .toBe("CL-01: formulation “T” has no dissolution time (50% dissolved), dissolution shape yet");
  // the spot check's group, never its key
  expect(spotGroupText("table_kind=pk_individual|unit_class=concentration|blq_form=BLQ|cross_file=yes"))
    .toBe("picked at random among the concentrations of individual PK tables, those written “BLQ”, read from another file than the study's own");
  expect(spotGroupText("table_kind=fact|unit_class=other|blq_form=|cross_file=no")).toBe("picked at random among the values of the facts read from the files");
  // a model check opens the area of Inputs where it is done, and a tablet study's formulation has a second way (gap 11):
  // with no product here, "ask the client" (round 4: the ways follow what the project holds)
  expect(stepWhere("S0 completeness (MS-01 §2.2)")).toMatchObject({ area: "todo", name: "To do" });
  expect(stepWhere("formulations of solid studies", { way: "add_product", products: [], studies: [] })!.ways.at(-1))
    .toMatchObject({ say: "ask the client", area: "todo" });
  expect(stepWhere("formulations of solid studies")).toMatchObject({ area: "formulations", name: "Products and dissolution", ways: [] });
  expect(stepWhere("Review the plan, then approve and sign the MAP")).toBeNull();
});

test("round 3: the ways forward from a tablet study's missing formulation, the gate in words, the problems one by one", () => {
  // with no product here, the step bar, Run and Review & sign name "add a product" (its form opens) and "ask the client" (its
  // line is shown); round 4: only then (`formulationWays`, checked above)
  const at = stepWhere("formulations of solid studies", { way: "add_product", products: [], studies: ["OJ-101"] })!;
  expect(at.fix).toContain("“Add a product”");
  const [add, or] = at.ways;
  expect(add).toEqual({ id: "add", say: "add a product", area: "formulations", query: "add=product", name: "Products and dissolution" });
  expect(or).toEqual({ id: "ask", say: "ask the client", area: "todo", query: `at=${ASK_FORMULATION}`, name: "To do" });
  expect(inputsHref("p 1", at)).toBe("/projects/p%201/inputs?tab=formulations");
  expect(inputsHref("p1", add)).toBe("/projects/p1/inputs?tab=formulations&add=product");
  expect(inputsHref("p1", or)).toBe("/projects/p1/inputs?tab=todo&at=todo-ask-REQ-form.release");
  // the plan's refusal is said in the step bar's words: no check's raw name, no reference
  const said = readinessText("the model inputs are not ready: S0 completeness (MS-01 §2.2); formulations of solid studies; "
                             + "demographics stated (D-29); every planned simulation builds (software)");
  expect(said).toBe("The model inputs are not ready: compound values missing; a tablet study has no formulation; the demographics of a "
                    + "study are missing; the model can't be built yet.");
  for (const raw of ["MS-01", "§", "S0 completeness", "formulations of solid studies", "demographics stated", "every planned simulation builds"]) {
    expect(said).not.toContain(raw);
  }
  expect(readinessText("the model inputs are not assembled yet")).not.toContain("assembled");
  expect(readinessText("the model inputs changed since they were checked: assemble them again")).not.toContain("assemble them");
  // a problem that holds "; " itself is one problem, said by its own rule; two problems are two
  const typed = "OJ-101: formulation 'Test 10 mg' is of type 'Table'; the builder places Weibull, Dissolved, Particles, ParticleBins";
  const none = "OJ-102: the study is a solid oral form but the CPF defines no formulation (form.{name}.type)";
  expect(formulationParts({ message: typed })).toEqual([typed]);
  expect(formulationParts({ message: `${typed}; ${none}` })).toEqual([typed, none]);
  expect(formulationParts({ message: "ignored", details: [typed, none] })).toEqual([typed, none]);
  expect(formulationProblem(formulationParts({ message: typed })[0]))
    .toBe("OJ-101: formulation “Test 10 mg” is a Table release, which the model cannot build yet");
  // a withheld file names the blinded study it waits for, and that it waits whole (a paper with one blinded figure too)
  expect(withheldWhy(["EXA-301"])).toBe("it holds the values of study EXA-301, blinded until the plan is signed, and the whole file "
                                        + "waits until then, its other figures and pages too");
  expect(withheldWhy(["230-25", "231-24"])).toContain("the values of studies 230-25, 231-24");
  expect(withheldWhy([])).toContain("the values of a blinded study");
  // a blinded delivery study's To do row says why too, so a wrong match of names is seen
  const listed = { row: { blinded_why: "the project's blinding list names it (study STUDY-1)" }, groups: [] } as unknown as Parameters<typeof blindedText>[0];
  expect(blindedText(listed, ": it is confirmed afterwards."))
    .toBe("Blinded until the plan is signed, because the project's blinding list names it (study STUDY-1): it is confirmed afterwards.");
  expect(blindedText({ row: null, groups: [] }, ".")).toBe("Blinded until the plan is signed.");
  // a study read with the sheet form only (round 4): its group says why it is withheld, as the delivery's card does; the
  // card's own reason comes first where both say one
  const group = { blinded: true, blinded_why: "the project's blinding list names it (study 230-25): the plan places it in S5 (external validation)" };
  const sheetOnly = { row: null, groups: [{ blinded: false, blinded_why: null }, group] } as unknown as Parameters<typeof blindedText>[0];
  expect(blindedWhy(sheetOnly)).toBe(group.blinded_why);
  expect(blindedText(sheetOnly, ".")).toBe(`Blinded until the plan is signed, because ${group.blinded_why}.`);
  const both = { row: { blinded_why: "it is entered for external validation on its card" }, groups: [group] } as unknown as Parameters<typeof blindedText>[0];
  expect(blindedWhy(both)).toBe("it is entered for external validation on its card");
  expect(blindedWhy({ row: null, groups: [{ blinded: false, blinded_why: null }] } as unknown as Parameters<typeof blindedWhy>[0])).toBeNull();
});

test("round 4: a tablet study confirmed with the sheet form only, with no product here, is asked of the client once (gap 11)", () => {
  // the delivery asks it for its own studies; the inputs' formulation item asks it for the study the sheet form loaded; a
  // study on both paths is named once, on one line
  const line = (study: string) => ({ req_id: "REQ-form.release", what: `The formulation or dissolution data of the product the study used (no file names the product) — study ${study}`,
                                     why: "the model itself", required: true, product: null, sheet: "" });
  const sources = copy(load("clientamide"));
  sources.inputs!.todo.push({ kind: "formulation", target: "form.*", tab: "formulations",
                              message: "OJ-9: the study is a solid oral form but the CPF defines no formulation (form.{name}.type)",
                              way: { way: "add_product", products: [], studies: ["OJ-9", "CL-1"] }, ask: [line("OJ-9"), line("cl-1")] });
  sources.delivery!.request = [line("CL-1")];
  const asked = askLines(sources.delivery, sources.inputs).filter((a) => a.req === "REQ-form.release");
  expect(asked).toEqual([{ req: "REQ-form.release", what: "The formulation or dissolution data of the product the study used (no file names the product)",
                           subjects: ["CL-1", "OJ-9"], required: true, why: "the model itself" }]);
  // with no delivery (the sheet form only), the inputs alone ask it, and the work model's "Ask the client" lists it
  sources.delivery = null;
  expect(askLines(null, sources.inputs).find((a) => a.req === "REQ-form.release")!.subjects).toEqual(["OJ-9", "cl-1"]);
  expect(buildWork(sources).ask.find((a) => a.req === "REQ-form.release")!.subjects).toEqual(["OJ-9", "cl-1"]);
  // without the item's ask (a product is here), only the delivery's lines
  expect(askLines(null, null)).toEqual([]);
});

// --- the final review's gate, layouts and To do fixes (plan §5 "Final review fixes: the gate, layouts and To do") --------

/** exampleamide's filled template with nothing left but its PK summary's "1,2" and the SD beside it (`silent_cells` as the
 *  API lists them): what no table layout can read. */
function stuckTemplate(): WorkSources {
  const sources = batch();
  const tpl = sources.delivery!.deliveries.flatMap((d) => d.files).find((f) => f.name === "client-template-filled.xlsx")!;
  tpl.outside = tpl.outside.map((o) => ({ ...o, counted: false }));
  const region = tpl.regions.find((r) => r.region_id === "rg-753d65349a")!;
  region.silent_cells = [{ where: "s:'PK_Summary'!F7", text: "1,2", why: "unparseable" }, { where: "s:'PK_Summary'!G7", text: "0.4", why: "" }];
  return sources;
}

test("numbers no table layout can read are not counted, their row says why, and the gate line names the owner's decisions (OWN-2 b, d)", () => {
  const before = buildWork(batch());
  const sources = stuckTemplate();
  const model = buildWork(sources);
  const tpl = model.items.find((i) => i.id.startsWith("notread:") && i.label.startsWith("client-template-filled.xlsx"))!;
  expect(tpl.blocked).toBe("“1,2” is not a plain number, so no table layout reads it. Setting a single cell aside as not data waits for the owner's decision;"
    + " until then, correct the file and send it again.");
  expect(tpl.open).toBe(false);
  expect(model.next?.id).not.toBe(tpl.id);
  expect(model.counts.to_decide).toBe(before.counts.to_decide - 1);
  // the signatures it holds say so once, with what the owner decides
  const confirm = model.items.find((i) => i.id === "confirm:study:230-23")!;
  expect(confirm.gate).toContain("files with numbers not read");
  expect(confirm.owner).toBe("Two decisions here are the owner's: whether a single cell can be set aside as not data (1 file waits for it),"
    + " and whether a signature waits for the whole delivery's clean-up or only for its own files'.");
  expect(before.items.find((i) => i.id === "confirm:study:230-23")!.owner).toBe(
    "It is the owner's decision whether a signature waits for the whole delivery's clean-up or only for its own files'.");
  // an SD read by no column, in a row of its own, is a layout's to read: counted
  expect(noLayoutReads({ silent: 2, silent_cells: [{ where: "s:'PK_Summary'!F7", why: "unparseable" }, { where: "s:'PK_Summary'!G8", why: "" }] })).toBe(false);
  expect(noLayoutReads({ silent: 3, silent_cells: [{ where: "s:'PK_Summary'!F7", why: "unparseable" }] })).toBe(false);   // not all listed
  // every study and product of the file confirmed with the sheet form: the whole table can be set aside, so it is counted
  for (const g of sources.review!.groups.filter((x) => ["study:CL-01", "product:Test 10 mg", "product:Brand 10 mg"].includes(x.id))) g.state = "confirmed";
  const elsewhere = buildWork(sources).items.find((i) => i.id === tpl.id)!;
  expect([elsewhere.elsewhere, elsewhere.blocked]).toEqual([true, undefined]);
  expect(notReadRows([elsewhere], sources.delivery)[0].elsewhere).toBe(true);
});

test("the words of a layout: fields by their labels, a rule and a fact in a sentence, findings in words, the rows a sample leaves out (OWN-8, OWN-15)", () => {
  expect(layoutFieldText("pk.AUC_last")).toBe("AUC last (PK parameter)");
  expect(layoutFieldText("relation.ddi_ratio.AUC_last")).toBe("AUC last ratio, with vs without the interacting drug");
  expect(layoutFieldText("link.study_id")).toBe("Study named for a link to another file");
  expect(layoutFieldText("percent_female")).toBe("Women (%)");
  // every field of the intake vocabulary (GET /delivery/vocabulary, 2026-11-15) has a label: none is its id with spaces
  // ("Temperature c", "Meal fat g", "Particle size d90 um"; gate-todo review)
  const vocabulary = ["study_id", "treatment", "reference", "design", "crossover", "population", "special_population", "species", "n",
    "n_evaluable", "age_mean", "age_min", "age_max", "weight_mean_kg", "height_mean_cm", "percent_female", "n_female", "child_pugh", "egfr",
    "gestational_week", "ethnicity", "genotype", "co_medication", "route", "dose", "dose_unit", "salt_or_base", "infusion_time_min",
    "dosing_interval_h", "n_doses", "food_state", "meal_type", "meal_kcal", "meal_fat_g", "formulation", "intended_use", "lloq", "matrix",
    "subject", "period", "sequence", "occasion", "vessel", "analyte", "analyte_role", "molecular_weight", "product", "product_role", "batch",
    "strength_mg", "dosage_form", "release", "particle_size_d10_um", "particle_size_d50_um", "particle_size_d90_um", "particle_size_method",
    "polymorph", "salt_form", "apparatus", "medium", "surfactant", "rpm", "volume_ml", "temperature_c", "ph", "interval_start_h",
    "interval_end_h", "cumulative", "component", "concentration", "percent_dissolved", "excretion.amount", "excretion.fraction",
    "pk.AUC_last", "pk.CL/F", "composition.amount", "relation.test_vs_reference.Cmax", "link.protocol", "link.cross_reference"];
  const named = vocabulary.map((f) => [f, layoutFieldText(f)]);
  expect(named.filter(([, label]) => /_|\.\w|\s(um|c|g|kcal|h|min|ml|kg|cm|mg)$|^(Egfr|Co medication|Child pugh)$/.test(label))).toEqual([]);
  expect(layoutFieldText("temperature_c")).toBe("Temperature (°C)");
  expect(layoutFieldText("particle_size_d90_um")).toBe("Particle size d90 (µm)");
  expect(layoutFieldText("meal_fat_g")).toBe("Meal fat (g)");
  // what approving a version changes for another table of its layout, said before the approval (round 3)
  expect(moveText({ from_version: 2, unread_before: 0, unread_after: 0, facts_lost: ["product_role"], facts_gained: [] }, 3))
    .toBe("Once version 3 is approved, it is read with version 3 instead of version 2: no number left unread either way; it no longer reads the product's role.");
  expect(moveText({ from_version: 1, unread_before: 24, unread_after: 0, facts_lost: [], facts_gained: ["batch", "lloq"] }, 3))
    .toBe("Once version 3 is approved, it is read with version 3 instead of version 1: 24 numbers left unread now, none then; it then also reads the batch and the LLOQ.");
  expect(constantText({ field: "batch", cite: { near: "caption", line: 1 } })).toBe("The batch is read from its caption.");
  expect(constantText({ field: "ph", cite: { row: 2, column: 3 } })).toBe("The pH is read from the cell in row 2, column 3.");
  expect(rowRuleText({ column: 1, role: "arithmetic_mean", pattern: "Mean" }, patternWords("Mean"))).toBe("Rows whose column 1 reads “Mean” are arithmetic means.");
  expect(rowRuleText({ column: 1, role: "exclude", pattern: "%CV", reason: "a ratio" }, "%CV")).toBe("Rows whose column 1 reads “%CV” are not data (left out): a ratio.");
  expect(patternWords("S\\.D\\.")).toBe("S.D.");
  expect(patternWords("(?i)\\b(?:batch|lot)")).toBeNull();
  expect(escapePattern("Mean (SD)")).toBe("Mean \\(SD\\)");
  const role = { code: "CONSTANT_NOT_STATED", location: "constants[0] (product_role)",
                 message: "code reads 0 readings where the cited text must state one choice: 'Dissolution of Reference product 50 mg (RLD)'" };
  expect(layoutFindingText(role, [{ field: "product_role", cite: { near: "caption", line: 1 } }])).toBe("The product's role is not stated in its caption.");
  expect(layoutFindingText({ code: "CELL_OUTSIDE_REGION", location: "last_data_row", message: "the region has 3 rows" })).toBe("The table has 3 rows.");
  expect(rowsLeftOut(2, 9, [2, 3, 4, 5, 6, 8, 9])).toBe("Row 7 not shown");
  expect(rowsLeftOut(2, 30, [2, 3, 4, 5, 6, 28, 29, 30])).toBe("Rows 7 to 27 not shown");
  expect(rowsLeftOut(2, 4, [2, 3, 4])).toBe("");
  expect(unreadWhy("")).toBe("no column or row of the layout reads it");
  expect(unreadWhy("unparseable")).toBe("not a plain number");
});

test("a batch of numbers marked as not data is said by file; a draft's own words name the cells to read as no sample (CODE-10, OWN-2 c)", () => {
  const group = (label: string, n: number) => ({ key: label, label, place: "", items: Array.from({ length: n }, () => ({
    where: "s:'A'!A1", text: "x", region: null, counted: true, decision: null, restored: null })) });
  expect(markedText([{ file: "OJ-101 plasma means.xlsx", groups: [group("“Note: 2 samples were re-assayed on day 14”", 1)] }], 0))
    .toBe("OJ-101 plasma means.xlsx: “Note: 2 samples were re-assayed on day 14” marked as not data. No loose number is left.");
  expect(markedText([{ file: "a.xlsx", groups: [group("12 like “vessel_1” … “vessel_12”", 12), group("3 like “d10”", 3)] },
                     { file: "b.xlsx", groups: [group("“x”", 1)] }], 4, 1))
    .toBe("16 loose numbers in 2 files marked as not data: a.xlsx (15), b.xlsx (1). 4 loose numbers left. 1 file not marked: see its row.");
  expect(markedText([], 0, 2)).toBe("2 files not marked: see their rows.");
  // a restore says what it did on the same line, which said the marking ("No loose number is left" no longer holds)
  expect(restoredText("“Note: 2 samples were re-assayed on day 14” in OJ-101 plasma means.xlsx"))
    .toBe("“Note: 2 samples were re-assayed on day 14” in OJ-101 plasma means.xlsx restored: back in To do, to decide again.");
  expect(restoredText("12 like “vessel_1” … “vessel_12” in a.xlsx")).toBe("12 like “vessel_1” … “vessel_12” in a.xlsx restored: back in To do, to decide again.");
  expect(noSampleCells(["Cells say '12.3*', '>1000': mark them as 'no sample' or correct the file.", "n = 12 is read from B2"]))
    .toEqual(["12.3*", ">1000"]);
  expect(noSampleCells(["Cells say \"it's\", 'n\\\\a': mark them as 'no sample' or correct the file."])).toEqual(["it's", "n\\a"]);
  expect(noSampleCells(["Cells say 'NS': read as no sample (no value at that time)."])).toEqual([]);
});

test("a study signed on the delivery is one study in the model, its datasets counted beside it (owner-job gap 3)", () => {
  const inputs = { todo: [], compound: [], readiness: null, studies: [
    { study_id: "OJ-101", excluded: null, blinded: false, dataset_id: "ds-1" },
    { study_id: "OJ-101-Reference", excluded: null, blinded: false, dataset_id: "ds-2" },
    { study_id: "OJ-101-Test", excluded: null, blinded: false, dataset_id: "ds-3" },
    { study_id: "doe-iv-250", excluded: null, blinded: false, dataset_id: "ds-9" },
    { study_id: "left-out", excluded: "a person left it out", blinded: false, dataset_id: "ds-8" }] };
  // the landing's own list of what it loaded (the signing dialog's count) groups the rows; a study it did not land is one
  const delivery = { subjects: [{ label: "OJ-101", confirmation: { landed_datasets: ["ds-1", "ds-2", "ds-3"] } }, { label: "OJ-102", confirmation: null }] };
  expect(inModel(inputs, delivery)).toEqual({ studies: 2, datasets: 4, formulations: 0, values: 0 });
  expect(inModel(inputs, null)).toEqual({ studies: 4, datasets: 4, formulations: 0, values: 0 });
});

test("a model check whose gap a To do group lists is not said again among the model checks (OWN-14)", () => {
  const model = buildWork(load("exampleamide"));
  const s0 = model.checks.find((c) => c.raw.startsWith("S0 completeness"))!;
  // the compound values missing are rows of To do (the /inputs to-do's "missing"): said there, once
  expect(s0.ok).toBe(false);
  expect(model.items.some((i) => i.id.startsWith("todo:missing:"))).toBe(true);
  expect(s0.said).toBe(true);
  // a check no group lists stays a model check
  const sources = load("exampleamide");
  sources.inputs!.todo = sources.inputs!.todo.filter((t) => t.kind !== "missing");
  expect(buildWork(sources).checks.find((c) => c.raw.startsWith("S0 completeness"))!.said).toBe(false);
  expect(model.checks.filter((c) => c.ok).every((c) => !c.said)).toBe(true);
});

test("the minimum compound data are said by a compound value held for a person's check, not only by a missing one (OWN-14)", () => {
  // the review's exampleamide-pbpk: S0 fails on the elimination pathway, and To do lists it as a value found for it that
  // waits for a person's check (the /inputs to-do's "review" of "elim"), not as "missing"
  const sources = load("exampleamide");
  const s0 = sources.inputs!.readiness!.content!.checks.find((c) => c.check.startsWith("S0 completeness"))!;
  Object.assign(s0, { ok: false, detail: ["at least one elimination pathway (elim.* or elim.hepatic.total.plasma_clearance)"] });
  sources.inputs!.todo = [
    ...sources.inputs!.todo.filter((t) => t.kind !== "missing"),
    { kind: "review", target: "elim", tab: "compound", message: "elim = 21.0 L/h is held until a person accepts or corrects it" },
  ];
  const model = buildWork(sources);
  expect(model.items.find((i) => i.id === "todo:review:elim")?.status).toBe("to_decide");
  expect(model.checks.find((c) => c.raw.startsWith("S0 completeness"))!.said).toBe(true);
  // a value to correct says it the same way; a review on another area (a study's) does not
  sources.inputs!.todo = sources.inputs!.todo.map((t) => (t.target === "elim" ? { ...t, kind: "correct" } : t));
  expect(buildWork(sources).checks.find((c) => c.raw.startsWith("S0 completeness"))!.said).toBe(true);
  sources.inputs!.todo = sources.inputs!.todo.map((t) => (t.target === "elim" ? { ...t, kind: "review", tab: "studies" } : t));
  expect(buildWork(sources).checks.find((c) => c.raw.startsWith("S0 completeness"))!.said).toBe(false);
  // an elimination pathway's process to choose settles its S0 gap as well (the to-do lists no "missing" for it then);
  // another pathway's process does not
  sources.inputs!.todo = sources.inputs!.todo.map((t) => (t.target === "elim"
    ? { ...t, kind: "process", target: "elim.hepatic.CYP3A4", tab: "compound" } : t));
  expect(buildWork(sources).checks.find((c) => c.raw.startsWith("S0 completeness"))!.said).toBe(true);
  sources.inputs!.todo = sources.inputs!.todo.map((t) => (t.kind === "process" ? { ...t, target: "abs.transporter.Pgp" } : t));
  expect(buildWork(sources).checks.find((c) => c.raw.startsWith("S0 completeness"))!.said).toBe(false);
  // nothing of the compound listed: the check stays among the model checks
  sources.inputs!.todo = sources.inputs!.todo.filter((t) => t.kind !== "process");
  expect(buildWork(sources).checks.find((c) => c.raw.startsWith("S0 completeness"))!.said).toBe(false);
});

test("a study's individual in words: what it is, and what it still needs, never an id or a field name (OWN-6)", () => {
  expect(individualText({ population: "European_ICRP_2002", sex: "FEMALE", age_years: 32, age_min: 21, age_max: 45, weight_kg: 74 }))
    .toBe("European ICRP 2002 · female · 32 y (21 to 45) · 74 kg");
  expect(individualNeeds(["individual_population", "individual_sex"], ""))
    .toBe("the study's individual needs the PK-Sim population and the sex simulated: give them with the demographics");
  expect(individualNeeds([], "age_mean (f-3) is not a number; individual_population (f-4) is not one of PK-Sim's"))
    .toBe("mean age (years) is not a number; PK-Sim population is not one of PK-Sim's: give them with the demographics");
  // the landing's held lines, as the card and the signing dialog say them
  expect(heldText("OJ-101: demographics not yet the study's individual (age_mean, weight_mean_kg, percent_female): kept in the ledger; "
                  + "the individual needs individual_population, individual_sex", "OJ-101"))
    .toBe("Kept, not used by the model yet: mean age (years), mean weight (kg), women (%) (the study's individual needs the PK-Sim "
          + "population and the sex simulated: give them with the demographics)");
  expect(heldText("OJ-101: demographics not yet the study's individual (age_mean): kept in the ledger; the individual needs "
                  + "individual_population (age_mean (f-12) is written in 'months', not years)", "OJ-101"))
    .toBe("Kept, not used by the model yet: mean age (years) (the study's individual needs the PK-Sim population; mean age (years) "
          + "is written in “months”, not years: give them with the demographics)");
  expect(heldText("OJ-101: demographics the individual does not carry (percent_female): kept in the ledger; the study's individual "
                  + "is one sex and one PK-Sim population, chosen by a person", "OJ-101"))
    .toBe("Kept, not used by the model: women (%) (the study's individual is one sex and one PK-Sim population, chosen by a person)");
});

test("the spot check says why so many values are drawn, from the draw's own reasons (OWN-9; the number drawn is the rules')", () => {
  const reasons = [...Array(4).fill("always:field"), ...Array(13).fill("always:derived"), ...Array(100).fill("table_kind=pk_individual")];
  expect(drawText(reasons)).toBe("117 values drawn: 4 key facts of the study, 13 computed from other values are always checked; "
                                 + "100 are a random sample");
  expect(drawText(["always:cross_file", "always:cross_file", "unit_class=time"]))
    .toBe("3 values drawn: 2 read from another file than the study's own are always checked; 1 is a random sample");
  expect(drawText(["always:field"])).toBe("1 value drawn: 1 key fact of the study is always checked");
  expect(drawText(["unit_class=concentration", "unit_class=concentration"])).toBe("2 values drawn: a random sample");
});

test("saving a person's entry says before Save that the spot check is drawn again, and which ticks carry over (round 3)", () => {
  const spot = { state: "complete", drawn: 117, always: 17, recorded_by: "dev-user", recorded_at: "2026-11-15T09:42:17.337Z" };
  // the review's 230-23: recorded; the values always checked are drawn again with their ticks, the sample is drawn anew
  expect(redrawText(spot)).toMatch(/^Saving this changes what the spot check was drawn from, so it is drawn again\. Of the 117 values ticked \(recorded by dev-user on 15 Nov 2026, \d\d:42\), the 17 always checked keep their ticks; the 100 drawn at random are drawn anew, and only those drawn again keep theirs\.$/);
  expect(redrawText({ ...spot, drawn: 3, always: 0 })).toMatch(/Of the 3 values ticked \(.*\), all were drawn at random: they are drawn anew, and only those drawn again keep their ticks\.$/);
  expect(redrawText({ ...spot, drawn: 2, always: 2 })).toMatch(/Of the 2 values ticked \(.*\), all are always checked and keep their ticks\.$/);
  expect(redrawText({ ...spot, drawn: 18, always: 17 })).toMatch(/the 17 always checked keep their ticks; the 1 drawn at random is drawn anew, and keeps its tick only if drawn again\.$/);
  // drawn, its ticks not recorded: they are not kept; none drawn, or stale already: nothing to say
  expect(redrawText({ ...spot, state: "drawn", recorded_by: null, recorded_at: null }))
    .toBe("Saving this changes what the spot check was drawn from, so it is drawn again: ticks not recorded yet are not kept.");
  expect(redrawText({ ...spot, state: "none" })).toBeNull();
  expect(redrawText({ ...spot, state: "stale" })).toBeNull();
  // each card decision that changes what the spot check is drawn from says why, in its own words (final review round 4,
  // each checked against the API's rule: test_the_card_says_which_decisions_draw_its_spot_check_again_as_the_review_rule_does)
  const lead = (why: Parameters<typeof redrawText>[1]) => redrawText({ ...spot, state: "drawn", recorded_by: null, recorded_at: null }, why);
  expect(lead({ kind: "accepted", values: 2 }))
    .toBe("Accepted as is, its values are always checked, and 2 of them are not in the spot check, so it is drawn again: ticks not recorded yet are not kept.");
  expect(lead({ kind: "accepted", values: 1 })).toMatch(/^Accepted as is, its values are always checked, and 1 of them is not in the spot check, so it is drawn again/);
  expect(lead({ kind: "analyte", values: 3 }))
    .toMatch(/^Stating the analyte computes the 3 values derived from these again \(a spread worked out from another\), so the spot check is drawn again:/);
  expect(lead({ kind: "kept" })).toMatch(/^Keeping one value sets the others aside, which changes what the spot check was drawn from, so it is drawn again:/);
  expect(lead({ kind: "refused" })).toMatch(/^Saying no takes the file's values out of the study, so the spot check is drawn again:/);
  expect(lead({ kind: "joined" })).toMatch(/^Saying yes joins the file's study and its values to this one, so the spot check is drawn again:/);
  expect(redrawText(spot, { kind: "kept" })).toMatch(/so it is drawn again\. Of the 117 values ticked \(recorded by dev-user on 15 Nov 2026, \d\d:42\), the 17 always checked/);
  expect(redrawText({ ...spot, state: "stale" }, { kind: "kept" })).toBeNull();
});

test("a table is told apart by where it starts in its file, a sheet form's chart by its source's file (round 4, A11Y-7)", () => {
  const sha = "254812adf39fbd9ff97d2ffa2b9fee5b59ad1a2f9198aae8bc75bbbcb1e92f31";
  expect(anchorPlace(`${sha}@pdfplumber/1.0+pdfplumber0.11.10#p:4/t:1/r:2/c:2@116.00`)).toBe("page 4, table 1");
  expect(anchorPlace(`${sha}@pdfplumber/1.0+pdfplumber0.11.10#p:5/t:1/r:2/c:2@116.00`)).toBe("page 5, table 1");
  expect(anchorPlace(`${sha}@workbook/1.0+openpyxl3.1.5#s:'Fasting'!B22`)).toBe("sheet Fasting from cell B22");
  expect(anchorPlace(`${sha}@workbook/1.0+openpyxl3.1.5#s:'Fasting'!B4:F9`)).toBe("sheet Fasting from cell B4");
  // nothing a person reads: no place said
  expect(anchorPlace(null)).toBe("");
  expect(anchorPlace(`${sha}@reader/1.0`)).toBe("");
  expect(anchorPlace(`${sha}@reader/1.0#zz:9`)).toBe("");
  const label = "Study EX-101: profile · 1 series · parent, plasma";
  expect(sourceNamed(label, { title: "EX-101_PK_sheet.xlsx", locator: "PK!A2:F10" })).toBe(`${label} · EX-101_PK_sheet.xlsx`);
  expect(sourceNamed(label, { locator: "PK_Summary!2:7" })).toBe(`${label} · sheet PK_Summary, rows 2 to 7`);
  expect(sourceNamed(label, { page: 3 })).toBe(`${label} · page 3`);
  expect(sourceNamed(label, null)).toBe(label);
});

test("a value is named by its field in words, its labels, conditions, statistic and file; two alike by their cell (round 5, A11Y-7)", () => {
  // the owner's 230-23: four urine intervals of one excretion table, read with the same labels; only the interval tells
  // them apart, and their field is the intake's `excretion.amount`
  const sha = "d8ffbf082f542e9aac89d7780cad3e03a724ed5dd7f8360355ed03f50f2288b8";
  const urine = [["0", "4", "C3"], ["4", "8", "C4"], ["8", "12", "C5"], ["12", "24", "C6"]].map(([from, to, cell]) => ({
    field: "excretion.amount", time: null, time_unit: null, labels: { analyte: "Exampleamide", matrix: "urine" },
    conditions: { interval_end_h: to, interval_start_h: from }, statistic: null, file: "messy-delivery.xlsx", method: "table",
    anchor: `${sha}@workbook/1.0+openpyxl3.1.5#s:'Urine'!${cell}`,
  }));
  const names = urine.map((v) => valueAbout(v));
  expect(names[0]).toBe("the amount excreted, analyte Exampleamide · matrix urine, interval 0 to 4 h, from messy-delivery.xlsx");
  expect(new Set(names).size).toBe(4);
  for (const n of names) expect(n).not.toMatch(/excretion\.amount|interval_start_h|_h\b/);
  // a time with its unit, the statistic in words, the card's own label left to the card
  const cmax = { field: "pk.Cmax", time: null, labels: { study: "230-23", analyte: "Exampleamide" }, conditions: {}, statistic: "arithmetic_mean",
                 file: "messy-delivery.xlsx" };
  expect(valueAbout(cmax, "study")).toBe("the Cmax (PK parameter), analyte Exampleamide, arithmetic mean, from messy-delivery.xlsx");
  expect(valueAbout({ field: "concentration", time: 0.5, time_unit: "h", labels: { subject: "001" }, statistic: "individual", file: "a.xlsx" }))
    .toBe("the concentration at 0.5 h, subject 001, individual, from a.xlsx");
  expect(valueAbout({ field: "food_state", time: null, labels: {}, method: "person" })).toBe("the fasted or fed state, entered by a person");
  // conditions in words, never the intake's ids: the interval in hours, a dissolution run's medium and pH
  expect(conditionsInWords({ interval_start_h: "0", interval_end_h: "4" })).toBe("interval 0 to 4 h");
  expect(conditionsInWords({ interval_start_h: "24" })).toBe("interval from 24 h");
  expect(conditionsInWords({ medium: "phosphate buffer", ph: "6.8", rpm: "50" })).toBe("medium phosphate buffer · pH 6.8 · stirring (rpm) 50");
  expect(conditionsInWords({})).toBe("");
  expect(layoutFieldInText("excretion.amount")).toBe("amount excreted");
  expect(layoutFieldInText("pk.AUC_last")).toBe("AUC last (PK parameter)");
  // two names alike are told apart by where each value is in its file; a name of its own is kept as it is
  const alike = [{ ...urine[0], conditions: {} }, { ...urine[1], conditions: {} }, { ...cmax, anchor: null }];
  expect(distinctNames(alike.map((v) => valueAbout(v)), alike.map((v) => anchorCell(v.anchor)))).toEqual([
    "the amount excreted, analyte Exampleamide · matrix urine, from messy-delivery.xlsx, sheet Urine, cell C3",
    "the amount excreted, analyte Exampleamide · matrix urine, from messy-delivery.xlsx, sheet Urine, cell C4",
    "the Cmax (PK parameter), study 230-23 · analyte Exampleamide, arithmetic mean, from messy-delivery.xlsx",
  ]);
  expect(anchorCell(`${sha}@pdfplumber/1.0+pdfplumber0.11.10#p:4/t:1/r:2/c:2@116.00`)).toBe("page 4, table 1");
  expect(anchorCell(`${sha}@reader/1.0#zz:9`)).toBe("");
  expect(anchorCell(null)).toBe("");
  // a file's tables and texts, in the reading under its row: the table's kind once read, never "table, pk individual"
  expect(regionKindText("table", "pk_individual")).toBe("individual PK table");
  expect(regionKindText("table", "unknown")).toBe("table");
  expect(regionKindText("prose", null)).toBe("text");
  expect(regionKindText("table_like_text")).toBe("text laid out as a table");
});

test("a values table whose rows need only checks decided in Checks stays one line naming each with its count (OWN-9)", () => {
  // the owner's 230-23 (review copy cut to seq 12): an arm's 76 concentrations name no analyte, and 6 of them also state
  // more than one LLOQ in their profile, because of the same missing analyte; that check marks 3 values of another table
  const rows = Array.from({ length: 76 }, (_, i) => ({ id: `tx-1#${i}` }));
  const analyte = { id: "ck-1", values: rows.map((r) => r.id) };
  const lloq = { id: "ck-2", values: [...rows.slice(10, 16).map((r) => r.id), "tx-2#0", "tx-2#1", "tx-2#2"] };
  const elsewhere = { id: "ck-9", values: ["tx-2#5"] };
  const listed = () => true;
  expect(foldChecks(rows, [lloq, analyte, elsewhere], listed, [])).toEqual([{ check: analyte, count: 76 }, { check: lloq, count: 6 }]);
  expect(foldChecks(rows, [analyte], listed, [])).toEqual([{ check: analyte, count: 76 }]);
  // a row in a disagreement, or a check that is not listed in Checks (a fact's, a required item's): the table opens
  expect(foldChecks(rows, [analyte, lloq], listed, [{ values: ["tx-1#5", "tx-2#5"] }])).toBeNull();
  expect(foldChecks(rows, [analyte, lloq], (c) => c !== lloq, [])).toBeNull();
  // a disagreement or an unlisted check of another table's rows changes nothing here
  expect(foldChecks(rows, [analyte, elsewhere], (c) => c !== elsewhere, [{ values: ["tx-2#5"] }])).toEqual([{ check: analyte, count: 76 }]);
  // no row needs the person: nothing to fold under (the table is folded anyway, and says nothing)
  expect(foldChecks(rows, [], listed, [])).toBeNull();
  expect(foldChecks(rows, [elsewhere], listed, [])).toBeNull();
  // a value named twice by one check counts once
  expect(foldChecks(rows.slice(0, 2), [{ id: "ck-3", values: ["tx-1#0", "tx-1#0"] }], listed, [])).toEqual([{ check: { id: "ck-3", values: ["tx-1#0", "tx-1#0"] }, count: 1 }]);
  // each check is named by what is wrong, from its own message
  expect(checkGist("arm Reference, analyte not stated, matrix plasma: the profile states more than one LLOQ; PK-Sim takes one per observed dataset"))
    .toEqual({ where: "arm Reference, analyte not stated, matrix plasma", gist: "the profile states more than one LLOQ" });
  expect(checkGist("arm Test, analyte not stated, matrix plasma: concentrations name no analyte").gist).toBe("concentrations name no analyte");
  expect(checkGist('concentration: values above the range (written ">x"): no number is kept').gist).toBe('values above the range (written ">x")');
  expect(checkGist("doses with no stated basis (salt or free base)")).toEqual({ where: "", gist: "doses with no stated basis (salt or free base)" });
});

test("round 5: a read on its way when a decision's answer is written is told apart by when it was asked for", () => {
  // the decision sent at 100: a read asked for before it (a poll, the end of a reading) is called off, the answer holds
  // what it was asked for; one asked for since and not yet out goes out after the answer and is left; one sent since may
  // have been answered before the decision or after it, so it is called off and the answer read once more (round 4 kept
  // the decision's answer, which could be the older)
  expect(afterAnswer(null, 100)).toBe("none");
  expect(afterAnswer({ asked: 90, sent: 91 }, 100)).toBe("cancel");
  expect(afterAnswer({ asked: 90, sent: null }, 100)).toBe("cancel");          // waiting its turn since before: the answer covers it
  expect(afterAnswer({ asked: 100, sent: null }, 100)).toBe("keep");
  expect(afterAnswer({ asked: 120, sent: 150 }, 100)).toBe("again");
  expect(afterAnswer({ asked: 100, sent: 100 }, 100)).toBe("again");
  // a decision whose time is not known: a read that went out cannot be told apart either
  expect(afterAnswer({ asked: 90, sent: 91 }, null)).toBe("again");
  expect(afterAnswer({ asked: 90, sent: null }, null)).toBe("keep");
});

test("round 5: the delivery rows a new answer changed, and whether a subject's blinding did", () => {
  const before = copy(load("exampleamide").delivery!);
  const ref = (label: string) => { const s = before.subjects.find((x) => x.label === label)!; return `${s.subject_type}/${s.subject}`; };
  // nothing read before: no card was drawn from it, nothing to follow
  expect(changedRows(undefined, before)).toEqual({ changed: [], blinding: false });
  expect(changedRows(before, copy(before))).toEqual({ changed: [], blinding: false });
  // a study signed: only its own row changes (the decision's answer is its card)
  const signed = copy(before);
  signed.subjects.find((s) => s.label === "230-23")!.values += 1;
  expect(changedRows(before, signed)).toEqual({ changed: [ref("230-23")], blinding: false });
  // the landing has the MS-01 split propose S5 for it: the study and the product that holds its values are blinded
  const landed = copy(signed);
  for (const label of ["230-23", "Exampleamide IR tablet"]) {
    const row = landed.subjects.find((s) => s.label === label)!;
    row.blinded = true;
    row.blinded_why = label === "230-23" ? "the study split proposes it for S5 (external validation), before a plan"
      : "it holds the values of a blinded study";
  }
  expect(changedRows(before, landed)).toEqual({ changed: [ref("230-23"), ref("Exampleamide IR tablet")], blinding: true });
  // a row whose reason alone changed is a change of its blinding too; any other field a card shows is a change of the row
  const why = copy(landed);
  why.subjects.find((s) => s.label === "230-23")!.blinded_why = "the plan places it in S5 (external validation)";
  expect(changedRows(landed, why)).toEqual({ changed: [ref("230-23")], blinding: true });
  const joined = copy(before);
  const cl = joined.subjects.find((s) => s.label === "CL-01")!;
  cl.legacy_groups = [...cl.legacy_groups, "sheet:CL-01 sheet 2"];          // a sheet the sheet form read joins its card
  expect(changedRows(before, joined)).toEqual({ changed: [ref("CL-01")], blinding: false });
  // a new subject is a change (no card of it is held yet); a blinded new one changes what is withheld elsewhere
  const more = copy(before);
  more.subjects.push({ ...copy(before.subjects[0]), subject: "st-99", label: "NEW-1", blinded: true,
                       blinded_why: "it is entered for external validation on its card" });
  expect(changedRows(before, more)).toEqual({ changed: [`${before.subjects[0].subject_type}/st-99`], blinding: true });
});

test("round 5: the studies the blinding list withholds, as the inputs name them, in one string", () => {
  expect(blindedStudies(null)).toBeNull();
  expect(blindedStudies({ studies: [] })).toBe("");
  const studies = [{ study_id: "po-50", blinded: true }, { study_id: "iv-250", blinded: false }, { study_id: "iv-500", blinded: true }];
  expect(blindedStudies({ studies })).toBe("iv-500|po-50");
  // a sheet form's study the split proposes for S5 once it is confirmed: one more name, so what the list withholds is read again
  expect(blindedStudies({ studies: [...studies, { study_id: "CL-01", blinded: true }] })).toBe("CL-01|iv-500|po-50");
  // the order of the rows or a left-out duplicate changes nothing
  expect(blindedStudies({ studies: [...studies].reverse().concat({ study_id: "po-50", blinded: true }) })).toBe("iv-500|po-50");
});
