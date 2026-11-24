// The Data room, end to end (plan 2026-11-21 v2 §5, §10), on the made-up Exampleamide's delivery (software test data,
// never client data) with no LLM provider:
// 1. the delivery is dropped as one zip, Run reads every file by code, and each agent stage says it waits for a model;
//    the Files section lists what was read;
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

  // reached from the project's own pages, beside the earlier Inputs page
  await page.goto(`/projects/${projectId}/inputs`);
  await expect(page.getByTestId("open-in-dataroom")).toBeVisible();
  await page.getByTestId("nav-dataroom").click();
  await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/dataroom$`));
  await expect(page.getByTestId("dataroom-run")).toBeDisabled();             // nothing to read yet

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
  await expect(page.getByTestId("headline-decisions")).toContainText("9");
  await expect(page.getByTestId("overview-conflicts").getByTestId("conflict")).toHaveCount(2);
  await page.getByTestId("question-confirm").click();
  await expect(page.getByTestId("question-confirmed")).toBeVisible();
  await shot(page, "dataroom-overview");

  // the clinical study: its subject flow, and who is out and why
  await page.getByTestId("rail-clinical").click();
  await expect(page.getByTestId("set-modeling")).toContainText("6");
  await expect(page.getByTestId("set-auc")).toContainText("5");
  await expect(page.getByTestId("excluded-3")).toContainText("every sample below the LLOQ");
  await expect(page.getByTestId("excluded-4")).toContainText("adverse event");

  // dissolution per medium: three products, the reformulated one levels off, f2 against the reference
  await page.getByTestId("rail-dissolution").click();
  await expect(page.getByTestId("dissolution-chart")).toHaveCount(2);
  await expect(page.getByTestId("profile-LOT-X").getByTestId("plateau")).toContainText("Levels off at 87 %");
  await expect(page.getByTestId("profile-LOT-X")).toContainText("Client's mean row: 30 min");
  await expect(page.getByTestId("f2").filter({ hasText: "f2 57.2, similar" })).toHaveCount(1);
  await expect(page.getByTestId("f2").filter({ hasText: "similar without f2" })).toHaveCount(1);
  await shot(page, "dataroom-dissolution");

  // observed PK: the mean profiles, and the client's exposure recomputed beside it
  await page.getByTestId("rail-observed").click();
  await expect(page.getByTestId("profile-chart")).toBeVisible();
  await expect(page.getByTestId("nca-method")).toContainText("linear trapezoidal");

  // a decision: the suggestion taken, who took it shown
  await page.getByTestId("rail-decisions").click();
  const population = page.getByTestId("decision-population:EX-01");
  await expect(population.getByTestId("decision-suggestion")).toContainText("Asian (Tanaka 1996)");
  await population.getByTestId("decision-accept").click();
  await expect(population.getByTestId("decision-chosen")).toBeVisible();
  await expect(population.getByTestId("decision-made")).toContainText("Asian (Tanaka 1996)");
  // another option needs a reason
  const meal = page.getByTestId("decision-meal:EX-01");
  await meal.getByTestId("decision-others").click();
  await meal.getByTestId("option-high_fat").click();
  await meal.getByTestId("decision-reason").fill("the protocol's breakfast was the FDA high-fat meal");
  await meal.getByTestId("decision-choose").click();
  await expect(meal.getByTestId("decision-made")).toContainText("High-fat breakfast");

  // a value's source: the synopsis page with the line highlighted, then a sheet with its cell
  await page.getByTestId("rail-substance").click();
  await page.getByTestId("value-substance.mw").getByTestId("source-chip").first().click();
  const drawer = page.getByTestId("source-drawer");
  await expect(drawer).toContainText("EX-01 synopsis.pdf");
  await expect(drawer.getByTestId("source-page").locator("img")).toBeVisible();
  await expect(drawer.getByTestId("source-highlight")).toBeVisible();
  await shot(page, "dataroom-source-page");
  await drawer.getByTestId("source-drawer-close").click();
  await page.getByTestId("rail-solubility").click();
  await page.getByTestId("source-chip").first().click();
  await expect(page.getByTestId("source-drawer").getByTestId("source-cell")).toHaveText("4.8");
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("source-drawer")).toHaveCount(0);

  // the PK-Sim inputs end with what "Send to the model" would send, and what still blocks it
  await page.getByTestId("rail-inputs").click();
  await expect(page.getByTestId("input-phys.mw")).toContainText("412.5 g/mol");
  await expect(page.getByTestId("publish-blocked")).toContainText("decisions waiting");

  // the evidence report, laid out for paper
  await page.goto(`/projects/${projectId}/dataroom/report`);
  await expect(page.getByTestId("report-cover")).toContainText("Evidence report");
  await expect(page.getByTestId("report-clinical")).toContainText("Who is out, and why");
  await expect(page.getByTestId("report-substance")).toContainText("EX-01 synopsis.pdf · p. 1, line 10");
});

test("a project's files stay in-house until the client's written permission for a cloud service is recorded", async ({ page, request }) => {
  const projectId = await project(request);
  await page.goto(`/projects/${projectId}/dataroom`);
  const said = page.getByTestId("files-go-said");
  await expect(said).toContainText("In-house only");

  // a cloud service needs the client's reference and a reason before Save; the DEV sign-in carries the step-up
  await page.getByTestId("files-go-change").click();
  await page.getByTestId("files-go-nvidia").check();
  await page.getByTestId("files-go-reason").fill("the client agreed to the trial service");
  await expect(page.getByTestId("files-go-save")).toBeDisabled();
  await page.getByTestId("files-go-ref-nvidia").fill("client email of 2026-11-20");
  await page.getByTestId("files-go-save").click();
  await expect(said).toContainText("NVIDIA API catalog (client email of 2026-11-20)");

  // recorded with who and why, and audited by the API
  const got = await request.get(`/api/v1/projects/${projectId}/data-permissions`, { headers: AUTH });
  const body = (await got.json()).data;
  expect(body.in_house_only).toBe(false);
  expect(body.history[0].reason).toBe("the client agreed to the trial service");

  // back to in-house only
  await page.getByTestId("files-go-change").click();
  await page.getByTestId("files-go-nvidia").uncheck();
  await page.getByTestId("files-go-reason").fill("trial over");
  await page.getByTestId("files-go-save").click();
  await expect(said).toContainText("In-house only");
  await page.getByTestId("files-go-change").click();
  await expect(page.getByTestId("files-go-history")).toContainText("Changes (2)");
});
