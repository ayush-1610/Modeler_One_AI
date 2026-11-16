// Inputs with the keyboard and a screen reader (plan docs/plans/2026-11-14-inputs-task-first.md §2.1; final review round 3,
// accessibility and forms), on the nine messy files of the made-up Exampleamide: the skip link to the areas; the status
// counts not said while the page reads its work, and said once when a decision changes them; the focus handed on when a
// control removes itself (a question answered, a form cancelled, the bulk bar cleared), never left on the page; the bulk
// bar never over the row the focus is on, and in view on a phone; a refusal said beside the field it is about, again on
// each press; each area under a heading of its own; repeated buttons named with what they are about, with every study
// card open at once and on the client-data template's project too; the demographics form taking the focus however it
// opens on a fresh page (round 4), again each time it is asked for while open, and a save of several fields moving the
// focus once (round 5); Client files on a phone, each file opened too (round 5); a message cleared whichever way the area
// changes; with every values table, its pages, every list of more checks and a spot check open, no two controls named
// alike and no field's id in a name (round 5), nor a raw id in the text or a name of any area, Client files' files open
// with their tables and texts (round 6; names with ": " are read too: the snapshot quotes them); on a phone a file's tables
// and texts are blocks with their state in view, and a PDF's page lines are read whole at a tablet's width (round 6). The
// focus after the signing step-up is checked where a study is signed, in delivery.spec.ts. Software test data, never a model.
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { expect, type APIRequestContext, type Locator, type Page, test } from "@playwright/test";

import { AUTH, finishStart } from "./fixtures/inputs";

const REPO = resolve(__dirname, "../../..");

type File = { file_id: string; name: string; sha256: string };
type Delivery = { running: boolean; deliveries: { files: File[] }[] };

let projectId = "";
let files: File[] = [];

const api = (path: string) => `/api/v1/projects/${projectId}/${path}`;
async function read<T>(request: APIRequestContext, path: string): Promise<T> {
  return (await (await request.get(api(path), { headers: AUTH })).json()).data as T;
}
const fid = (name: string) => files.find((f) => f.name === name)!.file_id;
const focused = (page: Page) => page.evaluate(() => document.activeElement?.getAttribute("data-testid") ?? document.activeElement?.id ?? document.activeElement?.tagName);
/** To do, read: every card the page counts from is read and the page is idle. */
async function settled(page: Page) {
  await expect(page.getByTestId("link-table")).toBeVisible();
  await expect(page.getByTestId("status-checking")).toHaveCount(0);
  await page.waitForLoadState("networkidle");
}

/** The names that more than one visible control of the panel shares: buttons, links and form fields (final review A11Y-7). */
const repeated = (panel: Locator) => panel.evaluate((root) => {
  const seen = new Map<string, number>();
  for (const el of root.querySelectorAll<HTMLElement>("button, select, input:not([type=hidden]), textarea, a[href]")) {
    if (!el.checkVisibility() || el.closest('[aria-hidden="true"]')) continue;
    const labelled = el.getAttribute("aria-label") ?? (el.id ? document.querySelector(`label[for="${CSS.escape(el.id)}"]`)?.textContent : null)
      ?? el.closest("label")?.textContent ?? el.textContent ?? "";
    const name = labelled.replace(/\s+/g, " ").trim();
    if (name) seen.set(name, (seen.get(name) ?? 0) + 1);
  }
  return [...seen].filter(([, n]) => n > 1).map(([name, n]) => `${name} ×${n}`);
});

/** Every study card of Clinical studies open at once (a delivery study's and a sheet-form study's), each read. */
async function openEveryStudy(page: Page) {
  const panel = page.locator("#inputs-panel-studies");
  const closed = panel.locator('[aria-expanded="false"][data-testid^="delivery-subject-open-"], [aria-expanded="false"][data-testid^="toggle-"]');
  for (let round = 0; round < 4 && await closed.count(); round += 1) {
    for (let n = await closed.count(); n > 0; n -= 1) await closed.first().click();
  }
  await expect(closed).toHaveCount(0);
  await page.waitForLoadState("networkidle");
  await expect(panel.locator('[data-testid^="delivery-card-reading-"]')).toHaveCount(0);
  return panel.locator('[aria-expanded="true"][data-testid^="delivery-subject-open-"], [aria-expanded="true"][data-testid^="toggle-"]').count();
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
  // the nine files of the 9-file project, as inputs-task-first.spec.ts seeds them
  const dir = mkdtempSync(join(tmpdir(), "inputs-a11y-"));
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

test("the skip link takes the keyboard to the areas; the counts are not said while the page reads its work, each area has its heading", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/projects/${projectId}/inputs?tab=todo`);
  await settled(page);
  await page.waitForTimeout(2500);
  // the counts climb while the cards are read: nothing is said of them (final review A11Y-6); the status line holds no
  // live region but the one that says a change after the page has read its work
  await expect(page.getByTestId("status-said")).toHaveText("");
  await expect(page.getByTestId("inputs-status").locator("[aria-live], [role=status]")).toHaveCount(1);
  // past the app's own skip link, the page's first stop is the skip link to the areas (plan §2.1), which lands on the
  // area shown
  await page.keyboard.press("Tab");
  await expect(page.locator(":focus")).toHaveText("Skip to the page");
  await page.keyboard.press("Enter");
  await page.keyboard.press("Tab");
  await expect(page.getByTestId("skip-to-areas")).toBeFocused();
  await expect(page.getByTestId("skip-to-areas")).toBeInViewport();
  await page.keyboard.press("Enter");
  await expect(page.locator("#inputs-tab-todo")).toBeFocused();
  await expect(page.locator("#inputs-tab-todo")).toHaveAttribute("aria-selected", "true");
  // each area under a heading of its own, named after it, under the page's (A11Y-10): no area jumps from h1 to h3
  for (const [tab, name] of [["compound", "Compound"], ["individuals", "Populations and individuals"], ["settings", "Simulation settings"]] as const) {
    await page.getByTestId(`tab-${tab}`).click();
    const panel = page.locator(`#inputs-panel-${tab}`);
    await expect(panel.getByRole("heading", { level: 2 }).first()).toHaveText(name);
    const levels = await panel.locator("h2, h3, h4").evaluateAll((hs) => hs.map((h) => Number(h.tagName[1])));
    expect(levels[0], `the first heading of ${name}`).toBe(2);
    for (let i = 1; i < levels.length; i += 1) expect(levels[i] - levels[i - 1], `${name}: no level skipped`).toBeLessThanOrEqual(1);
  }
});

