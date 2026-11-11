// Audit 2, item 7 (2026-11-11): every bare text field, select and textarea has the base control style (no more 21 px
// browser-default strips), every reason field says visibly that it is required and kept in the audit trail, and a form
// never drops what was typed: "70 kg" in a number field keeps Save disabled and says why; a typed table says what it
// still needs. Software check of the pages: no PK-Sim run here, the numbers are test inputs.
import { expect, type Page, test } from "@playwright/test";

import { projectWithInputs, START_DONE } from "./fixtures/inputs";

test.use({ viewport: { width: 1280, height: 900 } });

const CONTROLS = "input:not([type=checkbox]):not([type=radio]):not([type=file]):not([type=range]):not([type=hidden]), select, textarea";

/** The visible text controls on the page that are under 28 px tall (the client-data reading fields, .rf, are compact by
 *  design and left out). */
async function shortControls(page: Page): Promise<string[]> {
  return page.locator(CONTROLS).evaluateAll((els) => els
    .filter((el) => !el.closest(".rf"))
    .map((el) => ({ el, box: el.getBoundingClientRect() }))
    .filter(({ el, box }) => box.width > 0 && box.height > 0 && getComputedStyle(el).visibility !== "hidden")
    .filter(({ box }) => box.height < 28)
    .map(({ el, box }) => `${el.tagName}${el.className ? `.${String(el.className).replace(/ /g, ".")}` : ""}`
      + `[${el.getAttribute("aria-label") ?? el.getAttribute("placeholder") ?? ""}] ${Math.round(box.height)}px`));
}

async function controlsAtLeast28(page: Page, where: string) {
  await expect.poll(async () => page.locator(CONTROLS).count(), `${where}: has controls`).toBeGreaterThan(0);
  expect(await shortControls(page), `${where}: controls under 28 px`).toEqual([]);
}

test("text fields, selects and textareas are at least 28 px tall on Start, Inputs, Run, Review & sign and Library", async ({ page, request }) => {
  const projectId = await projectWithInputs(request, "Formamide", [
    { study_id: "iv-100", route: "iv_infusion", dose_mg: 100 }, { study_id: "po-10", route: "oral", dose_mg: 10 },
  ], { brief: START_DONE });

  await page.goto(`/projects/${projectId}/start`);
  await expect(page.getByTestId("start-routes")).toBeVisible();
  await controlsAtLeast28(page, "Start");

  await page.goto(`/projects/${projectId}/inputs`);
  await page.getByTestId("tab-studies").click();
  await page.getByTestId("type-table").click();
  await expect(page.getByTestId("typed-table")).toBeVisible();
  await controlsAtLeast28(page, "Inputs › Studies");
  await page.getByTestId("tab-individuals").click();
  await expect(page.getByTestId("individual-po-10")).toBeVisible();
  await controlsAtLeast28(page, "Inputs › Populations");

  await page.goto(`/projects/${projectId}/plan`);
  await expect(page.getByTestId("overall-data")).toBeVisible();
  const fit = page.locator("button[data-testid^='fit-']").first();
  if (await fit.count()) await fit.click();
  await controlsAtLeast28(page, "Review & sign");

  // Run (the project page): before the signature it waits on Review & sign, so it may hold no field; any it holds is measured
  await page.goto(`/projects/${projectId}`);
  await expect(page.getByTestId("run-blocked")).toBeVisible();
  expect(await shortControls(page), "Run: controls under 28 px").toEqual([]);

  await page.goto(`/projects/${projectId}/library`);
  await controlsAtLeast28(page, "Library");
});

test("reasons are labelled as required; typed numbers that are not numbers keep Save disabled and say why", async ({ page, request }) => {
  const projectId = await projectWithInputs(request, "Labelamide", [{ study_id: "po-20", route: "oral", dose_mg: 20 }], { brief: START_DONE });
  await page.goto(`/projects/${projectId}/inputs`);

  // the typed table says what it still needs; a dose with its unit typed in is named, not silently refused
  await page.getByTestId("tab-studies").click();
  await page.getByTestId("type-table").click();
  const table = page.getByTestId("typed-table");
  await expect(table.getByText("Time unit", { exact: true })).toBeVisible();
  await expect(table.getByText("Concentration unit", { exact: true })).toBeVisible();
  await table.getByLabel("study id").fill("po-typed");
  await table.getByLabel("dose").fill("10 mg");
  await expect(table.getByTestId("typed-dose-issue")).toBeVisible();
  await expect(table.getByLabel("dose")).toHaveAttribute("aria-invalid", "true");
  await expect(table.getByTestId("typed-needed")).toContainText("the dose, a number above 0 in mg");
  await expect(table.getByTestId("typed-needed")).toContainText("n, the number of subjects");
  await expect(table.getByRole("button", { name: "Add the study" })).toBeDisabled();
  await table.getByLabel("dose").fill("10");
  await table.getByLabel("subjects").fill("8");
  await table.getByLabel("times").fill("0.5 1 2");
  await table.getByLabel("values", { exact: true }).fill("4 3 1");
  await expect(table.getByTestId("typed-needed")).toHaveText("Still needed: a source title or link.");
  await table.getByLabel("source title").fill("Typed from Table 2");
  await expect(table.getByTestId("typed-needed")).toHaveCount(0);
  await expect(table.getByRole("button", { name: "Add the study" })).toBeEnabled();

  // leaving a study out: the reason field is labelled and marked required
  const study = page.getByTestId("study-po-20");
  await study.getByRole("button", { name: "Leave po-20 out" }).click();
  await expect(study.locator(".reason-field .ctl-label")).toHaveText("Reason, kept in the audit trail · required");
  await expect(study.getByLabel("reason for po-20")).toHaveAttribute("aria-required", "true");

  // the individual: a weight typed with its unit is not sent as null; Save waits and says what for
  await page.getByTestId("tab-individuals").click();
  const ind = page.getByTestId("individual-po-20");
  await expect(ind.getByText("Weight (kg)", { exact: true })).toBeVisible();
  await ind.getByLabel("population for po-20").selectOption({ index: 1 });
  await ind.getByLabel("sex for po-20").selectOption({ index: 1 });
  await ind.getByLabel("age for po-20", { exact: true }).fill("30");
  await expect(ind.getByRole("button", { name: "Save the individual" })).toBeEnabled();
  await ind.getByLabel("weight for po-20").fill("70 kg");
  await expect(ind.getByLabel("weight for po-20")).toHaveAttribute("aria-invalid", "true");
  await expect(ind.getByRole("button", { name: "Save the individual" })).toBeDisabled();
  await expect(ind.getByTestId("needed-individual-po-20")).toContainText("the weight as a number in kg");
  // the mean age within the stated range
  await ind.getByLabel("weight for po-20").fill("70");
  await ind.getByLabel("age from for po-20").fill("35");
  await expect(ind.getByRole("button", { name: "Save the individual" })).toBeDisabled();
  await expect(ind.getByTestId("needed-individual-po-20")).toContainText("age from ≤ mean age ≤ age to");
  await ind.getByLabel("age from for po-20").fill("18");
  await ind.getByLabel("age to for po-20").fill("45");
  await ind.getByRole("button", { name: "Save the individual" }).click();
  await expect(page.getByTestId("individual-po-20")).toContainText("70 kg");
});
