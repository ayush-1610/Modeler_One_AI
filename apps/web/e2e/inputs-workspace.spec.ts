// Redesign §3.2: the Inputs step is one workspace. Values flow in and agreeing sources are one value (D-32); a missing
// value is typed into its row with its source; each study's individual is entered or the explicit healthy adult default
// (D-29); a multiple-dose regimen is completed; a table is typed in by hand and a study left out with its reason; To do
// (the page's first area while anything is missing, plan 2026-11-14 slice 1) opens each open item on its area. Software
// test data entered through the API and the page, never a model.
import { expect, type Page, test } from "@playwright/test";

import { finishStart } from "./fixtures/inputs";

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
  await finishStart(request, projectId);      // Inputs opens once Start is done (page review 1, decision 7)
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

  // the page opens on To do while something is missing; the area bar holds the areas, the client's files the last
  await page.goto(`/projects/${projectId}/inputs`);
  const missing = page.getByTestId("still-missing");
  await expect(missing).toBeVisible();
  await expect(page.getByTestId("tab-todo")).toHaveAttribute("aria-selected", "true");
  await page.getByTestId("tab-compound").click();
  await expect(page.getByTestId("record-phys.logp")).toContainText("+1 agree");
  await shot(page, "1-compound");

  // the source opens in the centre peek over the dimmed page (plan 2026-11-03 §3.3): a quote and its link
  await page.getByTestId("peek-phys.logp").click();
  const peek = page.getByTestId("source-peek");
  await expect(peek.getByRole("dialog", { name: /Source of/ })).toBeVisible();
  await expect(peek).toContainText(/logP 2\.(29|35)/);
  await page.keyboard.press("Escape");
  await expect(peek).toHaveCount(0);

  // the client's files, in the last area
  await page.getByTestId("tab-files").click();
  await expect(page.getByTestId("files-none")).toContainText("No client file yet");
  await page.getByTestId("tab-compound").click();

  // the tabs answer the keyboard: arrows move and select, only the selected tab is in the Tab order, the panel is named
  await expect(page.getByRole("tabpanel", { name: "Compound" })).toBeVisible();
  await page.getByTestId("tab-compound").focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("tab-formulations")).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("tab-formulations")).toBeFocused();
  await expect(page.getByTestId("tab-compound")).toHaveAttribute("tabindex", "-1");
  await expect(page.getByRole("tabpanel", { name: "Products and dissolution" })).toBeVisible();
  await page.keyboard.press("Home");
  await expect(page.getByTestId("tab-todo")).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("tab-compound")).toHaveAttribute("aria-selected", "true");

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

  // D-29: the study's individual, from To do
  await page.getByTestId("tab-todo").click();
  await missing.getByTestId("missing-demographics-po-md").click();
  await expect(page.getByTestId("tab-individuals")).toHaveAttribute("aria-selected", "true");
  const individual = page.getByTestId("individual-po-md");
  await expect(individual).toContainText("not stated");
  await individual.getByLabel("population for po-md").selectOption("Japanese_Population");
  await individual.getByLabel("sex for po-md").selectOption("FEMALE");
  await individual.getByLabel("age for po-md").fill("41");
  await individual.getByRole("button", { name: "Save the individual" }).click();
  await expect(page.getByTestId("individual-po-md")).toContainText("entered");
  // the studies table's individual names its study and where it leads, and opens that study's own row there (final review
  // round 6: on the owner's project two rows' "not stated" were one name, and the button only changed the area)
  await page.getByTestId("tab-studies").click();
  const own = page.getByTestId("study-individual-po-md");
  await expect(own).toHaveAccessibleName("entered: the individual of study po-md, on Populations and individuals");
  await own.click();
  await expect(page.getByTestId("tab-individuals")).toHaveAttribute("aria-selected", "true");
  await expect.poll(() => page.evaluate(() => Boolean(document.activeElement?.closest('[data-testid="individual-po-md"]')))).toBe(true);
  // the proposal's populations are shown here, where the individuals are (page review 1, decision 3): one is added
  const populations = page.getByTestId("inputs-populations");
  await expect(populations).toContainText("The populations the proposal names · 0");
  await populations.getByTestId("inputs-populations-add").click();
  await populations.getByTestId("edit-populations[0].age_range").click();
  await populations.getByTestId("input-populations[0].age_range").fill("18 to 45 years");
  await populations.getByTestId("save-populations[0].age_range").click();
  await expect(populations.getByTestId("inputs-populations-0")).toContainText("18 to 45 years");
  await shot(page, "2-individuals");

  // the multiple-dose regimen, then a table typed in and a study left out
  await page.getByTestId("tab-todo").click();
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
  await typed.getByRole("button", { name: "Leave po-typed out" }).click();          // the reason is asked for only now
  await typed.getByLabel("reason for po-typed").fill("assay not validated");
  await typed.getByRole("button", { name: "Leave out" }).click();
  await expect(page.getByTestId("study-po-typed")).toContainText("left out: assay not validated");
  await shot(page, "3-studies");
});