test("a control that removes itself hands the focus on: a question answered, a form cancelled, the bulk bar cleared", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/projects/${projectId}/inputs?tab=todo`);
  await settled(page);
  const table = page.getByTestId("link-table");
  const ref = fid("230-23 Fasting Reference.xlsx"), tst = fid("230-23 Fasting Test.xlsx");
  // "Same study as 230-23?" answered from the keyboard: the focus goes to the row's own button, never to the page
  await table.getByTestId(`link-alias-yes-${ref}`).focus();
  await page.keyboard.press("Enter");
  await expect(table.getByTestId(`link-to-${ref}`)).toContainText("→ study 230-23");
  await expect(table.getByTestId(`link-open-${ref}`)).toBeFocused();
  await table.getByTestId(`link-alias-no-${tst}`).focus();
  await page.keyboard.press("Enter");
  await expect(table.getByTestId(`link-open-${tst}`)).toBeFocused();
  // a form opened in place takes the focus; cancelled, the focus is back on what opened it
  const queue = page.getByTestId("layout-queue");
  await queue.getByTestId("layout-notdata-open").focus();
  await page.keyboard.press("Enter");
  await expect(queue.getByTestId("layout-notdata-why")).toBeFocused();
  await queue.getByTestId("layout-notdata").getByRole("button", { name: "Cancel" }).focus();
  await page.keyboard.press("Enter");
  await expect(queue.getByTestId("layout-notdata-open")).toBeFocused();
  const messy = fid("messy-delivery.xlsx");
  const notRead = page.getByTestId("notread-table");
  await notRead.getByTestId(`notread-mark-open-${messy}`).focus();
  await page.keyboard.press("Enter");
  await expect(notRead.getByTestId(`notread-mark-${messy}-why`)).toBeFocused();
  await notRead.getByTestId(`notread-mark-${messy}`).getByRole("button", { name: "Cancel" }).focus();
  await page.keyboard.press("Enter");
  await expect(notRead.getByTestId(`notread-mark-open-${messy}`)).toBeFocused();
  // the bulk bar cleared from the keyboard: the focus goes to "Pick every file", the bar being gone
  await table.getByTestId(`link-pick-${ref}`).focus();
  await page.keyboard.press("Space");
  await table.getByTestId(`link-pick-${tst}`).focus();
  await page.keyboard.press("Space");
  const bar = page.getByTestId("bulk-link-bar");
  await expect(bar.getByTestId("bulk-link-bar-clear")).toHaveAccessibleName("Clear the files picked to link");
  await bar.getByTestId("bulk-link-bar-clear").focus();
  await page.keyboard.press("Enter");
  await expect(bar).toHaveCount(0);
  await expect(table.getByTestId("link-pick-all")).toBeFocused();
  expect(await focused(page)).not.toBe("BODY");
});

test("the bulk bar never covers the row the focus is on, and stays in view on a phone", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/projects/${projectId}/inputs?tab=todo`);
  await settled(page);
  const table = page.getByTestId("link-table");
  // every file picked: where each goes is folded under one line, so the bar stays low
  await table.getByTestId("link-pick-all").check();
  const bar = page.getByTestId("bulk-link-bar");
  await expect(bar.getByTestId("bulk-link-where")).toBeVisible();
  const height = (await bar.boundingBox())!.height;
  expect(height, "the bar with every file picked").toBeLessThan(260);
  // from "Pick every file", down the rows by Tab: no stop lies under the bar (WCAG 2.4.11, final review A11Y-3)
  await table.getByTestId("link-pick-all").focus();
  await table.getByTestId("link-pick-all").evaluate((el) => el.scrollIntoView({ block: "start" }));
  for (let i = 0; i < 14; i += 1) {
    await page.keyboard.press("Tab");
    const at = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement, barEl = document.querySelector<HTMLElement>('[data-testid="bulk-link-bar"]');
      if (!barEl || barEl.contains(el)) return null;
      const r = el.getBoundingClientRect(), b = barEl.getBoundingClientRect();
      return { id: el.getAttribute("data-testid") ?? el.tagName, under: r.bottom > b.top + 1 && r.top < b.bottom - 1 };
    });
    if (at === null) break;                                                      // into the bar itself
    expect(at.under, `${at.id} lies under the bulk bar`).toBe(false);
  }
  await table.getByTestId("link-pick-all").uncheck();

  // on a phone: the To do card is no scroll box, so the bar sticks to the bottom of the screen (final review A11Y-4)
  await page.setViewportSize({ width: 390, height: 844 });
  await table.getByTestId(`link-pick-${fid("Dissolution RLD pH 6.8.xlsx")}`).check();
  const first = table.locator("li.batch-row").first();
  await first.evaluate((el) => window.scrollBy(0, el.getBoundingClientRect().top - 300));
  await expect(bar).toBeInViewport({ ratio: 1 });
  const box = await bar.evaluate((el) => { const r = el.getBoundingClientRect(); return { top: r.top, bottom: r.bottom, h: window.innerHeight }; });
  expect(box.top).toBeGreaterThanOrEqual(0);
  expect(box.bottom).toBeLessThanOrEqual(box.h + 1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1)).toBe(false);
  await page.screenshot({ path: test.info().outputPath("phone-bar.png") });
});

