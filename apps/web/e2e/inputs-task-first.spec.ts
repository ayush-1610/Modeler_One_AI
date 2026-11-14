// To do's batch work (plan docs/plans/2026-11-14-inputs-task-first.md slice 4), end to end on the nine messy files of the
// made-up Exampleamide (the seed of the two UX projects): the link table, one row per file, where the two 230-23 files
// that hold the same subjects and periods are refused one arm of one study and given an arm each right there, then linked
// in one go, one call per destination; a file's loose numbers marked as not data in one go, restored, and two files' in
// one batch with the last reason offered again; the compound values no source gives entered with one citation; the
// layouts walked as a queue at their versions, and the "not data" readings approved together, each note naming the
// others; after each decision the focus moves on and the change is said; a decision costs at most two requests; and on
// a phone the rows stack, nothing scrolls sideways and the bulk bar stays reachable. Software test data, never a model.
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { AUTH, finishStart } from "./fixtures/inputs";

const REPO = resolve(__dirname, "../../..");

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
 *  settles; the app's own reads that are not the project's (the escalations bell) are not the decision's. */
async function requests(page: Page, act: () => Promise<void>, settle = 2500): Promise<string[]> {
  const seen: string[] = [];
  const hear = (r: { method(): string; url(): string }) => {
    if (r.url().includes(`/api/v1/projects/${projectId}/`) || r.url().includes("_rsc=")) {
      seen.push(`${r.method()} ${r.url().replace(/^.*\/projects\/[^/]+\//, "")}`);
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
  await expect(page.getByTestId("todo-live")).toContainText("linked to study 230-23 · arm Reference (new); study 230-23 · arm Test (new). 4 files left to link.");
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
  await expect(page.getByTestId("todo-live")).toContainText(`“Note: 3 samples were re-assayed on day 14” marked as not data. ${before - 1} loose numbers left.`);
  await expect(page.locator(":focus")).toHaveAttribute("data-testid", /^notread-/);
  await shot(page, "3-marked");
  // restored where it was marked, with the reason
  const marked = page.getByTestId("notread-marked");
  await marked.getByTestId(`notread-undo-${messy}-0`).click();
  await marked.getByTestId(`notread-undo-${messy}-0-why`).fill("it records a re-assay: kept as data");
  await marked.getByTestId(`notread-undo-${messy}-0-submit`).click();
  await expect(table.getByTestId(`notread-${messy}`)).toBeVisible();
  await expect.poll(async () => (await read<Delivery>(request, "delivery")).totals.outside_numeric).toBe(before);
  // two files' loose numbers in one batch, the last reason offered again: one decision per file
  await table.getByTestId(`notread-pick-${tpl}`).check();
  await table.getByTestId(`notread-pick-${raw}`).check();
  const bar = page.getByTestId("bulk-notread-bar");
  await expect(bar.getByTestId("bulk-notread-bar-count")).toHaveText("2 files picked");
  await expect(bar.getByTestId("bulk-notread-last")).toHaveText("use last: a note, not data");
  await bar.getByTestId("bulk-notread-last").click();
  await bar.getByTestId("bulk-notread-submit").click();
  await expect(table.getByTestId(`notread-${raw}`)).not.toContainText("loose number");
  await expect(table.getByTestId(`notread-${tpl}`)).not.toContainText("loose number");
  expect(excludes).toBe(3);
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
  await mv.getByTestId("mv-submit").click();
  await expect(mv.getByRole("alert")).toHaveText("Give the source's DOI or URL, or call it an assumption");
  await mv.getByTestId("mv-title").fill("Exampleamide physico-chemistry");
  await mv.getByTestId("mv-link").fill("10.1000/exampleamide");
  let posts = 0;
  page.on("request", (r) => { if (r.method() === "POST" && /\/evidence$/.test(r.url())) posts += 1; });
  await mv.getByTestId("mv-submit").click();
  await expect(page.getByTestId("todo-live")).toContainText("Molecular weight, Lipophilicity: 2 values added with “Exampleamide physico-chemistry”.");
  await expect(mv.getByTestId("mv-row-phys.mw")).toHaveCount(0);
  expect(posts).toBe(2);
  const rows = (await read<{ compound: { id: string; state: string }[] }>(request, "inputs")).compound;
  for (const id of ["phys.mw", "phys.logp"]) expect(rows.find((r) => r.id === id)!.state).not.toBe("missing");
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
  const sent = await requests(page, async () => {
    await dialog.getByTestId("mapping-approve-submit").click();
    await expect(dialog.getByTestId("mapping-said")).toContainText("of the excretion table layout is approved");
  }, 1000);
  // the approval and the page read once; the next layout's own read is the queue moving on (the page is read again
  // every 3 s while the layout's file is being read again: that is a reading, not the decision)
  expect(sent.filter((r) => !/mappings\/mp-[0-9a-f]+\?version=/.test(r)), sent.join("\n"))
    .toEqual([`POST delivery/mappings/${urine.mapping_id}:approve`, "GET delivery"]);
  if (at < total) await expect(dialog.getByTestId("mapping-position")).toHaveText(`${at + 1} of ${total}`);
  await shot(page, "4-queue");
  await dialog.getByTestId("mapping-close").click();
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
});
