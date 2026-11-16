// T-47 / T-49: the owner's whole job on Inputs, end to end on its own seed (plan docs/plans/2026-11-14-inputs-task-first.md
// §2.2.7): files uploaded → layouts checked → values linked (arms) → facts filled → signed → visible "In the model".
// Four workbooks of the made-up study OJ-101 (e2e/fixtures/owner_job.py) arrive through the head's Add data. Then, only
// through the page and starting where it says (To do and its "Next"): the one table layout that waits is approved in
// To do's queue, with a reason; the values of three files that name no study are linked: the study's two arms (the same
// subjects and periods) are first refused one arm of OJ-101 and given an arm each, and a file naming no study goes to a
// new study; the working note with a number is marked as not data; the study's card, opened from its To do row, gets
// the facts no file states (in its one facts form, with one reason and one submission: the dosage form the oral route
// asks for is offered as soon as the route is chosen) and its demographics with the individual PK-Sim simulates (its
// population database and sex, the person's choice); the spot check is ticked, recorded and folded to its result; the
// decisions listed on the card each name who made it and why; the card is confirmed and signed (the DEV sign-in carries a
// fresh step-up); then the card says who signed, when and what loaded (the dialog's, the card's and the status line's
// counts agree: one study, three datasets), To do fell to what remains and does not ask for the demographics again, and
// GET /inputs holds the study's data, its individual included, for what comes after Inputs. At every step the status line, the area badges, To do's filter and its groups (and the
// Clinical studies head) count the same open work; the sheet form's own reading of a file linked on the delivery joins the
// card it was linked to (no second card). Software test data on the stub engine: it proves the review path, never a model.
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { AUTH, finishStart } from "./fixtures/inputs";

const REPO = resolve(__dirname, "../../..");
const NEW = "__new__";
const AREAS = ["compound", "formulations", "studies", "individuals", "settings", "files"] as const;

type File = { file_id: string; name: string };
type Delivery = {
  running: boolean; deliveries: { files: File[] }[];
  subjects: { subject: string; label: string; subject_type: string; arms: { id: string; label: string }[]; legacy_groups: string[] }[];
  unassigned: { file: string | null; level: string }[];
  mappings: { mapping_id: string; version: number; kind: string; status: string; waiting: boolean }[];
};
type Study = { study_id: string; purpose: string | null; facts: Record<string, unknown>; demographics: string };

async function shot(page: Page, name: string) {
  await page.screenshot({ path: test.info().outputPath(`${name}.png`), fullPage: true });
}

/** What the page counts, read at one moment: the status line's three words, each area's badge, To do's "All" and the
 *  open rows of each of its groups (when To do is shown), and the Clinical studies head (when it is shown). */
async function snapshot(page: Page) {
  return page.evaluate((areas) => {
    const q = (id: string) => document.querySelector<HTMLElement>(`[data-testid="${id}"]`);
    const n = (el: Element | null | undefined) => (el ? Number(/\d+/.exec(el.textContent ?? "")?.[0] ?? 0) : 0);
    const badge = (tab: string) => n(q(`tab-${tab}`)?.querySelector(".tab-count"));
    const groups = [...document.querySelectorAll('section.todo-group[data-testid^="todo-group-"]')]
      .filter((s) => !/^todo-group-(ask|checks)$/.test(s.getAttribute("data-testid") ?? ""))
      .map((s) => n(s.querySelector("h3 .muted")));
    const head = q("area-head-studies")?.textContent ?? null;
    return {
      checking: Boolean(q("status-checking")),
      // a layout whose files are being read again is shown "Reading…" and is not counted until the reading ends
      reading: [...document.querySelectorAll(".chip")].some((c) => c.textContent?.trim() === "Reading…"),
      missing: n(q("status-missing")), confirm: n(q("to-confirm-count")), decide: n(q("status-decide")),
      todo: badge("todo"), areas: Object.fromEntries(areas.map((a) => [a, badge(a)])) as Record<string, number>,
      all: q("todo-filter-all") ? n(q("todo-filter-all")) : null,
      groups: q("still-missing") ? groups : null,
      studiesHead: head === null ? null : [...head.matchAll(/(\d+) (?:missing|to confirm|to decide)/g)].reduce((s, m) => s + Number(m[1]), 0),
      inModel: q("status-in-model")?.textContent ?? "",
    };
  }, [...AREAS]);
}
type Snapshot = Awaited<ReturnType<typeof snapshot>>;

/** The counts once the page has read every card and no file is being read again, checked to agree: the status line's
 *  open work = the To do badge = the
 *  sum of the area badges (= To do's "All" = the sum of its groups' open rows, on To do), and the Clinical studies head =
 *  its badge (on Clinical studies). Waits on the page's state, never on time. */
async function agreed(page: Page): Promise<Snapshot> {
  let last: Snapshot | null = null;
  await expect.poll(async () => {
    const s = (last = await snapshot(page));
    if (s.checking) return "checking cards…";
    if (s.reading) return "files being read again…";
    const chain = [s.missing + s.confirm + s.decide, s.todo, Object.values(s.areas).reduce((a, b) => a + b, 0),
                   ...(s.all === null ? [] : [s.all]), ...(s.groups === null ? [] : [s.groups.reduce((a, b) => a + b, 0)])];
    return `open ${chain.join(" = ")}${s.studiesHead === null ? "" : ` · studies ${s.studiesHead} = ${s.areas.studies}`}`;
  }, { message: "the status line, the area badges and To do count the same open work", timeout: 30_000 })
    .toMatch(/^open (\d+)(?: = \1)+(?: · studies (\d+) = \2)?$/);
  return last!;
}
const open = (s: Snapshot) => s.missing + s.confirm + s.decide;
const studiesInModel = (s: Snapshot) => Number(/In the model: (\d+) stud/.exec(s.inModel)?.[1] ?? NaN);