test("a refusal is said beside what it is about, again on each press; the reason field is marked only when the reason is missing", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/projects/${projectId}/inputs?tab=todo`);
  await settled(page);
  let assigns = 0, evidence = 0;
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().endsWith("/values:assign")) assigns += 1;
    if (r.method() === "POST" && r.url().endsWith("/evidence")) evidence += 1;
  });
  const table = page.getByTestId("link-table");
  await table.getByTestId(`link-pick-${fid("Dissolution RLD pH 6.8.xlsx")}`).check();
  const bar = page.getByTestId("bulk-link-bar");
  // pressed with no reason: the reason is what is missing, and its field says so
  await bar.getByTestId("bulk-link-one").check();
  await bar.getByTestId("bulk-link-submit").click();
  const said = bar.getByTestId("bulk-link-missing");
  await expect(said).toHaveText(/^Dissolution RLD pH 6\.8\.xlsx: Pick a study or a product$/);
  await expect(bar.getByTestId("bulk-link-why")).not.toHaveAttribute("aria-invalid", "true");
  await expect(bar.getByTestId("bulk-link-submit")).toHaveAttribute("aria-describedby", /.+/);
  // pressed again: said again (a new alert), not a silent repeat
  await said.evaluate((el) => el.setAttribute("data-seen", "1"));
  await bar.getByTestId("bulk-link-submit").click();
  await expect(said).toHaveText(/Pick a study or a product$/);
  await expect(said).not.toHaveAttribute("data-seen", "1");
  // the place chosen, the reason is what is left: now the field is marked, and the message is about it
  await bar.getByTestId("link-study-bulk").selectOption({ index: 1 });
  await expect(said).toHaveCount(0);
  await bar.getByTestId("bulk-link-submit").click();
  await expect(said).toHaveText("Give the reason: it is kept on the audit trail.");
  await expect(bar.getByTestId("bulk-link-why")).toHaveAttribute("aria-invalid", "true");
  expect(assigns).toBe(0);
  await bar.getByTestId("bulk-link-bar-clear").click();

  // the compound values to type: the field a message is about is marked; "Add" is named "Add" while nothing is typed
  const mv = page.getByTestId("missing-values");
  await expect(mv.getByTestId("mv-submit")).toHaveAccessibleName("Add");
  await mv.getByTestId("mv-submit").click();
  await expect(mv.getByRole("alert")).toHaveText("Type at least one value");
  await expect(mv.getByTestId("mv-value-phys.mw")).toHaveAttribute("aria-invalid", "true");
  await mv.getByTestId("mv-value-phys.mw").fill("225.2");
  await expect(mv.getByRole("alert")).toHaveCount(0);
  await expect(mv.getByTestId("mv-value-phys.mw")).not.toHaveAttribute("aria-invalid", "true");
  await mv.getByTestId("mv-submit").click();
  await expect(mv.getByRole("alert")).toHaveText("Give the source's DOI or URL, or call it an assumption");
  await expect(mv.getByTestId("mv-link")).toHaveAttribute("aria-invalid", "true");
  await expect(mv.getByTestId("mv-value-phys.mw")).not.toHaveAttribute("aria-invalid", "true");
  await mv.getByTestId("mv-link").fill("10.1000/exampleamide");
  await expect(mv.getByRole("alert")).toHaveCount(0);
  await expect(mv.getByTestId("mv-link")).not.toHaveAttribute("aria-invalid", "true");
  expect(evidence).toBe(0);
});

test("repeated buttons and fields carry what they are about; a decision is said once, and the counts once after it", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/projects/${projectId}/inputs?tab=todo`);
  await settled(page);
  await page.waitForTimeout(1500);
  // To do's tables, the link editors open: every repeated control names its file (plan §2.1, final review A11Y-7)
  const table = page.getByTestId("link-table");
  for (const name of ["Dissolution RLD pH 6.8.xlsx", "Dissolution Test pH 6.8.xlsx"]) {
    await table.getByTestId(`link-open-${fid(name)}`).click();
    await table.getByTestId(`link-values-${fid(name)}`).click();                 // each with its values shown
  }
  const found: string[] = (await repeated(page.locator("#inputs-panel-todo"))).map((x) => `To do: ${x}`);
  for (const name of ["Dissolution RLD pH 6.8.xlsx", "Dissolution Test pH 6.8.xlsx"]) await table.getByTestId(`link-open-${fid(name)}`).click();
  // every other area as it opens (its first cards open): each study's, product's and file's buttons name it; on Clinical
  // studies with every study's card open at once, so each card's forms, facts, tables and spot check name their study
  // (final review round 4: Route, Save this fact, Start the spot check, Open in To do … repeated once per card)
  for (const tab of ["compound", "formulations", "studies", "individuals", "settings", "files"]) {
    await page.getByTestId(`tab-${tab}`).click();
    await expect(page.locator(`#inputs-panel-${tab}`)).toBeVisible();
    await page.waitForLoadState("networkidle");
    if (tab === "studies") expect(await openEveryStudy(page), "study cards open at once").toBeGreaterThan(2);
    found.push(...(await repeated(page.locator(`#inputs-panel-${tab}`))).map((x) => `${tab}: ${x}`));
  }
  expect(found).toEqual([]);

  // a decision: said once, by To do's live region; the counts it changes said once after it, once they settle
  await page.getByTestId("tab-todo").click();
  await settled(page);
  await expect(page.getByTestId("status-said")).toHaveText("");
  const iv = fid("Nichols2012 IV 50 mg 5 h infusion.xlsx");
  await table.getByTestId(`link-open-${iv}`).click();
  const editor = table.getByTestId(`link-editor-${iv}`);
  await editor.getByTestId(`link-study-${iv}`).selectOption("__new__");
  await editor.getByTestId(`link-new-study-${iv}`).fill("Nichols2012-IV");
  await editor.getByTestId(`link-edit-${iv}-why`).fill("the file is the published IV study of Nichols 2012");
  await editor.getByTestId(`link-edit-${iv}-submit`).click();
  await expect(table.getByTestId(`link-${iv}`)).toHaveCount(0);
  await expect(page.getByTestId("todo-live")).toContainText("Nichols2012 IV 50 mg 5 h infusion.xlsx linked to study Nichols2012-IV");
  await expect(page.getByTestId("status-said")).toHaveText(/^Now \d+ missing, \d+ to confirm, \d+ to decide\.$/, { timeout: 20_000 });
  await expect(page.getByTestId("status-said")).not.toContainText("linked");
  // the next link's reason starts empty, with the last one offered for this kind of decision (final review CODE-7, INT-12)
  const rld = fid("Dissolution RLD pH 6.8.xlsx");
  await table.getByTestId(`link-open-${rld}`).click();
  await expect(table.getByTestId(`link-edit-${rld}-why`)).toHaveValue("");
  await expect(table.getByTestId(`link-edit-${rld}-last`)).toHaveAccessibleName("Use the last reason: the file is the published IV study of Nichols 2012");
  // a reason of another kind of decision is not offered here: the loose numbers' form has none yet
  await table.getByTestId(`link-open-${rld}`).click();
  const messy = fid("messy-delivery.xlsx");
  await page.getByTestId(`notread-mark-open-${messy}`).click();
  await expect(page.getByTestId(`notread-mark-${messy}-last`)).toHaveCount(0);
});

