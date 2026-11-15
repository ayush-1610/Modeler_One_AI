// To do's batch work (plan docs/plans/2026-11-14-inputs-task-first.md slice 4), end to end on the nine messy files of the
// made-up Exampleamide (the seed of the two UX projects): the link table, one row per file, where the two 230-23 files
// that hold the same subjects and periods are refused one arm of one study and given an arm each right there, then linked
// in one go, one call per destination; a file's loose numbers marked as not data in one go, restored, and two files' in
// one batch with the last reason offered again; the compound values no source gives entered with one citation; the
// layouts walked as a queue at their versions, and the "not data" readings approved together, each note naming the
// others; after each decision the focus moves on and the change is said; a decision costs at most two requests; "Next"
// opens its row whatever To do is narrowed to; on a phone the rows stack, nothing scrolls sideways (the compound values
// included) and the bulk bar stays reachable; and a later workbook with one sheet per study, whose delivery names no
// study yet, is in view with the rest of the link work, each table goes to its own place, and its first table is refused
// the arm that already holds its subjects even before the page has read that study. Software test data, never a model.
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { AUTH, finishStart } from "./fixtures/inputs";

const REPO = resolve(__dirname, "../../..");
const NEW = "__new__";

type File = { file_id: string; name: string; sha256: string };
type Delivery = {
  running: boolean; deliveries: { files: File[] }[]; totals: { outside_numeric: number };
  subjects: { subject: string; label: string; subject_type: string; arms: { id: string; label: string }[] }[];
  mappings: { mapping_id: string; version: number; kind: string; status: string; used_in: { file: string }[] }[];
};

let projectId = "";
let files: File[] = [];

const api = (path: string) => `/api/v1/projects/${projectId}/${path}`;
async function read<T>(request: APIRequestContext, path: string): Promise<T> {
  return (await (await request.get(api(path), { headers: AUTH })).json()).data as T;
}
const fid = (name: string) => files.find((f) => f.name === name)!.file_id;
const sideways = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
async function shot(page: Page, name: string) {
  await page.screenshot({ path: test.info().outputPath(`${name}.png`), fullPage: true });
}
/** The requests the page sends about the project (its API and its server-rendered parts) while `act` runs and the page
 *  settles; the app's own reads that are not the project's (the escalations bell) are not the decision's. Next's
 *  prefetch of a page a link leads to is said apart ("prefetch …"): it reads nothing of this page. */
async function requests(page: Page, act: () => Promise<void>, settle = 2500): Promise<string[]> {
  const seen: string[] = [];
  const hear = (r: { method(): string; url(): string; headers(): Record<string, string> }) => {
    if (r.url().includes(`/api/v1/projects/${projectId}/`) || r.url().includes("_rsc=")) {
      const prefetch = r.url().includes("_rsc=") && r.headers()["next-router-prefetch"] ? "prefetch " : "";
      seen.push(`${prefetch}${r.method()} ${r.url().replace(/^.*\/projects\/[^/]+\//, "")}`);
    }
  };
  page.on("request", hear);
  await act();
  await page.waitForTimeout(settle);
  page.off("request", hear);
  return seen;
}

test.describe.configure({ mode: "serial" });

test.beforeAll(async ({ playwright }, info) => {
  info.setTimeout(10 * 60_000);
  const request = await playwright.request.newContext({ baseURL: info.project.use.baseURL });
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: "Exampleamide", extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nOral tablet, 50 mg.") } } });
  projectId = (await started.json()).data.project_id as string;
  await finishStart(request, projectId);
  expect((await request.post(api("requirements:derive"), { headers: AUTH })).ok()).toBeTruthy();
  // the nine files of the 9-file project: the messy workbook and report (their layouts approved earlier, all but the urine
  // table's), the 230-23 BE arms, the dissolution and IV workbooks, a raw sheet and the filled client-data template
  const dir = mkdtempSync(join(tmpdir(), "task-first-"));
  execFileSync("uv", ["run", "python", join(__dirname, "fixtures", "delivery.py"), join(process.env.E2E_DATA_DIR!, "read-root"), projectId, dir], { cwd: REPO });
  execFileSync("uv", ["run", "python", join(__dirname, "fixtures", "er_be_workbooks.py"), dir], { cwd: REPO });
  execFileSync("uv", ["run", "python", join(__dirname, "fixtures", "client_workbooks.py"), dir], { cwd: REPO });
  const form = new FormData();
  for (const f of readdirSync(dir).filter((x) => /\.(xlsx|pdf)$/.test(x))) form.append("files", new Blob([readFileSync(join(dir, f))]), f);
  const up = await request.post(api("client-data"), { headers: AUTH, multipart: form });
  expect(up.status(), await up.text()).toBe(201);
  await expect.poll(async () => {
    const d = await read<Delivery | null>(request, "delivery");
    const c = await read<{ running: boolean } | null>(request, "client-data");
    return Boolean(d && !d.running && d.deliveries.length && c && !c.running);
  }, { timeout: 300_000, intervals: [2000] }).toBe(true);
  files = (await read<Delivery>(request, "delivery")).deliveries.flatMap((d) => d.files);
  expect(files).toHaveLength(9);
  await request.dispose();
});

