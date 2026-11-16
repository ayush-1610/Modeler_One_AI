// Inputs with the keyboard and a screen reader (plan docs/plans/2026-11-14-inputs-task-first.md §2.1; final review round 3,
// accessibility and forms), on the nine messy files of the made-up Exampleamide: the skip link to the areas; the status
// counts not said while the page reads its work, and said once when a decision changes them; the focus handed on when a
// control removes itself (a question answered, a form cancelled, the bulk bar cleared), never left on the page; the bulk
// bar never over the row the focus is on, and in view on a phone; a refusal said beside the field it is about, again on
// each press; each area under a heading of its own; repeated buttons named with what they are about, with every study
// card open at once and on the client-data template's project too; the demographics form taking the focus however it
// opens on a fresh page (round 4); Client files on a phone; a message cleared whichever way the area changes. The focus
// after the signing step-up is checked where a study is signed, in delivery.spec.ts. Software test data, never a model.
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
  await expect(card.getByTestId(`delivery-demographics-${choose}-individual_population`)).toBeFocused();
  expect(await focused(page)).not.toBe("BODY");
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