type Row = { subject: string; subject_type: string; label: string; blinded: boolean };
type Card = { confirm_on: string; requirements: { req_id: string; status: string; disposition: string | null }[];
              individual: { stated: string[] } | null };

test("the demographics form takes the focus on its first field however it opens, on a fresh page; Enter's fact field takes it", async ({ page, request }) => {
  // two client studies whose demographics no file states; the second gets its population and mean age, not its individual
  const rows = (await read<{ subjects: Row[] }>(request, "delivery")).subjects.filter((s) => s.subject_type === "study" && !s.blinded);
  const asked: string[] = [];
  for (const r of rows) {
    const card = await read<Card>(request, `delivery/subjects/study/${r.subject}`);
    const item = card.requirements.find((x) => x.req_id === "REQ-sys.demographics");
    if (card.confirm_on === "delivery" && item?.status === "missing" && !item.disposition && !card.individual?.stated.length) asked.push(r.subject);
  }
  expect(asked.length, "studies whose demographics are asked").toBeGreaterThanOrEqual(2);
  const [enter, choose] = asked;
  for (const body of [{ field: "population", value: "healthy" }, { field: "age_mean", value: 34 }]) {
    const answer = await request.post(api(`delivery/subjects/study/${choose}:enter`), { headers: AUTH, data: { ...body, why: "from the study report" } });
    expect(answer.ok(), await answer.text()).toBeTruthy();
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  // each opener on a page that has not read the layout's words yet: the population is drawn disabled while they are read,
  // and the form takes the focus once it can (final review round 4: an autoFocus never ran, and the focus fell to the page)
  await page.goto(`/projects/${projectId}/inputs?tab=individuals`);
  const enterThem = page.getByTestId(`individual-enter-open-${enter}`);
  await expect(enterThem).toBeEnabled();
  await enterThem.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId(`individual-enter-${enter}-population`)).toBeFocused();
  await expect(page.getByTestId(`individual-enter-${enter}-population`)).toBeEnabled();
  // "Choose the individual…" opens it on the individual's PK-Sim population
  await page.goto(`/projects/${projectId}/inputs?tab=individuals`);
  const chooseIt = page.getByTestId(`individual-enter-open-${choose}`);
  await expect(chooseIt).toHaveText("Choose the individual…");
  await chooseIt.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId(`individual-enter-${choose}-individual_population`)).toBeFocused();

  // on the study's card: "Enter them…", then "Enter another fact…", whose fact field takes the focus (not its reason)
  await page.goto(`/projects/${projectId}/inputs?tab=studies`);
  const openCard = async (subject: string) => {
    const toggle = page.getByTestId(`delivery-subject-open-${subject}`);
    if ((await toggle.getAttribute("aria-expanded")) !== "true") await toggle.click();
    await expect(page.getByTestId(`delivery-card-${subject}`)).toBeVisible();
    return page.getByTestId(`delivery-card-${subject}`);
  };
  let card = await openCard(enter);
  await card.getByTestId(`delivery-demographics-open-${enter}`).focus();
  await page.keyboard.press("Enter");
  await expect(card.getByTestId(`delivery-demographics-${enter}-population`)).toBeFocused();
  await card.getByTestId(`delivery-demographics-${enter}-reason`).getByRole("button", { name: "Cancel" }).click();
  await expect(card.getByTestId(`delivery-demographics-open-${enter}`)).toBeFocused();
  await card.getByTestId(`delivery-enter-open-${enter}`).focus();
  await page.keyboard.press("Enter");
  await expect(card.getByTestId(`delivery-enter-${enter}-field`)).toBeFocused();
  await expect(card.getByTestId(`delivery-enter-${enter}-field`)).toHaveAccessibleName(/^Fact: study /);

  // the spot check's "Choose the individual…" (the study's individual comes first): on a fresh page, the PK-Sim population
  await page.goto(`/projects/${projectId}/inputs?tab=studies`);
  card = await openCard(choose);
  const first = card.getByTestId(`spot-first-go-${choose}`);
  await expect(first).toBeVisible();
  await first.focus();
  await page.keyboard.press("Enter");
  const individualField = card.getByTestId(`delivery-demographics-${choose}-individual_population`);
  await expect(individualField).toBeFocused();
  expect(await focused(page)).not.toBe("BODY");
  // pressed again while the form is open (the person went on to another field, then back to the link): the focus goes
  // to the form again, every time, not only the first (final review round 5: it only scrolled)
  for (let press = 0; press < 2; press += 1) {
    await card.getByTestId(`delivery-demographics-${choose}-weight_mean_kg`).focus();
    await first.focus();
    await page.keyboard.press("Enter");
    await expect(individualField).toBeFocused();
  }
  // the form opened by the row's own "Choose the individual…", then the spot check's link: the same
  await card.getByTestId(`delivery-demographics-${choose}-reason`).getByRole("button", { name: "Cancel" }).click();
  await expect(card.getByTestId(`delivery-demographics-open-${choose}`)).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(individualField).toBeFocused();
  await first.focus();
  await expect(first).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(individualField).toBeFocused();

  // a save of several fields on Populations: the focus moves once, to where the work goes on (the study's "Choose the
  // individual…"), never back to the population on each field written (round 5: the form was remounted three times)
  await page.goto(`/projects/${projectId}/inputs?tab=individuals`);
  const opener = page.getByTestId(`individual-enter-open-${enter}`);
  await expect(opener).toBeEnabled();
  await opener.click();
  const form = `individual-enter-${enter}`;
  await expect(page.getByTestId(`${form}-population`)).toBeFocused();
  await page.getByTestId(`${form}-population`).selectOption({ index: 1 });
  await page.getByTestId(`${form}-age_mean`).fill("34");
  await page.getByTestId(`${form}-weight_mean_kg`).fill("70");
  await page.getByTestId(`${form}-why`).fill("from the study report");
  await page.getByTestId(`${form}-submit`).focus();
  await page.evaluate(() => {
    const moves: string[] = [];
    (window as unknown as { focusMoves: string[] }).focusMoves = moves;
    document.addEventListener("focusin", (e) => moves.push((e.target as HTMLElement).getAttribute("data-testid") ?? (e.target as HTMLElement).tagName), true);
  });
  let entered = 0;
  page.on("request", (r) => { if (r.method() === "POST" && r.url().endsWith(`/delivery/subjects/study/${enter}:enter`)) entered += 1; });
  await page.keyboard.press("Enter");
  await expect(page.getByTestId(form)).toHaveCount(0, { timeout: 20_000 });
  await expect(opener).toBeFocused();
  await expect(opener).toHaveText("Choose the individual…");
  expect(entered, "one entry per field").toBe(3);
  await page.waitForTimeout(500);
  expect(await page.evaluate(() => (window as unknown as { focusMoves: string[] }).focusMoves)).toEqual([`individual-enter-open-${enter}`]);
});

