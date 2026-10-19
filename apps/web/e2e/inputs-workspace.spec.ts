// Redesign §3.2: the Inputs step is one workspace. Values flow in and agreeing sources are one value (D-32); a missing
// value is typed into its row with its source; each study's individual is entered or the explicit healthy adult default
// (D-29); a multiple-dose regimen is completed; a table is typed in by hand and a study left out with its reason; the side
// list opens each open item on its tab. Software test data entered through the API and the page, never a model.
import { expect, type Page, test } from "@playwright/test";

const AUTH = { Authorization: "Bearer dev" };

async function shot(page: Page, name: string) {
  await page.screenshot({ path: test.info().outputPath(`${name}.png`), fullPage: true });
}

test("the Inputs workspace: values flow in, open items are settled on their tab, studies are added and left out", async ({ page, request }) => {
  const started = await request.post("/api/v1/projects:initiate", {
    headers: AUTH,
    multipart: { drug_name: "Workspacol", extract: "false",
                 files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nOral tablet, 7 days.") } },
  });
  const projectId = (await started.json()).data.project_id as string;
  expect((await request.post(`/api/v1/projects/${projectId}/requirements:derive`, { headers: AUTH })).ok()).toBeTruthy();
  for (const value of [2.29, 2.35]) {                     // within 10 %: one value with two sources, no decision
    const r = await request.post(`/api/v1/projects/${projectId}/evidence`, { headers: AUTH, data: {
      req_id: "REQ-phys.logp", target: "phys.logp", value, source_type: "PUBLICATION", doi: "10.1/logp", title: "logP paper",
      year: 2015, quote: `logP ${value}` } });
    expect(r.status(), await r.text()).toBe(201);
  }
  const md = await request.post(`/api/v1/projects/${projectId}/datasets`, { headers: AUTH, data: {
    study: { study_id: "po-md", n: 12, route: "oral", dose_mg: 10, formulation: "solution", food_state: "fasted", n_timepoints: 4,
             design: "MD" },
    time_unit: "h", unit: "ng/ml", origin: "LITERATURE", source: { title: "Repeat-dose study" },
    series: [{ times: [0.5, 1, 2, 4], values: [10, 20, 15, 5], n: 12 }] } });
  expect(md.status(), await md.text()).toBe(201);

  await page.goto(`/projects/${projectId}/inputs`);
  const missing = page.getByTestId("still-missing");
  await expect(missing).toBeVisible();
  await expect(page.getByTestId("record-phys.logp")).toContainText("+1 agree");
  await shot(page, "1-compound");

  // a value no source has given yet, typed into its row with its source
  await page.getByTestId("add-open-phys.mw").click();
  const mw = page.getByTestId("add-phys.mw");
  await mw.getByLabel("value for phys.mw").fill("225.2");
  await mw.getByLabel("unit for phys.mw").fill("g/mol");
  await mw.getByLabel("link for phys.mw").fill("10.1/mw");
  await mw.getByLabel("quote for phys.mw").fill("molecular weight 225.2 g/mol");
  await mw.getByRole("button", { name: "Add" }).click();
  await expect(page.getByTestId("record-phys.mw")).toContainText("225.2");
  await expect(page.getByTestId("record-phys.mw")).toContainText("in the model");

  // D-29: the study's individual, from the side list
  await missing.getByTestId("missing-demographics-po-md").click();
  await expect(page.getByTestId("tab-individuals")).toHaveAttribute("aria-selected", "true");
  const individual = page.getByTestId("individual-po-md");
  await expect(individual).toContainText("not stated");
  await individual.getByLabel("population for po-md").selectOption("Japanese_Population");
  await individual.getByLabel("sex for po-md").selectOption("FEMALE");
  await individual.getByLabel("age for po-md").fill("41");
  await individual.getByRole("button", { name: "Save the individual" }).click();
  await expect(page.getByTestId("individual-po-md")).toContainText("entered");
  await shot(page, "2-individuals");

  // the multiple-dose regimen, then a table typed in and a study left out
  await missing.getByTestId("missing-regimen-po-md").click();
  await expect(page.getByTestId("tab-studies")).toHaveAttribute("aria-selected", "true");
  const study = page.getByTestId("study-po-md");
  await study.getByLabel("doses for po-md").fill("7");
  await study.getByLabel("interval for po-md").fill("24");
  await study.getByRole("button", { name: "Save" }).click();
  await expect(page.getByTestId("study-po-md")).toContainText("7 doses every 24 h");
  await expect(page.getByTestId("study-po-md").locator('[title^="proposed by the MS-01 split"]')).toBeVisible();  // read-only

  await page.getByTestId("type-table").click();
  const table = page.getByTestId("typed-table");
  await table.getByLabel("study id").fill("po-typed");
  await table.getByLabel("dose").fill("20");
  await table.getByLabel("subjects").fill("8");
  await table.getByLabel("times").fill("0.5 1 2 4");
  await table.getByLabel("values", { exact: true }).fill("12 25 18 6");
  await table.getByLabel("source title").fill("Typed from Table 2");
  await table.getByRole("button", { name: "Add the study" }).click();
  const typed = page.getByTestId("study-po-typed");
  await expect(typed).toBeVisible();
  await typed.getByLabel("reason for po-typed").fill("assay not validated");
  await typed.getByRole("button", { name: "Leave out" }).click();
  await expect(page.getByTestId("study-po-typed")).toContainText("left out: assay not validated");
  await shot(page, "3-studies");

  // the same page in the dark theme
  await page.evaluate(() => document.documentElement.setAttribute("data-theme", "dark"));
  await shot(page, "4-studies-dark");
});
