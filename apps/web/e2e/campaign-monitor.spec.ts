// The Run step's monitor for a project whose CPF and studies were loaded through the API from a starting point (the
// template API stays for scripts and the reference runs; R5 removed only the Quick start wizard that drove it). Plus the
// two failure modes that used to be hidden behind sample data: a campaign that is not recorded, and an illustrative run.
import { expect, test, type APIRequestContext } from "@playwright/test";

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

test("a campaign on the published Dapagliflozin model's real data runs from the project page to the monitor", async ({ page, request }) => {
  const { projectId, compound } = await fromTemplate(request, "dapagliflozin-osp");
  await page.goto(`/projects/${projectId}`);
  await page.getByRole("button", { name: "Run campaign" }).click();

  await page.waitForURL(/\/campaigns\/[^/]+$/);
  await expect(page.getByTestId("api-problem")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: compound })).toBeVisible({ timeout: 60_000 });
  // the monitor refreshes itself; wait for the campaign to finish or stop for a human decision
  await expect(page.getByTestId("campaign-status")).toHaveText(TERMINAL, { timeout: 8 * 60_000 });
  await expect(page.getByTestId("campaign-stage-S0")).toContainText("passed");
  // T-54: the influence map (parameters × studies) is drawn from the signed MAP and the working parameter set
  await expect(page.getByTestId("influence-map")).toBeVisible();
  await expect(page.getByTestId("influence-map")).toContainText("elim.hepatic.UGT1A9.clspec");
  await page.screenshot({ path: test.info().outputPath("monitor.png"), fullPage: true });
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
  const { projectId } = await fromTemplate(request, "aciclovir-illustrative");
  await page.goto(`/projects/${projectId}`);
  await page.getByRole("button", { name: "Run campaign" }).click();
  await page.waitForURL(/\/campaigns\/[^/]+$/);
  await expect(page.getByTestId("campaign-status")).toHaveText(TERMINAL, { timeout: 8 * 60_000 });
  await expect(page.getByTestId("real-data-warning")).toContainText("TEST ONLY: no real observed data");
  await expect(page.getByText(/0 of 1 real/).first()).toBeVisible();
});