test("on a phone each file of Client files fits its box; a message of one area is cleared whichever way the area changes", async ({ page }) => {
  // a phone: each file is a block of its parts under their column's name, as wide as its box (final review round 4: the
  // kit's table width kept each block 560 px wide in a 358 px box, and its long lines were cut)
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/projects/${projectId}/inputs?tab=files`);
  const table = page.locator(".files-table").first();
  await expect(table).toBeVisible();
  await page.waitForLoadState("networkidle");
  const fit = await table.evaluate((t) => {
    const box = (t.closest(".table-scroll") ?? t.parentElement) as HTMLElement;
    const right = box.getBoundingClientRect().right;
    const cells = [...t.querySelectorAll<HTMLElement>("tbody tr:not(.files-detail) > td")];
    return { cells: cells.length, box: box.clientWidth, scroll: box.scrollWidth,
             cut: cells.filter((td) => td.getBoundingClientRect().right > right + 1 || td.scrollWidth > td.clientWidth + 1).length };
  });
  expect(fit.cells).toBeGreaterThan(0);
  expect(fit.cut, "cells cut at the box's edge").toBe(0);
  expect(fit.scroll, "the box scrolls sideways").toBeLessThanOrEqual(fit.box + 1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1)).toBe(false);
  await page.screenshot({ path: test.info().outputPath("phone-files.png"), fullPage: true });

  // each file opened, with its reading's tables and texts shown: nothing of it passes the box, but inside a scroll box of
  // its own that fits (a values table, the sheet grid), the box does not scroll sideways, nor does the page, and no line
  // is clipped (final review round 5: the file's sheet table kept the kit's 560 px and the files' phone rules, so its long
  // lines were cut whenever 7 of the 9 files was open)
  const toggles = table.locator(":scope > tbody > tr > td .files-name");
  const count = await toggles.count();
  expect(count).toBe(9);
  let statesSeen = 0;
  for (let i = 0; i < count; i += 1) {
    const name = (await toggles.nth(i).textContent())!.replace(/^[▸▾]/, "");
    await toggles.nth(i).click();
    const detail = table.locator("tr.files-detail");
    await expect(detail).toBeVisible();
    await page.waitForLoadState("networkidle");
    const reading = detail.getByRole("button", { name: /^Show its tables and texts/ });
    if (await reading.count()) { await reading.first().click(); await page.waitForLoadState("networkidle"); }
    const open = await detail.evaluate((det) => {
      const box = det.closest(".table-scroll") as HTMLElement;
      const right = box.getBoundingClientRect().right;
      // a scroll box of its own inside the files box, that fits it: what is in it scrolls there, nothing is cut
      const ownScroll = (el: Element) => {
        for (let p = el.parentElement; p && p !== box; p = p.parentElement) {
          if (/(auto|scroll)/.test(getComputedStyle(p).overflowX) && p.getBoundingClientRect().right <= right + 1) return true;
        }
        return false;
      };
      const past: string[] = [], clipped: string[] = [];
      for (const el of det.querySelectorAll<HTMLElement>("*")) {
        const r = el.getBoundingClientRect();
        if (!r.width || ownScroll(el)) continue;
        if (r.right > right + 1) past.push(`${el.tagName} “${(el.textContent ?? "").trim().slice(0, 40)}”`);
        if (/(hidden|clip)/.test(getComputedStyle(el).overflowX) && el.scrollWidth > el.clientWidth + 1 && !el.classList.contains("sr-only")) {
          clipped.push(`${el.tagName} “${(el.textContent ?? "").trim().slice(0, 40)}”`);
        }
      }
      return { past, clipped, box: box.clientWidth, scroll: box.scrollWidth,
               page: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1 };
    });
    expect(open.past, `${name}: past the box's edge`).toEqual([]);
    expect(open.clipped, `${name}: lines clipped`).toEqual([]);
    expect(open.scroll, `${name}: the box scrolls sideways`).toBeLessThanOrEqual(open.box + 1);
    expect(open.page, `${name}: the page scrolls sideways`).toBe(false);
    // its tables and texts, each a block under its column's names: no box of their own scrolls sideways, and each one's
    // state and its layout's chip are in view (round 6: that table scrolled in its own box, "waits for approval" of
    // messy-delivery.xlsx's layout half off the screen until it was scrolled)
    const regions = await detail.evaluate((det) => [...det.querySelectorAll<HTMLElement>("table.delivery-regions")].map((t) => {
      const box = (t.closest(".table-scroll") ?? t.parentElement) as HTMLElement;
      const right = Math.min(box.getBoundingClientRect().right, document.documentElement.clientWidth);
      const states = [...t.querySelectorAll<HTMLElement>("td[data-label='State'] .chip, td[data-label='Layout'] .delivery-chip-btn")];
      return { scroll: box.scrollWidth - box.clientWidth, states: states.length,
               off: states.filter((c) => c.getBoundingClientRect().right > right + 1).map((c) => (c.textContent ?? "").trim()) };
    }));
    for (const r of regions) {
      expect(r.scroll, `${name}: its tables and texts scroll sideways`).toBeLessThanOrEqual(1);
      expect(r.off, `${name}: a table's state off the screen`).toEqual([]);
    }
    statesSeen += regions.reduce((n, r) => n + r.states, 0);
    if (name === "Dissolution RLD pH 6.8.xlsx") await detail.screenshot({ path: test.info().outputPath("phone-file-open.png") });
    await toggles.nth(i).click();
    await expect(table.locator("tr.files-detail")).toHaveCount(0);
  }
  expect(statesSeen, "tables and texts with their state, read on a phone").toBeGreaterThan(0);

  // a tablet (601 to 900 px) and a laptop, each file opened with its tables and texts: a page's line of a PDF is read
  // whole, wrapping in its place (round 6: the one-line quote with an ellipsis was kept above a phone's width), and the
  // tables and texts do not scroll sideways in their box (at 768 px their last column did)
  for (const width of [768, 1024]) {
    // opened afresh at that width, as a tablet opens it (a page left from a phone's width keeps its menu drawn over it)
    await page.setViewportSize({ width, height: 1024 });
    await page.goto(`/projects/${projectId}/inputs?tab=files`);
    await expect(table).toBeVisible();
    await page.waitForLoadState("networkidle");
    let lines = 0;
    for (let i = 0; i < count; i += 1) {
      const name = (await toggles.nth(i).textContent())!.replace(/^[▸▾]/, "");
      await toggles.nth(i).click();
      const detail = table.locator("tr.files-detail");
      await expect(detail).toBeVisible();
      await page.waitForLoadState("networkidle");
      const reading = detail.getByRole("button", { name: /^Show its tables and texts/ });
      if (await reading.count()) { await reading.first().click(); await page.waitForLoadState("networkidle"); }
      const seen = await detail.evaluate((det) => ({
        lines: [...det.querySelectorAll<HTMLElement>(".doc-inventory li .muted")].map((l) => ({
          text: (l.textContent ?? "").slice(0, 40), cut: l.scrollWidth > l.clientWidth + 1 || getComputedStyle(l).textOverflow === "ellipsis",
        })),
        scroll: [...det.querySelectorAll<HTMLElement>("table.delivery-regions")]
          .map((t) => { const box = (t.closest(".table-scroll") ?? t.parentElement) as HTMLElement; return box.scrollWidth - box.clientWidth; }),
      }));
      lines += seen.lines.length;
      expect(seen.lines.filter((l) => l.cut).map((l) => l.text), `${name} at ${width} px: a page's line cut`).toEqual([]);
      for (const sideways of seen.scroll) expect(sideways, `${name} at ${width} px: its tables and texts scroll sideways`).toBeLessThanOrEqual(1);
      await toggles.nth(i).click();
      await expect(table.locator("tr.files-detail")).toHaveCount(0);
    }
    expect(lines, `a PDF's page lines at ${width} px`).toBeGreaterThan(0);
  }

  // a message said in Client files (a refusal: the request is cut here, nothing is stored) is not carried to To do when
  // the status line's count opens it (final review round 4: only the area bar and a To do row cleared it)
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.route("**/api/**", (route) => (route.request().method() === "GET" ? route.continue() : route.abort()));
  const useIt = page.getByRole("button", { name: /^Use it/ });
  expect(await useIt.count(), "a file's proposed area to take").toBeGreaterThan(0);
  await useIt.first().click();
  await expect(page.getByTestId("inputs-notice")).toBeVisible();
  await page.getByTestId("to-confirm").click();
  await expect(page.getByTestId("tab-todo")).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("inputs-notice")).toHaveCount(0);
  // and by the area bar, as before
  await page.getByTestId("tab-files").click();
  await useIt.first().click();
  await expect(page.getByTestId("inputs-notice")).toBeVisible();
  await page.getByTestId("tab-compound").click();
  await expect(page.getByTestId("inputs-notice")).toHaveCount(0);
  await page.unroute("**/api/**");
});

