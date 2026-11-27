// The Data room, end to end (plan 2026-11-21 v2 §5, §10), on the made-up Exampleamide's delivery (software test data,
// never client data) with no LLM provider:
// 1. the delivery is dropped as one zip, Run reads every file by code, and each agent stage says it waits for a model;
//    the Files section lists what was read;
// 1b. a paused run (plan 2026-11-24 §4, its record written as a run on a model leaves it): the page says where and why it
//    stopped and when it goes on, for the paid models' cap and for a provider that did not answer, and Resume now
//    finishes it where it stopped;
// 2. the agents' answers written straight into the store (as A6-A8 submit them): the clinical study's subject flow, the
//    dissolution per medium with f2 and the fitted release, the observed profiles beside the client's exposure, a
//    decision taken, the question confirmed, and a value's source opened in the drawer, on its page and in its sheet.
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { AUTH, finishStart } from "./fixtures/inputs";

const REPO = resolve(__dirname, "../../..");
const FIXTURE = join(__dirname, "fixtures", "dataroom.py");

function fixture(...args: string[]): Record<string, unknown> {
  const printed = execFileSync("uv", ["run", "python", FIXTURE, ...args], { cwd: REPO }).toString();
  return JSON.parse(printed.trim().split("\n").pop()!) as Record<string, unknown>;
}

async function project(request: APIRequestContext): Promise<string> {
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: "Exampleamide", extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nOral tablet, 100 mg.") } } });
  const projectId = (await started.json()).data.project_id as string;
  await finishStart(request, projectId);
  return projectId;
}

async function shot(page: Page, name: string) {
  await page.screenshot({ path: test.info().outputPath(`${name}.png`), fullPage: true });
}

