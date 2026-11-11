// Audit 2, item 2 (2026-11-11): Inputs › Populations with the published Dapagliflozin model's values. Each held value is
// drawn once, on its row, with one Accept/Reject; an expression profile document is clipped, never printed whole; the
// study individuals already settled are one line each; the page is short at 1280 and no wider than a 390 px phone.
// Software check of the pipeline: no PK-Sim run here.
import { expect, test } from "@playwright/test";

import { AUTH, finishStart } from "./fixtures/inputs";

const EHC = "indiv.Organism|Liver|EHC continuous fraction";

test("each held value on Populations is drawn once, as a row, and the page stays short and phone-wide", async ({ page, request }) => {
  const started = await request.post("/api/v1/projects:initiate", {
    headers: AUTH,
    multipart: { drug_name: "Dapagliflozin", extract: "false",
                 files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nOral 10 mg, healthy adults.") } },
  });
  expect(started.ok(), await started.text()).toBeTruthy();
  const projectId = (await started.json()).data.project_id as string;
  await finishStart(request, projectId);
  expect((await request.post(`/api/v1/projects/${projectId}/requirements:derive`, { headers: AUTH })).ok()).toBeTruthy();

  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(`/projects/${projectId}/inputs`);
  await page.getByTestId("published-model-dapagliflozin-osp").click();
  await expect(page.getByTestId("inputs-notice")).toContainText("The published OSP Dapagliflozin model");
  await page.getByTestId("tab-individuals").click();

  // held once: one to-do on its row, one Decide (one reason field, one Accept, one Reject)
  const row = page.getByTestId(`record-${EHC}`);
  await expect(row).toBeVisible();
  await expect(page.getByTestId(`todo-review-${EHC}`)).toHaveCount(1);
  await expect(row.getByTestId(`todo-review-${EHC}`)).toHaveCount(1);
  await expect(page.getByRole("button", { name: `Accept ${EHC} =` })).toHaveCount(1);
  await expect(page.getByRole("button", { name: `Reject ${EHC} =` })).toHaveCount(1);
  await expect(page.locator("input[data-why]")).toHaveCount(await page.locator("[data-testid^='todo-review-']").count());
  // a readable name from the path's own segments, the full path once in the row
  await expect(row.locator(".input-name strong")).toHaveText("Liver · EHC continuous fraction");
  await expect(row.getByText(EHC, { exact: true })).toHaveCount(1);

  // no raw JSON document in a value cell: each is clipped with "show all"
  const profiles = page.locator("[data-testid^='record-expr.profile.']");
  if (await profiles.count()) {
    // the expression profiles' group is folded while none waits on a person: opened, its documents stay clipped
    const group = page.getByTestId("organ-Expression profiles");
    if (!(await group.evaluate((d) => (d as HTMLDetailsElement).open))) await group.locator(":scope > summary").click();
    await expect(profiles.first().locator(".input-value .clip-more")).toBeVisible();
    for (const cell of await page.locator(".input-value").all()) {
      expect((await cell.innerText()).length).toBeLessThan(200);
    }
  }

  // settled individuals are one line; only the open ones are forms
  const forms = await page.locator("[data-testid^='individual-'] select").count();
  const open = await page.locator("[data-testid^='individual-']:not(.settled)").count();
  expect(forms).toBe(open * 2);

  const height = await page.evaluate(() => document.documentElement.scrollHeight);
  console.log(`populations height at 1280: ${height}`);
  expect(height).toBeLessThan(12000);                 // 44,224 px before (audit 2)
  await row.scrollIntoViewIfNeeded();
  await expect(page.getByTestId("organ-Liver")).toHaveCSS("opacity", "1");   // the scroll fade-in has played
  await page.screenshot({ path: test.info().outputPath("populations-1280.png") });

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(row).toBeVisible();
  const wide = await page.evaluate(() => document.documentElement.scrollWidth);
  const tall = await page.evaluate(() => document.documentElement.scrollHeight);
  console.log(`populations at 390: scrollWidth ${wide}, height ${tall}`);
  expect(wide).toBeLessThanOrEqual(390);              // 809 px before (audit 2)
  await row.scrollIntoViewIfNeeded();
  await expect(page.getByTestId("organ-Liver")).toHaveCSS("opacity", "1");
  await page.screenshot({ path: test.info().outputPath("populations-390.png") });

  // focus after a decision goes to the next held value's reason field, never to an Accept button
  const reason = row.locator("input[data-why]");
  await reason.fill("as the published model sets it, checked against the snapshot");
  await row.getByRole("button", { name: `Reject ${EHC} =` }).click();
  await expect(page.getByTestId(`todo-review-${EHC}`)).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => Boolean(document.activeElement?.matches("input[data-why], h2, h3")))).toBe(true);
});
