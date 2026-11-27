// The console redesign's acceptance pass (docs/plans/2026-11-23-console-redesign-implementation.md §5, slice 10): every
// page of the app, at a desktop's width (1440 px) and a phone's (390 px), has one top heading, names every visible
// control, scrolls nothing sideways, and makes every control at least 24 x 24 px to the pointer (WCAG 2.2 SC 2.5.8, with
// its exceptions). The pages are read from app/**/page.tsx, so a page added later is checked here or the test names it.
// Then the keyboard: the skip link is the first stop and takes the focus past the shell; a dialog holds the focus and
// gives it back. The project, campaign and agent run are seeded: software test data, no engine run, no model called.
import { mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join, relative } from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { lowContrast, open, sideways, smallTargets, unnamed } from "./fixtures/a11y";
import { projectWithInputs } from "./fixtures/inputs";

const DRUG = "Acceptamide";
const CAMPAIGN = "camp-acceptance-e2e";
const RUN = "ar_acceptancee2e01";

/** Every page of the app, as its route pattern ("/projects/[projectId]/history"). */
function routes(dir = join(__dirname, "..", "app")): string[] {
  const found: string[] = [];
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) found.push(...routes(path));
    else if (name === "page.tsx") found.push(`/${relative(join(__dirname, "..", "app"), dir)}`.replace(/\/$/, "") || "/");
  }
  return found.sort();
}

/** The platform owner's console: the development sign-in does not hold modeler-admin, so these answer the app's 404
 *  here (admin-console.spec.ts); the slice 10 audit ran these same checks on them signed in as the platform's owner. */
const ADMIN = /^\/admin(\/|$)/;

function seed(projectId: string) {
  const root = join(process.env.E2E_DATA_DIR!, "read-root", "dev");
  mkdirSync(join(root, "agent_runs", RUN), { recursive: true });
  const file = join(root, "campaigns.json");
  let rows: Record<string, unknown>[] = [];
  try { rows = JSON.parse(readFileSync(file, "utf-8")).campaigns ?? []; } catch { /* the first campaign */ }
  const stage = (s: string, label: string, status: string) => ({ stage: s, label, status, notes: [],
    rounds: [{ round: 1, action: "baseline", aucGmfe: 1.3, cmaxGmfe: 1.2, verdict: "passed" }] });
  writeFileSync(file, JSON.stringify({ campaigns: [...rows.filter((r) => r.id !== CAMPAIGN), {
    id: CAMPAIGN, project: projectId, compound: DRUG, question: "the oral dose in adults", modelRisk: "medium",
    budgetSeconds: 28800, elapsedSeconds: 3600, currentStage: "S2", status: "RUNNING",
    stages: [stage("S0", "Readiness", "PASSED"), stage("S1", "IV disposition", "PASSED"), stage("S2", "Oral fasted", "RUNNING")],
    gof: [{ name: "iv-100 observed", time_h: [0.5, 1, 2, 4], concentration: [20, 35, 21, 9], unit: "µmol/l", kind: "observed" },
          { name: "iv-100 simulated", time_h: [0.5, 1, 2, 4], concentration: [19, 33, 22, 10], unit: "µmol/l", kind: "simulated" }],
    engine: { kind: "software-fixture", command: "seeded" } }] }));
  writeFileSync(join(root, "agent_runs", RUN, "run.json"), JSON.stringify({
    run_id: RUN, tenant_id: "dev", project_id: projectId, agent: "A2-literature", started_by: "dev-user", provider: "nvidia",
    model: "nemotron", campaign_id: null, budget: { max_turns: 4 }, status: "COMPLETED", started_at: "2026-11-25T10:00:00+00:00",
    finished_at: "2026-11-25T10:02:00+00:00", input_tokens: 2400, output_tokens: 300, cost_usd: 0, summary: {}, proposals: [] }));
  writeFileSync(join(root, "agent_runs", RUN, "steps.jsonl"), JSON.stringify({ seq: 1, kind: "model_turn", at: "2026-11-25T10:01:00+00:00",
    content: { type: "model_turn", turn: 1, model: "nemotron", content: "Nothing to propose.", tool_calls: [] }, usage: {} }) + "\n");
}

/** Each page's address with the seeded records, and its tabs where a tab is its own address. */
function addresses(projectId: string): Record<string, string[]> {
  const p = `/projects/${projectId}`;
  return {
    "/": ["/"], "/account": ["/account"], "/campaigns": ["/campaigns"], "/help": ["/help"], "/projects": ["/projects"],
    "/projects/start": ["/projects/start"], "/review": ["/review"], "/work": ["/work"],
    // the sign-in pages, outside the console's shell
    "/signin": ["/signin?return=/projects"], "/signed-out": ["/signed-out"], "/no-access": ["/no-access"],
    "/campaigns/[campaignId]": ["stages", "fit", "rounds", "feedback"].map((t) => `/campaigns/${CAMPAIGN}?tab=${t}`),
    "/projects/[projectId]": [p],
    "/projects/[projectId]/agent-activity": [`${p}/agent-activity`],
    "/projects/[projectId]/agent-activity/[runId]": [`${p}/agent-activity/${RUN}`],
    "/projects/[projectId]/campaigns": [`${p}/campaigns`],
    "/projects/[projectId]/compounds": [`${p}/compounds`],
    "/projects/[projectId]/compounds/[compound]": [`${p}/compounds/${DRUG}`],
    "/projects/[projectId]/data-plan": [`${p}/data-plan`],
    "/projects/[projectId]/dataroom": [`${p}/dataroom`],
    "/projects/[projectId]/dataroom/report": [`${p}/dataroom/report`],
    "/projects/[projectId]/history": ["audit", "signatures", "versions", "stale"].map((t) => `${p}/history?tab=${t}`),
    "/projects/[projectId]/inputs": [`${p}/inputs`, `${p}/inputs?tab=studies`, `${p}/inputs?tab=files`],
    "/projects/[projectId]/library": [`${p}/library`],
    "/projects/[projectId]/members": [`${p}/members`],
    "/projects/[projectId]/plan": [`${p}/plan`],
    "/projects/[projectId]/settings": [`${p}/settings`],
    "/projects/[projectId]/start": [`${p}/start`],
  };
}