test("a delivery dropped in the Data room is read with agents off, each stage saying where it stands", async ({ page, request }) => {
  const projectId = await project(request);
  const zip = fixture("zip", mkdtempSync(join(tmpdir(), "dataroom-"))).zip as string;

  // reached from the side navigation's Data step (decision G1-1: no "earlier page" links either way; slice 4a)
  await page.goto(`/projects/${projectId}/inputs`);
  await expect(page.getByTestId("open-in-dataroom")).toHaveCount(0);
  await page.getByTestId("nav-dataroom").click();
  await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/dataroom$`));
  await expect(page.getByTestId("dataroom-run")).toBeDisabled();             // nothing to read yet
  // before a file arrives (plan 2026-11-26 §9, slice 5c): each group and what each section will hold, nothing asked yet
  await expect(page.getByTestId("section-finding")).toContainText("No file yet");
  const will = page.getByTestId("overview-will-hold");
  await expect(will.locator("[data-testid^='will-hold-section-']")).toHaveCount(16);
  await expect(will.getByTestId("will-hold-model_input")).toContainText("parameterise, calibrate or validate the model");
  await expect(will.getByTestId("will-hold-section-release")).toContainText("The dissolution profile chosen as each product's release input");
  await expect(page.getByTestId("headline")).toHaveCount(0);
  await expect(page.getByTestId("rail-requests")).toHaveAttribute("title", "Data Requests: Nothing yet");   // nothing is missing from no delivery
  await shot(page, "dataroom-empty");
  await page.getByTestId("rail-release").click();
  await expect(page.getByTestId("section-empty")).toHaveAttribute("data-stage", "empty");
  await expect(page.getByTestId("section-holds")).toContainText("the release model fitted to it");
  await page.getByTestId("rail-overview").click();

  await page.getByTestId("dataroom-upload").setInputFiles(zip);
  await expect(page.getByTestId("intake-note")).toContainText("1 file added");
  await page.getByTestId("dataroom-run").click();
  const progress = page.getByTestId("run-progress");
  await expect(progress).toHaveAttribute("data-state", "done", { timeout: 120_000 });
  await expect(page.getByTestId("run-summary")).toContainText("10 files, 0 scanned pages read by OCR");
  await expect(page.getByTestId("run-summary")).toContainText("5 steps wait for an AI model");
  // the steps stay open after a run the page watched; a run finished before the page opened folds to its summary
  const steps = page.getByTestId("run-steps-toggle");
  if ((await steps.getAttribute("aria-expanded")) !== "true") await steps.click();
  await expect(page.getByTestId("stage-read-note")).toHaveText("10 files, 0 scanned pages read by OCR");
  await expect(page.getByTestId("stage-extract")).toHaveAttribute("data-state", "skipped");
  await expect(page.getByTestId("stage-extract-note")).toContainText("no AI model is set up for A8");

  await page.getByTestId("rail-files").click();
  await expect(page.getByTestId("section-finding")).toHaveText("10 files read");
  const files = page.getByTestId("files-table");
  await expect(files.locator("tbody > tr")).toHaveCount(10);
  await expect(page.getByTestId("file-row-EX-01 synopsis.pdf")).toContainText("Not sorted yet");
  await page.getByTestId("file-row-EX-01 synopsis.pdf").getByRole("button").first().click();
  await expect(files).toContainText("Exampleamide delivery/Clinical/EX-01 synopsis.pdf");
  await shot(page, "dataroom-files");
});

test("a paused run says where and why it stopped and when it goes on, and resumes now on a click", async ({ page, request }) => {
  // plan 2026-11-24 §4: a provider that does not answer or a paid model's cap pauses the run, never fails it
  const projectId = await project(request);
  const api = `/api/v1/projects/${projectId}/dataroom`;
  const zip = fixture("zip", mkdtempSync(join(tmpdir(), "dataroom-"))).zip as string;
  const up = await request.post(`${api}/uploads`, { headers: AUTH, multipart: {
    files: { name: "Exampleamide delivery.zip", mimeType: "application/zip", buffer: readFileSync(zip) } } });
  expect(up.ok(), await up.text()).toBeTruthy();
  expect((await request.post(`${api}/run`, { headers: AUTH, data: {} })).ok()).toBeTruthy();
  await expect.poll(async () => (await (await request.get(`${api}/run`, { headers: AUTH })).json()).data.state,
                    { timeout: 120_000 }).toBe("done");
  const root = join(process.env.E2E_DATA_DIR!, "read-root");

  // the paid models' cap: it waits for the cap to be raised or a free model
  fixture("pause", root, projectId, "budget_cap");
  await page.goto(`/projects/${projectId}/dataroom`);
  await expect(page.getByTestId("run-progress")).toHaveAttribute("data-state", "paused");
  await expect(page.getByTestId("dr-run-paused")).toContainText(
    "Paused: the run reached its $10 limit for paid models (Admin → Limits). Stopped at extraction: 3 of 8 files done.");

  // a provider that did not answer: it goes on by itself, or now
  fixture("pause", root, projectId, "provider_unavailable");
  await page.reload();
  const paused = page.getByTestId("dr-run-paused");
  await expect(paused).toContainText("Paused at extraction: 3 of 8 files done.");
  await expect(paused).toContainText("Nemotron Ultra could not answer (too many requests: its rate limit was reached).");
  await expect(paused).toContainText("Continues by itself at");
  await expect(paused).toContainText("Nothing finished is read again.");
  await expect(page.getByTestId("stage-extract")).toHaveAttribute("data-state", "paused");
  await shot(page, "dataroom-paused");
  await page.getByTestId("dr-run-resume").click();
  // no model in these flows: the resumed run skips its agent stages, each waiting for a model, and finishes
  await expect(page.getByTestId("run-progress")).toHaveAttribute("data-state", "done", { timeout: 60_000 });
  await expect(page.getByTestId("dr-run-paused")).toHaveCount(0);
  await expect(page.getByTestId("stage-extract")).toHaveAttribute("data-state", "skipped");
  await expect(page.getByTestId("stage-question")).toHaveAttribute("data-state", "done");      // finished before the pause
});

test("while a run reads the delivery, the page says how many files and for how long, and each empty section says it is being read", async ({ page, request }) => {
  // plan 2026-11-26 §9, slice 5c. The run is read by code (no model in these flows), then its record is answered as a run
  // still at extraction, 12 minutes in: the page's reading state, over the real room
  const projectId = await project(request);
  const api = `/api/v1/projects/${projectId}/dataroom`;
  const zip = fixture("zip", mkdtempSync(join(tmpdir(), "dataroom-"))).zip as string;
  const up = await request.post(`${api}/uploads`, { headers: AUTH, multipart: {
    files: { name: "Exampleamide delivery.zip", mimeType: "application/zip", buffer: readFileSync(zip) } } });
  expect(up.ok(), await up.text()).toBeTruthy();
  expect((await request.post(`${api}/run`, { headers: AUTH, data: {} })).ok()).toBeTruthy();
  await expect.poll(async () => (await (await request.get(`${api}/run`, { headers: AUTH })).json()).data.state,
                    { timeout: 120_000 }).toBe("done");
  const started = new Date(Date.now() - 12 * 60_000 - 5_000).toISOString();
  await page.route((url) => url.pathname === `${api}/run`, async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.data = { ...body.data, state: "running", finished_at: null, started_at: started,
      stages: body.data.stages.map((st: { id: string }) => st.id === "extract" ? { ...st, state: "running", done: 3, total: 8, note: "Clinical/EX-01 synopsis.pdf" }
        : ["check", "write"].includes(st.id) ? { ...st, state: "waiting", note: "" } : { ...st, state: "done" }) };
    await route.fulfill({ response, json: body });
  });
  await page.goto(`/projects/${projectId}/dataroom`);
  const progress = page.getByTestId("run-progress");
  await expect(progress).toHaveAttribute("data-state", "running");
  await expect(progress).toContainText("Reading 10 files");
  await expect(page.getByTestId("run-elapsed")).toHaveText("12 min so far");
  await expect(page.getByTestId("run-reading-note")).toContainText("You can leave this page");
  await expect(page.getByTestId("stage-extract")).toContainText("3 of 8");
  // a section with nothing yet is being read; one that holds something keeps its own state
  await expect(page.getByTestId("rail-release")).toHaveAttribute("title", "In Vitro Release Input: Reading");
  await expect(page.getByTestId("rail-files")).not.toHaveAttribute("title", /Reading/);
  await expect(page.getByTestId("overview-section-release")).toContainText("Fills in as the files are read");
  await shot(page, "dataroom-reading");
  // the room is read again while the run goes on, so its sections fill in as each file's answers land
  const again = page.waitForRequest((r) => new URL(r.url()).pathname === api && r.method() === "GET", { timeout: 15_000 });
  await page.getByTestId("rail-release").click();
  await expect(page.getByTestId("section-empty")).toHaveAttribute("data-stage", "reading");
  await expect(page.getByTestId("section-empty")).toContainText("Reading: this section fills in as the files are read.");
  await again;
});

test("an extracted delivery shows its study and dissolution, a decision is taken and a source opens on its page", async ({ page, request }) => {
  const projectId = await project(request);
  const api = `/api/v1/projects/${projectId}/dataroom`;
  const zip = fixture("zip", mkdtempSync(join(tmpdir(), "dataroom-"))).zip as string;
  const up = await request.post(`${api}/uploads`, { headers: AUTH, multipart: {
    files: { name: "Exampleamide delivery.zip", mimeType: "application/zip", buffer: readFileSync(zip) } } });
  expect(up.ok(), await up.text()).toBeTruthy();
  expect((await request.post(`${api}/run`, { headers: AUTH, data: {} })).ok()).toBeTruthy();
  await expect.poll(async () => (await (await request.get(`${api}/run`, { headers: AUTH })).json()).data.state,
                    { timeout: 120_000 }).toBe("done");
  fixture("seed", join(process.env.E2E_DATA_DIR!, "read-root"), projectId);

  // the overview: the question to confirm, the headline numbers, the conflicts first
  await page.goto(`/projects/${projectId}/dataroom`);
  await expect(page.getByTestId("question-text-shown")).toContainText("reformulated Exampleamide tablet");
  await expect(page.getByTestId("headline-files")).toContainText("10");
  // six of the room, and which applications the question has (the requirement drafts, D5); the population, sex and meal
  // template are chosen on Inputs (the owner's D1), so not counted here
  await expect(page.getByTestId("headline-decisions")).toContainText("7");
  await expect(page.getByTestId("overview-conflicts").getByTestId("conflict")).toHaveCount(2);
  await page.getByTestId("question-confirm").click();
  await expect(page.getByTestId("question-confirmed")).toBeVisible();
  await shot(page, "dataroom-overview");

  // the page in its groups (plan 2026-11-26 §9): the study's design, its subject flow, and who is out and why
  await expect(page.getByTestId("rail-group-model_input")).toContainText("Clinical Study Design");
  await expect(page.getByTestId("rail-group-supporting")).toContainText("Metabolites and Other Analytes");
  await page.getByTestId("rail-design").click();
  await expect(page.getByTestId("set-modeling")).toContainText("6");
  await expect(page.getByTestId("set-auc")).toContainText("5");
  await expect(page.getByTestId("excluded-3")).toContainText("every sample below the LLOQ");
  await expect(page.getByTestId("excluded-4")).toContainText("adverse event");

  // the release inputs, each product's suggested profile (no file names a QC medium here, so the first: pH 1.2 for the
  // reference and the test, pH 6.8 for the reformulated one, which levels off) ...
  await page.getByTestId("rail-release").click();
  await expect(page.getByTestId("dissolution-chart")).toHaveCount(2);
  await expect(page.getByTestId("profile-LOT-X").getByTestId("plateau")).toContainText("Levels off at 87 %");
  await expect(page.getByTestId("profile-LOT-X")).toContainText("Client's mean row: 30 min");
  await expect(page.getByTestId("f2").filter({ hasText: "similar without f2" })).toHaveCount(1);
  // ... and the profiles not chosen, kept as Supporting Evidence, with their f2 against the reference
  await page.getByTestId("rail-other_dissolution").click();
  await expect(page.getByTestId("dissolution-chart")).toHaveCount(1);
  await expect(page.getByTestId("f2").filter({ hasText: "f2 57.2, similar" })).toHaveCount(1);
  await shot(page, "dataroom-dissolution");

  // observed PK: the mean profiles, and the client's exposure recomputed beside it
  await page.getByTestId("rail-observed").click();
  await expect(page.getByTestId("profile-chart")).toBeVisible();
  await expect(page.getByTestId("nca-method")).toContainText("linear trapezoidal");
  // the study's bioequivalence computed by code (phase 3a), beside the observed profiles
  await expect(page.getByTestId("be-results")).toBeVisible();
  await expect(page.getByTestId("be-auc_t-ours")).toContainText("within the limits");
  await shot(page, "dataroom-observed");

  // the population, sex and meal template are chosen on Inputs (the owner's D1): the study's design shows the room's
  // proposal for each, with why, and no decision to make here
  await page.getByTestId("rail-design").click();
  const choices = page.getByTestId("inputs-choices");
  await expect(choices.getByTestId("proposal-population:EX-01")).toContainText("Asian (Tanaka 1996) (proposed)");
  await expect(choices.getByTestId("proposal-meal:EX-01")).toContainText("(proposed)");
  await expect(choices.getByTestId("inputs-choices-link")).toHaveAttribute("href", `/projects/${projectId}/inputs?tab=individuals`);
  await expect(page.getByTestId("decision-population:EX-01")).toHaveCount(0);
  // a decision, on the section it decides (the observed profiles): the suggestion taken, who took it shown
  await page.getByTestId("rail-observed").click();
  const analysis = page.getByTestId("decision-analysis-set:EX-01");
  await analysis.getByTestId("decision-accept").click();
  await expect(analysis.getByTestId("decision-chosen")).toBeVisible();
  // another option needs a reason
  await page.getByTestId("rail-substance").click();
  const solubility = page.getByTestId("decision-solubility-ref");
  await solubility.getByTestId("decision-others").click();
  await solubility.getByTestId("option-sol-1").click();
  await solubility.getByTestId("decision-reason").fill("the medium nearest the intestine's pH");
  await solubility.getByTestId("decision-choose").click();
  await expect(solubility.getByTestId("decision-made")).toBeVisible();

  // a value's source: the synopsis page with the line highlighted, then a sheet with its cell
  await page.getByTestId("rail-substance").click();
  await page.getByTestId("value-substance.mw").getByTestId("source-chip").first().click();
  const drawer = page.getByTestId("source-drawer");
  await expect(drawer).toContainText("EX-01 synopsis.pdf");
  await expect(drawer.getByTestId("source-page").locator("img")).toBeVisible();
  await expect(drawer.getByTestId("source-highlight")).toBeVisible();
  await shot(page, "dataroom-source-page");
  await drawer.getByTestId("source-drawer-close").click();
  // solubility is in the same section: its table's first source
  await page.getByRole("table", { name: "Solubility and the dose" }).getByTestId("source-chip").first().click();
  await expect(page.getByTestId("source-drawer").getByTestId("source-cell")).toHaveText("4.8");
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("source-drawer")).toHaveCount(0);

  // the PK-Sim inputs end with what "Send to the model" would send, and what still blocks it
  await page.getByTestId("rail-scenarios").click();
  await expect(page.getByTestId("input-phys.mw")).toContainText("412.5 g/mol");
  await expect(page.getByTestId("publish-blocked")).toContainText("decisions waiting");

  // the evidence report, laid out for paper
  await page.goto(`/projects/${projectId}/dataroom/report`);
  await expect(page.getByTestId("report-cover")).toContainText("Evidence report");
  await expect(page.getByTestId("report-clinical")).toContainText("Who is out, and why");
  await expect(page.getByTestId("report-substance")).toContainText("EX-01 synopsis.pdf · p. 1, line 10");
});

test("the Data room no longer asks where the client's files may go: an administrator sets it for the company", async ({ page, request }) => {
  // the owner, 2026-11-24: set once for every person and project of a company on Admin → Companies, not shown to them
  const projectId = await project(request);
  await page.goto(`/projects/${projectId}/dataroom`);
  await expect(page.getByTestId("dataroom")).toBeVisible();
  await expect(page.getByTestId("files-go")).toHaveCount(0);
  const gone = await request.get(`/api/v1/projects/${projectId}/data-permissions`, { headers: AUTH });
  expect(gone.status()).toBe(404);
});