test("the owner's job: files uploaded, layouts checked, values linked with arms, facts filled, signed, in the model", async ({ page, request }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: "Exampleamide", extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nOral tablet, 50 mg.") } } });
  const projectId = (await started.json()).data.project_id as string;
  await finishStart(request, projectId);
  expect((await request.post(`/api/v1/projects/${projectId}/requirements:derive`, { headers: AUTH })).ok()).toBeTruthy();
  const api = `/api/v1/projects/${projectId}`;
  const read = async <T,>(r: APIRequestContext, path: string) => (await (await r.get(`${api}/${path}`, { headers: AUTH })).json()).data as T;

  // the seed: four workbooks, and the means table's layout signed off earlier (owner_job.py)
  const dir = mkdtempSync(join(tmpdir(), "owner-job-"));
  const printed = execFileSync("uv", ["run", "python", join(__dirname, "fixtures", "owner_job.py"),
                                      join(process.env.E2E_DATA_DIR!, "read-root"), projectId, dir], { cwd: REPO }).toString();
  const seed = JSON.parse(printed.trim().split("\n").pop()!) as { files: string[]; study: string; stray: string };

  // --- files uploaded: through the head's Add data, as the study's files; read by code (no AI on this server) ---
  await page.goto(`/projects/${projectId}/inputs`);
  await expect(page.getByTestId("tab-todo")).toHaveAttribute("aria-selected", "true");     // it opens on To do
  const next = page.getByTestId("inputs-next");
  await expect(next).toHaveText("Next: Fill in Molecular weight");                        // the compound values, as yet
  const empty = await agreed(page);
  expect(studiesInModel(empty)).toBe(0);
  await page.getByTestId("inputs-add-data").click();
  const chooser = page.waitForEvent("filechooser");
  await page.getByTestId("add-files-studies").click();
  await (await chooser).setFiles(seed.files.map((name) => join(dir, name)));
  // both readers have read the four files (the delivery and the sheet form)
  await expect.poll(async () => {
    const d = await read<Delivery | null>(request, "delivery");
    const c = await read<{ running: boolean } | null>(request, "client-data");
    return Boolean(d && !d.running && d.deliveries.flatMap((x) => x.files).length === 4 && c && !c.running);
  }, { timeout: 300_000, intervals: [2000] }).toBe(true);
  const delivery = await read<Delivery>(request, "delivery");
  const files = delivery.deliveries.flatMap((d) => d.files);
  const fid = (name: string) => files.find((f) => f.name === name)!.file_id;
  const ref = fid(`${seed.study} Reference.xlsx`), tst = fid(`${seed.study} Test.xlsx`), lab = fid("lab-export-0412.xlsx");
  const means = fid(`${seed.study} plasma means.xlsx`);
  const study = delivery.subjects.find((s) => s.label === seed.study)!.subject;       // named by the means file only
  const waiting = delivery.mappings.filter((m) => m.status === "proposed");
  expect(waiting.map((m) => m.kind)).toEqual(["pk_individual"]);                     // one layout waits, for 3 tables
  const layout = waiting[0].mapping_id;
  expect(delivery.unassigned).toHaveLength(156);                                     // 3 files of 52 values, no study

  // the work is in To do, in the order it is done: one layout to check, three files to link, one file with a number not read
  await expect(page.getByTestId("todo-group-layouts")).toBeVisible({ timeout: 60_000 });
  // counted once the page has read that its files are no longer being read (a layout being read again is "Reading…" and
  // not counted): the API's reading has ended, and so has the page's, before the counts are taken (a snapshot taken while
  // the layout's row still read "Reading…" counted one decision fewer)
  await expect.poll(async () => {
    const d = await read<Delivery>(request, "delivery");
    return !d.running && d.mappings.every((m) => !m.waiting);
  }, { timeout: 120_000, intervals: [1000] }).toBe(true);
  await expect(page.getByTestId(`todo-layout-${layout}`)).not.toContainText("Reading…");
  await expect(page.getByTestId("todo-group-layouts").locator("h3 .muted")).toHaveText("(1)");
  await expect(page.getByTestId("todo-group-link").locator("h3")).toContainText("(3)");
  await expect(page.getByTestId("todo-group-notread").locator("h3")).toContainText("(1)");
  await expect(page.getByTestId("todo-gate")).toContainText("1 table layout to check · 3 files to link · 1 file with numbers not read");
  const arrived = await agreed(page);
  expect(open(arrived)).toBeGreaterThan(open(empty));
  await shot(page, "1-arrived");

  // --- layouts checked: Next opens the queue's row; the layout is read in its dialog and approved, with a reason ---
  await expect(next).toHaveText("Next: Check 1 table layout");
  await next.click();
  const queue = page.getByTestId("layout-queue");
  await expect(queue.locator(".just-opened")).toHaveAttribute("data-testid", `todo-layout-${layout}`);
  await expect(queue.locator(".just-opened")).toBeInViewport();
  await expect(queue.getByTestId(`todo-layout-${layout}`)).toContainText("and 2 more files");
  await queue.getByTestId(`delivery-mapping-open-${layout}`).click();
  const dialog = page.getByTestId("delivery-mapping-dialog");
  await expect(dialog.getByTestId("mapping-position")).toHaveText("1 of 1");
  await expect(dialog.getByTestId("mapping-status")).toHaveText("waits for approval");
  await expect(dialog.getByTestId("mapping-columns")).toContainText("Subject No.");
  await expect(dialog.getByTestId("mapping-columns")).toContainText("Period");
  await expect(dialog.getByTestId("mapping-sample").locator("tbody td").filter({ hasText: /\d/ })).toHaveCount(0);   // values masked
  await dialog.getByTestId("mapping-approve-why").fill("checked against the files: subjects and periods down, times in hours across");
  await dialog.getByTestId("mapping-approve-submit").click();
  // said once, in the dialog's own live region; not a second time by To do's under it (final review A11Y-6)
  const approved = "Version 1 of the individual PK table layout is approved: 3 files of this layout are read again.";
  await expect(dialog.getByTestId("mapping-said")).toHaveText(approved);
  await expect(page.getByTestId("todo-live")).not.toContainText(approved);
  expect((await read<{ status: string }>(request, `delivery/mappings/${layout}?version=${waiting[0].version}`)).status).toBe("approved");
  // the three files are read again with the approved layout before anything is linked
  await expect.poll(async () => {
    const d = await read<Delivery>(request, "delivery");
    return !d.running && d.unassigned.length === 156 && d.unassigned.every((v) => v.level === "approved_mapping");
  }, { timeout: 120_000, intervals: [1000] }).toBe(true);
  await expect(page.getByTestId("todo-group-layouts")).toHaveCount(0);
  // its row and its group have left To do; the dialog is To do's and stays, still saying what was done, until the person
  // closes it (gap 2); the focus then goes to To do's title, the group's heading being gone
  await expect(dialog).toBeVisible();
  await expect(dialog.getByTestId("mapping-said")).toHaveText(approved);
  await dialog.getByTestId("mapping-close").click();
  await expect(dialog).toHaveCount(0);
  await expect(page.locator(":focus")).toHaveAttribute("id", "todo-title");
  const checked = await agreed(page);
  expect(checked.decide).toBe(arrived.decide - 1);

  // --- values linked: Next opens the link table; the two arms are refused one arm of OJ-101, given one each, linked ---
  await expect(next).toHaveText("Next: Link the values of 3 files");
  await next.click();
  const table = page.getByTestId("link-table");
  await expect(table.locator(".just-opened")).toHaveCount(1);
  await expect(table.locator("li.batch-row")).toHaveCount(3);
  // counted as the rows count them (final review OWN-16): 156 values to link, 144 in tables and 12 facts read beside them
  await expect(table.getByTestId("link-table-count")).toHaveText("3 files · 144 values and 12 facts");
  await expect(table.getByTestId(`link-${ref}`)).toContainText("individual PK table, 48 values · analyte Exampleamide · dose 50 mg · fasted · LLOQ 0.5 ng/mL");
  await expect(table.getByTestId(`link-to-${ref}`)).toContainText("The sheet form read it as OJ-101-REF. Same study as OJ-101?");
  await expect(table.getByTestId(`link-to-${lab}`)).toContainText("not chosen yet");     // it names no study
  let assigns = 0;
  page.on("request", (r) => { if (r.method() === "POST" && r.url().endsWith("/values:assign")) assigns += 1; });
  await table.getByTestId(`link-pick-${ref}`).check();
  await table.getByTestId(`link-pick-${tst}`).check();
  const bar = page.getByTestId("bulk-link-bar");
  await expect(bar.getByTestId("bulk-link-bar-count")).toHaveText("2 files picked");
  await bar.getByTestId("bulk-link-one").check();
  await bar.getByTestId("link-study-bulk").selectOption({ label: seed.study });
  // each file's analyte is an entity of its own, both called Exampleamide: offered once, and "as the file says" names
  // what the picked files state (review OWN-11, this job's gap 8)
  const analyte = bar.getByTestId("link-analyte-bulk");
  await expect(analyte.locator("option").first()).toHaveText("as each file says (Exampleamide)");
  await expect(analyte.locator("option", { hasText: /^Exampleamide$/ })).toHaveCount(1);
  // each file names Exampleamide, read as an analyte of its own: still one analyte, so the two collide
  await expect(bar.getByTestId("link-collision")).toContainText(
    "OJ-101 Reference.xlsx and OJ-101 Test.xlsx both hold subject 001, period I: in study OJ-101 each file needs its own arm.");
  await bar.getByTestId("bulk-link-why").fill("the two arms of study OJ-101, as their titles say");
  await bar.getByTestId("bulk-link-submit").click();
  await expect(bar.getByTestId("bulk-link-missing")).toHaveText("Give each file its own arm first (above)");
  expect(assigns).toBe(0);                                                   // refused before anything is sent
  await shot(page, "2-refused");
  await expect(bar.getByTestId(`link-collision-arm-${ref}`)).toHaveValue("Reference");
  await expect(bar.getByTestId(`link-collision-arm-${tst}`)).toHaveValue("Test");
  await bar.getByTestId("link-collision-apply").click();
  await expect(bar.getByTestId("link-collision")).toHaveCount(0);
  await expect(table.getByTestId(`link-to-${ref}`)).toContainText("→ study OJ-101 · arm Reference (new)");
  await expect(table.getByTestId(`link-to-${tst}`)).toContainText("→ study OJ-101 · arm Test (new)");
  await bar.getByTestId("bulk-link-submit").click();
  await expect(table.getByTestId(`link-${ref}`)).toHaveCount(0);
  await expect(table.getByTestId(`link-${tst}`)).toHaveCount(0);
  expect(assigns).toBe(2);                                                   // one call per destination
  // the arms the batch made are named as they now are (review CODE-10)
  await expect(page.getByTestId("todo-live")).toContainText("linked to study OJ-101 · arm Reference; study OJ-101 · arm Test.");
  // the file that names no study: to a new study, from its row's editor
  await table.getByTestId(`link-open-${lab}`).click();
  const editor = table.getByTestId(`link-editor-${lab}`);
  await editor.getByTestId(`link-study-${lab}`).selectOption(NEW);
  await editor.getByTestId(`link-new-study-${lab}`).fill("OJ-102");
  await editor.getByTestId(`link-edit-${lab}-why`).fill("the 25 mg fed pilot sent with OJ-101; the client calls it OJ-102");
  await editor.getByTestId(`link-edit-${lab}-submit`).click();
  await expect(page.getByTestId("link-table")).toHaveCount(0);
  expect(assigns).toBe(3);
  await expect(page.getByTestId("todo-live")).toContainText("lab-export-0412.xlsx linked to study OJ-102 · analyte Exampleamide.");
  await expect(page.getByTestId("todo-live")).toContainText("Every file is linked.");
  const linked = await read<Delivery>(request, "delivery");
  expect(linked.unassigned).toHaveLength(0);
  expect(linked.subjects.find((s) => s.subject === study)!.arms.map((a) => a.label).sort()).toEqual(["Reference", "Test"]);
  expect(linked.subjects.map((s) => s.label)).toContain("OJ-102");
  // the sheet form read the linked files under names of its own (OJ-101-REF, OJ-101-TEST, and one for the file that names
  // no study): each is named on the subject its file's values were linked to (review OWN-4, INT-9; this job's gap 4), so
  // it joins that card: no card, no Confirm and no "not stated" row of its own
  const joinedTo = (label: string) => linked.subjects.find((s) => s.label === label)!.legacy_groups;
  expect(joinedTo(seed.study)).toEqual(expect.arrayContaining([`study:${seed.study}-REF`, `study:${seed.study}-TEST`]));
  expect(joinedTo("OJ-102")).toHaveLength(1);
  await agreed(page);
  for (const group of [...joinedTo(seed.study), ...joinedTo("OJ-102")]) {
    await expect(page.getByTestId(`todo-confirm-${group}`)).toHaveCount(0);
    await expect(page.locator(`[data-testid^="todo-row-draft:"]`, { hasText: group.replace(/^study:/, "") })).toHaveCount(0);
  }

  // --- the number outside the tables: Next opens its file's row; marked as not data, with a reason ---
  await expect(next).toHaveText("Next: Numbers not read in 1 file");
  await next.click();
  const notRead = page.getByTestId("notread-table");
  await expect(notRead.locator(".just-opened")).toHaveAttribute("data-testid", `notread-${means}`);
  await notRead.getByTestId(`notread-open-${means}`).click();
  await expect(notRead.getByTestId(`notread-${means}`)).toContainText(`“${seed.stray}” · sheet Means, cell A19`);
  await notRead.getByTestId(`notread-mark-open-${means}`).click();
  await notRead.getByTestId(`notread-mark-${means}-why`).fill("a working note of the lab, not a value of the study");
  await notRead.getByTestId(`notread-mark-${means}-submit`).click();
  // its row and the table go; what was marked stays listed with "Restore…" and a line that says what was done (gap 5,
  // review CODE-3), where the focus goes; said by file (CODE-10)
  await expect(page.getByTestId("notread-table")).toHaveCount(0);
  const said = `${seed.study} plasma means.xlsx: “${seed.stray}” marked as not data. No loose number is left.`;
  const marked = page.getByTestId("notread-marked");
  await expect(marked.getByTestId("notread-marked-said")).toHaveText(said);
  await expect(marked.getByTestId(`notread-undo-${means}-0`)).toBeVisible();
  await expect(page.locator(":focus")).toHaveAttribute("id", "notread-marked-title");
  await expect(page.getByTestId("todo-live")).toContainText(said);
  await expect(page.getByTestId("todo-gate")).toHaveCount(0);                // the delivery's clean-up holds nothing now
  const tidied = await agreed(page);
  expect(tidied.decide).toBe(0);

  // --- the study's card, opened from its To do row: its facts in its one form, with one reason ---
  const factRow = page.getByTestId(`todo-row-fact:study:${seed.study}`);
  await expect(factRow).toContainText("Study OJ-101 · not stated: the route");
  await factRow.click();
  await expect(page).toHaveURL(/[?&]tab=studies/);
  await expect(page.getByTestId("tab-studies")).toHaveAttribute("aria-selected", "true");
  const card = page.getByTestId(`delivery-card-${study}`);
  await expect(card.getByTestId(`delivery-enter-gap-${study}-route-value`)).toBeFocused();     // at the fact To do named
  await agreed(page);
  // two studies, not five: the arms' files and the file that named no study are read on the cards they were linked to
  await expect(page.getByTestId("area-head-studies")).toContainText(/^2 studies\b/);
  const facts = card.getByTestId(`delivery-facts-form-${study}`);
  const row = (label: string) => facts.locator(".facts-row", { hasText: label });
  // the sheet form's answers are offered as chips the person still saves
  await row("Route").locator('[data-testid$="-suggest-0"]').click();
  await expect(card.getByTestId(`delivery-enter-gap-${study}-route-value`)).toHaveValue("oral");
  await row("Number of subjects").locator('[data-testid$="-suggest-0"]').click();
  await expect(row("Number of subjects").locator('[data-testid$="-value"]')).toHaveValue("12");
  await row("Purpose of the study").locator('[data-testid$="-value"]').selectOption("model_building");
  // an oral study's record also needs its dosage form: offered in the same form as soon as the route is chosen, so the
  // facts go in one submission with one reason (owner-job gap 7); the fasted state its file states is not asked
  await row("Dosage form").locator('[data-testid$="-value"]').selectOption("ir_tablet");
  await expect(row("Fasted or fed")).toHaveCount(0);
  await expect(facts.getByTestId(`delivery-facts-form-${study}-submit`)).toHaveText("Save these 4 facts");
  const source = "the protocol of OJ-101, section 9.1";
  await facts.getByTestId(`delivery-facts-form-${study}-why`).fill(source);
  await facts.getByTestId(`delivery-facts-form-${study}-submit`).click();
  await expect(card.getByTestId(`delivery-gap-${study}-route`)).toHaveCount(0);
  await expect(card.getByTestId(`delivery-blocker-${study}-SCHEMA_GAP`)).toHaveCount(0);
  await expect(facts).toHaveCount(0);
  await expect(card.locator('[data-code="LANDING_FIELD_MISSING"]')).toHaveCount(0);
  // the demographics the person has, entered on the card (not asked of the client)
  await card.getByTestId(`delivery-demographics-open-${study}`).click();
  const demo = card.getByTestId(`delivery-demographics-${study}`);
  await expect(demo.getByTestId(`delivery-demographics-${study}-population`).locator('option[value="healthy"]')).toHaveCount(1);
  await demo.getByTestId(`delivery-demographics-${study}-population`).selectOption("healthy");
  await demo.getByTestId(`delivery-demographics-${study}-age_mean`).fill("31");
  await demo.getByTestId(`delivery-demographics-${study}-weight_mean_kg`).fill("72");
  await demo.getByTestId(`delivery-demographics-${study}-percent_female`).fill("50");
  // the individual PK-Sim simulates: one population database and one sex, the person's choice (D-29, as on the sheet
  // form's path); with the mean age they are what loads (final review OWN-6, owner-job gap 1)
  await expect(demo.getByTestId(`delivery-demographics-${study}-individual-note`)).toContainText("without them the demographics are kept");
  await demo.getByTestId(`delivery-demographics-${study}-individual_population`).selectOption("European_ICRP_2002");
  await expect(demo.getByTestId(`delivery-demographics-${study}-individual`)).toContainText("(50 % women)");
  await demo.getByTestId(`delivery-demographics-${study}-individual_sex`).selectOption("MALE");
  await expect(demo.getByTestId(`delivery-demographics-${study}-individual-note`)).toContainText("the individual the study is simulated with");
  await demo.getByTestId(`delivery-demographics-${study}-why`).fill("the clinical study report, table 14.1.2");
  await demo.getByTestId(`delivery-demographics-${study}-submit`).click();
  await expect(demo).toHaveCount(0);
  await expect(card.getByTestId(`delivery-requirement-${study}-REQ-sys.demographics`)).toContainText("Done");
  // one truth: the card says the individual that loads, and only what it does not carry is said as kept
  await expect(card.getByTestId(`delivery-individual-${study}`)).toContainText("European ICRP 2002 · male · 31 y · 72 kg");
  await expect(card.getByTestId(`delivery-individual-${study}`)).toContainText("women (%) kept, not simulated");
  const held = card.getByTestId(`delivery-held-${study}`);
  await expect(held).not.toContainText("mean age");
  await expect(held).toContainText("Kept, not used by the model: women (%) (the study's individual is one sex and one PK-Sim population");
  // only the spot check is left
  await expect(card.locator('[data-testid^="delivery-blocker-"]')).toHaveCount(1);
  await expect(card.getByTestId(`delivery-blocker-${study}-SPOT_CHECK`)).toBeVisible();
  await agreed(page);
  await shot(page, "3-facts");

  // --- the spot check: drawn, each value ticked against its file, recorded once ---
  await card.getByTestId(`spot-draw-${study}`).click();
  const ticks = card.locator('[data-testid^="spot-tick-"]');
  await expect(ticks.first()).toBeVisible();
  const wanted = await ticks.count();
  for (let i = 0; i < wanted; i += 1) await ticks.nth(i).check();
  await expect(card.getByTestId(`spot-progress-${study}`)).toContainText(`${wanted} of ${wanted} ticked`);
  await card.getByTestId(`spot-submit-${study}`).click();
  await expect(card.getByTestId(`spot-state-${study}`)).toHaveText("complete");
  await expect(card.getByTestId(`delivery-ready-${study}`)).toBeVisible();
  // recorded: folded to its one-line result (OWN-9); showing its values again reads them, it never draws again
  await expect(card.getByTestId(`spot-done-${study}`)).toContainText(/Every value drawn matches its source · recorded by dev-user, \d{1,2} \w{3} \d{4}, \d\d:\d\d/);
  await expect(card.getByTestId(`spot-values-${study}`)).toHaveCount(0);
  const drawId = async () => (await read<{ spot_check: { draw_id: string; state: string } }>(request, `delivery/subjects/study/${study}`)).spot_check;
  const recorded = await drawId();
  await card.getByTestId(`spot-show-${study}`).click();
  await expect(card.getByTestId(`spot-values-${study}`)).toBeVisible();
  await expect(card.getByTestId(`spot-lede-${study}`)).toContainText(`${wanted} values drawn`);
  expect(await drawId()).toEqual(recorded);

  // --- before the signature: each decision made on the study, with who made it, when and why ---
  const decisions = card.getByTestId(`delivery-decisions-${study}`);
  // every decision the signature binds: the 4 facts, the 4 demographics and the individual's 2 choices, the 2 layouts of
  // its tables, the 2 links of its arms' values and the note marked as not data in its own file (final review gaps 6, 9)
  const listed = card.getByTestId(`delivery-decisions-own-${study}`).locator('[data-testid^="decision-"]');
  await expect(listed).toHaveCount(15);
  for (const text of await listed.allInnerTexts()) expect(text).toMatch(/(dev-user|e2e-fixture), \d{1,2} \w{3} \d{4}, \d\d:\d\d · “.+”/);
  const decision = (what: string | RegExp) => listed.filter({ hasText: what });
  // a layout names every file it reads
  await expect(decision("Table layout approved: the individual PK table of OJ-101 Reference.xlsx, OJ-101 Test.xlsx and lab-export-0412.xlsx"))
    .toContainText("dev-user");
  for (const arm of ["Reference", "Test"]) {
    await expect(decision(new RegExp(`Linked \\d+ values of OJ-101 ${arm}\\.xlsx to study OJ-101, arm ${arm}`)))
      .toContainText("“the two arms of study OJ-101, as their titles say”");
  }
  await expect(decision("Marked as not data: sheet Means, cell A19 of OJ-101 plasma means.xlsx"))
    .toContainText("“a working note of the lab, not a value of the study”");
  // the delivery's other file, linked to a new study: bound by the signature too, listed in the fold
  const others = card.getByTestId(`delivery-decisions-others-${study}`);
  await expect(others).toContainText("Your signature also binds the clean-up of the delivery's other files: 1 decision");
  await others.locator("summary").click();
  await expect(others.locator('[data-testid^="decision-"]')).toHaveCount(1);
  await expect(others).toContainText(/Linked \d+ values of lab-export-0412\.xlsx to study OJ-102/);
  await expect(decision(/Table layout approved: the individual PK table/)).toContainText("checked against the files: subjects and periods down");
  await expect(decision("Table layout approved: the PK summary table of OJ-101 plasma means.xlsx")).toContainText("e2e-fixture");
  await expect(decision("Table layout approved: the PK summary table of OJ-101 plasma means.xlsx")).toContainText("signed off earlier");
  for (const entered of ["Entered Oral for Route", "Entered 12 for Number of subjects", "Entered Model building for Purpose of the study",
                         "Entered IR tablet for Dosage form"]) {
    await expect(decision(entered)).toContainText(`dev-user`);
    await expect(decision(entered)).toContainText(`“${source}”`);
  }
  for (const entered of ["Entered Healthy for Population", "Entered 31 for Mean age (years)", "Entered 72 for Mean weight (kg)",
                         "Entered 50 for Women (%)", "Entered European ICRP 2002 for PK-Sim population", "Entered Male for Sex simulated"]) {
    await expect(decision(entered)).toContainText("“the clinical study report, table 14.1.2”");
  }
  await shot(page, "4-decisions");

  // --- confirmed and signed: Next says so; the dialog names what is signed; the DEV sign-in carries the step-up ---
  const before = await agreed(page);
  expect(studiesInModel(before)).toBe(0);
  // the /inputs to-do as it stands before the signature (what it lists of the studies once they are in the model, below)
  const inputsTodo = async () => (await read<{ todo: { kind: string; target: string }[] }>(request, "inputs")).todo
    .filter((t) => !["confirm", "check", "datasets"].includes(t.kind)).map((t) => `${t.kind}:${t.target}`);
  const todoBefore = await inputsTodo();
  await expect(next).toHaveText(`Next: Confirm study ${seed.study}`);
  await next.click();
  await card.getByTestId(`delivery-confirm-${study}`).click();
  const confirm = page.getByTestId("delivery-confirm-dialog");
  await expect(confirm.getByTestId("delivery-confirm-record")).toContainText(seed.study);
  await expect(confirm.getByTestId("delivery-confirm-coverage")).toContainText(
    "4 files: 0 numbers not read in their tables, 0 tables or texts not read, 0 loose numbers, 0 values not linked to a study");
  await expect(confirm.getByTestId("delivery-confirm-rules")).toContainText("v0.1, UNVERIFIED");
  // what the signature binds of the delivery beyond the study's own files is said in one line
  await expect(confirm.getByTestId("delivery-confirm-decisions")).toContainText(
    "15 decisions made on it, and 1 decision on the clean-up of the delivery's other files");
  await expect(confirm.getByTestId("delivery-confirm-blockers")).toHaveCount(0);
  await confirm.getByTestId("delivery-confirm-sign").click();
  await expect(confirm.getByTestId("delivery-signed")).toContainText(/Dev User \| Reviewed \| \d{4}-\d\d-\d\d/, { timeout: 60_000 });
  await expect(confirm.getByTestId("delivery-landed")).toContainText("Loaded into the project: 3 datasets");    // the means and each arm
  await shot(page, "5-signed");
  await confirm.getByTestId("delivery-confirm-done").click();

  // --- in the model: the card says who signed, when and what loaded (as many datasets as the dialog said); Done ---
  await expect(page.getByTestId(`card-loaded-study:${seed.study}`)).toContainText(/Signed by Dev User on \d{1,2} \w{3} \d{4}, \d\d:\d\d\. In the model: 3 datasets/);
  await expect(card.getByTestId(`delivery-manifestation-${study}`)).toContainText("Dev User | Reviewed |");
  await expect(card).toContainText(/In the model since \d{4}-\d\d-\d\d \d\d:\d\d: 3 datasets/);
  await expect(card.getByTestId(`delivery-confirm-${study}`)).toHaveCount(0);
  await expect(page.getByTestId(`study-status-study:${seed.study}`)).toHaveText("Done");
  // the Model inputs list on Clinical studies holds the study and each arm, as studies of the model
  for (const id of [seed.study, `${seed.study}-Reference`, `${seed.study}-Test`]) await expect(page.getByTestId(`study-${id}`)).toBeVisible();
  // one study signed, its means and its two arms loaded as three datasets: the status line, the studies list and the
  // dialog count the same (owner-job gap 3)
  await expect(page.getByTestId("status-in-model")).toContainText("In the model: 1 study (3 datasets)");
  await expect(page.getByTestId("studies-in-model-count")).toHaveText("(1 study, 3 datasets)");
  const after = await agreed(page);
  expect(studiesInModel(after)).toBe(1);                                     // the status line's "In the model" rose
  // To do: what remains, and nothing of OJ-101's signature is open there. OJ-101's confirm row is gone; what the loading
  // adds is the /inputs to-do of the studies now in the model: only the tablet studies' formulation (no product came in
  // this delivery; this job's gap 11, owned elsewhere). The demographics are not asked again: they loaded as the study's
  // individual (owner-job gap 1, final review OWN-6). Until the linked files' sheet-form groups joined OJ-101 (review
  // OWN-4), the signature also settled their double-counted rows, so the total happened to fall
  await page.getByTestId("tab-todo").click();
  const left = await agreed(page);
  const added = (await inputsTodo()).filter((t) => !todoBefore.includes(t));
  expect(added.filter((t) => !/^formulation:/.test(t))).toEqual([]);
  expect(added.filter((t) => t.startsWith("demographics:"))).toEqual([]);
  expect((await inputsTodo()).filter((t) => t.startsWith(`demographics:${seed.study}`))).toEqual([]);
  expect(open(left)).toBe(open(before) - 1 + added.length);
  for (const id of [`todo-row-fact:study:${seed.study}`, `todo-row-need:study:${seed.study}:REQ-sys.demographics`]) {
    await expect(page.getByTestId(id)).toHaveCount(0);
  }
  await expect(page.getByTestId("todo-group-confirm").getByTestId(`todo-confirm-study:${seed.study}`)).toHaveCount(0);
  await page.getByTestId("todo-group-done").locator("summary").click();
  await expect(page.getByTestId("todo-group-done").getByTestId(`todo-confirm-study:${seed.study}`)).toBeVisible();
  await shot(page, "6-what-remains");

  // --- downstream: GET /inputs holds the study and each arm with the facts the person filled and the files' values ---
  const inputs = await read<{ studies: Study[] }>(request, "inputs");
  const byId = Object.fromEntries(inputs.studies.map((s) => [s.study_id, s]));
  for (const id of [seed.study, `${seed.study}-Reference`, `${seed.study}-Test`]) {
    expect(byId[id], `${id} in GET /inputs`).toBeTruthy();
    expect(byId[id].purpose).toBe("model_building");
    expect(byId[id].facts).toMatchObject({ n: 12, route: "oral", dose_mg: 50, formulation: "ir_tablet", food_state: "fasted",
                                           population_type: "healthy", lloq: 0.5 });
    // the individual entered on the card, as the study is simulated
    expect(byId[id].demographics).toBe("entered");
    expect(byId[id].facts.demographics).toEqual({ population: "European_ICRP_2002", sex: "MALE", age_years: 31, weight_kg: 72 });
  }
  expect(byId[`${seed.study}-Reference`].facts.joined_from).toEqual([expect.stringMatching(/^OJ-101 Reference\.xlsx via /)]);
  expect(byId[`${seed.study}-Test`].facts.joined_from).toEqual([expect.stringMatching(/^OJ-101 Test\.xlsx via /)]);
  const evidence = await read<{ datasets: { study: { study_id: string }; state: string; decision_reason: string }[] }>(request, "evidence");
  const loaded = evidence.datasets.filter((d) => d.study.study_id.startsWith(seed.study));
  expect(loaded).toHaveLength(3);
  for (const d of loaded) {
    expect(d.state).toBe("ACCEPTED");
    expect(d.decision_reason).toMatch(/^confirmed on Delivery \(cf-\d+, signature /);
  }

  // --- a change after the signature (final review INT-8): the note is given back through the API; the card says it changed
  // since it was signed, and names what changed, who, when, why and in which file ---
  const page2 = await read<{ deliveries: { files: (File & { sha256: string })[] }[] }>(request, "delivery");
  const meansSha = page2.deliveries.flatMap((d) => d.files).find((f) => f.file_id === means)!.sha256;
  const back = await request.post(`${api}/delivery/regions:restore`, { headers: AUTH, data: {
    file_sha256: meansSha, regions: ["s:'Means'!A19"], scope: "outside", why: "the re-assay count is asked of the lab" } });
  expect(back.ok(), await back.text()).toBeTruthy();
  await page.reload();
  await page.getByTestId("tab-studies").click();
  const reopened = page.getByTestId(`delivery-subject-open-${study}`);
  if ((await reopened.getAttribute("aria-expanded")) !== "true") await reopened.click();
  await expect(page.getByTestId(`card-changed-study:${seed.study}`)).toContainText(/Changed since signed by Dev User on .*: confirm again/);
  const changed = page.getByTestId(`card-changed-since-${study}`);
  await expect(changed).toContainText("Given back (counted again): sheet Means, cell A19 of OJ-101 plasma means.xlsx");
  await expect(changed).toContainText(/dev-user, \d{1,2} \w{3} \d{4}, \d\d:\d\d · “the re-assay count is asked of the lab”/);
  await shot(page, "7-changed-since-signed");

  // --- what is left points to where it is done (this job's gap 11): the tablet study's missing formulation opens
  // Products and dissolution, or To do to ask the client; no product came, so its To do row says how a release is set ---
  const stepBar = page.getByTestId("step-waiting");
  await expect(stepBar.getByTestId("step-waiting-go-formulations")).toHaveText("a tablet study has no formulation");
  await expect(stepBar.getByTestId("step-waiting-or-todo")).toHaveText("ask the client");
  // the real lever is named (round 3): with no product here, the product the study used is added first
  await expect(stepBar.getByTestId("step-waiting-add")).toHaveText("add a product");
  await expect(stepBar).toContainText("a tablet study has no formulation (add a product on Products and dissolution, or ask the client)");
  await stepBar.getByTestId("step-waiting-go-formulations").click();
  await expect(page.getByTestId("tab-formulations")).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("todo-formulation-form.*")).toContainText("a tablet or capsule study, and the model holds no formulation yet");
  // the item's ways are the step bar's, as the project stands (round 4): no product is here
  await expect(page.getByTestId("todo-formulation-form.*").getByTestId("formulation-how"))
    .toContainText("No product is here: add a product on Products and dissolution, or ask the client on To do.");
  await expect(page.getByTestId("todo-formulation-form.*").getByTestId("formulation-add-product")).toHaveAttribute("href", /\?tab=formulations&add=product$/);
  await expect(page.getByTestId("todo-formulation-form.*")).not.toContainText("form.");
  // no product is here: the solid study's row says so and offers to add it, never "use a product's profile, above"
  await expect(page.getByTestId("inputs-products")).toContainText("Products named in the proposal · 0");
  const none = page.getByTestId(`formulation-none-${seed.study}`);
  await expect(none).toContainText("no product here");
  await expect(none.getByTestId(`formulation-add-product-${seed.study}`)).toHaveText("add the product it used");
  await expect(page.getByTestId(`formulation-${seed.study}`)).not.toContainText("dissolution profile as its release, above");

  // "ask the client" lands on the line of To do that asks the client for the formulation or dissolution of OJ-101's product
  // (round 3: with no product in the delivery, the release model was never asked), with the focus on it
  await stepBar.getByTestId("step-waiting-or-todo").click();
  await expect(page).toHaveURL(/\?tab=todo&at=todo-ask-REQ-form\.release/);
  await expect(page.getByTestId("tab-todo")).toHaveAttribute("aria-selected", "true");
  const asked = page.getByTestId("todo-group-ask").getByTestId("todo-ask-REQ-form.release");
  await expect(asked).toContainText("The formulation or dissolution data of the product the study used (no file names the product)");
  await expect(asked).toContainText(seed.study);
  await expect(asked).toContainText("needed for the model itself");
  await expect(asked).toBeFocused();
  // To do's formulation row names the lever too
  await expect(page.locator("li.todo-line", { has: page.getByTestId("missing-formulation-form.*") })).toContainText("“Add a product”");
  // "add a product" lands on the form that adds one, its first field focused
  await page.getByTestId("step-waiting").getByTestId("step-waiting-add").click();
  await expect(page.getByTestId("tab-formulations")).toHaveAttribute("aria-selected", "true");
  const adding = page.getByTestId("inputs-products-new");
  await expect(adding).toBeVisible();
  await expect(adding.locator("input, select, textarea, button").first()).toBeFocused();       // the product's "Set"
  await shot(page, "8-add-a-product");

  // --- downstream pages agree with Inputs (final review OWN-13): the Run page lists the studies Inputs holds, and Review &
  // sign says what Inputs still waits on, in words, each opening where it is done ---
  await page.goto(`/projects/${projectId}`);
  for (const id of [seed.study, `${seed.study}-Reference`, `${seed.study}-Test`]) {
    await expect(page.getByTestId(`overview-study-${id}`)).toContainText("Inputs");
  }
  await expect(page.getByText("No observed data yet")).toHaveCount(0);
  await page.goto(`/projects/${projectId}/plan`);
  const blocked = page.getByTestId("step-blocked-reasons");
  await expect(blocked.getByTestId("step-blocked-check-formulations")).toContainText("A tablet study has no formulation");
  await expect(blocked.getByTestId("step-blocked-check-formulations").getByRole("link", { name: "ask the client" })).toBeVisible();
  await expect(blocked.getByTestId("step-blocked-check-formulations").getByTestId("step-blocked-add")).toHaveText("add a product");
  // the situation, then each way once (round 4; round 3 said the lever twice, in the sentence and in brackets)
  await expect(blocked.getByTestId("step-blocked-check-formulations"))
    .toHaveText("A tablet study has no formulation: no product is here; add a product on Products and dissolution, or ask the client on To do.");
  // the whole blocked panel, not only its list, is in words: no reference, no raw check name (round 3, OWN-8: the API's
  // "the model inputs are not ready: S0 completeness (MS-01 §2.2); …" was printed under the list)
  const panel = page.getByTestId("plan-blocked");
  await expect(panel).toBeVisible();
  for (const raw of ["MS-01", "§", "S0 completeness", "formulations of solid studies", "demographics stated", "every planned simulation builds",
                     "the model inputs are not ready"]) {
    await expect(panel).not.toContainText(raw);
  }
  await expect(page.getByTestId("step-blocked-detail")).toHaveCount(0);
  await expect(page.getByTestId("step-blocked-todo")).toContainText("its count is of items, not of checks");
  await blocked.getByTestId("step-blocked-check-formulations").getByRole("link").first().click();
  await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/inputs\\?tab=formulations`));
  await expect(page.getByTestId("tab-formulations")).toHaveAttribute("aria-selected", "true");
});

// Round 4 (the regression round 3's skeptic found on the owner's review project): where products with dissolution
// profiles are here, the step bar, To do, Products and dissolution and Review & sign name that lever ("use a product's
// dissolution profile as its release"), opening the first such product's card at "Use this profile as the release",
// never an empty "add a product" form. The filled client-data template of e2e/fixtures/client_workbooks.py: a tablet
// study CL-01 and the dissolution of Test 10 mg and Brand 10 mg. Software test data on the stub engine, never a model.
test("products with dissolution profiles here: every page names the profile as the lever, not 'add a product'", async ({ page, request }) => {
  test.setTimeout(6 * 60_000);
  const dir = mkdtempSync(join(tmpdir(), "owner-release-"));
  execFileSync("uv", ["run", "python", join(__dirname, "fixtures", "client_workbooks.py"), dir], { cwd: REPO });
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: "Releaseamide", extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nOral 10 mg tablet.") } } });
  const projectId = (await started.json()).data.project_id as string;
  await finishStart(request, projectId);
  const api = `/api/v1/projects/${projectId}`;
  expect((await request.post(`${api}/requirements:derive`, { headers: AUTH })).ok()).toBeTruthy();
  const up = await request.post(`${api}/client-data`, { headers: AUTH, multipart: {
    files: { name: "client-template-filled.xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
             buffer: readFileSync(join(dir, "client-template-filled.xlsx")) } } });
  expect(up.status(), await up.text()).toBe(201);
  // the tablet study confirmed with the sheet form: the model now needs its formulation
  const confirmed = await request.post(`${api}/client-review:confirm`, { headers: AUTH, data: { group: "study:CL-01" } });
  expect(confirmed.ok(), await confirmed.text()).toBeTruthy();
  expect((await request.post(`${api}/inputs:assemble`, { headers: AUTH })).ok()).toBeTruthy();
  const steps = (await (await request.get(`${api}/steps`, { headers: AUTH })).json()).data.steps as { step: string; formulation: unknown }[];
  // the products' dissolution data are still to confirm: the profile is used once they are (`ready` false)
  // (round 5: with each study's own way; CL-01 names no product, so either product's profile can give its release)
  expect(steps.find((s) => s.step === "inputs")!.formulation)
    .toEqual({ way: "use_profile", products: ["Test 10 mg", "Brand 10 mg"], studies: ["CL-01"], ready: false,
               each: [{ study: "CL-01", way: "use_profile", products: ["Test 10 mg", "Brand 10 mg"], ready: false, named: null }] });

  // Review & sign: the situation and the lever, in the order they are done; no "add a product"
  await page.goto(`/projects/${projectId}/plan`);
  const check = page.getByTestId("step-blocked-reasons").getByTestId("step-blocked-check-formulations");
  await expect(check).toHaveText("A tablet study has no formulation: the dissolution profiles of Test 10 mg and Brand 10 mg are here, their "
                                 + "data to confirm first; confirm a product's dissolution data, then use its profile as its release on Products "
                                 + "and dissolution.");
  await expect(check.getByTestId("step-blocked-add")).toHaveCount(0);
  await check.getByTestId("step-blocked-release").click();
  await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/inputs\\?tab=formulations`));
  const testCard = page.locator("[data-testid^='product-card-']", { has: page.locator(".card-title", { hasText: /^Test 10 mg$/ }) });
  const toConfirm = testCard.locator("[data-testid^='card-release-'][data-testid$='-to-confirm']");
  await expect(toConfirm).toBeFocused();

  // the step bar says the same; no "add a product", nothing to ask the client
  await page.goto(`/projects/${projectId}/inputs?tab=todo`);
  const stepBar = page.getByTestId("step-waiting");
  await expect(stepBar).toContainText("a tablet study has no formulation (confirm a product's dissolution data, then use its profile as its "
                                      + "release on Products and dissolution)");
  await expect(stepBar.getByTestId("step-waiting-add")).toHaveCount(0);
  await expect(stepBar.getByTestId("step-waiting-or-todo")).toHaveCount(0);
  // To do's row says it in a sentence, naming the products
  const todoRow = page.locator("li.todo-line", { has: page.getByTestId("missing-formulation-form.*") });
  await expect(todoRow).toContainText("Confirm the dissolution data of Test 10 mg on its card (“Confirm”), then use its profile as its release "
                                      + "(“Use this profile as the release”), on Products and dissolution (or the profile of Brand 10 mg).");
  await expect(todoRow).not.toContainText("Add a product");
  await shot(page, "r4-1-todo-profile-lever");

  // the link lands on Test 10 mg's card, at its release: "Confirm its data first", focused; no empty form opened
  await stepBar.getByTestId("step-waiting-release").click();
  await expect(page.getByTestId("tab-formulations")).toHaveAttribute("aria-selected", "true");
  await expect(toConfirm).toBeFocused();
  await expect(testCard.locator("[data-testid$='-confirm-first']")).toContainText("once you have confirmed the product's data on this card");
  await expect(page.getByTestId("inputs-products-new")).toHaveCount(0);
  // the solid study's row on Products and the formulation item there name the same lever, never "no product here"
  const row = page.getByTestId("formulation-none-CL-01");
  await expect(row).toContainText("no formulation in the model yet: confirm a product's dissolution data, then use its profile as its release, "
                                  + "above (Test 10 mg's card)");
  await expect(row).not.toContainText("no product here");
  const item = page.getByTestId("todo-formulation-form.*");
  await expect(item.getByTestId("formulation-how")).toContainText("The dissolution profiles of Test 10 mg and Brand 10 mg are here, their data to "
                                                                  + "confirm first: confirm a product's dissolution data, then use its profile as its release on Products and dissolution.");
  await expect(item).not.toContainText("add a product");
  await shot(page, "r4-2-confirm-first-focused");
  // the To do row opens the same card at the same place
  await page.getByTestId("tab-todo").click();
  await page.getByTestId("missing-formulation-form.*").click();
  await expect(page.getByTestId("tab-formulations")).toHaveAttribute("aria-selected", "true");
  await expect(toConfirm).toBeFocused();

  // the owner's job, done: "Confirm its data first" takes the focus to the product's Confirm; confirmed, the card offers
  // "Use this profile as the release" and the step bar says to use it; used, the tablet study has its formulation
  await toConfirm.click();
  const confirmProduct = testCard.getByTestId("confirm-product:Test 10 mg");
  await expect(confirmProduct).toBeFocused();
  await confirmProduct.click();
  const use = testCard.locator("[data-testid^='card-release-'][data-testid$='-use']");
  await expect(use).toHaveText("Use this profile as the release");
  await expect(page.getByTestId("step-waiting")).toContainText("a tablet study has no formulation (use a product's dissolution profile as its "
                                                               + "release on Products and dissolution)");
  await use.click();
  await expect(testCard.locator("[data-testid^='card-release-']").first()).toContainText("In the model as the formulation “Test 10 mg”");
  await expect(page.getByTestId("step-waiting")).not.toContainText("a tablet study has no formulation");
  await shot(page, "r4-3-release-set");
});

