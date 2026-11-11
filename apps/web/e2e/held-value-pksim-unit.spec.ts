// Audit 2, item 1 (owner's decision 3 of 2026-11-11): a held number with no automatic conversion is accepted on its row
// with the value the person types in PK-Sim's unit, the unit chosen only from the units harvested for its parameter.
// The field starts empty (nothing prefilled or converted). The published Dapagliflozin model's EHC continuous fraction is
// such a value: PK-Sim's snapshot gives it no unit (dimensionless). Software check of the pipeline: no PK-Sim run here.
import { expect, test } from "@playwright/test";

import { AUTH, finishStart } from "./fixtures/inputs";

const EHC = "indiv.Organism|Liver|EHC continuous fraction";

test("a needs-conversion value is accepted on its row with the value typed in a harvested PK-Sim unit", async ({ page, request }) => {
  const started = await request.post("/api/v1/projects:initiate", {
    headers: AUTH,
    multipart: { drug_name: "Dapagliflozin", extract: "false",
                 files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nOral 10 mg, healthy adults.") } },
  });
  expect(started.ok(), await started.text()).toBeTruthy();
  const projectId = (await started.json()).data.project_id as string;
  await finishStart(request, projectId);
  expect((await request.post(`/api/v1/projects/${projectId}/requirements:derive`, { headers: AUTH })).ok()).toBeTruthy();

  await page.goto(`/projects/${projectId}/inputs`);
  await page.getByTestId("published-model-dapagliflozin-osp").click();
  await expect(page.getByTestId("inputs-notice")).toContainText("The published OSP Dapagliflozin model");
  await page.getByTestId("tab-individuals").click();

  const card = page.getByTestId(`todo-review-${EHC}`).first();
  await expect(card).toBeVisible();
  // the stale hover title is gone; the reason is said in visible text
  await expect(card).toContainText("No automatic conversion: type the value in PK-Sim's unit to accept it.");
  await expect(card.locator("[title*='Literature page']")).toHaveCount(0);
  const value = card.getByLabel("Value in PK-Sim's unit");
  const unit = card.getByLabel("PK-Sim unit");
  const accept = card.getByRole("button", { name: "Accept" });
  await expect(value).toHaveValue("");                   // never prefilled
  await expect(value).toHaveAttribute("inputmode", "decimal");
  // only the harvested unit is offered (the snapshot's own: dimensionless), with nothing chosen yet
  await expect(unit.locator("option:not([disabled])")).toHaveText(["dimensionless (no unit)"]);

  await card.locator("input[placeholder='why']").fill("as the published model sets it, checked against the snapshot");
  await expect(accept).toBeDisabled();                   // no value typed yet
  await value.fill("1,0");
  await expect(accept).toBeDisabled();                   // not a number: nothing is guessed
  await value.fill("1.0");
  await expect(accept).toBeDisabled();                   // no unit chosen yet
  await unit.selectOption({ label: "dimensionless (no unit)" });
  await expect(accept).toBeEnabled();
  await accept.click();
  await expect(page.getByText(`${EHC} = 1.0 accepted, typed in PK-Sim's unit.`)).toBeVisible();
  await expect(page.getByTestId(`todo-review-${EHC}`)).toHaveCount(0);

  const evidence = await request.get(`/api/v1/projects/${projectId}/evidence`, { headers: AUTH });
  const item = ((await evidence.json()).data.evidence as { target: string; state: string; value_pksim: number | null;
    unit_pksim: string | null; conversion: string }[]).find((e) => e.target === EHC)!;
  expect(item).toMatchObject({ state: "ACCEPTED", value_pksim: 1, unit_pksim: null });
  expect(item.conversion).toMatch(/^set by .* on acceptance: 1$/);
});