test("the client-data template's project: with every study card open, no two controls share a name", async ({ page, request }) => {
  // the review's template project: EX-101 from its PK sheet and its protocol (two files, two datasets), and four studies
  // in one workbook (software test data, never a model)
  const dir = mkdtempSync(join(tmpdir(), "inputs-a11y-template-"));
  execFileSync("uv", ["run", "python", join(__dirname, "fixtures", "conflict_workbooks.py"), dir], { cwd: REPO });
  execFileSync("uv", ["run", "python", join(__dirname, "fixtures", "four_studies.py"), dir], { cwd: REPO });
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: "Clientamide", extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nOral tablet, 10 mg.") } } });
  const template = (await started.json()).data.project_id as string;
  await finishStart(request, template);
  expect((await request.post(`/api/v1/projects/${template}/requirements:derive`, { headers: AUTH })).ok()).toBeTruthy();
  for (const name of ["EX-101_protocol_PK.xlsx", "EX-101_PK_sheet.xlsx", "four-studies.xlsx"]) {
    const up = await request.post(`/api/v1/projects/${template}/client-data`, { headers: AUTH, multipart: {
      files: { name, mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer: readFileSync(join(dir, name)) } } });
    expect(up.status(), await up.text()).toBe(201);
  }
  await expect.poll(async () => {
    const c = (await (await request.get(`/api/v1/projects/${template}/client-data`, { headers: AUTH })).json()).data as { running: boolean } | null;
    return Boolean(c && !c.running);
  }, { timeout: 120_000, intervals: [1000] }).toBe(true);

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/projects/${template}/inputs?tab=studies`);
  await expect(page.getByTestId("study-row-study:EX-101")).toBeVisible();
  expect(await openEveryStudy(page), "study cards open at once").toBeGreaterThan(2);
  // EX-101's two datasets and charts, one per file, each named by its source (final review round 4)
  await expect(page.getByTestId("group-study:EX-101").getByTestId("profile-chart").first()).toBeVisible();
  const found = (await repeated(page.locator("#inputs-panel-studies"))).map((x) => `studies: ${x}`);
  for (const tab of ["todo", "compound", "formulations", "individuals", "settings", "files"]) {
    await page.getByTestId(`tab-${tab}`).click();
    await expect(page.locator(`#inputs-panel-${tab}`)).toBeVisible();
    await page.waitForLoadState("networkidle");
    found.push(...(await repeated(page.locator(`#inputs-panel-${tab}`))).map((x) => `${tab}: ${x}`));
  }
  expect(found).toEqual([]);
});

