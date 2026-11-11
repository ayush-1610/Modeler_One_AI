// The Run step's monitor for a project whose CPF and studies were loaded through the API from a starting point (the
// template API stays for scripts and the reference runs; R5 removed only the Quick start wizard that drove it). Plus the
// two failure modes that used to be hidden behind sample data: a campaign that is not recorded, and an illustrative run.
// Such a project has no plan signed on Review & sign, so its Run step starts nothing (the owner's decision 2 of
// 2026-11-11): these runs start through the API's scripted route (campaign:prepare, the MAP signature, the start), as the
// reference runs and CI do. The person's route, Review & sign → Run → the monitor, is model-plan.spec.ts.
import { expect, test, type APIRequestContext } from "@playwright/test";

import { dropEscalations } from "./fixtures/escalations";

const AUTH = { Authorization: "Bearer dev" };
const TERMINAL = /completed|escalated|awaiting_signature|aborted|failed/;

/** A project loaded from a starting point: its CPF and its studies, as the template answers them. */
async function fromTemplate(request: APIRequestContext, templateId: string) {
  const template = (await (await request.get(`/api/v1/templates/${templateId}`, { headers: AUTH })).json()).data;
  // an illustrative starting point is a demo: its project is exploratory and may sign TEST ONLY verdicts (plan §9.4)
  const exploratory = !template.real_data && !template.blank;
  const created = await request.post("/api/v1/projects", { headers: AUTH, data: {
    name: `${template.compound} ${Date.now()}`, compound: template.compound, question: template.question,
    model_risk: template.model_risk, exploratory } });
  expect(created.ok(), await created.text()).toBeTruthy();
  const projectId = (await created.json()).data.id as string;
  const cpf = await request.put(`/api/v1/projects/${projectId}/compounds/${template.compound}/cpf`, { headers: AUTH,
    data: { ...template.cpf, compound: template.compound } });
  expect(cpf.ok(), await cpf.text()).toBeTruthy();
  const studies = await request.post(`/api/v1/projects/${projectId}/studies`, { headers: AUTH, data: { studies: template.studies } });
  expect(studies.ok(), await studies.text()).toBeTruthy();
  return { projectId, compound: template.compound as string };
}

/** The scripted start (API and CI only, never the web app): the MAP generated and signed, then the campaign started. */
async function startScripted(request: APIRequestContext, projectId: string, compound: string) {
  const project = (await (await request.get(`/api/v1/projects/${projectId}`, { headers: AUTH })).json()).data;
  const prepared = await request.post(`/api/v1/projects/${projectId}/questions/${project.questions[0].id}/campaign:prepare`,
                                      { headers: AUTH, data: { compound } });
  expect(prepared.ok(), await prepared.text()).toBeTruthy();
  const prep = (await prepared.json()).data;
  const signed = await request.post(`/api/v1/projects/${projectId}/signatures`, { headers: AUTH, data: {
    meaning: "Approved", record_type: "map_approval", record_id: prep.map_id, record_sha256: prep.map_sha256 } });
  expect(signed.ok(), await signed.text()).toBeTruthy();
  const started = await request.post(`/api/v1/projects/${projectId}/campaigns`, { headers: AUTH, data: {
    compound, map_id: prep.map_id, cpf_uri: prep.cpf_uri, cpf_sha256: prep.cpf_sha256, map_uri: prep.map_uri,
    observed_uri: prep.observed_uri, model_risk: prep.tier, stages: prep.stages } });
  expect(started.ok(), await started.text()).toBeTruthy();
  return (await started.json()).campaign_id as string;     // the start answers without the envelope
}

// a run that stops for a decision leaves an escalation open, and the decision pop-up asks for it on every page (the
// review inbox is gone, 2026-11-11): close it after each test (each waits for its run to stop), or it would sit over the
// next test's pages and the next specs' pages
test.afterEach(() => dropEscalations());