// Round 5 (round 4's downstream-blinding skeptic): a tablet study confirmed with the sheet form only, in a project whose
// proposal names a product with no dissolution data. "add a product's dissolution data" lands on what adds them, "Add
// data" opened on "Formulation and dissolution files…" for that product, focused (it landed on the proposal's "Change");
// once the product has a card (its dissolution read as a table, which no Weibull fit can be the release of), on the card's
// "Add its dissolution file…". "ask the client" lands on the study's line of "Ask the client", the study named once (round
// 4 asked only while no product was here at all). e2e/fixtures/study_only_workbooks.py; software test data on the stub
// engine, never a model.
test("a product with no dissolution profile: the lever lands on what adds its data, and the study is asked of the client", async ({ page, request }) => {
  test.setTimeout(6 * 60_000);
  const dir = mkdtempSync(join(tmpdir(), "owner-dissolution-"));
  execFileSync("uv", ["run", "python", join(__dirname, "fixtures", "study_only_workbooks.py"), dir], { cwd: REPO });
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: "Dissolamide", extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nOral 10 mg tablet.") } } });
  const projectId = (await started.json()).data.project_id as string;
  await finishStart(request, projectId);
  const api = `/api/v1/projects/${projectId}`;
  expect((await request.post(`${api}/requirements:derive`, { headers: AUTH })).ok()).toBeTruthy();
  const up = await request.post(`${api}/client-data`, { headers: AUTH, multipart: {
    files: { name: "study-only.xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
             buffer: readFileSync(join(dir, "study-only.xlsx")) } } });
  expect(up.status(), await up.text()).toBe(201);
  const confirmed = await request.post(`${api}/client-review:confirm`, { headers: AUTH, data: { group: "study:CL-01" } });
  expect(confirmed.ok(), await confirmed.text()).toBeTruthy();
  // the proposal names the product, Tab 10; no file gives its dissolution
  const named = await request.put(`${api}/brief`, { headers: AUTH, data: {
    changes: [{ path: "products[0].name", status: "EDITED", value: "Tab 10", note: "the proposal" }], reason: "the proposal's product" } });
  expect(named.ok(), await named.text()).toBeTruthy();
  expect((await request.post(`${api}/inputs:assemble`, { headers: AUTH })).ok()).toBeTruthy();
  const item = ((await (await request.get(`${api}/inputs`, { headers: AUTH })).json()).data.todo as
    { kind: string; way: { way: string; products: string[] }; ask: { what: string }[] }[]).find((t) => t.kind === "formulation")!;
  expect(item.way).toMatchObject({ way: "add_dissolution", products: ["Tab 10"] });
  // the inputs ask for the study themselves, whatever the delivery asks (the pipeline set to legacy has no delivery)
  expect(item.ask.map((a) => a.what)).toEqual(["The formulation or dissolution data of the product the study used (no file names the product) — study CL-01"]);

  await page.goto(`/projects/${projectId}/inputs?tab=todo`);
  const stepBar = page.getByTestId("step-waiting");
  await expect(stepBar).toContainText("a tablet study has no formulation (add a product's dissolution data on Products and dissolution, or ask the client)");
  // "ask the client": the study's own line, focused, the study named once (the delivery asks it too: one line)
  await stepBar.getByTestId("step-waiting-or-todo").click();
  await expect(page).toHaveURL(/\?tab=todo&at=todo-ask-REQ-form\.release/);
  const asked = page.getByTestId("todo-group-ask").getByTestId("todo-ask-REQ-form.release");
  await expect(asked).toBeFocused();
  await expect(asked).toContainText("The formulation or dissolution data of the product the study used (no file names the product) · CL-01");
  expect((await asked.innerText()).match(/CL-01/g)).toHaveLength(1);
  await expect(page.getByTestId("todo-group-ask")).not.toContainText("Nothing the client alone holds is missing");

  // "add a product's dissolution data": Tab 10 has no card, so "Add data" opens on the dissolution files, for Tab 10, focused
  await page.getByTestId("step-waiting").getByTestId("step-waiting-dissolution").click();
  await expect(page.getByTestId("tab-formulations")).toHaveAttribute("aria-selected", "true");
  const files = page.getByTestId("inputs-add-data-panel").getByTestId("add-files-formulations");
  await expect(files).toBeFocused();
  await expect(files).toHaveText("Formulation and dissolution files… · the dissolution data of Tab 10");
  // the view as it is (a full-page shot resizes the page, which closes the menu)
  await page.screenshot({ path: test.info().outputPath("r5-1-add-data-for-the-proposals-product.png") });
  await expect(files).toBeFocused();
  // closed with Escape, the focus goes back to "Add data"; opened by its own button, it names no product
  await page.keyboard.press("Escape");
  await expect(files).toBeHidden();
  await expect(page.getByTestId("inputs-add-data")).toBeFocused();
  await page.getByTestId("inputs-add-data").click();
  await expect(files).toHaveText("Formulation and dissolution files…");
  await page.keyboard.press("Escape");
  // the study's row says its own way and lands on the same control
  const row = page.getByTestId("formulation-none-CL-01");
  await expect(row).toContainText("no formulation in the model yet, and no product here has a dissolution profile that can give it");
  await row.getByTestId("formulation-dissolution-CL-01").click();
  await expect(files).toBeFocused();
  // the control adds the data: Tab 10's dissolution file, read as a table (it plateaus below complete release)
  await page.getByTestId("client-upload-formulations").setInputFiles(join(dir, "plateau.xlsx"));
  await expect(page.getByTestId("inputs-notice")).toContainText("1 file stored", { timeout: 60_000 });
  const card = page.locator("[data-testid^='product-card-']", { has: page.locator(".card-title", { hasText: /^Tab 10$/ }) });
  await expect(card).toBeVisible({ timeout: 60_000 });

  // now Tab 10 has a card: the link lands on its release line, "Add its dissolution file…" focused, which opens the same
  await page.goto(`/projects/${projectId}/inputs?tab=todo`);
  await expect(page.getByTestId("step-waiting")).toContainText("add a product's dissolution data");
  await page.getByTestId("step-waiting").getByTestId("step-waiting-dissolution").click();
  const addFile = card.locator("[data-testid^='card-release-'][data-testid$='-add-file']");
  await expect(addFile).toBeFocused();
  await expect(card.locator("[data-testid^='card-release-'][data-testid$='-add']")).toContainText("no dissolution profile with a fit is here");
  await shot(page, "r5-2-card-add-its-dissolution-file");
  await addFile.click();
  await expect(files).toBeFocused();
  await expect(files).toHaveText("Formulation and dissolution files… · the dissolution data of Tab 10");
  await page.screenshot({ path: test.info().outputPath("r5-3-add-data-from-the-card.png") });
  await page.keyboard.press("Escape");
  // "ask the client" still holds the study's line (no profile here can give its release)
  await page.getByTestId("tab-todo").click();
  await expect(page.getByTestId("todo-group-ask").getByTestId("todo-ask-REQ-form.release")).toContainText("CL-01");
});