/** The names Chromium gives the panel's buttons, links and form fields (its ARIA snapshot, not a guess from the markup),
 *  each with how many controls carry it. */
async function computedNames(panel: Locator): Promise<Map<string, number>> {
  const out = new Map<string, number>();
  // a line is `- button "name"`, or `- 'button "name: …"': …` when the name holds ": " (the snapshot is YAML: such a line
  // is quoted, its ' doubled). Round 6: the scan read only the first, so every name with a colon went unchecked
  const control = /^\s*- '?(button|link|combobox|textbox|searchbox|spinbutton|checkbox|radio|switch|listbox|slider)(?: "((?:[^"\\]|\\.)*)")?/;
  for (const line of (await panel.ariaSnapshot()).split("\n")) {
    const m = control.exec(line);
    if (!m) continue;
    const name = /^\s*- '/.test(line) ? (m[2] ?? "").replace(/''/g, "'") : m[2] ?? "";
    const key = `${m[1]} “${name}”`;
    out.set(key, (out.get(key) ?? 0) + 1);
  }
  return out;
}
/** The controls that repeat by design, each inside the table or the question that names it: a values table's sort
 *  buttons (under the table's caption) and the spot check's two answers for each value (under the value's question). */
const byDesign = (panel: Locator) => panel.evaluate((root) => {
  const out: Record<string, number> = {};
  const add = (key: string) => { out[key] = (out[key] ?? 0) + 1; };
  for (const b of root.querySelectorAll<HTMLElement>("button.sort-th")) if (b.checkVisibility()) add(`button “${(b.textContent ?? "").trim()}”`);
  for (const r of root.querySelectorAll<HTMLInputElement>(".delivery-tick input[type=radio]")) {
    if (r.checkVisibility()) add(`radio “${(r.closest("label")?.textContent ?? "").trim()}”`);
  }
  return out;
});
// an id of the intake vocabulary in a name: a field ("excretion.amount", "interval_start_h"), a statistic or a table's kind;
// a file's own name is left out of the test (a sheet's name is the client's, as written)
const RAW_FIELD = new RegExp([
  String.raw`\b(?:excretion|composition|pk|relation|link|phys|elim)\.[A-Za-z_]`,
  String.raw`\b(?:interval_(?:start|end)_h|percent_(?:dissolved|female)|study_id|(?:product|analyte)_role|molecular_weight|food_state|dose_unit)\b`,
  String.raw`\b(?:individual_(?:population|sex)|(?:age|weight|height)_[a-z_]+|n_(?:evaluable|female|doses)|(?:arithmetic|geometric)_mean)\b`,
  String.raw`\bpk_(?:individual|summary|parameters)\b`,
].join("|"));
/** What the page must never say in its text or names (round 6, found on the owner's project): a field's id (above), a
 *  table's kind as its id's words ("pk individual", "pK summary"), a confirmation's id, the ledger, a cell's raw locator
 *  ("PK_Summary!F7"), a PK parameter's id (`t_half`, `AUC_last`), a vocabulary entry's id (`ir_tablet`), a template's
 *  numbered column as a label ("vessel vessel_1"). A file's name and a quote of a file's own words (“…”) are the client's. */