test("a campaign on the published Dapagliflozin model's real data runs and is followed on the monitor", async ({ page, request }) => {
  const { projectId, compound } = await fromTemplate(request, "dapagliflozin-osp");
  // no plan signed on Review & sign: the Run step says so, links there, and offers no start (decision 2 of 2026-11-11)
  await page.goto(`/projects/${projectId}`);
  await expect(page.getByTestId("run-blocked")).toBeVisible();
  await expect(page.getByTestId("run-blocked").getByTestId("step-blocked-go")).toHaveAttribute("href", `/projects/${projectId}/plan`);
  await expect(page.getByRole("button", { name: "Run campaign" })).toHaveCount(0);

  await page.goto(`/campaigns/${await startScripted(request, projectId, compound)}`);
  await expect(page.getByTestId("api-problem")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: compound })).toBeVisible({ timeout: 60_000 });
  // the monitor refreshes itself; wait for the campaign to finish or stop for a human decision
  await expect(page.getByTestId("campaign-status")).toHaveText(TERMINAL, { timeout: 8 * 60_000 });
  await expect(page.getByTestId("campaign-stage-S0")).toContainText("passed");
  // T-54: the influence map (parameters × studies) is drawn from the signed MAP and the working parameter set
  await expect(page.getByTestId("influence-map")).toBeVisible();
  await expect(page.getByTestId("influence-map")).toContainText("elim.hepatic.UGT1A9.clspec");
  // the goodness-of-fit chart has a text alternative (audit 2, item 10): a caption, a labelled image, and its points in
  // a table; the log axis prints powers of ten, never an SI suffix ('100µ' beside a µmol/l title)
  const gof = page.getByTestId("gof-figure");
  await expect(gof.getByTestId("gof-caption")).toContainText("against time in hours");
  await expect(gof.getByTestId("gof-plot")).toHaveAttribute("aria-label", /Plasma concentration \(.+\) against time/);
  await expect(gof.getByTestId("gof-data")).toBeAttached();
  await expect(gof.locator(".ytick text").first()).toBeAttached();
  const ticks = await gof.locator(".ytick text").allTextContents();
  expect(ticks.filter((t) => /\d\s*[µmkMGn]$/.test(t)), ticks.join(" | ")).toEqual([]);
  await page.screenshot({ path: test.info().outputPath("monitor.png"), fullPage: true });
  // on a phone the parameter names are a sticky 140 px column, so heat cells are on screen beside them (audit 2, item 8:
  // the 220 px+ name column filled the box and every cell was off to the right)
  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();                                       // laid out for the phone from the start, as a phone opens it
  await expect(page.getByTestId("influence-map")).toBeVisible();
  const heat = await page.getByTestId("influence-map").evaluate((t) => {
    const name = t.querySelector("tbody td:first-child")!.getBoundingClientRect();
    const cell = t.querySelector("tbody td.heat-cell")!.getBoundingClientRect();
    return { nameWidth: name.width, cellLeft: cell.left, sw: document.documentElement.scrollWidth };
  });
  expect(heat.nameWidth).toBeLessThanOrEqual(141);
  expect(heat.cellLeft).toBeLessThan(390 - 44);                                       // at least one cell in view
  expect(heat.sw).toBeLessThanOrEqual(390);
  await page.getByTestId("influence-map").screenshot({ path: test.info().outputPath("influence-map-390.png") });
  await page.setViewportSize({ width: 1280, height: 720 });
  // what produced the numbers is on the page: a stub run is flagged, a PK-Sim run is not
  if (process.env.E2E_ENGINE_COMMAND) await expect(page.getByTestId("engine-warning")).toHaveCount(0);
  else await expect(page.getByTestId("engine-warning")).toContainText("Not a PBPK result");

  // the project is listed on the home page, from the API
  await page.goto("/");
  await expect(page.getByRole("link", { name: new RegExp(`^${compound} `) }).first()).toBeVisible();
});

test("a campaign that is not recorded says so and never shows sample data", async ({ page }) => {
  await page.goto("/campaigns/does-not-exist");
  await expect(page.getByTestId("campaign-pending")).toBeVisible();
  await expect(page.getByText("sample data")).toHaveCount(0);
});

test("the illustrative example runs, but its verdicts are shown as test only (plan §9.4)", async ({ page, request }) => {
  const { projectId, compound } = await fromTemplate(request, "aciclovir-illustrative");
  await page.goto(`/campaigns/${await startScripted(request, projectId, compound)}`);
  await expect(page.getByTestId("campaign-status")).toHaveText(TERMINAL, { timeout: 8 * 60_000 });
  await expect(page.getByTestId("real-data-warning")).toContainText("TEST ONLY: no real observed data");
  await expect(page.getByText(/0 of 1 real/).first()).toBeVisible();
});