/** Where to keep a picture of each page for the owner's visual review, when asked (ACCEPTANCE_SCREENSHOTS=<folder>). */
const SHOTS = process.env.ACCEPTANCE_SCREENSHOTS;

/** Addresses that land on another page, checked once they have landed: the review inbox's (since 2026-11-11), and
 *  /no-access, which sends the development sign-in (every role) home; both headings stand on the page mid-redirect. */
const LANDS: Record<string, RegExp> = { "/review": /\/work$/, "/no-access": /:\d+\/$/ };

async function check(page: Page, path: string) {
  await open(page, path);
  if (LANDS[path]) {
    await page.waitForURL(LANDS[path]);
    await open(page, new URL(page.url()).pathname);
  }
  if (SHOTS) {
    await page.waitForLoadState("networkidle", { timeout: 10_000 }).catch(() => { /* a page that polls */ });   // a chart's library arrives late
    await page.locator(".js-plotly-plot .main-svg").first().waitFor({ timeout: 5_000 }).catch(() => { /* a page with no chart */ });
    const width = page.viewportSize()?.width ?? 0;
    const name = path.replace(/\/projects\/(?!start\b)[^/?]+/, "/project").replace(/[/?=&]+/g, "_").replace(/^_|_$/g, "") || "home";
    await page.screenshot({ path: join(SHOTS, `${width}-${name}.jpg`), type: "jpeg", quality: 70 });
  }
  await expect(page.locator("h1"), `${path}: one top heading`).toHaveCount(1);   // retried: a page still arriving
  expect(await unnamed(page), `${path}: every control named`).toEqual([]);
  const [wide, who] = await sideways(page);
  expect(wide, `${path}: no sideways scroll (${who})`).toBeLessThanOrEqual(1);
  expect(await smallTargets(page), `${path}: every control at least 24 x 24 px to the pointer`).toEqual([]);
  // soft: one run names every page whose text falls short, not only the first (the Graphite restyle's pass, R4)
  expect.soft(await lowContrast(page), `${path}: text contrast AA (4.5:1, large text 3:1)`).toEqual([]);
}

test("every page of the app, at 1440 and 390 px: one heading, named controls, no sideways scroll, 24 px targets, AA contrast", async ({ page, request }) => {
  test.setTimeout(600_000);
  const projectId = await projectWithInputs(request, DRUG, [{ study_id: "iv-100", route: "iv_infusion", dose_mg: 100 }]);
  seed(projectId);
  const pages = addresses(projectId);
  const all = routes();
  const missed = all.filter((r) => !(r in pages) && !ADMIN.test(r));
  expect(missed, "every page is checked here (the admin console's, signed in as its owner: see ADMIN)").toEqual([]);
  expect(all.filter((r) => ADMIN.test(r)).length, "the admin console's pages, audited signed in as the owner").toBeGreaterThan(0);
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    for (const path of Object.values(pages).flat()) await test.step(`${width} px ${path}`, () => check(page, path));
  }
});

test("the keyboard: the skip link first, past the shell to the page; a dialog keeps the focus and gives it back", async ({ page, request }) => {
  const projectId = await projectWithInputs(request, `${DRUG}-keys`, [{ study_id: "iv-100", route: "iv_infusion", dose_mg: 100 }]);
  await page.setViewportSize({ width: 1440, height: 900 });
  await open(page, `/projects/${projectId}/settings`);

  // the first Tab stop is the skip link; it takes the focus past the sidebar and the page bar
  await page.keyboard.press("Tab");
  const skip = page.locator(".skip-link");
  await expect(skip).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#content")).toBeFocused();
  await page.keyboard.press("Tab");
  const inShell = await page.evaluate(() => Boolean(document.activeElement?.closest(".pagebar, .sidenav")));
  expect(inShell, "the next stop is on the page, not the shell").toBe(false);

  // a dialog: the focus moves in, Tab stays inside, Escape closes it and the focus is back on its opener
  const opener = page.getByTestId("settings-archive");
  await opener.click();
  const dialog = page.getByTestId("settings-archive-dialog");
  await expect(dialog).toBeVisible();
  for (let i = 0; i < 8; i += 1) {
    await page.keyboard.press("Tab");
    expect(await dialog.evaluate((d) => d.contains(document.activeElement)), `Tab ${i + 1} stays in the dialog`).toBe(true);
  }
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(opener).toBeFocused();

  // on a phone the navigation is a menu its button opens and closes, the focus staying on the button
  await page.setViewportSize({ width: 390, height: 900 });
  await open(page, `/projects/${projectId}/settings`);
  const menu = page.getByTestId("nav-menu");
  await menu.focus();
  await page.keyboard.press("Enter");
  await expect(menu).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByTestId("sidebar")).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(menu).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByTestId("sidebar")).toBeHidden();
  await expect(menu).toBeFocused();
});