test("the link table: asked first, two files refused one arm, given an arm each right there, linked in one go", async ({ page, request }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/projects/${projectId}/inputs?tab=todo`);
  const table = page.getByTestId("link-table");
  const ref = fid("230-23 Fasting Reference.xlsx"), tst = fid("230-23 Fasting Test.xlsx");
  // one row per file: 366 values of 6 files
  await expect(table.locator("li.batch-row")).toHaveCount(6);
  await expect(table).toContainText("6 files · 366 values");
  await expect(table.getByTestId(`link-${ref}`)).toContainText("individual PK table, 76 values · dose 50 mg · fasted · LLOQ 0.5 ng/mL");
  // the sheet form read it as 230-23-REF: asked before anything is filled; Yes fills the study and an arm of its own
  await expect(table.getByTestId(`link-to-${ref}`)).toContainText("The sheet form read it as 230-23-REF. Same study as 230-23?");
  await expect(table.getByTestId(`link-alias-yes-${ref}`)).toHaveAccessibleName("Yes: the 79 values of 230-23 Fasting Reference.xlsx are study 230-23");
  await table.getByTestId(`link-alias-yes-${ref}`).click();
  await expect(table.getByTestId(`link-to-${ref}`)).toContainText("→ study 230-23 · arm Reference (new)");
  await expect(table.getByTestId(`link-to-${ref}`)).toContainText("suggested");

  // both picked and sent to one place with no arm: refused before anything is sent, in words, with an arm each offered
  let assigns = 0;
  page.on("request", (r) => { if (r.method() === "POST" && r.url().endsWith("/values:assign")) assigns += 1; });
  await table.getByTestId(`link-pick-${ref}`).check();
  await table.getByTestId(`link-pick-${tst}`).check();
  const bar = page.getByTestId("bulk-link-bar");
  await expect(bar.getByTestId("bulk-link-bar-count")).toHaveText("2 files picked");
  await bar.getByTestId("bulk-link-one").check();
  await bar.getByTestId("link-study-bulk").selectOption({ label: "230-23" });
  await expect(bar.getByTestId("link-collision")).toContainText(
    "230-23 Fasting Reference.xlsx and 230-23 Fasting Test.xlsx both hold subject 001, period I: in study 230-23 each file needs its own arm.");
  await bar.getByTestId("bulk-link-why").fill("the file names and their titles say study 230-23");
  await bar.getByTestId("bulk-link-submit").click();
  await expect(bar.getByTestId("bulk-link-missing")).toHaveText("Give each file its own arm first (above)");
  expect(assigns).toBe(0);
  await shot(page, "1-collision");
  await expect(bar.getByTestId(`link-collision-arm-${ref}`)).toHaveValue("Reference");
  await expect(bar.getByTestId(`link-collision-arm-${tst}`)).toHaveValue("Test");
  await bar.getByTestId("link-collision-apply").click();
  await expect(bar.getByTestId("link-collision")).toHaveCount(0);
  await expect(table.getByTestId(`link-to-${tst}`)).toContainText("→ study 230-23 · arm Test (new)");
  // linked in one go: one call per destination, the focus on the next row, the change said
  await bar.getByTestId("bulk-link-submit").click();
  await expect(table.getByTestId(`link-${ref}`)).toHaveCount(0);
  await expect(table.getByTestId(`link-${tst}`)).toHaveCount(0);
  expect(assigns).toBe(2);
  // the arms the batch made are named as they now are (review CODE-10)
  await expect(page.getByTestId("todo-live")).toContainText("linked to study 230-23 · arm Reference; study 230-23 · arm Test. 4 files left to link.");
  await expect(page.locator(":focus")).toHaveAttribute("data-testid", /^link-pick-/);
  const after = await read<Delivery>(request, "delivery");
  expect(after.subjects.find((s) => s.label === "230-23")!.arms.map((a) => a.label).sort()).toEqual(["Reference", "Test"]);
  await shot(page, "2-linked");

  // one file, from its row's editor, to a new study named as the sheet form read it: the link and one read at most
  const iv = fid("Nichols2012 IV 50 mg 5 h infusion.xlsx");
  await table.getByTestId(`link-open-${iv}`).click();
  const editor = table.getByTestId(`link-editor-${iv}`);
  await editor.getByTestId(`link-study-${iv}`).selectOption("__new__");
  await editor.getByTestId(`link-new-study-${iv}`).fill("Nichols2012-IV");
  await editor.getByTestId(`link-edit-${iv}-why`).fill("the file is the published IV study of Nichols 2012");
  const sent = await requests(page, async () => {
    await editor.getByTestId(`link-edit-${iv}-submit`).click();
    await expect(table.getByTestId(`link-${iv}`)).toHaveCount(0);
  });
  expect(sent.filter((r) => r.startsWith("POST"))).toEqual(["POST delivery/values:assign"]);
  expect(sent.length, sent.join("\n")).toBeLessThanOrEqual(2);
});

test("a link is changed from its file's row in Client files: the other arm refused, then linked elsewhere with a reason", async ({ page, request }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/projects/${projectId}/inputs?tab=files`);
  // the Reference file, linked above to 230-23 · arm Reference: its row says where its values went, who and when
  const ref = fid("230-23 Fasting Reference.xlsx");
  const refRow = page.getByTestId("file-toggle-230-23 Fasting Reference.xlsx");
  if ((await refRow.getAttribute("aria-expanded")) !== "true") await refRow.click();
  const links = page.getByTestId(`delivery-file-links-${ref}`);
  await expect(links).toContainText("79 values linked to study 230-23 · arm Reference");
  await expect(links).toContainText("by dev-user on");
  let assigns = 0;
  page.on("request", (r) => { if (r.method() === "POST" && r.url().endsWith("/values:assign")) assigns += 1; });
  await links.locator('[data-testid^="delivery-file-relink-"]').first().click();
  const form = page.getByTestId(`delivery-file-relink-form-${ref}`);
  const key = `elsewhere-${ref}`;
  // into the arm the Test file holds: refused before anything is sent, in words
  await expect(form.getByTestId(`link-study-${key}`)).toHaveValue(/st-/);
  await form.getByTestId(`link-arm-${key}`).selectOption({ label: "Test" });
  await form.getByTestId(`link-edit-${key}-why`).fill("checking the other arm");
  await form.getByTestId(`link-edit-${key}-submit`).click();
  await expect(form.getByTestId(`link-problem-${key}`)).toContainText(
    "230-23 Fasting Reference.xlsx holds subject 001, period I, which study 230-23 has in that arm already", { timeout: 60_000 });
  expect(assigns).toBe(0);
  await form.getByTestId(`delivery-file-relink-cancel-${ref}`).click();
  await expect(form).toHaveCount(0);

  // the IV file, linked above to a new study: linked elsewhere, to another new one, with a reason; the link is replaced
  const iv = fid("Nichols2012 IV 50 mg 5 h infusion.xlsx");
  const ivRow = page.getByTestId("file-toggle-Nichols2012 IV 50 mg 5 h infusion.xlsx");
  if ((await ivRow.getAttribute("aria-expanded")) !== "true") await ivRow.click();
  const ivLinks = page.getByTestId(`delivery-file-links-${iv}`);
  await expect(ivLinks).toContainText("linked to study Nichols2012-IV");
  await ivLinks.locator('[data-testid^="delivery-file-relink-"]').first().click();
  const moved = page.getByTestId(`delivery-file-relink-form-${iv}`);
  const ivKey = `elsewhere-${iv}`;
  // linked there now: it asks for another place first
  await moved.getByTestId(`link-edit-${ivKey}-why`).fill("the published study's own name");
  await moved.getByTestId(`link-edit-${ivKey}-submit`).click();
  await expect(moved.getByTestId(`link-edit-${ivKey}-missing`)).toContainText("It is linked there now: choose another place");
  await moved.getByTestId(`link-study-${ivKey}`).selectOption(NEW);
  // a name the ledger knows already ("Nichols 2012 IV" is Nichols2012-IV) is refused in the server's words
  await moved.getByTestId(`link-new-study-${ivKey}`).fill("Nichols 2012 IV");
  await moved.getByTestId(`link-edit-${ivKey}-submit`).click();
  await expect(moved.getByTestId(`link-problem-${ivKey}`)).toContainText("a study named 'Nichols2012-IV' exists already", { timeout: 60_000 });
  expect(assigns).toBe(1);                                                 // sent, and refused: nothing written
  await moved.getByTestId(`link-new-study-${ivKey}`).fill("Nichols IV infusion");
  await moved.getByTestId(`link-edit-${ivKey}-submit`).click();
  await expect(moved).toHaveCount(0, { timeout: 60_000 });
  expect(assigns).toBe(2);
  await expect(ivLinks).toContainText("linked to study Nichols IV infusion");
  const after = await read<Delivery>(request, "delivery");
  expect(after.subjects.map((s) => s.label)).toContain("Nichols IV infusion");
  expect(after.subjects.map((s) => s.label)).not.toContain("Nichols2012-IV");          // no value left there: replaced whole
  await shot(page, "2b-linked-elsewhere");
});