const RAW_WORDS = new RegExp([
  RAW_FIELD.source, String.raw`\bpK\b`, String.raw`\bpk (?:individual|summary|parameters)\b`, String.raw`\btable, pk\b`,
  String.raw`\bcf-\d+\b`, String.raw`\bledger\b`, String.raw`\b[A-Za-z0-9_]+![A-Z]{1,3}\d+\b`, String.raw`\b(?:t_half|AUC_last|AUC_inf)\b`,
  String.raw`\b(?:ir_tablet|ir_capsule|iv_bolus|iv_infusion|model_building|external_validation)\b`, String.raw`\bvessel vessel_`,
  String.raw`\bintended_use\b`,
].join("|"));
const plainOf = (text: string) => text.replace(/“[^”]*”/g, "").replace(/[^\s“(]+\.(?:xlsx|xls|csv|pdf|docx?)\b/g, "");

test("with every values table, its pages, every list of more checks and a spot check open, no two controls share a name and no name or text spells an id", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const found: string[] = [];
  const seen: Record<string, number> = {};
  for (const tab of ["studies", "formulations"] as const) {
    await page.goto(`/projects/${projectId}/inputs?tab=${tab}`);
    const panel = page.locator(`#inputs-panel-${tab}`);
    await expect(panel).toBeVisible();
    await page.waitForLoadState("networkidle");
    const closed = panel.locator('[aria-expanded="false"][data-testid^="delivery-subject-open-"], [aria-expanded="false"][data-testid^="toggle-"]');
    for (let round = 0; round < 4 && await closed.count(); round += 1) {
      for (let n = await closed.count(); n > 0; n -= 1) await closed.first().click();
    }
    await page.waitForLoadState("networkidle");
    await expect(panel.locator('[data-testid^="delivery-card-reading-"]')).toHaveCount(0);
    if (tab === "studies") {
      // a spot check drawn, its values shown with their two answers; two of them answered "does not match", so their
      // "what differs" fields are there too (final review round 5: its source buttons repeated, by field id)
      const draw = panel.locator('[data-testid^="spot-draw-"]').filter({ hasText: "Start the spot check" }).first();
      await expect(draw).toBeVisible();
      await draw.click();
      const spot = panel.locator('[data-testid^="spot-values-"]');
      await expect(spot).toHaveCount(1);
      expect(await spot.locator('[data-testid^="spot-source-"]').count(), "values drawn with a source").toBeGreaterThan(3);
      for (const wrong of (await spot.locator('[data-testid^="spot-wrong-"]').all()).slice(0, 2)) await wrong.check();
      await expect(spot.locator('[data-testid^="spot-note-"]')).toHaveCount(2);
    }
    // every folded values table shown, every closed one opened, every list of more checks opened: each table's pager
    // ("Show 8 more", "Show all N") is there with them
    for (const sel of ['[data-testid^="delivery-table-show-"]', '[data-testid^="delivery-table-toggle-"][aria-expanded="false"]',
                       '[data-testid^="delivery-checks-more-"][aria-expanded="false"]']) {
      for (let n = await panel.locator(sel).count(); n > 0; n -= 1) await panel.locator(sel).first().click();
    }
    await page.waitForLoadState("networkidle");
    seen[`${tab} tables`] = await panel.locator("table.delivery-values").count();
    seen[`${tab} pagers`] = await panel.locator('[data-testid^="delivery-table-more-"][data-testid$="-next"]').count();
    const names = await computedNames(panel);
    const designed = await byDesign(panel);
    for (const [name, n] of names) {
      if (n > 1 && designed[name] !== n) found.push(`${tab}: ${name} ×${n}`);
      if (RAW_WORDS.test(plainOf(name.replace(/^\w+ “|”$/g, "")))) found.push(`${tab}: a raw id in ${name}`);
    }
    // nor in what the page shows (round 6: the more checks' notes printed "pk.Cmax: values in 'ng/mL'…")
    for (const line of (await panel.innerText()).split("\n")) {
      if (RAW_WORDS.test(plainOf(line))) found.push(`${tab}: a raw id in the text “${line.trim().slice(0, 140)}”`);
    }
    // the repeats left by design are only these, each inside its own table or question
    for (const name of Object.keys(designed)) expect(name).toMatch(/^(button “(Field|Value|Time|Read by)”|radio “(matches|does not match)”)$/);
  }
  // Client files, every file opened with its reading's tables and texts, and the other areas: no raw id in a name or the
  // text (round 6: "looks like a pk individual table", "PK_Summary!F7", "arithmetic_mean" in the template's problems)
  await page.goto(`/projects/${projectId}/inputs?tab=files`);
  const files = page.locator("#inputs-panel-files");
  await expect(files.locator(".files-table")).toBeVisible();
  await page.waitForLoadState("networkidle");
  const fileToggles = files.locator(".files-table > tbody > tr > td .files-name");
  for (let i = 0, n = await fileToggles.count(); i < n; i += 1) {
    await fileToggles.nth(i).click();
    const detail = files.locator("tr.files-detail");
    await expect(detail).toBeVisible();
    await page.waitForLoadState("networkidle");
    const reading = detail.getByRole("button", { name: /^Show its tables and texts/ });
    if (await reading.count()) { await reading.first().click(); await page.waitForLoadState("networkidle"); }
    for (const [name] of await computedNames(detail)) {
      if (RAW_WORDS.test(plainOf(name.replace(/^\w+ “|”$/g, "")))) found.push(`files: a raw id in ${name}`);
    }
    for (const line of (await detail.innerText()).split("\n")) {
      if (RAW_WORDS.test(plainOf(line))) found.push(`files: a raw id in the text “${line.trim().slice(0, 140)}”`);
    }
    await fileToggles.nth(i).click();
    await expect(files.locator("tr.files-detail")).toHaveCount(0);
  }
  for (const tab of ["todo", "compound", "individuals", "settings"]) {
    await page.getByTestId(`tab-${tab}`).click();
    const panel = page.locator(`#inputs-panel-${tab}`);
    await expect(panel).toBeVisible();
    await page.waitForLoadState("networkidle");
    for (const [name, n] of await computedNames(panel)) {
      if (n > 1) found.push(`${tab}: ${name} ×${n}`);
      if (RAW_WORDS.test(plainOf(name.replace(/^\w+ “|”$/g, "")))) found.push(`${tab}: a raw id in ${name}`);
    }
    for (const line of (await panel.innerText()).split("\n")) {
      if (RAW_WORDS.test(plainOf(line))) found.push(`${tab}: a raw id in the text “${line.trim().slice(0, 140)}”`);
    }
  }
  expect(found).toEqual([]);
  // the cards had values tables, paged ones among them, and a spot check (its table is one of them)
  expect(seen["studies tables"], "values tables shown on Clinical studies").toBeGreaterThan(3);
  expect(seen["studies pagers"], "values tables with more than a page").toBeGreaterThan(0);
});