test("numbers not read: a file's loose numbers marked as not data in one go, restored, then two files' in one batch", async ({ page, request }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/projects/${projectId}/inputs?tab=todo`);
  const table = page.getByTestId("notread-table");
  const messy = fid("messy-delivery.xlsx"), tpl = fid("client-template-filled.xlsx"), raw = fid("client-raw.xlsx");
  // alike loose numbers said once, with their cells
  await table.getByTestId(`notread-open-${tpl}`).click();
  await expect(table.getByTestId(`notread-${tpl}`)).toContainText("3 like “particle_size_d10_um” … “particle_size_d90_um” · sheet Product, cells F1 to H1");
  // a file's one loose number: marked as not data with a suggested reason the person still sends
  let excludes = 0;
  page.on("request", (r) => { if (r.method() === "POST" && r.url().endsWith("/regions:exclude")) excludes += 1; });
  const before = (await read<Delivery>(request, "delivery")).totals.outside_numeric;
  await table.getByTestId(`notread-mark-open-${messy}`).click();
  await expect(page.locator(":focus")).toHaveAttribute("data-testid", `notread-mark-${messy}-why`);
  await table.getByTestId(`notread-mark-${messy}-suggest-1`).click();
  await expect(table.getByTestId(`notread-mark-${messy}-why`)).toHaveValue("a note, not data");
  expect(excludes).toBe(0);                                                      // a chip fills the field, never sends it
  await table.getByTestId(`notread-mark-${messy}-submit`).click();
  await expect(table.getByTestId(`notread-${messy}`)).toHaveCount(0);            // its one loose number was all it had
  expect(excludes).toBe(1);
  await expect(page.getByTestId("todo-live")).toContainText(
    `messy-delivery.xlsx: “Note: 3 samples were re-assayed on day 14” marked as not data. ${before - 1} loose numbers left.`);
  await expect(page.locator(":focus")).toHaveAttribute("data-testid", /^notread-/);
  // what was done is said where the marked notes are listed, not only to a screen reader (review CODE-3)
  await expect(page.getByTestId("notread-marked-said")).toHaveText(
    `messy-delivery.xlsx: “Note: 3 samples were re-assayed on day 14” marked as not data. ${before - 1} loose numbers left.`);
  await shot(page, "3-marked");
  // restored where it was marked, with the reason
  const marked = page.getByTestId("notread-marked");
  await marked.getByTestId(`notread-undo-${messy}-0`).click();
  await marked.getByTestId(`notread-undo-${messy}-0-why`).fill("it records a re-assay: kept as data");
  await marked.getByTestId(`notread-undo-${messy}-0-submit`).click();
  await expect(table.getByTestId(`notread-${messy}`)).toBeVisible();
  await expect.poll(async () => (await read<Delivery>(request, "delivery")).totals.outside_numeric).toBe(before);
  // two files' loose numbers in one batch, the last reason offered again: one decision per file. The template's is refused
  // (a second reviewer marked a cell of it first, a 409 the page is served here): said on its row and in the bar, in a
  // person's words, never hidden by the other file's success (review CODE-2)
  const tplSha = files.find((f) => f.name === "client-template-filled.xlsx")!.sha256;
  await page.route(/\/regions:exclude$/, async (route) => {
    if ((route.request().postDataJSON() as { file_sha256: string }).file_sha256 !== tplSha) return route.continue();
    await route.fulfill({ status: 409, json: { detail: { code: "CONFLICT", message: "already marked as not data: s:'Product'!F1 by rd-9",
      decided: [{ id: "rd-9", where: "s:'Product'!F1", by: "reviewer-b", at: "2026-11-15T10:21:00Z", why: "a header of the template" }] } } });
  });
  await table.getByTestId(`notread-pick-${tpl}`).check();
  await table.getByTestId(`notread-pick-${raw}`).check();
  const bar = page.getByTestId("bulk-notread-bar");
  await expect(bar.getByTestId("bulk-notread-bar-count")).toHaveText("2 files picked");
  await expect(bar.getByTestId("bulk-notread-last")).toHaveText("use last: a note, not data");
  await bar.getByTestId("bulk-notread-last").click();
  await bar.getByTestId("bulk-notread-submit").click();
  await expect(table.getByTestId(`notread-${raw}`)).not.toContainText("loose number");
  const refused = "reviewer-b marked sheet Product, cell F1 as not data on 15 Nov 2026, 10:21: “a header of the template”. Restore it to decide again.";
  await expect(table.getByTestId(`notread-row-problem-${tpl}`)).toHaveText(refused);
  await expect(bar.getByTestId("bulk-notread-problems")).toHaveText(`client-template-filled.xlsx: ${refused}`);
  await expect(page.getByTestId("todo-live")).toContainText("client-raw.xlsx: ");
  await expect(page.getByTestId("todo-live")).toContainText("1 file not marked: see its row.");
  await page.unrouteAll({ behavior: "ignoreErrors" });
  // sent again, it is marked, and its refusal goes
  await expect(bar.getByTestId("bulk-notread-bar-count")).toHaveText("1 file picked");
  await bar.getByTestId("bulk-notread-submit").click();
  await expect(table.getByTestId(`notread-${tpl}`)).not.toContainText("loose number");
  await expect(table.getByTestId(`notread-row-problem-${tpl}`)).toHaveCount(0);
  expect(excludes).toBe(4);
  expect((await read<Delivery>(request, "delivery")).totals.outside_numeric).toBe(before - 4);
});

test("the compound values no source gives: entered together with one citation", async ({ page, request }) => {
  await page.goto(`/projects/${projectId}/inputs?tab=todo`);
  const mv = page.getByTestId("missing-values");
  await expect(mv.getByTestId("missing-missing-phys.mw")).toHaveText("Molecular weight");
  await mv.getByTestId("mv-value-phys.mw").fill("263.4");
  await mv.getByTestId("mv-unit-phys.mw").fill("g/mol");
  await mv.getByTestId("mv-quote-phys.mw").fill("a molecular weight of 263.4 g/mol");
  await mv.getByTestId("mv-value-phys.logp").fill("2.3");
  await mv.getByTestId("mv-quote-phys.logp").fill("log P 2.3");
  // the minimum elimination pathway (final review OWN-5): its pathway is asked first, never a value for the placeholder
  await expect(mv.getByTestId("missing-missing-elim")).toHaveText("An elimination pathway");
  await mv.getByTestId("mv-value-elim").fill("3.2");
  await mv.getByTestId("mv-quote-elim").fill("a hepatic plasma clearance of 3.2 mL/min/kg");
  await mv.getByTestId("mv-submit").click();
  await expect(mv.getByRole("alert")).toHaveText("Choose the elimination pathway the value is for");
  const pathway = mv.getByTestId("mv-pathway-elim");
  await expect(pathway.locator("option")).toHaveText(["choose the pathway…", "GFR fraction (renal filtration) (no unit)",
                                                      "Hepatic plasma clearance (total) (ml/min/kg)"]);
  await pathway.selectOption("elim.hepatic.total.plasma_clearance");
  await expect(mv.getByTestId("mv-unit-elim")).toHaveValue("ml/min/kg");      // the unit the model stores it in
  await mv.getByTestId("mv-submit").click();
  await expect(mv.getByRole("alert")).toHaveText("Give the source's DOI or URL, or call it an assumption");
  await mv.getByTestId("mv-title").fill("Exampleamide physico-chemistry");
  await mv.getByTestId("mv-link").fill("10.1000/exampleamide");
  const posted: string[] = [];
  page.on("request", (r) => { if (r.method() === "POST" && /\/evidence$/.test(r.url())) posted.push(String(r.postDataJSON()?.target)); });
  const live = page.getByTestId("todo-live");
  // the three values, then what a model input changes, read once (the inputs; the evidence and the offers are not shown
  // on To do), and the step bar drawn again because the readiness it says changed (final review OWN-7, CODE-4); the
  // page's own reads of the cards (once it is idle) are done before the decision is counted
  await expect(page.getByTestId("status-checking")).toHaveCount(0);
  await page.waitForLoadState("networkidle");
  const sent = await requests(page, async () => {
    await mv.getByTestId("mv-submit").click();
    await expect(live).toContainText("3 values added with “Exampleamide physico-chemistry”.");
  });
  const reads = sent.filter((r) => !r.startsWith("POST") && !r.startsWith("prefetch"));
  expect(sent.filter((r) => r.startsWith("POST")), sent.join("\n")).toEqual(["POST evidence", "POST evidence", "POST evidence"]);
  expect(reads.filter((r) => !/_rsc=/.test(r)), sent.join("\n")).toEqual(["GET inputs"]);
  expect(reads.length, sent.join("\n")).toBeLessThanOrEqual(2);
  for (const name of ["Molecular weight", "Lipophilicity", "Hepatic plasma clearance (total)"]) await expect(live).toContainText(name);
  await expect(mv.getByTestId("mv-row-phys.mw")).toHaveCount(0);
  await expect(mv.getByTestId("mv-row-elim")).toHaveCount(0);
  expect(posted.sort()).toEqual(["elim.hepatic.total.plasma_clearance", "phys.logp", "phys.mw"]);
  const inputs = await read<{ compound: { id: string; state: string }[]; todo: { kind: string; target: string }[] }>(request, "inputs");
  for (const id of ["phys.mw", "phys.logp"]) expect(inputs.compound.find((r) => r.id === id)!.state).not.toBe("missing");
  // the pathway's value is in the model, and the minimum elimination pathway is no longer missing
  expect(inputs.compound.find((r) => r.id === "elim.hepatic.total.plasma_clearance")!.state).toBe("kept");
  expect(inputs.todo.some((t) => t.target === "elim")).toBe(false);
});

test("the layouts' queue: walked at their versions, approved and on to the next; the 'not data' readings approved together", async ({ page, request }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/projects/${projectId}/inputs?tab=todo`);
  const queue = page.getByTestId("layout-queue");
  const delivery = await read<Delivery>(request, "delivery");
  const urine = delivery.mappings.find((m) => m.kind === "excretion" && m.status === "proposed")!;
  // a row opens on its columns in one line
  const row = queue.getByTestId(`todo-layout-${urine.mapping_id}`);
  await expect(row).toContainText("kept, not used by the model");
  const total = await queue.locator("li.batch-row").count();
  await row.getByTestId(`todo-layout-show-${urine.mapping_id}@${urine.version}`).click();
  await expect(row.getByTestId(`todo-layout-columns-${urine.mapping_id}`)).toContainText("←");
  // the queue, from that row: Previous and Next walk it; "Approve and next" approves and moves on
  await row.getByTestId(`delivery-mapping-open-${urine.mapping_id}`).click();
  const dialog = page.getByTestId("delivery-mapping-dialog");
  const at = Number((await dialog.getByTestId("mapping-position").textContent())!.split(" of ")[0]);
  await expect(dialog.getByTestId("mapping-position")).toHaveText(`${at} of ${total}`);
  await expect(dialog.getByTestId("mapping-columns")).toContainText("Amount (mg)");
  if (at > 1) {
    await dialog.getByTestId("mapping-prev").click();
    await expect(dialog.getByTestId("mapping-position")).toHaveText(`${at - 1} of ${total}`);
    await dialog.getByTestId("mapping-next").click();
  }
  await expect(dialog.getByTestId("mapping-columns")).toContainText("Amount (mg)");
  await dialog.getByTestId("mapping-approve-why").fill("the urine table's layout, checked against the file");
  // the page's own reads of the cards (once it is idle) are done before the decision is counted
  await expect(page.getByTestId("status-checking")).toHaveCount(0);
  await page.waitForLoadState("networkidle");
  const sent = await requests(page, async () => {
    await dialog.getByTestId("mapping-approve-submit").click();
    await expect(dialog.getByTestId("mapping-said")).toContainText(at < total ? "Approved: the excretion table layout, version" : "of the excretion table layout is approved");
  }, 1000);
  // the approval and the page read once; the next layout's own read is the queue moving on (the page is read again
  // every 3 s while the layout's file is being read again: that is a reading, not the decision)
  expect(sent.filter((r) => !/mappings\/mp-[0-9a-f]+\?version=/.test(r)), sent.join("\n"))
    .toEqual([`POST delivery/mappings/${urine.mapping_id}:approve`, "GET delivery"]);
  if (at < total) {
    // on to the next layout: said of the one before, with where the queue is now; the focus back on the dialog (the
    // button pressed went with its layout), so Tab stays inside and Escape closes it
    await expect(dialog.getByTestId("mapping-position")).toHaveText(`${at + 1} of ${total}`);
    await expect(dialog.getByTestId("mapping-said")).toContainText(`Now ${at + 1} of ${total}.`);
    await expect(dialog.locator('[role="dialog"]')).toBeFocused();
    await page.keyboard.press("Tab");
    await expect.poll(() => dialog.evaluate((d) => d.contains(document.activeElement))).toBe(true);
    await dialog.getByTestId("mapping-prev").click();
    await expect(dialog.getByTestId("mapping-said")).toHaveCount(0);                   // the next move clears it
    await dialog.getByTestId("mapping-next").click();
  }
  await shot(page, "4-queue");
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  const approved = (await read<{ status: string }>(request, `delivery/mappings/${urine.mapping_id}?version=${urine.version}`)).status;
  expect(approved).toBe("approved");

  // two layouts that read a table as not data (the second one made up for this check): approved together, each note
  // naming the other
  const notData = delivery.mappings.find((m) => m.kind === "not_data")!;
  const real = await read<Record<string, unknown>>(request, `delivery/mappings/${notData.mapping_id}?version=${notData.version}`);
  const twin = "mp-000000000000";
  await page.route(/\/delivery$/, async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const res = await route.fetch();
    const body = await res.json();
    body.data.mappings.push({ ...body.data.mappings.find((m: { mapping_id: string }) => m.mapping_id === notData.mapping_id), mapping_id: twin });
    await route.fulfill({ response: res, json: body });
  });
  const notes: string[] = [];
  await page.route(/\/mappings\/mp-[0-9a-f]+:approve$/, async (route) => {
    notes.push((route.request().postDataJSON() as { note: string }).note);
    await route.fulfill({ json: { data: { ...real, status: "approved", mapping_id: route.request().url().includes(twin) ? twin : notData.mapping_id },
                                  meta: { request_id: "", timestamp: "", api_version: "" }, errors: [] } });
  });
  await page.reload();
  await queue.getByTestId("layout-notdata-open").click();
  await queue.getByTestId("layout-notdata-why").fill("README sheets");
  await queue.getByTestId("layout-notdata-submit").click();
  await expect(page.getByTestId("todo-live")).toContainText("2 layouts that read a table as not data approved.");
  expect(notes).toEqual(Array(2).fill("README sheets · approved with 1 other layout that read a table as not data"));
  await expect(page.locator(":focus")).toHaveAttribute("id", "todo-group-layouts-title");
  await page.unrouteAll({ behavior: "ignoreErrors" });          // the page is still read while the urine file is read again
});

test("Next opens its row whatever To do is narrowed to", async ({ page }) => {
  // with the sheet form's cards out of the way, Next is a table layout; To do narrowed to Missing hides the layouts
  await page.route(/\/client-review$/, async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    body.data.groups = [];
    await route.fulfill({ response: res, json: body });
  });
  await page.goto(`/projects/${projectId}/inputs?tab=todo&status=missing`);
  await expect(page.getByTestId("layout-queue")).toHaveCount(0);
  const next = page.getByTestId("inputs-next");
  await expect(next).toHaveText(/^Next: Check \d+ table layouts?$/);
  await next.click();
  // the filter that hid it is dropped, and the row is brought into view
  await expect(page).toHaveURL(/[?&]tab=todo(?![^#]*status=)/);
  await expect(page.getByTestId("todo-filter-all")).toHaveAttribute("aria-pressed", "true");
  const opened = page.getByTestId("layout-queue").locator(".just-opened");
  await expect(opened).toHaveCount(1);
  await expect(opened).toBeInViewport();
  await page.unrouteAll({ behavior: "ignoreErrors" });
});

test("a sheet-form draft's problems lead to its sheet, with the cells its own words name read as no sample (OWN-2 c)", async ({ page, request }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  // 230-23's sheet-form path: the Fasting sheet of the messy workbook says "Cells say '12.3*', '>1000': mark them as 'no
  // sample' or correct the file"; its "Read these data" is refused until they are. The draft leads to the sheet itself.
  const study = (await read<Delivery>(request, "delivery")).subjects.find((s) => s.label === "230-23")!;
  await page.goto(`/projects/${projectId}/inputs?tab=studies`);
  const toggle = page.getByTestId(`delivery-subject-open-${study.subject}`);
  await expect(toggle).toBeVisible();
  if ((await toggle.getAttribute("aria-expanded")) !== "true") await toggle.click();
  await page.getByTestId("confirm-sheet-study:230-23").click();
  const open = page.getByTestId("draft-read-sheet-Fasting");
  await expect(open).toHaveText("Read this sheet: mark “12.3*” and “>1000” as no sample…");
  let sent = 0;
  page.on("request", (r) => { if (r.method() === "POST") sent += 1; });
  await open.click();
  // Client files, the workbook's row open on its Fasting sheet in the reader, the two texts among the cells that mean no
  // sample; nothing is read or kept until the person checks the sheet and saves it
  await expect(page).toHaveURL(/[?&]tab=files/);
  const noSample = page.getByLabel("no sample texts");
  await expect(noSample).toHaveValue(/12\.3\*/);
  await expect(noSample).toHaveValue(/>1000/);
  expect(sent).toBe(0);
  await shot(page, "6b-sheet-from-draft");
});

test("on a phone the rows stack, nothing scrolls sideways, and the bulk bar stays in reach", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/projects/${projectId}/inputs?tab=todo`);
  const table = page.getByTestId("link-table");
  const rld = fid("Dissolution RLD pH 6.8.xlsx"), test68 = fid("Dissolution Test pH 6.8.xlsx");
  await table.getByTestId(`link-open-${rld}`).click();
  await table.getByTestId(`link-pick-${rld}`).check();
  await table.getByTestId(`link-pick-${test68}`).check();
  await page.getByTestId("notread-table").locator('[data-testid^="notread-open-"]').first().click();
  expect(await sideways(page), "no sideways page scroll with a row's editor open").toBe(false);
  // a row's parts stack under its name
  const line = table.getByTestId(`link-${rld}`).locator(".batch-line");
  const name = await line.locator(".batch-what").boundingBox(), where = await line.locator(".batch-where").boundingBox();
  expect(where!.y).toBeGreaterThan(name!.y + name!.height - 1);
  // the bar is in view at the bottom of the window while its table is
  await table.getByTestId(`link-${rld}`).scrollIntoViewIfNeeded();
  await expect(page.getByTestId("bulk-link-bar")).toBeInViewport();
  await expect(page.getByTestId("bulk-link-bar")).toContainText("2 files picked");
  await shot(page, "5-phone");
  // the compound values to fill: each a card no wider than the box, value and unit side by side, the sentence under them
  const mv = page.getByTestId("missing-values");
  await mv.scrollIntoViewIfNeeded();
  const box = await mv.locator(".mv-scroll").evaluate((el) => ({ sw: el.scrollWidth, cw: el.clientWidth, right: el.getBoundingClientRect().right }));
  expect(box.sw, "the compound values do not scroll sideways").toBeLessThanOrEqual(box.cw + 1);
  const row = mv.locator('[data-testid^="mv-row-"]').first();
  const [value, unit, quote] = await Promise.all(["value", "unit", "quote"].map((k) => row.locator(`[data-testid^="mv-${k}-"]`).boundingBox()));
  expect(unit!.x + unit!.width).toBeLessThanOrEqual(box.right + 1);
  expect(Math.abs(unit!.y - value!.y)).toBeLessThan(2);
  expect(quote!.y).toBeGreaterThan(value!.y + value!.height - 1);
  expect(await sideways(page)).toBe(false);
  await mv.screenshot({ path: test.info().outputPath("6-phone-missing.png") });
});

test("a workbook with one sheet per study: in view though it holds up nothing, each table to its own place, an arm that holds its subjects refused", async ({ page, request }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  // a later delivery: one workbook, Sheet1 "Study 230-23 … Reference …" (the subjects of the Reference file, linked to
  // 230-23's Reference arm above), Sheet2 "Study 777-01 …" (no study of that name yet)
  const deliveries = (await read<Delivery>(request, "delivery")).deliveries.length;
  const dir = mkdtempSync(join(tmpdir(), "two-studies-"));
  execFileSync("uv", ["run", "python", join(__dirname, "fixtures", "two_studies_workbook.py"), dir], { cwd: REPO });
  const name = "two-studies-one-workbook.xlsx";
  const form = new FormData();
  form.append("files", new Blob([readFileSync(join(dir, name))]), name);
  const up = await request.post(api("client-data"), { headers: AUTH, multipart: form });
  expect(up.status(), await up.text()).toBe(201);
  await expect.poll(async () => {
    const d = await read<Delivery | null>(request, "delivery");
    const c = await read<{ running: boolean } | null>(request, "client-data");
    return Boolean(d && !d.running && d.deliveries.length === deliveries + 1 && c && !c.running);
  }, { timeout: 300_000, intervals: [2000] }).toBe(true);
  const delivery = await read<Delivery & { unassigned: { file: string | null }[] }>(request, "delivery");
  files = delivery.deliveries.flatMap((d) => d.files);
  const two = fid(name);
  const study = delivery.subjects.find((s) => s.label === "230-23")!;

  // its delivery names no study yet: it holds up nothing, and its row is shown with the rest of the link work, not
  // folded away, saying why it is not counted; its file in Client files lists its values to link
  await page.goto(`/projects/${projectId}/inputs?tab=todo`);
  const table = page.getByTestId("todo-group-link").getByTestId("link-table");
  await expect(table.getByTestId(`link-${two}`)).toBeVisible();
  await expect(page.getByTestId("todo-why-link")).toContainText("1 not counted now: Its files name no study or product yet");
  // each table where its own title says: Sheet1's to 230-23 (its Reference arm, named in the title), Sheet2's not chosen
  await expect(table.getByTestId(`link-to-${two}-0`)).toContainText("sheet Sheet1: → study 230-23 · arm Reference");
  await expect(table.getByTestId(`link-to-${two}-0`)).toContainText("suggested");
  await expect(table.getByTestId(`link-to-${two}-1`)).toContainText("sheet Sheet2: not chosen yet");
  await page.getByTestId("tab-files").click();
  await expect(page.getByTestId(`file-needs-${name}`)).toContainText(/\d+ values to link · not counted now/);

  // on a fresh page, sent before the page has read what 230-23 holds: the card is read first, and the arm refused
  let assigns = 0;
  page.on("request", (r) => { if (r.method() === "POST" && r.url().endsWith("/values:assign")) assigns += 1; });
  await page.route(new RegExp(`/delivery/subjects/study/${study.subject}$`), async (route) => {
    await new Promise((go) => setTimeout(go, 6000));
    await route.continue();
  });
  await page.goto(`/projects/${projectId}/inputs?tab=todo`);
  await table.getByTestId(`link-open-${two}`).click();
  const editor = table.getByTestId(`link-editor-${two}`);
  await expect(editor.getByTestId(`link-split-${two}`)).toBeChecked();
  await expect(editor.getByTestId(`link-part-${two}-0`)).toContainText("individual PK table, 76 values · sheet Sheet1 · 3 facts");
  await editor.getByTestId(`link-study-${two}-1`).selectOption(NEW);
  await editor.getByTestId(`link-new-study-${two}-1`).fill("777-01");
  await editor.getByTestId(`link-edit-${two}-why`).fill("each sheet's title names its study");
  await expect(table.getByTestId(`link-checking-${two}`)).toContainText("checking what study 230-23 holds");
  await editor.getByTestId(`link-edit-${two}-submit`).click();
  await expect(table.getByTestId(`link-row-problem-${two}`)).toContainText(
    "subject 001, period I, which study 230-23 has in that arm already: in study 230-23 each file needs its own arm. Nothing was linked.");
  expect(assigns).toBe(0);
  await page.unrouteAll({ behavior: "ignoreErrors" });
  await shot(page, "7-refused");

  // an arm of its own for Sheet1's table: one call per place, and the file is linked
  await editor.getByTestId(`link-arm-${two}-0`).selectOption(NEW);
  await editor.getByTestId(`link-new-arm-${two}-0`).fill("Reference repeat");
  await expect(table.getByTestId(`link-row-problem-${two}`)).toHaveCount(0);
  await editor.getByTestId(`link-edit-${two}-submit`).click();
  await expect(table.getByTestId(`link-${two}`)).toHaveCount(0);
  expect(assigns).toBe(2);
  const after = await read<Delivery & { unassigned: { file: string | null }[] }>(request, "delivery");
  expect(after.unassigned.filter((v) => v.file === name)).toHaveLength(0);
  expect(after.subjects.find((s) => s.subject === study.subject)!.arms.map((a) => a.label)).toContain("Reference repeat");
  expect(after.subjects.map((s) => s.label)).toContain("777-01");
});

test("a table the newest layout cannot read: its row says why and lists its numbers; its layout opens on it, at its version, and is corrected there", async ({ page, request }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  // the two dissolution tables share one layout: version 1 was made for RLD's table, version 2 for Test's, which reads the
  // product's role from its caption ("(Test)"); RLD's caption names "Reference" and "RLD" both, so version 2 cannot read
  // it. Both versions approved (as a person would in the queue), each table is read with the newest that reads it.
  const before = await read<{ mappings: { mapping_id: string; version: number; kind: string; used_in: { file: string }[] }[] }>(request, "delivery");
  const diss = before.mappings.filter((m) => m.kind === "dissolution" && m.used_in.some((u) => u.file.startsWith("Dissolution ")));
  const id = diss[0].mapping_id;
  for (const version of [1, 2]) {
    const ok = await request.post(api(`delivery/mappings/${id}:approve`), { headers: AUTH, data: { version, note: "checked against the files" } });
    expect(ok.status(), await ok.text()).toBe(200);
    await expect.poll(async () => !(await read<Delivery>(request, "delivery")).running, { timeout: 120_000, intervals: [1000] }).toBe(true);
  }
  type Region = { region_id: string; mapping_version: number; silent: number; newer: { version: number } | null };
  const regionOf = async (name: string) => (await read<{ deliveries: { files: (File & { regions: Region[] })[] }[] }>(request, "delivery"))
    .deliveries.flatMap((d) => d.files).find((f) => f.name === name)!.regions[0];
  const rld = await regionOf("Dissolution RLD pH 6.8.xlsx");
  const tst = await regionOf("Dissolution Test pH 6.8.xlsx");
  expect([rld.mapping_version, rld.newer?.version, tst.mapping_version]).toEqual([1, 2, 2]);

  // To do: RLD's row lists its numbers not read, why, and why the newest layout does not read its table
  await page.goto(`/projects/${projectId}/inputs?tab=todo`);
  const file = fid("Dissolution RLD pH 6.8.xlsx");
  const row = page.getByTestId(`notread-${file}`);
  await row.getByTestId(`notread-open-${file}`).click();
  await expect(row.getByTestId(`notread-silent-${rld.region_id}`)).toContainText("24 numbers in the table pH 6.8 of Dissolution RLD pH 6.8.xlsx");
  await expect(row.getByTestId(`notread-cells-${rld.region_id}`)).toContainText("No column or row of the layout reads it (24): sheet pH 6.8, cell");
  await expect(row.getByTestId(`notread-newer-${rld.region_id}`)).toContainText(
    "Version 2 of its layout, the newest approved, does not read this table: the product's role is not stated in its caption.");
  await shot(page, "7-not-read-why");
  // its layout opens at the version and on the table the row names (review OWN-2 a, OWN-15)
  await row.getByTestId(`notread-layout-${rld.region_id}`).click();
  const dialog = page.getByTestId("delivery-mapping-dialog");
  await expect(dialog.getByTestId("mapping-version")).toHaveText("version 1");
  await expect(dialog.getByTestId("mapping-sample")).toContainText("of Dissolution RLD pH 6.8.xlsx");
  await expect(dialog.getByTestId("mapping-sample-said")).toContainText("as the layout says");
  await expect(dialog.getByTestId(`mapping-table-${rld.region_id}`)).toContainText(
    "Read with this version. Version 2, the newest approved, does not read it (the product's role is not stated in its caption), so it is still read with version 1.");
  await expect(dialog.getByTestId(`mapping-table-${tst.region_id}`)).toContainText("Read with version 2.");
  // no engine words: the facts read once in a sentence, a rule's id and its patterns in the technical detail
  await expect(dialog.getByTestId("mapping-constants")).toContainText("The batch is read from its caption.");
  await expect(dialog.locator(".delivery-mapping")).not.toContainText(/proposed by|sheet_form\/rules|as the mapper|\(\?i\)/, { useInnerText: true });
  await expect(dialog.getByTestId("mapping-technical")).toContainText("sheet_form/rules");
  // the focus follows each form, and comes back to the button that opened it (review A11Y-2)
  await dialog.getByTestId("mapping-reject-open").click();
  await expect(dialog.getByTestId("mapping-reject-why")).toBeFocused();
  await dialog.getByTestId("mapping-reject").getByRole("button", { name: "Cancel" }).click();
  await expect(dialog.getByTestId("mapping-reject-open")).toBeFocused();
  await page.keyboard.press("Enter");                                  // the keyboard alone: Reject… opens its form again
  await expect(dialog.getByTestId("mapping-reject-why")).toBeFocused();
  await dialog.getByTestId("mapping-reject").getByRole("button", { name: "Cancel" }).click();
  await dialog.getByTestId(`mapping-table-fix-${rld.region_id}`).click();
  await expect(dialog.getByTestId("mapping-edit-title")).toBeFocused();
  await expect(dialog.getByTestId("mapping-edit-title")).toContainText("checked on sheet pH 6.8");
  // the form: fields by their labels, the rows told apart by a cell and the facts read once, no JSON to type (OWN-8)
  await expect(dialog.getByTestId("mapping-layout-rule-add")).toBeVisible();
  await expect(dialog.getByTestId("mapping-layout-fact-batch")).toContainText("Batch, read from");
  await expect(dialog.getByTestId("mapping-layout-kind").locator("option:checked")).toHaveText("dissolution table");
  // the three columns that are not values (Mean, SD, %CV) are not data, said with a reason; stored for RLD's table
  for (const column of [14, 15, 16]) {
    await dialog.getByTestId(`mapping-layout-role-${column}`).selectOption("ignore");
    await dialog.getByTestId(`mapping-layout-reason-${column}`).fill("a summary of the vessels, not data");
  }
  await dialog.getByTestId("mapping-edit-why").fill("RLD's Mean, SD and %CV columns summarise the vessels");
  await dialog.getByTestId("mapping-edit-submit").click();
  await expect(dialog.getByTestId("mapping-said")).toContainText("Version 3 is stored and waits for approval");
  await expect(dialog.getByTestId("mapping-version")).toHaveText("version 3");
  await expect(dialog.getByTestId("mapping-sample")).toContainText("of Dissolution RLD pH 6.8.xlsx");
  await expect(dialog.getByTestId("mapping-status")).toHaveText("waits for approval");
  await expect.poll(async () => !(await read<Delivery>(request, "delivery")).running, { timeout: 120_000, intervals: [1000] }).toBe(true);
  await dialog.getByTestId("mapping-approve-why").fill("checked against RLD's file");
  await dialog.getByTestId("mapping-approve-submit").click();
  await expect(dialog.getByTestId("mapping-said")).toContainText("Version 3 of the dissolution table layout is approved");
  await expect.poll(async () => {
    const r = await regionOf("Dissolution RLD pH 6.8.xlsx");
    return [r.mapping_version, r.silent];
  }, { timeout: 120_000, intervals: [1000] }).toEqual([3, 0]);
  // RLD's row leaves To do; the dialog stays, still saying what was done, until it is closed
  await expect(page.getByTestId(`notread-${file}`)).toHaveCount(0);
  await expect(dialog).toBeVisible();
  await expect(dialog.getByTestId("mapping-said")).toContainText("is approved");
  await shot(page, "8-layout-corrected");
  await dialog.getByTestId("mapping-close").click();
  await expect(dialog).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => document.activeElement !== document.body)).toBe(true);
});
